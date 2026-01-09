"""SQLite database storage for trades, signals, and analytics."""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from kalshi_trading.clients.espn import GameState
from kalshi_trading.strategies.base import TradeSignal


def get_default_db_path() -> Path:
    """Get default database path."""
    return Path("data/trading.db")


class TradingDatabase:
    """
    SQLite database for storing trading data and analytics.

    Stores trades, signals, game states, and provides analytics queries.

    Example:
        db = TradingDatabase()
        db.initialize()

        # Store a trade
        db.insert_trade(signal, game_state, strategy_name, executed=True)

        # Query analytics
        summary = db.get_strategy_performance("nfl_spread")
    """

    SCHEMA = """
    -- Trades table: all executed and dry-run trades
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        event_id TEXT NOT NULL,
        sport TEXT NOT NULL,
        matchup TEXT NOT NULL,
        ticker TEXT NOT NULL,
        signal_type TEXT NOT NULL,  -- buy, sell, hold
        side TEXT NOT NULL,         -- yes, no
        size INTEGER NOT NULL,
        price INTEGER,              -- in cents
        fill_price INTEGER,         -- actual fill price
        status TEXT NOT NULL,       -- executed, rejected, dry_run
        strategy_name TEXT NOT NULL,
        reason TEXT,
        pnl INTEGER DEFAULT 0,      -- realized P&L in cents
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- Signals table: all signals generated (for analysis)
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        event_id TEXT NOT NULL,
        sport TEXT NOT NULL,
        ticker TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        side TEXT NOT NULL,
        size INTEGER NOT NULL,
        price INTEGER,
        strategy_name TEXT NOT NULL,
        reason TEXT,
        was_executed INTEGER DEFAULT 0,  -- boolean
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- Game states table: snapshots of game data
    CREATE TABLE IF NOT EXISTS game_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        event_id TEXT NOT NULL,
        sport TEXT NOT NULL,
        home_team TEXT NOT NULL,
        away_team TEXT NOT NULL,
        home_score INTEGER NOT NULL,
        away_score INTEGER NOT NULL,
        period INTEGER NOT NULL,
        clock_seconds REAL NOT NULL,
        status TEXT NOT NULL,       -- pre, in, post
        margin INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- Daily summary table: aggregated daily stats
    CREATE TABLE IF NOT EXISTS daily_summary (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL UNIQUE,
        total_signals INTEGER DEFAULT 0,
        total_trades INTEGER DEFAULT 0,
        executed_trades INTEGER DEFAULT 0,
        dry_run_trades INTEGER DEFAULT 0,
        rejected_trades INTEGER DEFAULT 0,
        total_pnl INTEGER DEFAULT 0,       -- in cents
        winning_trades INTEGER DEFAULT 0,
        losing_trades INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    -- Indexes for common queries
    CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
    CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_name);
    CREATE INDEX IF NOT EXISTS idx_trades_sport ON trades(sport);
    CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
    CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
    CREATE INDEX IF NOT EXISTS idx_signals_strategy ON signals(strategy_name);
    CREATE INDEX IF NOT EXISTS idx_game_states_event ON game_states(event_id);
    CREATE INDEX IF NOT EXISTS idx_daily_summary_date ON daily_summary(date);
    """

    def __init__(self, db_path: Path | str | None = None):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path) if db_path else get_default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection as context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Create database tables if they don't exist."""
        with self._get_connection() as conn:
            conn.executescript(self.SCHEMA)

    # -- Insert Methods --

    def insert_trade(
        self,
        signal: TradeSignal,
        event_id: str,
        sport: str,
        matchup: str,
        strategy_name: str,
        status: str,
        fill_price: int | None = None,
        pnl: int = 0,
    ) -> int:
        """
        Insert a trade record.

        Args:
            signal: Trade signal
            event_id: ESPN event ID
            sport: Sport type
            matchup: Game matchup string
            strategy_name: Strategy that generated signal
            status: executed, rejected, or dry_run
            fill_price: Actual fill price if executed
            pnl: Realized P&L in cents

        Returns:
            Inserted row ID
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO trades (
                    timestamp, event_id, sport, matchup, ticker,
                    signal_type, side, size, price, fill_price,
                    status, strategy_name, reason, pnl
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.timestamp.isoformat(),
                    event_id,
                    sport,
                    matchup,
                    signal.ticker,
                    signal.signal.value,
                    signal.side,
                    signal.size,
                    signal.price,
                    fill_price,
                    status,
                    strategy_name,
                    signal.reason,
                    pnl,
                ),
            )
            return cursor.lastrowid or 0

    def insert_signal(
        self,
        signal: TradeSignal,
        event_id: str,
        sport: str,
        strategy_name: str,
        was_executed: bool = False,
    ) -> int:
        """Insert a signal record for analysis."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO signals (
                    timestamp, event_id, sport, ticker,
                    signal_type, side, size, price,
                    strategy_name, reason, was_executed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.timestamp.isoformat(),
                    event_id,
                    sport,
                    signal.ticker,
                    signal.signal.value,
                    signal.side,
                    signal.size,
                    signal.price,
                    strategy_name,
                    signal.reason,
                    1 if was_executed else 0,
                ),
            )
            return cursor.lastrowid or 0

    def insert_game_state(self, game: GameState) -> int:
        """Insert a game state snapshot."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO game_states (
                    timestamp, event_id, sport,
                    home_team, away_team,
                    home_score, away_score,
                    period, clock_seconds, status, margin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    game.event_id,
                    game.sport,
                    game.home_team.abbreviation,
                    game.away_team.abbreviation,
                    game.home_score,
                    game.away_score,
                    game.period,
                    game.clock_seconds,
                    game.status.value,
                    game.margin,
                ),
            )
            return cursor.lastrowid or 0

    # -- Analytics Queries --

    def get_strategy_performance(
        self,
        strategy_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Get performance metrics for a strategy.

        Args:
            strategy_name: Filter by strategy (None for all)
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)

        Returns:
            Dict with performance metrics
        """
        query = """
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN status = 'executed' THEN 1 ELSE 0 END) as executed,
                SUM(CASE WHEN status = 'dry_run' THEN 1 ELSE 0 END) as dry_runs,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(pnl) as total_pnl,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                AVG(pnl) as avg_pnl
            FROM trades
            WHERE 1=1
        """
        params: list[Any] = []

        if strategy_name:
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        if start_date:
            query += " AND date(timestamp) >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date(timestamp) <= ?"
            params.append(end_date)

        with self._get_connection() as conn:
            row = conn.execute(query, params).fetchone()

            if not row or row["total_trades"] == 0:
                return {
                    "total_trades": 0,
                    "executed": 0,
                    "dry_runs": 0,
                    "rejected": 0,
                    "total_pnl": 0,
                    "total_pnl_dollars": 0.0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "win_rate": 0.0,
                    "avg_pnl": 0.0,
                }

            executed = row["executed"] or 0
            winning = row["winning_trades"] or 0

            return {
                "total_trades": row["total_trades"],
                "executed": executed,
                "dry_runs": row["dry_runs"] or 0,
                "rejected": row["rejected"] or 0,
                "total_pnl": row["total_pnl"] or 0,
                "total_pnl_dollars": (row["total_pnl"] or 0) / 100,
                "winning_trades": winning,
                "losing_trades": row["losing_trades"] or 0,
                "win_rate": winning / executed if executed > 0 else 0.0,
                "avg_pnl": row["avg_pnl"] or 0.0,
            }

    def get_performance_by_sport(self) -> dict[str, dict[str, Any]]:
        """Get performance metrics grouped by sport."""
        query = """
            SELECT
                sport,
                COUNT(*) as total_trades,
                SUM(pnl) as total_pnl,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses
            FROM trades
            WHERE status = 'executed'
            GROUP BY sport
        """

        with self._get_connection() as conn:
            rows = conn.execute(query).fetchall()

            result = {}
            for row in rows:
                wins = row["wins"] or 0
                total = row["total_trades"]
                result[row["sport"]] = {
                    "total_trades": total,
                    "total_pnl": row["total_pnl"] or 0,
                    "total_pnl_dollars": (row["total_pnl"] or 0) / 100,
                    "wins": wins,
                    "losses": row["losses"] or 0,
                    "win_rate": wins / total if total > 0 else 0.0,
                }

            return result

    def get_performance_by_strategy(self) -> dict[str, dict[str, Any]]:
        """Get performance metrics grouped by strategy."""
        query = """
            SELECT
                strategy_name,
                COUNT(*) as total_trades,
                SUM(pnl) as total_pnl,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses
            FROM trades
            WHERE status = 'executed'
            GROUP BY strategy_name
        """

        with self._get_connection() as conn:
            rows = conn.execute(query).fetchall()

            result = {}
            for row in rows:
                wins = row["wins"] or 0
                total = row["total_trades"]
                result[row["strategy_name"]] = {
                    "total_trades": total,
                    "total_pnl": row["total_pnl"] or 0,
                    "total_pnl_dollars": (row["total_pnl"] or 0) / 100,
                    "wins": wins,
                    "losses": row["losses"] or 0,
                    "win_rate": wins / total if total > 0 else 0.0,
                }

            return result

    def get_daily_pnl(self, days: int = 30) -> list[dict[str, Any]]:
        """Get daily P&L for the last N days."""
        query = """
            SELECT
                date(timestamp) as date,
                COUNT(*) as trades,
                SUM(pnl) as pnl
            FROM trades
            WHERE status = 'executed'
              AND date(timestamp) >= date('now', ?)
            GROUP BY date(timestamp)
            ORDER BY date(timestamp)
        """

        with self._get_connection() as conn:
            rows = conn.execute(query, (f"-{days} days",)).fetchall()

            return [
                {
                    "date": row["date"],
                    "trades": row["trades"],
                    "pnl": row["pnl"] or 0,
                    "pnl_dollars": (row["pnl"] or 0) / 100,
                }
                for row in rows
            ]

    def get_recent_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get most recent trades."""
        query = """
            SELECT * FROM trades
            ORDER BY timestamp DESC
            LIMIT ?
        """

        with self._get_connection() as conn:
            rows = conn.execute(query, (limit,)).fetchall()
            return [dict(row) for row in rows]

    def get_signal_execution_rate(self) -> dict[str, float]:
        """Get signal execution rate by strategy."""
        query = """
            SELECT
                strategy_name,
                COUNT(*) as total_signals,
                SUM(was_executed) as executed_signals
            FROM signals
            GROUP BY strategy_name
        """

        with self._get_connection() as conn:
            rows = conn.execute(query).fetchall()

            return {
                row["strategy_name"]: (
                    row["executed_signals"] / row["total_signals"]
                    if row["total_signals"] > 0
                    else 0.0
                )
                for row in rows
            }
