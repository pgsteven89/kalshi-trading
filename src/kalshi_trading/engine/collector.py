"""Data collector for capturing live game snapshots and market data."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from kalshi_trading.clients.espn import ESPNClient, GameState, Sport
from kalshi_trading.monitoring.database import TradingDatabase

logger = structlog.get_logger()


@dataclass
class MarketSnapshot:
    """Snapshot of market prices at a point in time."""

    timestamp: str
    ticker: str
    yes_bid: int
    yes_ask: int
    no_bid: int
    no_ask: int
    volume: int


class DataCollector:
    """
    Collects game state and market snapshots during live games.

    Runs periodically to capture data for future backtesting.

    Example:
        collector = DataCollector(
            espn_client=espn,
            db=db,
            interval=30,  # Capture every 30 seconds
        )

        await collector.run()
    """

    def __init__(
        self,
        espn_client: ESPNClient,
        db: TradingDatabase,
        interval: float = 30.0,
    ):
        """
        Initialize data collector.

        Args:
            espn_client: ESPN API client
            db: Trading database for storage
            interval: Seconds between snapshots
        """
        self.espn = espn_client
        self.db = db
        self.interval = interval
        self._running = False

    async def run(self) -> None:
        """Run data collection loop."""
        self._running = True
        logger.info("Starting data collector", interval=self.interval)

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

        total_snapshots = 0
        for sport, games in all_games.items():
            for game in games:
                self.db.insert_game_state(game)
                total_snapshots += 1

        if total_snapshots > 0:
            logger.info("Collected game snapshots", count=total_snapshots)


async def run_data_collector(
    db_path: Path | None = None,
    interval: float = 30.0,
) -> None:
    """
    Convenience function to run data collector standalone.

    Args:
        db_path: Path to SQLite database
        interval: Collection interval in seconds
    """
    db = TradingDatabase(db_path)
    db.initialize()

    espn = ESPNClient()

    async with espn:
        collector = DataCollector(
            espn_client=espn,
            db=db,
            interval=interval,
        )
        await collector.run()
