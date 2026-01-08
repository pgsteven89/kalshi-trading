# Kalshi/ESPN Trading System

A spec-driven, test-driven trading system that uses ESPN sports data to inform automated buying/selling of Kalshi event contracts.

## Features

- 📊 **ESPN Integration**: Real-time scores for NFL, NBA, and College Football
- 📈 **Kalshi Trading**: Automated event contract trading via Kalshi API
- ⚙️ **Configurable Strategies**: YAML-based strategy configuration
- 🛡️ **Risk Management**: Position limits and daily loss caps
- ✅ **Test-Driven**: Comprehensive test coverage with pytest

## Quick Start

### Prerequisites

- Python 3.11+
- Kalshi account with API key (get from [kalshi.com](https://kalshi.com))

### Installation

```bash
# Clone and install
cd Kalshi_trading
pip install -e ".[dev]"

# Copy environment template
copy .env.example .env
# Edit .env with your API credentials
```

### Running Tests

```bash
# Run all unit tests
pytest

# Run with coverage
pytest --cov

# Run integration tests (requires API credentials)
pytest -m integration
```

### Usage

```bash
# Start the trading system
kalshi-trading --config config/strategies/nfl_spread.yaml
```

## Project Structure

```
├── src/kalshi_trading/     # Main application code
│   ├── clients/            # API clients (Kalshi, ESPN)
│   ├── strategies/         # Trading strategy implementations
│   ├── engine/             # Core trading engine
│   └── config/             # Configuration loading
├── specs/                  # API and strategy specifications
├── config/                 # Runtime configuration files
└── tests/                  # Test suite
```

## Development

This project follows **spec-driven** and **test-driven development**:

1. Specifications are documented in `specs/`
2. Tests are written before implementation
3. All code must pass tests before merge

## License

MIT
