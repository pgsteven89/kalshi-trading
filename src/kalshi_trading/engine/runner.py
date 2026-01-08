"""Main trading engine runner."""

import asyncio
import signal
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from kalshi_trading.clients.espn import ESPNClient, GameState, Sport
from kalshi_trading.clients.kalshi import KalshiClient
from kalshi_trading.clients.models import CreateOrderRequest, OrderAction, OrderSide, OrderType
from kalshi_trading.config import load_all_strategies
from kalshi_trading.strategies.base import MarketState, Signal, TradeSignal, TradingStrategy

from .risk import RiskLimits, RiskManager

logger = structlog.get_logger()


class TradingEngine:
    """
    Main trading engine that orchestrates data collection and trade execution.

    Example:
        engine = TradingEngine(
            kalshi_client=kalshi,
            espn_client=espn,
            strategies_dir=Path("config/strategies"),
            risk_limits=RiskLimits(max_position_size=50),
        )

        await engine.run()
    """

    def __init__(
        self,
        kalshi_client: KalshiClient,
        espn_client: ESPNClient,
        strategies_dir: Path | None = None,
        strategies: list[TradingStrategy] | None = None,
        risk_limits: RiskLimits | None = None,
        poll_interval: float = 30.0,
        dry_run: bool = True,
    ):
        """
        Initialize trading engine.

        Args:
            kalshi_client: Configured Kalshi API client
            espn_client: Configured ESPN API client
            strategies_dir: Directory containing strategy YAML files
            strategies: Pre-loaded strategies (alternative to strategies_dir)
            risk_limits: Risk management configuration
            poll_interval: Seconds between polling cycles
            dry_run: If True, log trades but don't execute
        """
        self.kalshi = kalshi_client
        self.espn = espn_client
        self.poll_interval = poll_interval
        self.dry_run = dry_run

        # Load strategies
        if strategies:
            self.strategies = strategies
        elif strategies_dir:
            self.strategies = load_all_strategies(strategies_dir)
        else:
            self.strategies = []

        # Initialize risk manager
        self.risk = RiskManager(risk_limits)

        # Control flags
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Market cache
        self._market_cache: dict[str, MarketState] = {}

    async def start(self) -> None:
        """Start the trading engine."""
        self._running = True
        self._shutdown_event.clear()

        logger.info(
            "Starting trading engine",
            strategies=len(self.strategies),
            dry_run=self.dry_run,
            poll_interval=self.poll_interval,
        )

        # Register signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._handle_shutdown)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

    async def stop(self) -> None:
        """Stop the trading engine gracefully."""
        logger.info("Stopping trading engine")
        self._running = False
        self._shutdown_event.set()

    def _handle_shutdown(self) -> None:
        """Handle shutdown signal."""
        logger.info("Shutdown signal received")
        asyncio.create_task(self.stop())

    async def run(self) -> None:
        """
        Main run loop.

        Continuously polls for game updates and evaluates strategies.
        """
        await self.start()

        try:
            while self._running:
                await self._run_cycle()

                # Wait for next poll or shutdown
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.poll_interval,
                    )
                except asyncio.TimeoutError:
                    pass  # Normal timeout, continue loop

        except Exception as e:
            logger.exception("Error in main loop", error=str(e))
        finally:
            await self.stop()

    async def _run_cycle(self) -> None:
        """Run a single polling cycle."""
        try:
            # Reset daily risk tracking
            self.risk.reset_daily()

            # Check if daily limit reached
            if self.risk.is_daily_limit_reached():
                logger.warning("Daily loss limit reached, skipping cycle")
                return

            # Fetch live games
            all_games = await self._fetch_live_games()

            if not all_games:
                logger.debug("No live games")
                return

            # Process each game
            for sport, games in all_games.items():
                for game in games:
                    await self._process_game(game)

        except Exception as e:
            logger.exception("Error in polling cycle", error=str(e))

    async def _fetch_live_games(self) -> dict[Sport, list[GameState]]:
        """Fetch all live games from ESPN."""
        return await self.espn.get_all_live_games()

    async def _process_game(self, game: GameState) -> None:
        """Process a single game through all strategies."""
        log = logger.bind(
            event_id=game.event_id,
            matchup=f"{game.away_team.abbreviation}@{game.home_team.abbreviation}",
        )

        # Get market for this game
        market = await self._get_market_for_game(game)
        if not market:
            log.debug("No market found for game")
            return

        # Get current position
        position = await self._get_position(market.ticker)

        # Evaluate all strategies
        for strategy in self.strategies:
            if not self._is_strategy_applicable(strategy, game):
                continue

            signal = strategy.evaluate(game, market, position)

            if signal and signal.is_actionable:
                await self._handle_signal(signal, log)

    async def _get_market_for_game(self, game: GameState) -> MarketState | None:
        """
        Get Kalshi market for a game.

        This is a simplified implementation - in production you'd
        have a proper mapping from ESPN events to Kalshi tickers.
        """
        # Check cache first
        cache_key = f"{game.sport}:{game.event_id}"
        if cache_key in self._market_cache:
            return self._market_cache[cache_key]

        # In production, implement proper market discovery
        # For now, return None (would need market mapping config)
        return None

    async def _get_position(self, ticker: str) -> Any:
        """Get current position for a market."""
        try:
            positions = await self.kalshi.get_positions(ticker=ticker)
            for pos in positions.market_positions:
                if pos.ticker == ticker:
                    self.risk.update_position(pos)
                    return pos
        except Exception:
            pass
        return None

    def _is_strategy_applicable(self, strategy: TradingStrategy, game: GameState) -> bool:
        """Check if strategy applies to this game's sport."""
        # Check strategy config for target sports
        targets = strategy.config.get("targets", [])
        if not targets:
            return True  # No filter, applies to all

        for target in targets:
            if target.get("sport") == game.sport:
                return True

        return False

    async def _handle_signal(
        self,
        signal: TradeSignal,
        log: Any,
    ) -> None:
        """Handle a trade signal."""
        log = log.bind(
            signal=signal.signal.value,
            ticker=signal.ticker,
            size=signal.size,
        )

        # Check risk limits
        if not self.risk.can_trade(signal):
            log.warning("Trade blocked by risk limits")
            return

        # Adjust signal if needed
        adjusted = self.risk.adjust_signal(signal)

        if adjusted.size == 0:
            log.warning("Trade size reduced to 0")
            return

        if self.dry_run:
            log.info(
                "DRY RUN: Would execute trade",
                side=adjusted.side,
                size=adjusted.size,
                price=adjusted.price,
                reason=adjusted.reason,
            )
            return

        # Execute trade
        await self._execute_trade(adjusted, log)

    async def _execute_trade(self, signal: TradeSignal, log: Any) -> None:
        """Execute a trade on Kalshi."""
        try:
            order = CreateOrderRequest(
                ticker=signal.ticker,
                side=OrderSide(signal.side),
                action=OrderAction(signal.signal.value),
                type=OrderType.LIMIT if signal.price else OrderType.MARKET,
                count=signal.size,
                yes_price=signal.price if signal.side == "yes" else None,
                no_price=signal.price if signal.side == "no" else None,
            )

            result = await self.kalshi.create_order(order)

            log.info(
                "Order placed",
                order_id=result.order_id,
                status=result.status.value,
            )

            # Record trade in risk manager
            self.risk.record_trade(signal, signal.price or 0)

        except Exception as e:
            log.exception("Failed to execute trade", error=str(e))


async def run_trading_engine(
    kalshi_api_key_id: str,
    kalshi_private_key_path: Path,
    strategies_dir: Path,
    environment: str = "sandbox",
    dry_run: bool = True,
    risk_limits: RiskLimits | None = None,
) -> None:
    """
    Convenience function to run the trading engine.

    Args:
        kalshi_api_key_id: Kalshi API key ID
        kalshi_private_key_path: Path to RSA private key
        strategies_dir: Directory with strategy YAML files
        environment: "sandbox" or "production"
        dry_run: If True, only log trades
        risk_limits: Risk management configuration
    """
    kalshi = KalshiClient(
        api_key_id=kalshi_api_key_id,
        private_key_path=kalshi_private_key_path,
        environment=environment,
    )
    espn = ESPNClient()

    async with kalshi, espn:
        engine = TradingEngine(
            kalshi_client=kalshi,
            espn_client=espn,
            strategies_dir=strategies_dir,
            risk_limits=risk_limits,
            dry_run=dry_run,
        )

        await engine.run()
