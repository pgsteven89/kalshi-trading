"""Command-line interface for Kalshi Trading System."""

import argparse
import asyncio
import sys
from pathlib import Path

from kalshi_trading.engine import RiskLimits, run_trading_engine


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kalshi/ESPN Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in dry-run mode (default)
  kalshi-trading --config config/strategies

  # Run with live trading (careful!)
  kalshi-trading --config config/strategies --live

  # Use production environment
  kalshi-trading --config config/strategies --env production --live
        """,
    )

    parser.add_argument(
        "--config",
        "-c",
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

    return parser.parse_args()


def get_credentials(args: argparse.Namespace) -> tuple[str, Path]:
    """Get API credentials from args or environment."""
    import os

    key_id = args.key_id or os.environ.get("KALSHI_API_KEY_ID")
    key_path = args.key_path or os.environ.get("KALSHI_PRIVATE_KEY_PATH")

    if not key_id:
        print("Error: Kalshi API key ID required. Use --key-id or set KALSHI_API_KEY_ID")
        sys.exit(1)

    if not key_path:
        print("Error: RSA key path required. Use --key-path or set KALSHI_PRIVATE_KEY_PATH")
        sys.exit(1)

    key_path = Path(key_path)
    if not key_path.exists():
        print(f"Error: RSA key file not found: {key_path}")
        sys.exit(1)

    return key_id, key_path


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Validate strategies directory
    if not args.config.exists():
        print(f"Error: Strategies directory not found: {args.config}")
        sys.exit(1)

    # Get credentials
    key_id, key_path = get_credentials(args)

    # Configure risk limits
    risk_limits = RiskLimits(
        max_position_size=args.max_position,
        max_daily_loss=args.max_daily_loss * 100,  # Convert to cents
    )

    # Confirm live trading
    if args.live and args.env == "production":
        print("\n⚠️  WARNING: You are about to run LIVE TRADING on PRODUCTION!")
        print(f"   Max position: {args.max_position} contracts")
        print(f"   Max daily loss: ${args.max_daily_loss}")
        response = input("\nType 'yes' to confirm: ")
        if response.lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    # Display startup info
    print("\n🚀 Kalshi/ESPN Trading System")
    print(f"   Environment: {args.env}")
    print(f"   Mode: {'LIVE' if args.live else 'DRY RUN'}")
    print(f"   Strategies: {args.config}")
    print(f"   Poll interval: {args.poll_interval}s")
    print()

    # Run the engine
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
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
