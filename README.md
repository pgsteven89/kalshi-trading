# Kalshi/ESPN Trading System

A spec-driven, test-driven trading system that uses ESPN sports data to inform automated buying/selling of Kalshi event contracts.

## Features

- 📊 **ESPN Integration**: Real-time scores for NFL, NBA, and College Football
- 📈 **Kalshi Trading**: Automated event contract trading via Kalshi API
- ⚙️ **Configurable Strategies**: YAML-based strategy configuration
- 🛡️ **Risk Management**: Position limits and daily loss caps
- 📦 **SQLite Database**: Store trades, signals, and game states
- 🔄 **Backtesting**: Replay historical data through strategies
- ✅ **Test-Driven**: 95+ tests with pytest

## Quick Start

### Prerequisites

- Python 3.11+
- Kalshi account with API key (get from [kalshi.com](https://kalshi.com))

### Installation

```bash
cd Kalshi_trading
pip install -e ".[dev]"

# Copy environment template
copy .env.example .env
# Edit .env with your API credentials
```

## CLI Commands

### 1. Collect Data (for backtesting)

Capture live game states and market prices:

```bash
# Collect ESPN data only (no credentials needed)
kalshi-trading collect

# Collect ESPN + Kalshi price data
kalshi-trading collect --key-id YOUR_KEY --key-path path/to/key.pem

# Custom interval (default: 30 seconds)
kalshi-trading collect --interval 60
```

### 2. Run Backtest

Replay historical data through your strategies:

```bash
# Backtest all collected data
kalshi-trading backtest

# Backtest specific date range
kalshi-trading backtest --start 2026-01-01 --end 2026-01-08

# Backtest by sport
kalshi-trading backtest --sport nfl
```

### 3. Run Trading

Execute trading strategies:

```bash
# Dry run mode (default - logs only, no trades)
kalshi-trading trade --key-id YOUR_KEY --key-path path/to/key.pem

# Live trading on sandbox (fake money)
kalshi-trading trade --key-id YOUR_KEY --key-path path/to/key.pem --live

# Live trading on production (REAL MONEY - be careful!)
kalshi-trading trade --key-id YOUR_KEY --key-path path/to/key.pem --live --env production
```

### Options

| Flag | Description |
|------|-------------|
| `--config` | Path to strategies directory (default: `config/strategies`) |
| `--key-id` | Kalshi API key ID |
| `--key-path` | Path to RSA private key file |
| `--env` | Environment: `sandbox` (default) or `production` |
| `--live` | Execute real trades (default: dry run) |
| `--max-position` | Max contracts per market (default: 100) |
| `--max-daily-loss` | Max daily loss in dollars (default: $500) |
| `--interval` | Polling interval in seconds (default: 30) |

## Strategies

Strategies are configured in YAML files in `config/strategies/`:

| Strategy | Sport | Description |
|----------|-------|-------------|
| `nfl_spread.yaml` | NFL | Buy when team leads by 7+ in 4th quarter |
| `nfl_blowout.yaml` | NFL | Buy when team leads by 14+ in 2nd half |
| `nba_close_late.yaml` | NBA | Trade tight games in final 5 minutes |
| `nba_blowout.yaml` | NBA | Buy when team leads by 15+ in 4th |
| `cfb_leading_late.yaml` | CFB | Buy when team leads by 10+ in 4th |
| `cfb_garbage_time.yaml` | CFB | Fade 21+ point blowouts |

### Example Strategy

```yaml
# config/strategies/nfl_spread.yaml
name: nfl_leading_late
description: Buy YES when team is leading by 7+ in 4th quarter
enabled: true

entry_conditions:
  - type: score_margin
    params:
      min_margin: 7
      direction: leading
  - type: game_time
    params:
      min_period: 4

trade:
  side: yes
  size: 10

risk:
  max_position: 50
  stop_loss: 100
```

## Project Structure

```
├── src/kalshi_trading/
│   ├── clients/       # API clients (Kalshi, ESPN)
│   ├── strategies/    # Trading strategy engine
│   ├── engine/        # Runner, risk, backtester, collector
│   ├── config/        # YAML configuration loading
│   └── monitoring/    # Database, logging, analytics
├── config/
│   ├── strategies/    # Strategy YAML files
│   └── markets.yaml   # Market mapping config
├── data/              # SQLite database (created on first run)
├── specs/             # API specifications
└── tests/             # Test suite (95+ tests)
```

## Database

All data is stored in SQLite (`data/trading.db`):

| Table | Purpose |
|-------|---------|
| `trades` | Executed and dry-run trades |
| `signals` | All generated signals |
| `game_states` | ESPN game snapshots |
| `market_snapshots` | Kalshi price snapshots |
| `daily_summary` | Aggregated daily stats |

### Query Example

```python
from kalshi_trading.monitoring import TradingDatabase

db = TradingDatabase()

# Get performance by strategy
db.get_strategy_performance("nfl_spread")

# Get performance by sport
db.get_performance_by_sport()

# Get recent trades
db.get_recent_trades(limit=50)
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov

# Run specific test file
pytest tests/unit/test_strategies.py -v
```

## Development

This project follows **spec-driven** and **test-driven development**:

1. Specifications are documented in `specs/`
2. Tests are written before implementation
3. All code must pass tests before merge

## License

MIT
