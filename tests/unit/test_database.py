"""Unit tests for SQLite database."""

from datetime import datetime
from pathlib import Path

import pytest

from kalshi_trading.clients.espn import GameState, GameStatus, Team
from kalshi_trading.monitoring import TradingDatabase
from kalshi_trading.strategies.base import Signal, TradeSignal


@pytest.fixture
def db(tmp_path: Path) -> TradingDatabase:
    """Create a test database."""
    db = TradingDatabase(tmp_path / "test.db")
    db.initialize()
    return db


@pytest.fixture
def sample_signal() -> TradeSignal:
    """Create sample trade signal."""
    return TradeSignal(
        signal=Signal.BUY,
        ticker="NFL-2426-BUF",
        side="yes",
        size=10,
        price=64,
        reason="Margin exceeded threshold",
    )


@pytest.fixture
def sample_game() -> GameState:
    """Create sample game state."""
    return GameState(
        event_id="12345",
        sport="nfl",
        home_team=Team(id="1", abbreviation="BUF", display_name="Buffalo Bills"),
        away_team=Team(id="2", abbreviation="KC", display_name="Kansas City Chiefs"),
        home_score=21,
        away_score=14,
        period=4,
        clock_seconds=300.0,
        status=GameStatus.IN,
    )


class TestDatabaseInitialization:
    """Tests for database initialization."""

    def test_creates_database_file(self, tmp_path: Path):
        """Should create database file on initialize."""
        db_path = tmp_path / "test.db"
        db = TradingDatabase(db_path)
        db.initialize()

        assert db_path.exists()

    def test_creates_tables(self, db: TradingDatabase):
        """Should create all required tables."""
        with db._get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row["name"] for row in cursor.fetchall()}

        assert "trades" in tables
        assert "signals" in tables
        assert "game_states" in tables
        assert "daily_summary" in tables


class TestTradeInsertion:
    """Tests for inserting trades."""

    def test_insert_trade(self, db: TradingDatabase, sample_signal: TradeSignal):
        """Should insert trade record."""
        row_id = db.insert_trade(
            signal=sample_signal,
            event_id="12345",
            sport="nfl",
            matchup="KC@BUF",
            strategy_name="nfl_spread",
            status="executed",
            fill_price=65,
            pnl=100,
        )

        assert row_id > 0

        # Verify data
        trades = db.get_recent_trades(1)
        assert len(trades) == 1
        assert trades[0]["ticker"] == "NFL-2426-BUF"
        assert trades[0]["status"] == "executed"
        assert trades[0]["pnl"] == 100

    def test_insert_dry_run_trade(
        self, db: TradingDatabase, sample_signal: TradeSignal
    ):
        """Should insert dry run trade."""
        db.insert_trade(
            signal=sample_signal,
            event_id="12345",
            sport="nfl",
            matchup="KC@BUF",
            strategy_name="nfl_spread",
            status="dry_run",
        )

        trades = db.get_recent_trades(1)
        assert trades[0]["status"] == "dry_run"


class TestSignalInsertion:
    """Tests for inserting signals."""

    def test_insert_signal(self, db: TradingDatabase, sample_signal: TradeSignal):
        """Should insert signal record."""
        row_id = db.insert_signal(
            signal=sample_signal,
            event_id="12345",
            sport="nfl",
            strategy_name="nfl_spread",
            was_executed=True,
        )

        assert row_id > 0


class TestGameStateInsertion:
    """Tests for inserting game states."""

    def test_insert_game_state(self, db: TradingDatabase, sample_game: GameState):
        """Should insert game state snapshot."""
        row_id = db.insert_game_state(sample_game)

        assert row_id > 0


class TestStrategyPerformance:
    """Tests for performance analytics."""

    def test_empty_performance(self, db: TradingDatabase):
        """Should return zeros for empty database."""
        perf = db.get_strategy_performance("nfl_spread")

        assert perf["total_trades"] == 0
        assert perf["total_pnl"] == 0
        assert perf["win_rate"] == 0.0

    def test_performance_with_trades(
        self, db: TradingDatabase, sample_signal: TradeSignal
    ):
        """Should calculate performance metrics."""
        # Insert some trades
        db.insert_trade(
            signal=sample_signal,
            event_id="1",
            sport="nfl",
            matchup="KC@BUF",
            strategy_name="nfl_spread",
            status="executed",
            pnl=100,
        )
        db.insert_trade(
            signal=sample_signal,
            event_id="2",
            sport="nfl",
            matchup="DEN@LV",
            strategy_name="nfl_spread",
            status="executed",
            pnl=-50,
        )
        db.insert_trade(
            signal=sample_signal,
            event_id="3",
            sport="nfl",
            matchup="SF@SEA",
            strategy_name="nfl_spread",
            status="dry_run",
        )

        perf = db.get_strategy_performance("nfl_spread")

        assert perf["total_trades"] == 3
        assert perf["executed"] == 2
        assert perf["dry_runs"] == 1
        assert perf["total_pnl"] == 50  # 100 - 50
        assert perf["winning_trades"] == 1
        assert perf["losing_trades"] == 1

    def test_performance_by_strategy(
        self, db: TradingDatabase, sample_signal: TradeSignal
    ):
        """Should group performance by strategy."""
        db.insert_trade(
            signal=sample_signal,
            event_id="1",
            sport="nfl",
            matchup="KC@BUF",
            strategy_name="nfl_spread",
            status="executed",
            pnl=100,
        )
        db.insert_trade(
            signal=sample_signal,
            event_id="2",
            sport="nba",
            matchup="LAL@BOS",
            strategy_name="nba_blowout",
            status="executed",
            pnl=200,
        )

        by_strategy = db.get_performance_by_strategy()

        assert "nfl_spread" in by_strategy
        assert "nba_blowout" in by_strategy
        assert by_strategy["nfl_spread"]["total_pnl"] == 100
        assert by_strategy["nba_blowout"]["total_pnl"] == 200


class TestPerformanceBySport:
    """Tests for sport-based analytics."""

    def test_performance_by_sport(
        self, db: TradingDatabase, sample_signal: TradeSignal
    ):
        """Should group performance by sport."""
        db.insert_trade(
            signal=sample_signal,
            event_id="1",
            sport="nfl",
            matchup="KC@BUF",
            strategy_name="nfl_spread",
            status="executed",
            pnl=100,
        )
        db.insert_trade(
            signal=sample_signal,
            event_id="2",
            sport="nfl",
            matchup="DEN@LV",
            strategy_name="nfl_blowout",
            status="executed",
            pnl=50,
        )
        db.insert_trade(
            signal=sample_signal,
            event_id="3",
            sport="nba",
            matchup="LAL@BOS",
            strategy_name="nba_blowout",
            status="executed",
            pnl=200,
        )

        by_sport = db.get_performance_by_sport()

        assert "nfl" in by_sport
        assert "nba" in by_sport
        assert by_sport["nfl"]["total_trades"] == 2
        assert by_sport["nfl"]["total_pnl"] == 150
        assert by_sport["nba"]["total_trades"] == 1
        assert by_sport["nba"]["total_pnl"] == 200


class TestRecentTrades:
    """Tests for recent trades query."""

    def test_get_recent_trades_limit(
        self, db: TradingDatabase, sample_signal: TradeSignal
    ):
        """Should respect limit parameter."""
        for i in range(10):
            db.insert_trade(
                signal=sample_signal,
                event_id=str(i),
                sport="nfl",
                matchup="KC@BUF",
                strategy_name="nfl_spread",
                status="executed",
            )

        trades = db.get_recent_trades(5)

        assert len(trades) == 5
