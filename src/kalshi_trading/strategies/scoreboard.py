"""Score-based trading strategies."""

from typing import Any

from kalshi_trading.clients.espn import GameState
from kalshi_trading.clients.models import Position

from .base import MarketState, Signal, TradeSignal, TradingStrategy


class ScoreMarginStrategy(TradingStrategy):
    """
    Strategy that triggers based on point margin.

    Generates a BUY signal when a team is leading (or trailing)
    by at least a specified margin.

    Config:
        min_margin: Minimum point difference to trigger (required)
        direction: "leading" or "trailing" (default: "leading")
        side: "yes" or "no" (default: "yes")
        size: Number of contracts (default: 10)
        limit_offset: Cents to add to current price for limit order (default: 2)
    """

    def _validate_config(self) -> None:
        """Validate required configuration."""
        if "min_margin" not in self.config:
            raise ValueError("ScoreMarginStrategy requires 'min_margin' config")

        min_margin = self.config["min_margin"]
        if not isinstance(min_margin, int) or min_margin < 1:
            raise ValueError("min_margin must be a positive integer")

        direction = self.config.get("direction", "leading")
        if direction not in ("leading", "trailing"):
            raise ValueError("direction must be 'leading' or 'trailing'")

    def evaluate(
        self,
        game_state: GameState,
        market_state: MarketState,
        position: Position | None,
    ) -> TradeSignal | None:
        """
        Evaluate if margin conditions are met.

        Returns a BUY signal if:
        - Game is live
        - Market is open
        - Point margin meets threshold
        - Direction matches (leading/trailing)
        """
        # Only trade during live games
        if not game_state.is_live:
            return None

        # Only trade in open markets
        if not market_state.is_open:
            return None

        # Get config values
        min_margin = self.config["min_margin"]
        direction = self.config.get("direction", "leading")
        side = self.config.get("side", "yes")
        size = self.config.get("size", 10)
        limit_offset = self.config.get("limit_offset", 2)

        # Calculate margin (positive = home leading)
        margin = abs(game_state.margin)

        # Check if margin threshold met
        if margin < min_margin:
            return None

        # Check direction
        home_leading = game_state.margin > 0

        if direction == "leading":
            # We want the favored team to be leading
            # For simplicity, assume we're tracking the home team
            if not home_leading:
                return None
        else:  # trailing
            if home_leading:
                return None

        # Calculate limit price
        if side == "yes":
            price = market_state.yes_ask + limit_offset
        else:
            price = market_state.no_ask + limit_offset

        return TradeSignal(
            signal=Signal.BUY,
            ticker=market_state.ticker,
            side=side,
            size=size,
            price=price,
            reason=f"Margin {margin} exceeds threshold {min_margin} ({direction})",
        )


class GameTimeStrategy(TradingStrategy):
    """
    Strategy that filters based on game clock position.

    Only allows trading during specific periods and clock times.
    This is typically used as a filter combined with other strategies.

    Config:
        min_period: Minimum period/quarter to allow trading (required)
        max_clock: Maximum seconds remaining in period (optional)
    """

    def _validate_config(self) -> None:
        """Validate required configuration."""
        if "min_period" not in self.config:
            raise ValueError("GameTimeStrategy requires 'min_period' config")

        min_period = self.config["min_period"]
        if not isinstance(min_period, int) or min_period < 1:
            raise ValueError("min_period must be a positive integer")

    def evaluate(
        self,
        game_state: GameState,
        market_state: MarketState,
        position: Position | None,
    ) -> TradeSignal | None:
        """
        Check if game is in the target time window.

        Returns None (no signal) - this strategy is meant to be
        used as a filter in composite strategies.
        """
        # This is a filter strategy - it doesn't generate signals
        # but can be checked via is_time_valid()
        return None

    def is_time_valid(self, game_state: GameState) -> bool:
        """
        Check if current game time meets criteria.

        Args:
            game_state: Current game state

        Returns:
            True if game is in valid time window
        """
        if not game_state.is_live:
            return False

        min_period = self.config["min_period"]
        max_clock = self.config.get("max_clock")

        # Check period
        if game_state.period < min_period:
            return False

        # Check clock if specified
        if max_clock is not None:
            if game_state.clock_seconds > max_clock:
                return False

        return True


class CompositeStrategy(TradingStrategy):
    """
    Strategy that combines multiple sub-strategies.

    Uses AND/OR logic to combine conditions from sub-strategies.

    Config:
        operator: "and" or "or" (default: "and")
        strategies: List of strategy configs
    """

    def __init__(
        self,
        name: str,
        config: dict[str, Any] | None = None,
        strategies: list[TradingStrategy] | None = None,
    ):
        """
        Initialize composite strategy.

        Args:
            name: Strategy name
            config: Configuration including operator
            strategies: List of sub-strategies
        """
        super().__init__(name, config)
        self.strategies = strategies or []
        self.operator = self.config.get("operator", "and")

    def _validate_config(self) -> None:
        """Validate configuration."""
        operator = self.config.get("operator", "and")
        if operator not in ("and", "or"):
            raise ValueError("operator must be 'and' or 'or'")

    def add_strategy(self, strategy: TradingStrategy) -> None:
        """Add a sub-strategy."""
        self.strategies.append(strategy)

    def evaluate(
        self,
        game_state: GameState,
        market_state: MarketState,
        position: Position | None,
    ) -> TradeSignal | None:
        """
        Evaluate all sub-strategies based on operator.

        For AND: All strategies must return a signal
        For OR: Any strategy returning a signal triggers

        Returns the first non-None signal found.
        """
        if not self.strategies:
            return None

        signals: list[TradeSignal] = []

        for strategy in self.strategies:
            # Handle GameTimeStrategy specially
            if isinstance(strategy, GameTimeStrategy):
                if not strategy.is_time_valid(game_state):
                    if self.operator == "and":
                        return None  # AND fails if any condition fails
                    continue
                continue  # Time strategy doesn't produce signals

            signal = strategy.evaluate(game_state, market_state, position)

            if signal is not None:
                signals.append(signal)
            elif self.operator == "and":
                # AND requires all strategies to signal
                return None

        if signals:
            # Return the first signal (could enhance to merge signals)
            return signals[0]

        return None
