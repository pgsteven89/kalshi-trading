"""Shared test fixtures and configuration."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock

# -- Sample Data Fixtures --


@pytest.fixture
def sample_espn_scoreboard():
    """Sample ESPN scoreboard response for NFL."""
    return {
        "events": [
            {
                "id": "401547417",
                "name": "Kansas City Chiefs at Buffalo Bills",
                "date": "2026-01-08T20:00:00Z",
                "status": {
                    "type": {
                        "id": "2",
                        "name": "STATUS_IN_PROGRESS",
                        "state": "in",
                        "completed": False,
                    }
                },
                "competitions": [
                    {
                        "id": "401547417",
                        "competitors": [
                            {
                                "id": "2",
                                "homeAway": "home",
                                "score": "21",
                                "team": {
                                    "id": "2",
                                    "abbreviation": "BUF",
                                    "displayName": "Buffalo Bills",
                                },
                            },
                            {
                                "id": "12",
                                "homeAway": "away",
                                "score": "14",
                                "team": {
                                    "id": "12",
                                    "abbreviation": "KC",
                                    "displayName": "Kansas City Chiefs",
                                },
                            },
                        ],
                        "status": {
                            "clock": 423.0,
                            "displayClock": "7:03",
                            "period": 3,
                        },
                    }
                ],
            }
        ]
    }


@pytest.fixture
def sample_espn_nba_scoreboard():
    """Sample ESPN scoreboard response for NBA."""
    return {
        "events": [
            {
                "id": "401584922",
                "name": "Los Angeles Lakers at Boston Celtics",
                "date": "2026-01-08T19:30:00Z",
                "status": {
                    "type": {
                        "id": "2",
                        "name": "STATUS_IN_PROGRESS",
                        "state": "in",
                        "completed": False,
                    }
                },
                "competitions": [
                    {
                        "id": "401584922",
                        "competitors": [
                            {
                                "id": "2",
                                "homeAway": "home",
                                "score": "88",
                                "team": {
                                    "id": "2",
                                    "abbreviation": "BOS",
                                    "displayName": "Boston Celtics",
                                },
                            },
                            {
                                "id": "13",
                                "homeAway": "away",
                                "score": "82",
                                "team": {
                                    "id": "13",
                                    "abbreviation": "LAL",
                                    "displayName": "Los Angeles Lakers",
                                },
                            },
                        ],
                        "status": {
                            "clock": 180.0,
                            "displayClock": "3:00",
                            "period": 3,
                        },
                    }
                ],
            }
        ]
    }


@pytest.fixture
def sample_kalshi_markets():
    """Sample Kalshi markets response."""
    return {
        "markets": [
            {
                "ticker": "NFL-2426-BUF",
                "event_ticker": "NFL-2426",
                "title": "Will the Buffalo Bills win?",
                "status": "open",
                "yes_bid": 62,
                "yes_ask": 64,
                "no_bid": 36,
                "no_ask": 38,
                "volume": 15420,
                "open_interest": 8234,
            }
        ],
        "cursor": None,
    }


@pytest.fixture
def sample_kalshi_order():
    """Sample Kalshi order response."""
    return {
        "order_id": "ord_abc123",
        "ticker": "NFL-2426-BUF",
        "status": "pending",
        "side": "yes",
        "action": "buy",
        "type": "limit",
        "count": 10,
        "remaining_count": 10,
        "price": 64,
        "created_time": "2026-01-08T20:15:00Z",
    }


@pytest.fixture
def sample_kalshi_position():
    """Sample Kalshi position response."""
    return {
        "ticker": "NFL-2426-BUF",
        "market_exposure": 640,
        "position": 10,
        "realized_pnl": 0,
    }


@pytest.fixture
def sample_kalshi_balance():
    """Sample Kalshi balance response."""
    return {
        "balance": 10000,  # $100.00 in cents
        "payout": 0,
    }


# -- Mock Client Fixtures --


@pytest.fixture
def mock_httpx_client():
    """Mock httpx async client."""
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.delete = AsyncMock()
    return client
