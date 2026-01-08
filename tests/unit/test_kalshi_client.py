"""Unit tests for Kalshi API client."""

import base64
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from kalshi_trading.clients.kalshi import (
    KalshiAPIError,
    KalshiAuthError,
    KalshiClient,
    KalshiRateLimitError,
)
from kalshi_trading.clients.models import (
    CreateOrderRequest,
    OrderAction,
    OrderSide,
    OrderType,
)


@pytest.fixture
def temp_key_file(tmp_path: Path) -> Path:
    """Create a temporary RSA private key file with a valid key."""
    # Generate a valid RSA private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    # Serialize to PEM format
    pem_data = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_file = tmp_path / "test_key.pem"
    key_file.write_bytes(pem_data)
    return key_file


@pytest.fixture
def kalshi_client(temp_key_file: Path) -> KalshiClient:
    """Create a Kalshi client for testing."""
    return KalshiClient(
        api_key_id="test_key_id",
        private_key_path=temp_key_file,
        environment="sandbox",
    )


class TestKalshiAuthentication:
    """Tests for Kalshi API authentication."""

    def test_signature_generation_format(self, kalshi_client: KalshiClient):
        """Signature should be base64-encoded."""
        timestamp = int(time.time() * 1000)
        signature = kalshi_client._generate_signature(timestamp, "GET", "/markets")

        # Should be valid base64
        decoded = base64.b64decode(signature)
        assert len(decoded) > 0

    def test_auth_headers_included(self, kalshi_client: KalshiClient):
        """All required auth headers should be present."""
        headers = kalshi_client._get_auth_headers("GET", "/markets")

        assert "KALSHI-ACCESS-KEY" in headers
        assert "KALSHI-ACCESS-TIMESTAMP" in headers
        assert "KALSHI-ACCESS-SIGNATURE" in headers

    def test_auth_headers_values(self, kalshi_client: KalshiClient):
        """Auth headers should have correct values."""
        headers = kalshi_client._get_auth_headers("GET", "/markets")

        assert headers["KALSHI-ACCESS-KEY"] == "test_key_id"
        # Timestamp should be recent (within 5 seconds)
        ts = int(headers["KALSHI-ACCESS-TIMESTAMP"])
        now = int(time.time() * 1000)
        assert abs(now - ts) < 5000

    def test_invalid_key_path_raises_error(self, tmp_path: Path):
        """Should raise KalshiAuthError for invalid key path."""
        with pytest.raises(KalshiAuthError, match="not found"):
            KalshiClient(
                api_key_id="test",
                private_key_path=tmp_path / "nonexistent.pem",
            )


class TestKalshiMarkets:
    """Tests for market data retrieval."""

    @pytest.mark.asyncio
    async def test_get_markets_returns_list(
        self, kalshi_client: KalshiClient, sample_kalshi_markets: dict
    ):
        """get_markets should return a MarketsResponse."""
        with patch.object(
            kalshi_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_kalshi_markets

            async with kalshi_client:
                result = await kalshi_client.get_markets()

            assert len(result.markets) == 1
            assert result.markets[0].ticker == "NFL-2426-BUF"

    @pytest.mark.asyncio
    async def test_get_markets_with_filter(
        self, kalshi_client: KalshiClient, sample_kalshi_markets: dict
    ):
        """get_markets should accept filter parameters."""
        with patch.object(
            kalshi_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_kalshi_markets

            async with kalshi_client:
                await kalshi_client.get_markets(event_ticker="NFL-2426", status="open")

            # Verify filters were passed
            call_args = mock_request.call_args
            assert call_args[1]["params"]["event_ticker"] == "NFL-2426"
            assert call_args[1]["params"]["status"] == "open"


class TestKalshiOrders:
    """Tests for order management."""

    @pytest.mark.asyncio
    async def test_create_order_sends_correct_payload(
        self, kalshi_client: KalshiClient, sample_kalshi_order: dict
    ):
        """create_order should send properly formatted request."""
        with patch.object(
            kalshi_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {"order": sample_kalshi_order}

            order_request = CreateOrderRequest(
                ticker="NFL-2426-BUF",
                side=OrderSide.YES,
                action=OrderAction.BUY,
                type=OrderType.LIMIT,
                count=10,
                yes_price=64,
            )

            async with kalshi_client:
                result = await kalshi_client.create_order(order_request)

            assert result.order_id == "ord_abc123"
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_order_calls_delete(
        self, kalshi_client: KalshiClient
    ):
        """cancel_order should call DELETE endpoint."""
        with patch.object(
            kalshi_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {}

            async with kalshi_client:
                await kalshi_client.cancel_order("ord_abc123")

            mock_request.assert_called_once_with(
                "DELETE", "/portfolio/orders/ord_abc123"
            )


class TestKalshiPortfolio:
    """Tests for portfolio operations."""

    @pytest.mark.asyncio
    async def test_get_balance_returns_cents(
        self, kalshi_client: KalshiClient, sample_kalshi_balance: dict
    ):
        """get_balance should return balance in cents."""
        with patch.object(
            kalshi_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_kalshi_balance

            async with kalshi_client:
                result = await kalshi_client.get_balance()

            assert result.balance == 10000  # $100.00 in cents

    @pytest.mark.asyncio
    async def test_get_positions_returns_list(
        self, kalshi_client: KalshiClient, sample_kalshi_position: dict
    ):
        """get_positions should return list of positions."""
        with patch.object(
            kalshi_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "market_positions": [sample_kalshi_position],
                "cursor": None,
            }

            async with kalshi_client:
                result = await kalshi_client.get_positions()

            assert len(result.market_positions) == 1
            assert result.market_positions[0].ticker == "NFL-2426-BUF"


class TestKalshiErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_rate_limit_error(self, kalshi_client: KalshiClient):
        """Should raise KalshiRateLimitError on 429."""
        mock_response = MagicMock()
        mock_response.status_code = 429

        with patch.object(kalshi_client, "_client") as mock_client:
            mock_client.request = AsyncMock(return_value=mock_response)
            kalshi_client._client = mock_client

            with pytest.raises(KalshiRateLimitError):
                await kalshi_client._request("GET", "/markets")

    @pytest.mark.asyncio
    async def test_handles_api_error(self, kalshi_client: KalshiClient):
        """Should raise KalshiAPIError on 4xx/5xx."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "bad_request", "message": "Invalid"}
        mock_response.text = "Invalid"

        with patch.object(kalshi_client, "_client") as mock_client:
            mock_client.request = AsyncMock(return_value=mock_response)
            kalshi_client._client = mock_client

            with pytest.raises(KalshiAPIError) as exc_info:
                await kalshi_client._request("GET", "/markets")

            assert exc_info.value.status_code == 400
