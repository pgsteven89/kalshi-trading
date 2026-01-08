# Configuration Schema

This document defines the configuration file formats for the trading system.

## Environment Configuration (.env)

```ini
# Kalshi Credentials
KALSHI_API_KEY_ID=<key_id>
KALSHI_PRIVATE_KEY_PATH=<path_to_pem>
KALSHI_ENVIRONMENT=sandbox|production

# Risk Limits
MAX_POSITION_SIZE=100
MAX_DAILY_LOSS=500
MAX_EXPOSURE_PER_MARKET=200

# Logging
LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
```

## Settings Model

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Kalshi
    kalshi_api_key_id: str
    kalshi_private_key_path: Path
    kalshi_environment: Literal["sandbox", "production"] = "sandbox"
    
    # Risk
    max_position_size: int = 100
    max_daily_loss: int = 500
    max_exposure_per_market: int = 200
    
    # Logging
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
```

## Strategy Configuration (YAML)

Location: `config/strategies/<name>.yaml`

### Schema

```yaml
# Strategy metadata
name: string           # Unique identifier
description: string    # Human-readable description
enabled: boolean       # Whether strategy is active

# Target sports/leagues
targets:
  - sport: nfl|nba|college-football
    
# Entry conditions (ALL must be true to trigger)
entry_conditions:
  - type: score_margin
    params:
      min_margin: number   # Minimum point difference
      direction: leading|trailing  # Which team
      
  - type: game_time
    params:
      min_period: number   # Minimum quarter/half
      max_clock: number    # Maximum seconds remaining

# Trade parameters
trade:
  side: yes|no
  action: buy|sell
  size: number           # Contract count
  price_type: market|limit
  limit_offset: number   # Cents from current price (for limit)

# Risk overrides (optional, uses defaults if not specified)
risk:
  max_position: number
  stop_loss: number      # Exit if position loses this amount
```

### Example: NFL Spread Strategy

```yaml
name: nfl_leading_late
description: Buy YES when team is leading by 7+ in 4th quarter
enabled: true

targets:
  - sport: nfl

entry_conditions:
  - type: score_margin
    params:
      min_margin: 7
      direction: leading
      
  - type: game_time
    params:
      min_period: 4
      max_clock: 900  # 15 minutes

trade:
  side: yes
  action: buy
  size: 10
  price_type: limit
  limit_offset: 2

risk:
  max_position: 50
  stop_loss: 100
```

## Market Mapping Configuration

Location: `config/markets.yaml`

Maps ESPN events to Kalshi market tickers.

```yaml
# Pattern-based matching
patterns:
  - sport: nfl
    event_pattern: "{away_team} at {home_team}"
    kalshi_pattern: "NFL-{game_id}-{team}"
    
# Explicit mappings (for when patterns don't work)
explicit:
  - espn_event_id: "401547417"
    kalshi_ticker: "NFL-2426-KC"
```
