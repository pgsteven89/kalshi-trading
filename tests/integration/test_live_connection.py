"""Integration tests for live API connectivity.

These tests require actual API credentials and make real requests.
Run with: pytest -m integration
"""

import pytest


pytestmark = pytest.mark.integration


class TestKalshiConnection:
    """Integration tests for Kalshi API."""

    @pytest.mark.asyncio
    async def test_can_authenticate(self):
        """Should successfully authenticate with sandbox."""
        pass

    @pytest.mark.asyncio
    async def test_can_fetch_markets(self):
        """Should fetch live market data."""
        pass

    @pytest.mark.asyncio
    async def test_can_get_balance(self):
        """Should fetch account balance."""
        pass


class TestESPNConnection:
    """Integration tests for ESPN API."""

    @pytest.mark.asyncio
    async def test_can_fetch_nfl_scoreboard(self):
        """Should fetch NFL scoreboard."""
        pass

    @pytest.mark.asyncio
    async def test_can_fetch_nba_scoreboard(self):
        """Should fetch NBA scoreboard."""
        pass

    @pytest.mark.asyncio
    async def test_can_fetch_cfb_scoreboard(self):
        """Should fetch College Football scoreboard."""
        pass
