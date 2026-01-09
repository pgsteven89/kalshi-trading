"""Backtesting engine for replaying historical data through strategies."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from kalshi_trading.clients.espn import GameState, GameStatus, Team
from kalshi_trading.clients.models import Market, MarketStatus
from kalshi_trading.config import load_all_strategies
from kalshi_trading.monitoring.database import TradingDatabase
from kalshi_trading.strategies.base import MarketState, Signal, TradeSignal, TradingStrategy

logger = structlog.get_logger()


@dataclass
class BacktestTrade:
    """Record of a simulated trade during backtesting."""

    timestamp: str
    event_id: str
    sport: str
    matchup: str
    strategy_name: str
    signal: str
    side: str
    size: int
    entry_price: int
    exit_price: int | None = None
    pnl: int = 0
    outcome: str = "pending"  # win, loss, pending


@dataclass
class BacktestResult:
    """Results from a backtest run."""

    start_date: str
    end_date: str
    strategies: list[str]
    total_signals: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: int = 0
    trades: list[BacktestTrade] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        """Calculate win rate."""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def total_pnl_dollars(self) -> float:
        """P&L in dollars."""
        return self.total_pnl / 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for reporting."""
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "strategies": self.strategies,
            "total_signals": self.total_signals,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": f"{self.win_rate:.1%}",
            "total_pnl": self.total_pnl,
            "total_pnl_dollars": f"${self.total_pnl_dollars:.2f}",
        }


class Backtester:
    """
    Replays historical game data through strategies.

    Uses collected game state snapshots to simulate what trades
    would have been made and estimates P&L.

    Example:
        backtester = Backtester(db, strategies)
        result = backtester.run(
            start_date="2026-01-01",
            end_date="2026-01-08",
        )
        print(f"Win rate: {result.win_rate:.1%}")
        print(f"P&L: ${result.total_pnl_dollars:.2f}")
    """

    def __init__(
        self,
        db: TradingDatabase,
        strategies: list[TradingStrategy] | None = None,
        strategies_dir: Path | None = None,
    ):
        """
        Initialize backtester.

        Args:
            db: Trading database with historical data
            strategies: Pre-loaded strategies
            strategies_dir: Directory with strategy YAML files
        """
        self.db = db

        if strategies:
            self.strategies = strategies
        elif strategies_dir:
            self.strategies = load_all_strategies(strategies_dir)
        else:
            self.strategies = []

    def run(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        sport: str | None = None,
    ) -> BacktestResult:
        """
        Run backtest on historical data.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            sport: Filter by sport (optional)

        Returns:
            BacktestResult with performance metrics
        """
        # Get historical game states
        snapshots = self._get_game_snapshots(start_date, end_date, sport)

        if not snapshots:
            logger.warning("No historical data found for backtest")
            return BacktestResult(
                start_date=start_date or "",
                end_date=end_date or "",
                strategies=[s.name for s in self.strategies],
            )

        result = BacktestResult(
            start_date=start_date or snapshots[0]["timestamp"][:10],
            end_date=end_date or snapshots[-1]["timestamp"][:10],
            strategies=[s.name for s in self.strategies],
        )

        # Group snapshots by event
        events = self._group_by_event(snapshots)

        # Process each event
        for event_id, event_snapshots in events.items():
            self._process_event(event_snapshots, result)

        return result

    def _get_game_snapshots(
        self,
        start_date: str | None,
        end_date: str | None,
        sport: str | None,
    ) -> list[dict[str, Any]]:
        """Get historical game state snapshots from database."""
        query = "SELECT * FROM game_states WHERE 1=1"
        params: list[Any] = []

        if start_date:
            query += " AND date(timestamp) >= ?"
            params.append(start_date)
        if end_date:
            query += " AND date(timestamp) <= ?"
            params.append(end_date)
        if sport:
            query += " AND sport = ?"
            params.append(sport)

        query += " ORDER BY timestamp"

        with self.db._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def _group_by_event(
        self, snapshots: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Group snapshots by event ID."""
        events: dict[str, list[dict[str, Any]]] = {}
        for snapshot in snapshots:
            event_id = snapshot["event_id"]
            if event_id not in events:
                events[event_id] = []
            events[event_id].append(snapshot)
        return events

    def _process_event(
        self,
        snapshots: list[dict[str, Any]],
        result: BacktestResult,
    ) -> None:
        """Process all snapshots for a single event."""
        if not snapshots:
            return

        # Track if we've already signaled for this event per strategy
        signaled: set[str] = set()

        for snapshot in snapshots:
            game_state = self._snapshot_to_game_state(snapshot)

            if not game_state.is_live:
                continue

            # Create a simulated market state
            market_state = self._create_simulated_market(snapshot)

            for strategy in self.strategies:
                strategy_key = f"{strategy.name}:{snapshot['event_id']}"

                if strategy_key in signaled:
                    continue

                signal = strategy.evaluate(game_state, market_state, None)

                if signal and signal.is_actionable:
                    result.total_signals += 1
                    signaled.add(strategy_key)

                    # Simulate the trade
                    trade = self._simulate_trade(
                        signal, snapshot, strategy.name, snapshots
                    )
                    result.trades.append(trade)
                    result.total_trades += 1

                    if trade.outcome == "win":
                        result.winning_trades += 1
                        result.total_pnl += trade.pnl
                    elif trade.outcome == "loss":
                        result.losing_trades += 1
                        result.total_pnl += trade.pnl

    def _snapshot_to_game_state(self, snapshot: dict[str, Any]) -> GameState:
        """Convert database snapshot to GameState."""
        return GameState(
            event_id=snapshot["event_id"],
            sport=snapshot["sport"],
            home_team=Team(
                id="0",
                abbreviation=snapshot["home_team"],
                display_name=snapshot["home_team"],
            ),
            away_team=Team(
                id="0",
                abbreviation=snapshot["away_team"],
                display_name=snapshot["away_team"],
            ),
            home_score=snapshot["home_score"],
            away_score=snapshot["away_score"],
            period=snapshot["period"],
            clock_seconds=snapshot["clock_seconds"],
            status=GameStatus(snapshot["status"]),
        )

    def _create_simulated_market(self, snapshot: dict[str, Any]) -> MarketState:
        """Create a simulated market state based on game state."""
        # Estimate implied probability from margin
        margin = snapshot["margin"]

        # Simple model: higher margin = higher probability
        # Base probability of 50%, adjust by ~3% per point of margin
        base_prob = 50
        prob_adjustment = min(40, abs(margin) * 3)

        if margin > 0:
            yes_price = min(95, base_prob + prob_adjustment)
        else:
            yes_price = max(5, base_prob - prob_adjustment)

        market = Market(
            ticker=f"{snapshot['sport'].upper()}-{snapshot['event_id']}",
            event_ticker=snapshot["event_id"],
            title=f"{snapshot['away_team']} @ {snapshot['home_team']}",
            status=MarketStatus.OPEN,
            yes_bid=yes_price - 2,
            yes_ask=yes_price,
            no_bid=100 - yes_price - 2,
            no_ask=100 - yes_price,
            volume=0,
            open_interest=0,
        )
        return MarketState(market=market)

    def _simulate_trade(
        self,
        signal: TradeSignal,
        entry_snapshot: dict[str, Any],
        strategy_name: str,
        all_snapshots: list[dict[str, Any]],
    ) -> BacktestTrade:
        """
        Simulate a trade outcome.

        Uses final game result to determine win/loss.
        """
        # Find final snapshot for this event
        final_snapshot = all_snapshots[-1]

        # Determine outcome based on final margin
        home_won = final_snapshot["home_score"] > final_snapshot["away_score"]

        # Assume we're betting YES on home team winning
        if signal.side == "yes":
            won = home_won
        else:
            won = not home_won

        # Calculate simulated P&L
        entry_price = signal.price or 50
        if won:
            # Win: receive 100 cents, paid entry_price
            pnl = (100 - entry_price) * signal.size
            outcome = "win"
        else:
            # Loss: lose entire entry
            pnl = -entry_price * signal.size
            outcome = "loss"

        return BacktestTrade(
            timestamp=entry_snapshot["timestamp"],
            event_id=entry_snapshot["event_id"],
            sport=entry_snapshot["sport"],
            matchup=f"{entry_snapshot['away_team']}@{entry_snapshot['home_team']}",
            strategy_name=strategy_name,
            signal=signal.signal.value,
            side=signal.side,
            size=signal.size,
            entry_price=entry_price,
            exit_price=100 if won else 0,
            pnl=pnl,
            outcome=outcome,
        )

    def print_summary(self, result: BacktestResult) -> None:
        """Print a formatted summary of backtest results."""
        print("\n" + "=" * 60)
        print("BACKTEST RESULTS")
        print("=" * 60)
        print(f"Period: {result.start_date} to {result.end_date}")
        print(f"Strategies: {', '.join(result.strategies)}")
        print("-" * 60)
        print(f"Total Signals: {result.total_signals}")
        print(f"Total Trades: {result.total_trades}")
        print(f"Winning Trades: {result.winning_trades}")
        print(f"Losing Trades: {result.losing_trades}")
        print(f"Win Rate: {result.win_rate:.1%}")
        print(f"Total P&L: ${result.total_pnl_dollars:.2f}")
        print("=" * 60)


def run_backtest(
    db_path: Path | None = None,
    strategies_dir: Path | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    sport: str | None = None,
) -> BacktestResult:
    """
    Convenience function to run a backtest.

    Args:
        db_path: Path to SQLite database
        strategies_dir: Directory with strategy YAML files
        start_date: Start date for backtest
        end_date: End date for backtest
        sport: Filter by sport

    Returns:
        BacktestResult with performance metrics
    """
    db = TradingDatabase(db_path)

    backtester = Backtester(
        db=db,
        strategies_dir=strategies_dir or Path("config/strategies"),
    )

    result = backtester.run(
        start_date=start_date,
        end_date=end_date,
        sport=sport,
    )

    backtester.print_summary(result)
    return result
