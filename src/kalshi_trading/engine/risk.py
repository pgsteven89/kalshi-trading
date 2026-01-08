"""Risk management for trading operations."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from kalshi_trading.clients.models import Position
from kalshi_trading.strategies.base import TradeSignal


@dataclass
class RiskLimits:
    """
    Risk limit configuration.

    All monetary values are in cents.
    """

    max_position_size: int = 100  # Max contracts per position
    max_daily_loss: int = 50000  # $500 max daily loss
    max_exposure_per_market: int = 20000  # $200 max per market
    max_total_exposure: int = 100000  # $1000 max total exposure


@dataclass
class TradeRecord:
    """Record of a completed trade."""

    timestamp: datetime
    ticker: str
    side: str
    action: str  # "buy" or "sell"
    size: int
    price: int  # In cents
    pnl: int = 0  # Realized P&L in cents


@dataclass
class RiskState:
    """
    Current risk state tracking.

    Tracks positions, daily P&L, and exposure.
    """

    positions: dict[str, int] = field(default_factory=dict)  # ticker -> size
    exposure: dict[str, int] = field(default_factory=dict)  # ticker -> exposure in cents
    daily_pnl: int = 0  # Today's realized P&L in cents
    trade_date: date = field(default_factory=date.today)
    trades: list[TradeRecord] = field(default_factory=list)

    def reset_daily(self) -> None:
        """Reset daily tracking for a new day."""
        today = date.today()
        if self.trade_date != today:
            self.daily_pnl = 0
            self.trade_date = today
            self.trades = []

    @property
    def total_exposure(self) -> int:
        """Total exposure across all markets."""
        return sum(self.exposure.values())


class RiskManager:
    """
    Manages trading risk limits.

    Enforces position sizes, daily loss limits, and market exposure.

    Example:
        risk = RiskManager(RiskLimits(max_position_size=50))

        # Check if trade is allowed
        if risk.can_trade(signal):
            adjusted = risk.adjust_signal(signal)
            # Execute trade...
            risk.record_trade(adjusted, fill_price)
    """

    def __init__(self, limits: RiskLimits | None = None):
        """
        Initialize risk manager.

        Args:
            limits: Risk limits configuration
        """
        self.limits = limits or RiskLimits()
        self.state = RiskState()

    def reset_daily(self) -> None:
        """Reset daily P&L tracking."""
        self.state.reset_daily()

    def can_trade(self, signal: TradeSignal) -> bool:
        """
        Check if a trade signal can be executed within risk limits.

        Args:
            signal: Trade signal to evaluate

        Returns:
            True if trade is allowed
        """
        self.state.reset_daily()

        # Check daily loss limit
        if self.state.daily_pnl <= -self.limits.max_daily_loss:
            return False

        # Check position limit
        current_position = self.state.positions.get(signal.ticker, 0)
        new_position = current_position + signal.size

        if abs(new_position) > self.limits.max_position_size:
            # Would exceed position limit
            return False

        # Check market exposure
        if signal.price:
            trade_exposure = signal.size * signal.price
            current_exposure = self.state.exposure.get(signal.ticker, 0)

            if current_exposure + trade_exposure > self.limits.max_exposure_per_market:
                return False

            # Check total exposure
            if self.state.total_exposure + trade_exposure > self.limits.max_total_exposure:
                return False

        return True

    def max_allowed_size(self, ticker: str) -> int:
        """
        Get maximum allowed position size for a ticker.

        Args:
            ticker: Market ticker

        Returns:
            Maximum contracts that can be added
        """
        current = abs(self.state.positions.get(ticker, 0))
        return max(0, self.limits.max_position_size - current)

    def adjust_signal(self, signal: TradeSignal) -> TradeSignal:
        """
        Adjust trade signal to fit within risk limits.

        Reduces size if necessary to stay within limits.

        Args:
            signal: Original trade signal

        Returns:
            Adjusted trade signal (may have reduced size)
        """
        max_size = self.max_allowed_size(signal.ticker)

        if signal.size <= max_size:
            return signal

        # Create adjusted signal with reduced size
        return TradeSignal(
            signal=signal.signal,
            ticker=signal.ticker,
            side=signal.side,
            size=max_size,
            price=signal.price,
            reason=f"{signal.reason} (reduced from {signal.size} to {max_size})",
            timestamp=signal.timestamp,
        )

    def record_trade(
        self,
        signal: TradeSignal,
        fill_price: int,
        realized_pnl: int = 0,
    ) -> None:
        """
        Record a completed trade.

        Args:
            signal: Executed trade signal
            fill_price: Actual fill price in cents
            realized_pnl: Realized P&L from trade in cents
        """
        self.state.reset_daily()

        # Update position
        current = self.state.positions.get(signal.ticker, 0)
        if signal.signal.value == "buy":
            self.state.positions[signal.ticker] = current + signal.size
        else:
            self.state.positions[signal.ticker] = current - signal.size

        # Update exposure
        exposure = signal.size * fill_price
        current_exposure = self.state.exposure.get(signal.ticker, 0)
        self.state.exposure[signal.ticker] = current_exposure + exposure

        # Update daily P&L
        self.state.daily_pnl += realized_pnl

        # Record trade
        self.state.trades.append(
            TradeRecord(
                timestamp=signal.timestamp,
                ticker=signal.ticker,
                side=signal.side,
                action=signal.signal.value,
                size=signal.size,
                price=fill_price,
                pnl=realized_pnl,
            )
        )

    def update_position(self, position: Position) -> None:
        """
        Update state from a Kalshi position.

        Args:
            position: Position from Kalshi API
        """
        self.state.positions[position.ticker] = position.position
        self.state.exposure[position.ticker] = position.market_exposure

    def daily_loss_remaining(self) -> int:
        """Get remaining daily loss budget in cents."""
        self.state.reset_daily()
        return self.limits.max_daily_loss + self.state.daily_pnl

    def is_daily_limit_reached(self) -> bool:
        """Check if daily loss limit has been reached."""
        return self.daily_loss_remaining() <= 0

    def get_risk_summary(self) -> dict[str, Any]:
        """
        Get summary of current risk state.

        Returns:
            Dict with risk metrics
        """
        return {
            "positions": dict(self.state.positions),
            "total_exposure": self.state.total_exposure,
            "daily_pnl": self.state.daily_pnl,
            "daily_loss_remaining": self.daily_loss_remaining(),
            "trades_today": len(self.state.trades),
            "is_daily_limit_reached": self.is_daily_limit_reached(),
        }
