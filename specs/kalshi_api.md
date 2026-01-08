# Kalshi API Specification

This document specifies our interface with the Kalshi REST API.

## Environments

| Environment | Base URL |
|-------------|----------|
| Sandbox | `https://demo.kalshi.com/trade-api/v2` |
| Production | `https://trading-api.kalshi.com/trade-api/v2` |

## Authentication

Kalshi uses RSA-PSS signature authentication with three required headers:

| Header | Description |
|--------|-------------|
| `KALSHI-ACCESS-KEY` | Your API Key ID |
| `KALSHI-ACCESS-TIMESTAMP` | Current Unix timestamp in milliseconds |
| `KALSHI-ACCESS-SIGNATURE` | RSA-PSS SHA256 signed request hash, base64 encoded |

### Signature Generation

```
message = timestamp + method + path
signature = rsa_pss_sign(private_key, message, sha256)
header_value = base64_encode(signature)
```

**Note**: Path should NOT include query parameters when signing.

## Endpoints

### Markets

#### GET /markets
List available markets with optional filtering.

**Query Parameters:**
- `event_ticker`: Filter by event
- `series_ticker`: Filter by series
- `status`: Filter by status (`open`, `closed`, `settled`)
- `limit`: Max results (default 100)
- `cursor`: Pagination cursor

**Response Model:**
```python
class Market:
    ticker: str
    event_ticker: str
    title: str
    status: str  # "open", "closed", "settled"
    yes_bid: int  # Best bid for YES in cents
    yes_ask: int  # Best ask for YES in cents
    no_bid: int
    no_ask: int
    volume: int
    open_interest: int
```

### Orders

#### POST /portfolio/orders
Create a new order.

**Request Body:**
```python
class CreateOrderRequest:
    ticker: str
    side: str      # "yes" or "no"
    action: str    # "buy" or "sell"
    type: str      # "limit" or "market"
    count: int     # Number of contracts
    price: int     # Price in cents (for limit orders)
```

**Response Model:**
```python
class Order:
    order_id: str
    ticker: str
    status: str  # "pending", "filled", "canceled"
    side: str
    action: str
    count: int
    remaining_count: int
    price: int
    created_time: datetime
```

#### GET /portfolio/orders
List your orders.

#### DELETE /portfolio/orders/{order_id}
Cancel an order.

### Portfolio

#### GET /portfolio/balance
Get account balance.

```python
class Balance:
    balance: int  # Available balance in cents
    payout: int   # Pending payout
```

#### GET /portfolio/positions
Get open positions.

```python
class Position:
    ticker: str
    market_exposure: int
    position: int  # Positive = long YES, negative = short YES
    realized_pnl: int
```

## Rate Limits

Rate limits are not published. Our implementation uses:
- 10 requests/second for market data
- 5 requests/second for trading operations
- Exponential backoff on 429 responses

## Error Handling

All errors return JSON:
```python
class KalshiError:
    error: str
    message: str
    code: int
```
