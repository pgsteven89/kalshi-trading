"""Unit tests for monitoring and logging."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from kalshi_trading.monitoring import PerformanceTracker, TradeLogEntry, TradeLogger
from kalshi_trading.strategies.base import Signal, TradeSignal


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """Create temporary log directory."""
    return tmp_path / "logs"


@pytest.fixture
def trade_logger(log_dir: Path) -> TradeLogger:
    """Create trade logger for testing."""
    return TradeLogger(log_dir)


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


class TestTradeLogEntry:
    """Tests for TradeLogEntry dataclass."""

    def test_create_entry(self):
        """Should create log entry with all fields."""
        entry = TradeLogEntry(
            timestamp="2026-01-08T16:00:00",
            event_id="12345",
            sport="nfl",
            matchup="KC@BUF",
            ticker="NFL-2426-BUF",
            signal="buy",
            side="yes",
            size=10,
            price=64,
            fill_price=65,
            status="executed",
            reason="Test trade",
            strategy_name="nfl_spread",
            risk_check=True,
            pnl=100,
        )

        assert entry.ticker == "NFL-2426-BUF"
        assert entry.status == "executed"
        assert entry.pnl == 100


class TestTradeLogger:
    """Tests for TradeLogger."""

    def test_creates_log_directory(self, log_dir: Path):
        """Should create log directory if not exists."""
        assert not log_dir.exists()

        logger = TradeLogger(log_dir)

        assert log_dir.exists()

    def test_log_signal_writes_to_file(
        self, trade_logger: TradeLogger, sample_signal: TradeSignal, log_dir: Path
    ):
        """Should write signal to log file."""
        trade_logger.log_signal(
            signal=sample_signal,
            event_id="12345",
            sport="nfl",
            matchup="KC@BUF",
            strategy_name="nfl_spread",
            executed=True,
            fill_price=65,
        )

        # Check log file exists
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"trades_{today}.jsonl"

        assert log_file.exists()

        # Check content
        with open(log_file) as f:
            line = f.readline()
            data = json.loads(line)

        assert data["ticker"] == "NFL-2426-BUF"
        assert data["status"] == "executed"

    def test_log_dry_run(
        self, trade_logger: TradeLogger, sample_signal: TradeSignal, log_dir: Path
    ):
        """Should mark dry run signals."""
        trade_logger.log_signal(
            signal=sample_signal,
            event_id="12345",
            sport="nfl",
            matchup="KC@BUF",
            strategy_name="nfl_spread",
            dry_run=True,
        )

        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"trades_{today}.jsonl"

        with open(log_file) as f:
            data = json.loads(f.readline())

        assert data["status"] == "dry_run"

    def test_log_rejected(
        self, trade_logger: TradeLogger, sample_signal: TradeSignal, log_dir: Path
    ):
        """Should mark rejected signals with reason."""
        trade_logger.log_signal(
            signal=sample_signal,
            event_id="12345",
            sport="nfl",
            matchup="KC@BUF",
            strategy_name="nfl_spread",
            executed=False,
            rejected_reason="Position limit exceeded",
        )

        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"trades_{today}.jsonl"

        with open(log_file) as f:
            data = json.loads(f.readline())

        assert data["status"] == "rejected"
        assert data["reason"] == "Position limit exceeded"

    def test_get_trades_for_date(
        self, trade_logger: TradeLogger, sample_signal: TradeSignal
    ):
        """Should retrieve trades for a specific date."""
        # Log some trades
        for _ in range(3):
            trade_logger.log_signal(
                signal=sample_signal,
                event_id="12345",
                sport="nfl",
                matchup="KC@BUF",
                strategy_name="nfl_spread",
                executed=True,
            )

        today = datetime.now().strftime("%Y-%m-%d")
        trades = trade_logger.get_trades_for_date(today)

        assert len(trades) == 3

    def test_get_trades_returns_empty_for_no_file(self, trade_logger: TradeLogger):
        """Should return empty list if no log file."""
        trades = trade_logger.get_trades_for_date("2020-01-01")

        assert trades == []


class TestPerformanceTracker:
    """Tests for PerformanceTracker."""

    def test_get_daily_summary_empty(self, trade_logger: TradeLogger):
        """Should return empty summary for no trades."""
        tracker = PerformanceTracker(trade_logger)

        summary = tracker.get_daily_summary("2020-01-01")

        assert summary["total_trades"] == 0
        assert summary["total_pnl"] == 0

    def test_get_daily_summary_with_trades(
        self, trade_logger: TradeLogger, sample_signal: TradeSignal
    ):
        """Should calculate summary for trades."""
        # Log executed trades with P&L
        trade_logger.log_signal(
            signal=sample_signal,
            event_id="1",
            sport="nfl",
            matchup="KC@BUF",
            strategy_name="nfl_spread",
            executed=True,
            pnl=100,
        )
        trade_logger.log_signal(
            signal=sample_signal,
            event_id="2",
            sport="nba",
            matchup="LAL@BOS",
            strategy_name="nba_margin",
            executed=True,
            pnl=-50,
        )
        trade_logger.log_signal(
            signal=sample_signal,
            event_id="3",
            sport="nfl",
            matchup="DEN@LAS",
            strategy_name="nfl_spread",
            dry_run=True,
        )

        tracker = PerformanceTracker(trade_logger)
        today = datetime.now().strftime("%Y-%m-%d")
        summary = tracker.get_daily_summary(today)

        assert summary["total_trades"] == 3
        assert summary["executed"] == 2
        assert summary["dry_runs"] == 1
        assert summary["total_pnl"] == 50  # 100 - 50
        assert summary["by_sport"]["nfl"] == 2
        assert summary["by_sport"]["nba"] == 1
