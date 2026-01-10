"""Kalshi API client with RSA-PSS authentication."""

import base64
import time
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .models import (
    Balance,
    CreateOrderRequest,
    Market,
    MarketsResponse,
    Order,
    OrdersResponse,
    Position,
    PositionsResponse,
)


class KalshiAuthError(Exception):
    """Raised when authentication fails."""

    pass


class KalshiAPIError(Exception):
    """Raised when API request fails."""

    def __init__(self, message: str, status_code: int, error_code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class KalshiRateLimitError(KalshiAPIError):
    """Raised when rate limit is exceeded."""

    pass


class KalshiClient:
    """
    Async client for Kalshi REST API.

    Uses RSA-PSS signature authentication as required by Kalshi.

    Example:
        client = KalshiClient(
            api_key_id="your_key_id",
            private_key_path=Path("path/to/private_key.pem"),
            environment="sandbox"
        )
        async with client:
            markets = await client.get_markets()
    """

    ENVIRONMENTS = {
        "sandbox": "https://demo.kalshi.com/trade-api/v2",
        "production": "https://api.elections.kalshi.com/trade-api/v2",
    }

    def __init__(
        self,
        api_key_id: str,
        private_key_path: Path | str,
        environment: str = "sandbox",
        timeout: float = 30.0,
    ):
        """
        Initialize Kalshi client.

        Args:
            api_key_id: Your Kalshi API key ID
            private_key_path: Path to RSA private key PEM file
            environment: "sandbox" or "production"
            timeout: Request timeout in seconds
        """
        if environment not in self.ENVIRONMENTS:
            raise ValueError(f"Invalid environment: {environment}")

        self.api_key_id = api_key_id
        self.base_url = self.ENVIRONMENTS[environment]
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

        # Load private key
        self._private_key = self._load_private_key(Path(private_key_path))

    def _load_private_key(self, path: Path) -> rsa.RSAPrivateKey:
        """Load RSA private key from PEM file."""
        try:
            with open(path, "rb") as f:
                key_data = f.read()
            private_key = serialization.load_pem_private_key(key_data, password=None)
            if not isinstance(private_key, rsa.RSAPrivateKey):
                raise KalshiAuthError("Key must be an RSA private key")
            return private_key
        except FileNotFoundError:
            raise KalshiAuthError(f"Private key file not found: {path}")
        except Exception as e:
            raise KalshiAuthError(f"Failed to load private key: {e}")

    def _generate_signature(self, timestamp: int, method: str, path: str) -> str:
        """
        Generate RSA-PSS signature for request authentication.

        Args:
            timestamp: Unix timestamp in milliseconds
            method: HTTP method (GET, POST, etc.)
            path: Request path without query params

        Returns:
            Base64-encoded signature string
        """
        # Message format: timestamp + method + path
        message = f"{timestamp}{method}{path}"
        message_bytes = message.encode("utf-8")

        # Sign with RSA-PSS SHA256
        signature = self._private_key.sign(
            message_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        return base64.b64encode(signature).decode("utf-8")

    def _get_auth_headers(self, method: str, path: str) -> dict[str, str]:
        """Generate authentication headers for a request."""
        timestamp = int(time.time() * 1000)  # Milliseconds
        signature = self._generate_signature(timestamp, method, path)

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp),
            "KALSHI-ACCESS-SIGNATURE": signature,
        }

    async def __aenter__(self) -> "KalshiClient":
        """Enter async context."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make authenticated request to Kalshi API.

        Args:
            method: HTTP method
            path: API path (without base URL)
            params: Query parameters
            json: JSON body for POST/PUT

        Returns:
            Parsed JSON response

        Raises:
            KalshiRateLimitError: If rate limit exceeded
            KalshiAPIError: For other API errors
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        # Path for signing should not include query params
        auth_headers = self._get_auth_headers(method.upper(), path)

        response = await self._client.request(
            method=method,
            url=path,
            params=params,
            json=json,
            headers=auth_headers,
        )

        if response.status_code == 429:
            raise KalshiRateLimitError(
                "Rate limit exceeded", status_code=429, error_code="rate_limit"
            )

        if response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("message", response.text)
                error_code = error_data.get("error")
            except Exception:
                message = response.text
                error_code = None

            raise KalshiAPIError(message, response.status_code, error_code)

        return response.json()

    # -- Market Endpoints --

    async def get_markets(
        self,
        event_ticker: str | None = None,
        status: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> MarketsResponse:
        """
        Get list of markets.

        Args:
            event_ticker: Filter by event ticker
            status: Filter by status (open, closed, settled)
            limit: Max results per page
            cursor: Pagination cursor

        Returns:
            MarketsResponse with list of markets
        """
        params: dict[str, Any] = {"limit": limit}
        if event_ticker:
            params["event_ticker"] = event_ticker
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor

        data = await self._request("GET", "/markets", params=params)
        return MarketsResponse.model_validate(data)

    async def get_market(self, ticker: str) -> Market:
        """
        Get single market by ticker.

        Args:
            ticker: Market ticker

        Returns:
            Market data
        """
        data = await self._request("GET", f"/markets/{ticker}")
        return Market.model_validate(data["market"])

    # -- Order Endpoints --

    async def create_order(self, order: CreateOrderRequest) -> Order:
        """
        Create a new order.

        Args:
            order: Order details

        Returns:
            Created order with ID
        """
        data = await self._request(
            "POST",
            "/portfolio/orders",
            json=order.model_dump(exclude_none=True),
        )
        return Order.model_validate(data["order"])

    async def get_orders(
        self,
        ticker: str | None = None,
        status: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> OrdersResponse:
        """
        Get list of orders.

        Args:
            ticker: Filter by market ticker
            status: Filter by order status
            limit: Max results per page
            cursor: Pagination cursor

        Returns:
            OrdersResponse with list of orders
        """
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor

        data = await self._request("GET", "/portfolio/orders", params=params)
        return OrdersResponse.model_validate(data)

    async def cancel_order(self, order_id: str) -> None:
        """
        Cancel an open order.

        Args:
            order_id: ID of order to cancel
        """
        await self._request("DELETE", f"/portfolio/orders/{order_id}")

    # -- Portfolio Endpoints --

    async def get_balance(self) -> Balance:
        """
        Get account balance.

        Returns:
            Balance with available funds in cents
        """
        data = await self._request("GET", "/portfolio/balance")
        return Balance.model_validate(data)

    async def get_positions(
        self,
        ticker: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> PositionsResponse:
        """
        Get open positions.

        Args:
            ticker: Filter by market ticker
            limit: Max results per page
            cursor: Pagination cursor

        Returns:
            PositionsResponse with list of positions
        """
        params: dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor

        data = await self._request("GET", "/portfolio/positions", params=params)
        return PositionsResponse.model_validate(data)
