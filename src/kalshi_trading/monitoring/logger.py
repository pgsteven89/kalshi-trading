"""Trade logging and audit trail."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from kalshi_trading.engine.risk import TradeRecord
from kalshi_trading.strategies.base import TradeSignal

logger = structlog.get_logger()


@dataclass
class TradeLogEntry:
    """Complete log entry for a trade."""

    timestamp: str
    event_id: str
    sport: str
    matchup: str
    ticker: str
    signal: str
    side: str
    size: int
    price: int | None
    fill_price: int | None
    status: str  # "executed", "rejected", "dry_run"
    reason: str
    strategy_name: str
    risk_check: bool
    pnl: int = 0


class TradeLogger:
    """
    Logs all trade activity to file and structured logs.

    Creates a JSON Lines file with one trade per line for easy analysis.

    Example:
        logger = TradeLogger(Path("logs"))
        logger.log_signal(signal, game, "nfl_spread", executed=True)
    """

    def __init__(self, log_dir: Path | None = None):
        """
        Initialize trade logger.

        Args:
            log_dir: Directory for log files (created if needed)
        """
        self.log_dir = log_dir or Path("logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Daily log file
        self._current_date: str = ""
        self._log_file: Path | None = None

    def _get_log_file(self) -> Path:
        """Get current day's log file."""
        today = datetime.now().strftime("%Y-%m-%d")

        if today != self._current_date:
            self._current_date = today
            self._log_file = self.log_dir / f"trades_{today}.jsonl"

        return self._log_file  # type: ignore

    def log_signal(
        self,
        signal: TradeSignal,
        event_id: str,
        sport: str,
        matchup: str,
        strategy_name: str,
        executed: bool = False,
        rejected_reason: str | None = None,
        fill_price: int | None = None,
        pnl: int = 0,
        dry_run: bool = False,
    ) -> None:
        """
        Log a trade signal.

        Args:
            signal: The trade signal
            event_id: ESPN event ID
            sport: Sport type (nfl, nba, etc.)
            matchup: Game matchup string
            strategy_name: Name of strategy that generated signal
            executed: Whether trade was executed
            rejected_reason: Reason if rejected
            fill_price: Actual fill price if executed
            pnl: Realized P&L if any
            dry_run: Whether this was a dry run
        """
        # Determine status
        if dry_run:
            status = "dry_run"
        elif executed:
            status = "executed"
        else:
            status = "rejected"

        entry = TradeLogEntry(
            timestamp=datetime.now().isoformat(),
            event_id=event_id,
            sport=sport,
            matchup=matchup,
            ticker=signal.ticker,
            signal=signal.signal.value,
            side=signal.side,
            size=signal.size,
            price=signal.price,
            fill_price=fill_price,
            status=status,
            reason=rejected_reason or signal.reason,
            strategy_name=strategy_name,
            risk_check=not rejected_reason,
            pnl=pnl,
        )

        # Log to structured logger
        logger.info(
            "Trade signal",
            **asdict(entry),
        )

        # Append to file
        self._write_entry(entry)

    def _write_entry(self, entry: TradeLogEntry) -> None:
        """Write entry to log file."""
        log_file = self._get_log_file()

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

    def log_risk_block(
        self,
        signal: TradeSignal,
        reason: str,
        strategy_name: str,
    ) -> None:
        """Log a trade blocked by risk management."""
        logger.warning(
            "Trade blocked by risk",
            ticker=signal.ticker,
            signal=signal.signal.value,
            size=signal.size,
            reason=reason,
            strategy=strategy_name,
        )

    def get_trades_for_date(self, date: str) -> list[TradeLogEntry]:
        """
        Get all trades for a specific date.

        Args:
            date: Date string in YYYY-MM-DD format

        Returns:
            List of trade log entries
        """
        log_file = self.log_dir / f"trades_{date}.jsonl"

        if not log_file.exists():
            return []

        entries = []
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    entries.append(TradeLogEntry(**data))

        return entries


class PerformanceTracker:
    """
    Tracks trading performance metrics.

    Calculates P&L, win rate, and other statistics.
    """

    def __init__(self, trade_logger: TradeLogger):
        """
        Initialize performance tracker.

        Args:
            trade_logger: Trade logger to read from
        """
        self.trade_logger = trade_logger

    def get_daily_summary(self, date: str) -> dict[str, Any]:
        """
        Get summary for a specific date.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            Summary dict with metrics
        """
        trades = self.trade_logger.get_trades_for_date(date)

        if not trades:
            return {
                "date": date,
                "total_trades": 0,
                "executed": 0,
                "rejected": 0,
                "dry_runs": 0,
                "total_pnl": 0,
                "winning_trades": 0,
                "losing_trades": 0,
            }

        executed = [t for t in trades if t.status == "executed"]
        rejected = [t for t in trades if t.status == "rejected"]
        dry_runs = [t for t in trades if t.status == "dry_run"]

        total_pnl = sum(t.pnl for t in trades)
        winning = [t for t in executed if t.pnl > 0]
        losing = [t for t in executed if t.pnl < 0]

        return {
            "date": date,
            "total_trades": len(trades),
            "executed": len(executed),
            "rejected": len(rejected),
            "dry_runs": len(dry_runs),
            "total_pnl": total_pnl,
            "total_pnl_dollars": total_pnl / 100,
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": len(winning) / len(executed) if executed else 0,
            "by_sport": self._group_by_sport(trades),
            "by_strategy": self._group_by_strategy(trades),
        }

    def _group_by_sport(self, trades: list[TradeLogEntry]) -> dict[str, int]:
        """Group trade count by sport."""
        counts: dict[str, int] = {}
        for trade in trades:
            counts[trade.sport] = counts.get(trade.sport, 0) + 1
        return counts

    def _group_by_strategy(self, trades: list[TradeLogEntry]) -> dict[str, int]:
        """Group trade count by strategy."""
        counts: dict[str, int] = {}
        for trade in trades:
            counts[trade.strategy_name] = counts.get(trade.strategy_name, 0) + 1
        return counts

    def get_period_summary(self, start_date: str, end_date: str) -> dict[str, Any]:
        """
        Get summary for a date range.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Aggregated summary
        """
        from datetime import datetime, timedelta

        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        all_trades: list[TradeLogEntry] = []
        current = start

        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            all_trades.extend(self.trade_logger.get_trades_for_date(date_str))
            current += timedelta(days=1)

        executed = [t for t in all_trades if t.status == "executed"]

        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_trades": len(all_trades),
            "executed": len(executed),
            "total_pnl": sum(t.pnl for t in all_trades),
            "total_pnl_dollars": sum(t.pnl for t in all_trades) / 100,
        }
