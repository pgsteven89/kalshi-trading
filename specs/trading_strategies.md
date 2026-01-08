# Trading Strategies Specification

This document defines how trading strategies are structured and executed.

## Strategy Interface

All strategies implement this interface:

```python
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass

class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

@dataclass
class TradeSignal:
    signal: Signal
    ticker: str
    side: str          # "yes" or "no"
    size: int          # Number of contracts
    price: int | None  # Limit price in cents, None for market
    reason: str        # Human-readable explanation

class TradingStrategy(ABC):
    @abstractmethod
    def evaluate(
        self,
        game_state: GameState,
        market_state: MarketState,
        position: Position | None,
    ) -> TradeSignal | None:
        """
        Evaluate current state and return a trade signal if conditions met.
        Returns None if no action should be taken.
        """
        pass
    
    @abstractmethod
    def validate_config(self, config: dict) -> bool:
        """Validate strategy configuration."""
        pass
```

## Data Models

### GameState

```python
@dataclass
class GameState:
    event_id: str
    sport: str         # "nfl", "nba", "college-football"
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    period: int        # Quarter/half number
    clock_seconds: float
    status: str        # "pre", "in", "post"
    
    @property
    def margin(self) -> int:
        """Positive = home leading, negative = away leading."""
        return self.home_score - self.away_score
    
    @property
    def is_live(self) -> bool:
        return self.status == "in"
```

### MarketState

```python
@dataclass
class MarketState:
    ticker: str
    yes_bid: int       # Best bid in cents
    yes_ask: int       # Best ask in cents
    no_bid: int
    no_ask: int
    last_price: int
    volume: int
    status: str        # "open", "closed"
```

## Strategy Types

### 1. Score Margin Strategy

Triggers when point spread exceeds threshold.

**Configuration:**
```yaml
type: score_margin
params:
  min_margin: 7      # Minimum point difference
  direction: leading # "leading" or "trailing"
```

**Logic:**
```python
def evaluate(self, game, market, position):
    if not game.is_live:
        return None
    
    margin = abs(game.margin)
    if margin < self.config.min_margin:
        return None
    
    # Determine if target team is leading
    if self.config.direction == "leading":
        target_leading = game.margin > 0  # Assuming we track home team
    else:
        target_leading = game.margin < 0
    
    if target_leading:
        return TradeSignal(
            signal=Signal.BUY,
            ticker=market.ticker,
            side="yes",
            size=self.config.size,
            price=market.yes_ask + 2,  # Slight premium
            reason=f"Margin {margin} exceeds threshold {self.config.min_margin}"
        )
    
    return None
```

### 2. Game Time Strategy

Filters by game clock position.

**Configuration:**
```yaml
type: game_time
params:
  min_period: 4        # Must be in 4th quarter
  max_clock: 300       # 5 minutes or less remaining
```

### 3. Composite Strategy

Combines multiple conditions.

**Configuration:**
```yaml
type: composite
operator: and  # "and" or "or"
conditions:
  - type: score_margin
    params: {...}
  - type: game_time
    params: {...}
```

## Risk Integration

All strategies respect risk limits:

```python
def execute_signal(signal: TradeSignal, risk: RiskManager):
    # Check position limits
    if not risk.can_open_position(signal.ticker, signal.size):
        log.warning("Position limit would be exceeded, reducing size")
        signal.size = risk.max_allowed_size(signal.ticker)
    
    # Check daily loss limit
    if risk.daily_loss_limit_reached():
        log.warning("Daily loss limit reached, blocking trade")
        return None
    
    # Check per-market exposure
    if not risk.can_increase_exposure(signal.ticker, signal.size * signal.price):
        log.warning("Market exposure limit reached")
        return None
    
    return execute_trade(signal)
```

## Strategy Lifecycle

1. **Load**: Read YAML config, validate parameters
2. **Initialize**: Connect to data sources
3. **Evaluate**: Called on each game state update
4. **Execute**: Trade signals passed to executor
5. **Monitor**: Track performance metrics
6. **Shutdown**: Close positions (optional), save state
