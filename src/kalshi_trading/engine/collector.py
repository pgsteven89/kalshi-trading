"""Data collector for capturing live game snapshots and market data."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from kalshi_trading.clients.espn import ESPNClient, GameState, Sport
from kalshi_trading.clients.kalshi import KalshiClient
from kalshi_trading.monitoring.database import TradingDatabase

logger = structlog.get_logger()


@dataclass
class MarketSnapshot:
    """Snapshot of market prices at a point in time."""

    timestamp: str
    event_id: str
    ticker: str
    sport: str
    yes_bid: int
    yes_ask: int
    no_bid: int
    no_ask: int
    volume: int
    open_interest: int


class DataCollector:
    """
    Collects game state and market snapshots during live games.

    Runs periodically to capture data for future backtesting.
    Collects both ESPN game data and Kalshi market prices.

    Example:
        collector = DataCollector(
            espn_client=espn,
            kalshi_client=kalshi,  # Optional
            db=db,
            interval=30,  # Capture every 30 seconds
        )

        await collector.run()
    """

    def __init__(
        self,
        espn_client: ESPNClient,
        db: TradingDatabase,
        kalshi_client: KalshiClient | None = None,
        market_mapping: dict[str, str] | None = None,
        interval: float = 30.0,
    ):
        """
        Initialize data collector.

        Args:
            espn_client: ESPN API client
            db: Trading database for storage
            kalshi_client: Optional Kalshi client for price data
            market_mapping: Map ESPN event IDs to Kalshi tickers
            interval: Seconds between snapshots
        """
        self.espn = espn_client
        self.kalshi = kalshi_client
        self.db = db
        self.market_mapping = market_mapping or {}
        self.interval = interval
        self._running = False

    async def run(self) -> None:
        """Run data collection loop."""
        self._running = True
        logger.info(
            "Starting data collector",
            interval=self.interval,
            kalshi_enabled=self.kalshi is not None,
        )

        while self._running:
            try:
                await self._collect_cycle()
            except Exception as e:
                logger.exception("Error in collection cycle", error=str(e))

            await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        """Stop data collection."""
        self._running = False
        logger.info("Stopping data collector")

    async def _collect_cycle(self) -> None:
        """Run a single collection cycle."""
        all_games = await self.espn.get_all_live_games()

        game_snapshots = 0
        market_snapshots = 0

        for sport, games in all_games.items():
            for game in games:
                # Store game state
                self.db.insert_game_state(game)
                game_snapshots += 1

                # Store market prices if Kalshi client available
                if self.kalshi:
                    captured = await self._capture_market_prices(game, sport)
                    market_snapshots += captured

        if game_snapshots > 0:
            logger.info(
                "Collected snapshots",
                games=game_snapshots,
                markets=market_snapshots,
            )

    async def _capture_market_prices(self, game: GameState, sport: Sport) -> int:
        """
        Capture Kalshi market prices for a game.

        Args:
            game: Game state from ESPN
            sport: Sport type

        Returns:
            Number of market snapshots captured
        """
        if not self.kalshi:
            return 0

        # Try to find Kalshi markets for this game
        try:
            # Search for markets matching this game
            # Kalshi uses event tickers like "NFL-2426" for events
            sport_prefix = sport.value.upper().replace("-", "")
            
            # Get markets for this sport
            markets_response = await self.kalshi.get_markets(status="open")
            
            captured = 0
            for market in markets_response.markets:
                # Check if this market relates to our game
                # This is a heuristic - real implementation would have better mapping
                if self._market_matches_game(market.ticker, game, sport):
                    self.db.insert_market_snapshot(
                        event_id=game.event_id,
                        ticker=market.ticker,
                        sport=sport.value,
                        yes_bid=market.yes_bid,
                        yes_ask=market.yes_ask,
                        no_bid=market.no_bid,
                        no_ask=market.no_ask,
                        volume=market.volume,
                        open_interest=market.open_interest,
                    )
                    captured += 1

            return captured

        except Exception as e:
            logger.warning("Failed to capture market prices", error=str(e))
            return 0

    def _market_matches_game(
        self,
        ticker: str,
        game: GameState,
        sport: Sport,
    ) -> bool:
        """
        Check if a Kalshi market ticker matches a game.

        This uses heuristics - in production you'd have explicit mapping.
        """
        ticker_upper = ticker.upper()
        
        # Check if market is for correct sport
        sport_prefixes = {
            Sport.NFL: ["NFL"],
            Sport.NBA: ["NBA"],
            Sport.COLLEGE_FOOTBALL: ["CFB", "NCAAF", "COLLEGE"],
        }
        
        prefixes = sport_prefixes.get(sport, [])
        if not any(ticker_upper.startswith(p) for p in prefixes):
            return False

        # Check if team abbreviations appear in ticker
        home = game.home_team.abbreviation.upper()
        away = game.away_team.abbreviation.upper()

        if home in ticker_upper or away in ticker_upper:
            return True

        # Check explicit mapping
        if game.event_id in self.market_mapping:
            return self.market_mapping[game.event_id] == ticker

        return False

    def add_market_mapping(self, event_id: str, ticker: str) -> None:
        """Add explicit mapping from ESPN event to Kalshi ticker."""
        self.market_mapping[event_id] = ticker


async def run_data_collector(
    db_path: Path | None = None,
    kalshi_api_key_id: str | None = None,
    kalshi_private_key_path: Path | None = None,
    kalshi_environment: str = "sandbox",
    interval: float = 30.0,
) -> None:
    """
    Convenience function to run data collector standalone.

    Args:
        db_path: Path to SQLite database
        kalshi_api_key_id: Kalshi API key ID (optional)
        kalshi_private_key_path: Path to Kalshi private key (optional)
        kalshi_environment: Kalshi environment (sandbox/production)
        interval: Collection interval in seconds
    """
    db = TradingDatabase(db_path)
    db.initialize()

    espn = ESPNClient()

    # Initialize Kalshi client if credentials provided
    kalshi: KalshiClient | None = None
    if kalshi_api_key_id and kalshi_private_key_path:
        kalshi = KalshiClient(
            api_key_id=kalshi_api_key_id,
            private_key_path=kalshi_private_key_path,
            environment=kalshi_environment,
        )

    async with espn:
        if kalshi:
            async with kalshi:
                collector = DataCollector(
                    espn_client=espn,
                    kalshi_client=kalshi,
                    db=db,
                    interval=interval,
                )
                await collector.run()
        else:
            collector = DataCollector(
                espn_client=espn,
                db=db,
                interval=interval,
            )
            await collector.run()
