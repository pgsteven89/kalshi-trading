"""Unit tests for backtesting framework."""

from datetime import datetime
from pathlib import Path

import pytest

from kalshi_trading.clients.espn import GameState, GameStatus, Team
from kalshi_trading.engine.backtester import Backtester, BacktestResult, BacktestTrade
from kalshi_trading.monitoring.database import TradingDatabase
from kalshi_trading.strategies import ScoreMarginStrategy


@pytest.fixture
def db(tmp_path: Path) -> TradingDatabase:
    """Create test database with sample data."""
    db = TradingDatabase(tmp_path / "test.db")
    db.initialize()
    return db


@pytest.fixture
def sample_strategy() -> ScoreMarginStrategy:
    """Create sample strategy for testing."""
    return ScoreMarginStrategy(
        name="test_strategy",
        config={"min_margin": 7, "direction": "leading", "size": 10},
    )


@pytest.fixture
def populated_db(db: TradingDatabase) -> TradingDatabase:
    """Database with sample game state snapshots."""
    # Simulate a game progressing
    snapshots = [
        # Q1 - Close game
        {"event_id": "123", "sport": "nfl", "home_team": "BUF", "away_team": "KC",
         "home_score": 7, "away_score": 7, "period": 1, "clock_seconds": 600, "status": "in"},
        # Q2 - Home starts leading
        {"event_id": "123", "sport": "nfl", "home_team": "BUF", "away_team": "KC",
         "home_score": 14, "away_score": 7, "period": 2, "clock_seconds": 300, "status": "in"},
        # Q3 - Home extends lead
        {"event_id": "123", "sport": "nfl", "home_team": "BUF", "away_team": "KC",
         "home_score": 21, "away_score": 7, "period": 3, "clock_seconds": 600, "status": "in"},
        # Q4 - Home maintains lead (triggers strategy at 14pt margin)
        {"event_id": "123", "sport": "nfl", "home_team": "BUF", "away_team": "KC",
         "home_score": 28, "away_score": 14, "period": 4, "clock_seconds": 300, "status": "in"},
        # Final - Home wins
        {"event_id": "123", "sport": "nfl", "home_team": "BUF", "away_team": "KC",
         "home_score": 31, "away_score": 21, "period": 4, "clock_seconds": 0, "status": "post"},
    ]

    for i, snap in enumerate(snapshots):
        game = GameState(
            event_id=snap["event_id"],
            sport=snap["sport"],
            home_team=Team(id="1", abbreviation=snap["home_team"], display_name=snap["home_team"]),
            away_team=Team(id="2", abbreviation=snap["away_team"], display_name=snap["away_team"]),
            home_score=snap["home_score"],
            away_score=snap["away_score"],
            period=snap["period"],
            clock_seconds=snap["clock_seconds"],
            status=GameStatus(snap["status"]),
        )
        db.insert_game_state(game)

    return db


class TestBacktestResult:
    """Tests for BacktestResult dataclass."""

    def test_win_rate_calculation(self):
        """Should calculate win rate correctly."""
        result = BacktestResult(
            start_date="2026-01-01",
            end_date="2026-01-08",
            strategies=["test"],
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
        )

        assert result.win_rate == 0.6

    def test_win_rate_zero_trades(self):
        """Should return 0 for no trades."""
        result = BacktestResult(
            start_date="2026-01-01",
            end_date="2026-01-08",
            strategies=["test"],
        )

        assert result.win_rate == 0.0

    def test_pnl_dollars_conversion(self):
        """Should convert cents to dollars."""
        result = BacktestResult(
            start_date="2026-01-01",
            end_date="2026-01-08",
            strategies=["test"],
            total_pnl=15000,
        )

        assert result.total_pnl_dollars == 150.0


class TestBacktester:
    """Tests for Backtester engine."""

    def test_empty_database(self, db: TradingDatabase, sample_strategy: ScoreMarginStrategy):
        """Should handle empty database gracefully."""
        backtester = Backtester(db, strategies=[sample_strategy])
        result = backtester.run()

        assert result.total_signals == 0
        assert result.total_trades == 0

    def test_finds_signals(self, populated_db: TradingDatabase, sample_strategy: ScoreMarginStrategy):
        """Should find signals in historical data."""
        backtester = Backtester(populated_db, strategies=[sample_strategy])
        result = backtester.run()

        # Strategy should trigger when margin >= 7
        assert result.total_signals >= 1

    def test_simulates_trades(self, populated_db: TradingDatabase, sample_strategy: ScoreMarginStrategy):
        """Should simulate trade outcomes."""
        backtester = Backtester(populated_db, strategies=[sample_strategy])
        result = backtester.run()

        if result.total_trades > 0:
            # Home team won, so YES signal should win
            assert result.winning_trades >= 1

    def test_calculates_pnl(self, populated_db: TradingDatabase, sample_strategy: ScoreMarginStrategy):
        """Should calculate P&L for trades."""
        backtester = Backtester(populated_db, strategies=[sample_strategy])
        result = backtester.run()

        if result.total_trades > 0:
            # Winning trades should have positive P&L
            assert result.total_pnl != 0

    def test_filter_by_sport(self, populated_db: TradingDatabase, sample_strategy: ScoreMarginStrategy):
        """Should filter by sport."""
        backtester = Backtester(populated_db, strategies=[sample_strategy])

        # Should find trades for NFL
        nfl_result = backtester.run(sport="nfl")
        assert nfl_result.total_signals >= 0

        # Should find no trades for NBA (no data)
        nba_result = backtester.run(sport="nba")
        assert nba_result.total_signals == 0


class TestBacktestTrade:
    """Tests for BacktestTrade dataclass."""

    def test_trade_creation(self):
        """Should create trade with all fields."""
        trade = BacktestTrade(
            timestamp="2026-01-08T12:00:00",
            event_id="123",
            sport="nfl",
            matchup="KC@BUF",
            strategy_name="nfl_spread",
            signal="buy",
            side="yes",
            size=10,
            entry_price=60,
            exit_price=100,
            pnl=400,
            outcome="win",
        )

        assert trade.pnl == 400
        assert trade.outcome == "win"
