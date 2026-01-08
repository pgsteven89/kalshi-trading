"""Unit tests for risk management."""

import pytest
from datetime import datetime

from kalshi_trading.engine.risk import (
    RiskLimits,
    RiskManager,
    RiskState,
    TradeRecord,
)
from kalshi_trading.strategies.base import Signal, TradeSignal


@pytest.fixture
def risk_manager() -> RiskManager:
    """Create a risk manager with default limits."""
    limits = RiskLimits(
        max_position_size=100,
        max_daily_loss=50000,  # $500
        max_exposure_per_market=20000,  # $200
        max_total_exposure=100000,  # $1000
    )
    return RiskManager(limits)


@pytest.fixture
def buy_signal() -> TradeSignal:
    """Create a sample buy signal."""
    return TradeSignal(
        signal=Signal.BUY,
        ticker="NFL-2426-BUF",
        side="yes",
        size=10,
        price=64,  # 64 cents
        reason="Test signal",
    )


class TestRiskLimits:
    """Tests for RiskLimits configuration."""

    def test_default_limits(self):
        """Should have sensible defaults."""
        limits = RiskLimits()

        assert limits.max_position_size == 100
        assert limits.max_daily_loss == 50000
        assert limits.max_exposure_per_market == 20000

    def test_custom_limits(self):
        """Should accept custom limits."""
        limits = RiskLimits(
            max_position_size=50,
            max_daily_loss=10000,
        )

        assert limits.max_position_size == 50
        assert limits.max_daily_loss == 10000


class TestRiskState:
    """Tests for RiskState tracking."""

    def test_initial_state(self):
        """Should start with empty state."""
        state = RiskState()

        assert state.positions == {}
        assert state.exposure == {}
        assert state.daily_pnl == 0

    def test_total_exposure(self):
        """Should calculate total exposure correctly."""
        state = RiskState()
        state.exposure = {
            "TICKER-1": 5000,
            "TICKER-2": 3000,
        }

        assert state.total_exposure == 8000


class TestRiskManagerCanTrade:
    """Tests for can_trade() checks."""

    def test_allows_valid_trade(self, risk_manager: RiskManager, buy_signal: TradeSignal):
        """Should allow trade within limits."""
        assert risk_manager.can_trade(buy_signal) is True

    def test_blocks_exceeds_position_limit(self, risk_manager: RiskManager):
        """Should block trade exceeding position limit."""
        large_signal = TradeSignal(
            signal=Signal.BUY,
            ticker="NFL-2426-BUF",
            side="yes",
            size=150,  # Over 100 limit
            price=64,
        )

        assert risk_manager.can_trade(large_signal) is False

    def test_blocks_exceeds_market_exposure(self, risk_manager: RiskManager):
        """Should block trade exceeding market exposure."""
        # 100 contracts at 64 cents = 6400 cents = $64, should pass
        # But if price is high enough to exceed $200 exposure, should fail
        expensive_signal = TradeSignal(
            signal=Signal.BUY,
            ticker="NFL-2426-BUF",
            side="yes",
            size=100,
            price=250,  # 100 * 250 = 25000 > 20000 limit
        )

        assert risk_manager.can_trade(expensive_signal) is False

    def test_blocks_when_daily_loss_reached(
        self, risk_manager: RiskManager, buy_signal: TradeSignal
    ):
        """Should block trades when daily loss limit reached."""
        # Simulate a big loss
        risk_manager.state.daily_pnl = -50000  # $500 loss

        assert risk_manager.can_trade(buy_signal) is False


class TestRiskManagerAdjustSignal:
    """Tests for adjust_signal() size reduction."""

    def test_no_adjustment_within_limits(
        self, risk_manager: RiskManager, buy_signal: TradeSignal
    ):
        """Should not adjust signal within limits."""
        adjusted = risk_manager.adjust_signal(buy_signal)

        assert adjusted.size == buy_signal.size

    def test_reduces_size_to_fit_limits(self, risk_manager: RiskManager):
        """Should reduce size to fit position limit."""
        # Already have 80 contracts
        risk_manager.state.positions["NFL-2426-BUF"] = 80

        large_signal = TradeSignal(
            signal=Signal.BUY,
            ticker="NFL-2426-BUF",
            side="yes",
            size=50,  # Would be 130, over 100 limit
        )

        adjusted = risk_manager.adjust_signal(large_signal)

        assert adjusted.size == 20  # Reduced to stay at limit


class TestRiskManagerRecordTrade:
    """Tests for record_trade() tracking."""

    def test_records_trade(self, risk_manager: RiskManager, buy_signal: TradeSignal):
        """Should record trade in state."""
        risk_manager.record_trade(buy_signal, fill_price=64)

        assert len(risk_manager.state.trades) == 1
        assert risk_manager.state.trades[0].ticker == "NFL-2426-BUF"

    def test_updates_position(self, risk_manager: RiskManager, buy_signal: TradeSignal):
        """Should update position after trade."""
        risk_manager.record_trade(buy_signal, fill_price=64)

        assert risk_manager.state.positions["NFL-2426-BUF"] == 10

    def test_updates_exposure(self, risk_manager: RiskManager, buy_signal: TradeSignal):
        """Should update exposure after trade."""
        risk_manager.record_trade(buy_signal, fill_price=64)

        # 10 contracts * 64 cents = 640 cents
        assert risk_manager.state.exposure["NFL-2426-BUF"] == 640

    def test_updates_daily_pnl(self, risk_manager: RiskManager, buy_signal: TradeSignal):
        """Should update daily P&L after trade."""
        risk_manager.record_trade(buy_signal, fill_price=64, realized_pnl=-100)

        assert risk_manager.state.daily_pnl == -100


class TestRiskManagerMaxAllowedSize:
    """Tests for max_allowed_size() calculation."""

    def test_full_limit_when_no_position(self, risk_manager: RiskManager):
        """Should return full limit when no position."""
        max_size = risk_manager.max_allowed_size("NFL-2426-BUF")

        assert max_size == 100

    def test_reduced_when_has_position(self, risk_manager: RiskManager):
        """Should reduce by existing position."""
        risk_manager.state.positions["NFL-2426-BUF"] = 30

        max_size = risk_manager.max_allowed_size("NFL-2426-BUF")

        assert max_size == 70


class TestRiskManagerSummary:
    """Tests for risk summary."""

    def test_get_risk_summary(self, risk_manager: RiskManager, buy_signal: TradeSignal):
        """Should return summary dict."""
        risk_manager.record_trade(buy_signal, fill_price=64)

        summary = risk_manager.get_risk_summary()

        assert "positions" in summary
        assert "total_exposure" in summary
        assert "daily_pnl" in summary
        assert summary["trades_today"] == 1
