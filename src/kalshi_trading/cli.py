"""Command-line interface for Kalshi Trading System."""

import argparse
import asyncio
import sys
from pathlib import Path

from kalshi_trading.engine import RiskLimits, run_trading_engine, run_data_collector, run_backtest


def create_main_parser() -> argparse.ArgumentParser:
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        description="Kalshi/ESPN Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Trading command
    trade_parser = subparsers.add_parser(
        "trade",
        help="Run the trading engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in dry-run mode (default)
  kalshi-trading trade --config config/strategies

  # Run with live trading (careful!)
  kalshi-trading trade --config config/strategies --live

  # Use production environment
  kalshi-trading trade --config config/strategies --env production --live
        """,
    )
    add_trading_args(trade_parser)

    # Collect command
    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect live game and market data for backtesting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect ESPN data only (no Kalshi credentials needed)
  kalshi-trading collect

  # Collect ESPN + Kalshi price data
  kalshi-trading collect --key-id YOUR_KEY --key-path key.pem

  # Custom interval
  kalshi-trading collect --interval 60
        """,
    )
    add_collect_args(collect_parser)

    # Backtest command
    backtest_parser = subparsers.add_parser(
        "backtest",
        help="Run backtest on historical data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backtest all strategies
  kalshi-trading backtest

  # Backtest specific date range
  kalshi-trading backtest --start 2026-01-01 --end 2026-01-08

  # Backtest NFL only
  kalshi-trading backtest --sport nfl
        """,
    )
    add_backtest_args(backtest_parser)

    return parser


def add_trading_args(parser: argparse.ArgumentParser) -> None:
    """Add trading-related arguments."""
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=Path("config/strategies"),
        help="Path to strategies directory (default: config/strategies)",
    )
    parser.add_argument(
        "--key-id",
        type=str,
        help="Kalshi API key ID (or set KALSHI_API_KEY_ID env var)",
    )
    parser.add_argument(
        "--key-path",
        type=Path,
        help="Path to RSA private key (or set KALSHI_PRIVATE_KEY_PATH env var)",
    )
    parser.add_argument(
        "--env",
        choices=["sandbox", "production"],
        default="sandbox",
        help="Kalshi environment (default: sandbox)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute real trades (default: dry run only)",
    )
    parser.add_argument(
        "--max-position",
        type=int,
        default=100,
        help="Maximum position size per market (default: 100)",
    )
    parser.add_argument(
        "--max-daily-loss",
        type=int,
        default=500,
        help="Maximum daily loss in dollars (default: $500)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=30.0,
        help="Polling interval in seconds (default: 30)",
    )


def add_collect_args(parser: argparse.ArgumentParser) -> None:
    """Add data collection arguments."""
    parser.add_argument(
        "--key-id",
        type=str,
        help="Kalshi API key ID (optional - enables price collection)",
    )
    parser.add_argument(
        "--key-path",
        type=Path,
        help="Path to RSA private key (optional - enables price collection)",
    )
    parser.add_argument(
        "--env",
        choices=["sandbox", "production"],
        default="sandbox",
        help="Kalshi environment (default: sandbox)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="Collection interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/trading.db"),
        help="Path to SQLite database (default: data/trading.db)",
    )


def add_backtest_args(parser: argparse.ArgumentParser) -> None:
    """Add backtesting arguments."""
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=Path("config/strategies"),
        help="Path to strategies directory (default: config/strategies)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/trading.db"),
        help="Path to SQLite database (default: data/trading.db)",
    )
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--sport",
        type=str,
        choices=["nfl", "nba", "college-football"],
        help="Filter by sport",
    )


def get_credentials(args: argparse.Namespace, required: bool = True) -> tuple[str | None, Path | None]:
    """Get API credentials from args or environment."""
    import os

    key_id = getattr(args, "key_id", None) or os.environ.get("KALSHI_API_KEY_ID")
    key_path = getattr(args, "key_path", None) or os.environ.get("KALSHI_PRIVATE_KEY_PATH")

    if required:
        if not key_id:
            print("Error: Kalshi API key ID required. Use --key-id or set KALSHI_API_KEY_ID")
            sys.exit(1)
        if not key_path:
            print("Error: RSA key path required. Use --key-path or set KALSHI_PRIVATE_KEY_PATH")
            sys.exit(1)

    if key_path:
        key_path = Path(key_path)
        if not key_path.exists():
            print(f"Error: RSA key file not found: {key_path}")
            sys.exit(1)

    return key_id, key_path


def cmd_trade(args: argparse.Namespace) -> None:
    """Run trading engine."""
    if not args.config.exists():
        print(f"Error: Strategies directory not found: {args.config}")
        sys.exit(1)

    key_id, key_path = get_credentials(args, required=True)

    risk_limits = RiskLimits(
        max_position_size=args.max_position,
        max_daily_loss=args.max_daily_loss * 100,
    )

    if args.live and args.env == "production":
        print("\n⚠️  WARNING: You are about to run LIVE TRADING on PRODUCTION!")
        print(f"   Max position: {args.max_position} contracts")
        print(f"   Max daily loss: ${args.max_daily_loss}")
        response = input("\nType 'yes' to confirm: ")
        if response.lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    print("\n🚀 Kalshi/ESPN Trading System")
    print(f"   Environment: {args.env}")
    print(f"   Mode: {'LIVE' if args.live else 'DRY RUN'}")
    print(f"   Strategies: {args.config}")
    print(f"   Poll interval: {args.poll_interval}s")
    print()

    try:
        asyncio.run(
            run_trading_engine(
                kalshi_api_key_id=key_id,
                kalshi_private_key_path=key_path,
                strategies_dir=args.config,
                environment=args.env,
                dry_run=not args.live,
                risk_limits=risk_limits,
            )
        )
    except KeyboardInterrupt:
        print("\nShutdown requested.")


def cmd_collect(args: argparse.Namespace) -> None:
    """Run data collector."""
    key_id, key_path = get_credentials(args, required=False)

    print("\n📊 Kalshi/ESPN Data Collector")
    print(f"   Database: {args.db}")
    print(f"   Interval: {args.interval}s")
    print(f"   Kalshi prices: {'ENABLED' if key_id else 'DISABLED (no credentials)'}")
    print("\n   Collecting data... (Ctrl+C to stop)\n")

    try:
        asyncio.run(
            run_data_collector(
                db_path=args.db,
                kalshi_api_key_id=key_id,
                kalshi_private_key_path=key_path,
                kalshi_environment=getattr(args, "env", "sandbox"),
                interval=args.interval,
            )
        )
    except KeyboardInterrupt:
        print("\nData collection stopped.")


def cmd_backtest(args: argparse.Namespace) -> None:
    """Run backtester."""
    if not args.config.exists():
        print(f"Error: Strategies directory not found: {args.config}")
        sys.exit(1)

    if not args.db.exists():
        print(f"Error: Database not found: {args.db}")
        print("Run 'kalshi-trading collect' first to gather data.")
        sys.exit(1)

    print("\n📈 Running Backtest...")
    print(f"   Strategies: {args.config}")
    print(f"   Database: {args.db}")
    if args.start:
        print(f"   Start date: {args.start}")
    if args.end:
        print(f"   End date: {args.end}")
    if args.sport:
        print(f"   Sport: {args.sport}")
    print()

    result = run_backtest(
        db_path=args.db,
        strategies_dir=args.config,
        start_date=args.start,
        end_date=args.end,
        sport=args.sport,
    )

    # Result is already printed by run_backtest


def main() -> None:
    """Main entry point."""
    parser = create_main_parser()
    args = parser.parse_args()

    if args.command == "trade":
        cmd_trade(args)
    elif args.command == "collect":
        cmd_collect(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    else:
        # Default to trade for backwards compatibility
        if len(sys.argv) > 1 and not sys.argv[1] in ["trade", "collect", "backtest", "-h", "--help"]:
            # Old-style usage, parse as trade command
            parser = argparse.ArgumentParser()
            add_trading_args(parser)
            args = parser.parse_args()
            cmd_trade(args)
        else:
            parser.print_help()


if __name__ == "__main__":
    main()
