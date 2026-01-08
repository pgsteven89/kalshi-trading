"""Unit tests for ESPN API client."""

from unittest.mock import AsyncMock, patch

import pytest

from kalshi_trading.clients.espn import (
    ESPNClient,
    ESPNError,
    GameState,
    GameStatus,
    Sport,
    Team,
)


@pytest.fixture
def espn_client() -> ESPNClient:
    """Create an ESPN client for testing."""
    return ESPNClient()


class TestESPNScoreboard:
    """Tests for scoreboard retrieval."""

    @pytest.mark.asyncio
    async def test_get_nfl_scoreboard(
        self, espn_client: ESPNClient, sample_espn_scoreboard: dict
    ):
        """Should fetch and parse NFL scoreboard."""
        with patch.object(
            espn_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_espn_scoreboard

            async with espn_client:
                games = await espn_client.get_scoreboard(Sport.NFL)

            assert len(games) == 1
            assert games[0].sport == "nfl"
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_nba_scoreboard(
        self, espn_client: ESPNClient, sample_espn_nba_scoreboard: dict
    ):
        """Should fetch and parse NBA scoreboard."""
        with patch.object(
            espn_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_espn_nba_scoreboard

            async with espn_client:
                games = await espn_client.get_scoreboard(Sport.NBA)

            assert len(games) == 1
            assert games[0].sport == "nba"

    @pytest.mark.asyncio
    async def test_get_college_football_scoreboard(self, espn_client: ESPNClient):
        """Should fetch college football scoreboard with FBS filter."""
        with patch.object(
            espn_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {"events": []}

            async with espn_client:
                await espn_client.get_scoreboard(Sport.COLLEGE_FOOTBALL)

            # Verify FBS groups parameter
            call_args = mock_request.call_args
            assert call_args[1]["params"]["groups"] == "80"

    @pytest.mark.asyncio
    async def test_scoreboard_with_date_filter(
        self, espn_client: ESPNClient, sample_espn_scoreboard: dict
    ):
        """Should accept date parameter."""
        with patch.object(
            espn_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_espn_scoreboard

            async with espn_client:
                await espn_client.get_scoreboard(Sport.NFL, date="20260108")

            call_args = mock_request.call_args
            assert call_args[1]["params"]["dates"] == "20260108"


class TestESPNGameParsing:
    """Tests for parsing game data."""

    def test_parse_event_extracts_teams(
        self, espn_client: ESPNClient, sample_espn_scoreboard: dict
    ):
        """Should extract home and away teams."""
        event = sample_espn_scoreboard["events"][0]
        game = espn_client._parse_game(event, Sport.NFL)

        assert game is not None
        assert game.home_team.abbreviation == "BUF"
        assert game.away_team.abbreviation == "KC"

    def test_parse_event_extracts_scores(
        self, espn_client: ESPNClient, sample_espn_scoreboard: dict
    ):
        """Should extract current scores as integers."""
        event = sample_espn_scoreboard["events"][0]
        game = espn_client._parse_game(event, Sport.NFL)

        assert game is not None
        assert game.home_score == 21
        assert game.away_score == 14

    def test_parse_event_extracts_clock(
        self, espn_client: ESPNClient, sample_espn_scoreboard: dict
    ):
        """Should extract game clock in seconds."""
        event = sample_espn_scoreboard["events"][0]
        game = espn_client._parse_game(event, Sport.NFL)

        assert game is not None
        assert game.clock_seconds == 423.0  # 7:03 in seconds

    def test_parse_event_extracts_period(
        self, espn_client: ESPNClient, sample_espn_scoreboard: dict
    ):
        """Should extract current period/quarter."""
        event = sample_espn_scoreboard["events"][0]
        game = espn_client._parse_game(event, Sport.NFL)

        assert game is not None
        assert game.period == 3  # 3rd quarter

    def test_parse_event_determines_status(
        self, espn_client: ESPNClient, sample_espn_scoreboard: dict
    ):
        """Should correctly identify in-progress status."""
        event = sample_espn_scoreboard["events"][0]
        game = espn_client._parse_game(event, Sport.NFL)

        assert game is not None
        assert game.status == GameStatus.IN


class TestESPNGameState:
    """Tests for GameState model."""

    def test_margin_calculation_home_leading(
        self, espn_client: ESPNClient, sample_espn_scoreboard: dict
    ):
        """Margin should be positive when home team leads."""
        event = sample_espn_scoreboard["events"][0]
        game = espn_client._parse_game(event, Sport.NFL)

        assert game is not None
        # Buffalo (home) 21, KC (away) 14 -> margin = 7
        assert game.margin == 7

    def test_margin_calculation_away_leading(self):
        """Margin should be negative when away team leads."""
        game = GameState(
            event_id="test",
            sport="nfl",
            home_team=Team(id="1", abbreviation="BUF", display_name="Bills"),
            away_team=Team(id="2", abbreviation="KC", display_name="Chiefs"),
            home_score=14,
            away_score=21,
            period=3,
            clock_seconds=423.0,
            status=GameStatus.IN,
        )

        assert game.margin == -7

    def test_is_live_during_game(
        self, espn_client: ESPNClient, sample_espn_scoreboard: dict
    ):
        """is_live should be True during active game."""
        event = sample_espn_scoreboard["events"][0]
        game = espn_client._parse_game(event, Sport.NFL)

        assert game is not None
        assert game.is_live is True

    def test_is_live_false_before_game(self):
        """is_live should be False before game starts."""
        game = GameState(
            event_id="test",
            sport="nfl",
            home_team=Team(id="1", abbreviation="BUF", display_name="Bills"),
            away_team=Team(id="2", abbreviation="KC", display_name="Chiefs"),
            home_score=0,
            away_score=0,
            period=0,
            clock_seconds=0,
            status=GameStatus.PRE,
        )

        assert game.is_live is False

    def test_is_final_after_game(self):
        """is_final should be True after game ends."""
        game = GameState(
            event_id="test",
            sport="nfl",
            home_team=Team(id="1", abbreviation="BUF", display_name="Bills"),
            away_team=Team(id="2", abbreviation="KC", display_name="Chiefs"),
            home_score=28,
            away_score=21,
            period=4,
            clock_seconds=0,
            status=GameStatus.POST,
        )

        assert game.is_final is True


class TestESPNErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_empty_response(self, espn_client: ESPNClient):
        """Should gracefully handle empty events list."""
        with patch.object(
            espn_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {"events": []}

            async with espn_client:
                games = await espn_client.get_scoreboard(Sport.NFL)

            assert games == []

    @pytest.mark.asyncio
    async def test_handles_malformed_event(self, espn_client: ESPNClient):
        """Should skip malformed events without crashing."""
        with patch.object(
            espn_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = {
                "events": [
                    {"id": "bad", "competitions": []},  # No competitors
                ]
            }

            async with espn_client:
                games = await espn_client.get_scoreboard(Sport.NFL)

            assert games == []  # Malformed event skipped

    @pytest.mark.asyncio
    async def test_get_live_games_filters_correctly(
        self, espn_client: ESPNClient, sample_espn_scoreboard: dict
    ):
        """get_live_games should only return in-progress games."""
        with patch.object(
            espn_client, "_request", new_callable=AsyncMock
        ) as mock_request:
            mock_request.return_value = sample_espn_scoreboard

            async with espn_client:
                live_games = await espn_client.get_live_games(Sport.NFL)

            # Sample game is in progress
            assert len(live_games) == 1
            assert live_games[0].is_live
