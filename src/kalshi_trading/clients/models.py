"""Pydantic models for Kalshi API responses and requests."""

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class OrderSide(str, Enum):
    """Side of the order (yes/no contract)."""

    YES = "yes"
    NO = "no"


class OrderAction(str, Enum):
    """Order action type."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Order type."""

    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(str, Enum):
    """Order status."""

    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELED = "canceled"
    EXPIRED = "expired"


class MarketStatus(str, Enum):
    """Market status."""

    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


class Market(BaseModel):
    """Kalshi market data."""

    ticker: str
    event_ticker: str
    title: str
    status: MarketStatus
    yes_bid: int = Field(description="Best bid for YES in cents")
    yes_ask: int = Field(description="Best ask for YES in cents")
    no_bid: int = Field(description="Best bid for NO in cents")
    no_ask: int = Field(description="Best ask for NO in cents")
    volume: int = 0
    open_interest: int = 0


class MarketsResponse(BaseModel):
    """Response from GET /markets endpoint."""

    markets: list[Market]
    cursor: str | None = None


class CreateOrderRequest(BaseModel):
    """Request body for POST /portfolio/orders."""

    ticker: str
    side: OrderSide
    action: OrderAction
    type: OrderType
    count: int = Field(gt=0, description="Number of contracts")
    # Price in cents, required for limit orders
    yes_price: int | None = Field(default=None, ge=1, le=99)
    no_price: int | None = Field(default=None, ge=1, le=99)


class Order(BaseModel):
    """Kalshi order data."""

    order_id: str
    ticker: str
    status: OrderStatus
    side: OrderSide
    action: OrderAction
    type: OrderType
    count: int
    remaining_count: int
    yes_price: int | None = None
    no_price: int | None = None
    created_time: datetime


class OrdersResponse(BaseModel):
    """Response from GET /portfolio/orders."""

    orders: list[Order]
    cursor: str | None = None


class Balance(BaseModel):
    """Account balance information."""

    balance: int = Field(description="Available balance in cents")
    payout: int = Field(description="Pending payout in cents")


class Position(BaseModel):
    """Open position data."""

    ticker: str
    market_exposure: int
    position: int = Field(description="Positive = long YES, negative = short")
    realized_pnl: int


class PositionsResponse(BaseModel):
    """Response from GET /portfolio/positions."""

    market_positions: list[Position]
    cursor: str | None = None


class KalshiError(BaseModel):
    """Kalshi API error response."""

    error: str
    message: str
    code: int | None = None
