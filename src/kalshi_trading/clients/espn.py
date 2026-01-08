"""ESPN API client for sports scoreboards."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx


class Sport(str, Enum):
    """Supported sports."""

    NFL = "nfl"
    NBA = "nba"
    COLLEGE_FOOTBALL = "college-football"


class GameStatus(str, Enum):
    """Game status states."""

    PRE = "pre"  # Not started
    IN = "in"  # In progress
    POST = "post"  # Finished


@dataclass
class Team:
    """Team information."""

    id: str
    abbreviation: str
    display_name: str


@dataclass
class GameState:
    """
    Current state of a game.

    This is the primary data model passed to trading strategies.
    """

    event_id: str
    sport: str
    home_team: Team
    away_team: Team
    home_score: int
    away_score: int
    period: int  # Quarter/half number
    clock_seconds: float  # Time remaining in period
    status: GameStatus

    @property
    def margin(self) -> int:
        """
        Point margin from home team's perspective.

        Positive = home leading, negative = away leading.
        """
        return self.home_score - self.away_score

    @property
    def is_live(self) -> bool:
        """Check if game is currently in progress."""
        return self.status == GameStatus.IN

    @property
    def is_final(self) -> bool:
        """Check if game has finished."""
        return self.status == GameStatus.POST


class ESPNError(Exception):
    """Raised when ESPN API request fails."""

    pass


class ESPNClient:
    """
    Async client for ESPN scoreboard API.

    Note: This uses unofficial ESPN endpoints that may change without notice.

    Example:
        async with ESPNClient() as client:
            games = await client.get_scoreboard(Sport.NFL)
            for game in games:
                print(f"{game.away_team.abbreviation} @ {game.home_team.abbreviation}")
                print(f"Score: {game.away_score}-{game.home_score}")
    """

    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"

    SPORT_PATHS = {
        Sport.NFL: "/football/nfl",
        Sport.NBA: "/basketball/nba",
        Sport.COLLEGE_FOOTBALL: "/football/college-football",
    }

    def __init__(self, timeout: float = 30.0):
        """
        Initialize ESPN client.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ESPNClient":
        """Enter async context."""
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=self.timeout,
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Make request to ESPN API.

        Args:
            path: API path
            params: Query parameters

        Returns:
            Parsed JSON response

        Raises:
            ESPNError: On request failure
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context.")

        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise ESPNError(f"HTTP error {e.response.status_code}: {e.response.text}")
        except httpx.RequestError as e:
            raise ESPNError(f"Request failed: {e}")
        except Exception as e:
            raise ESPNError(f"Unexpected error: {e}")

    def _parse_game(self, event: dict[str, Any], sport: Sport) -> GameState | None:
        """
        Parse ESPN event data into GameState.

        Args:
            event: Raw event data from ESPN
            sport: Sport type

        Returns:
            GameState or None if parsing fails
        """
        try:
            competitions = event.get("competitions", [])
            if not competitions:
                return None

            competition = competitions[0]
            competitors = competition.get("competitors", [])

            if len(competitors) != 2:
                return None

            # Find home and away teams
            home_data = None
            away_data = None
            for comp in competitors:
                if comp.get("homeAway") == "home":
                    home_data = comp
                else:
                    away_data = comp

            if not home_data or not away_data:
                return None

            # Parse teams
            home_team = Team(
                id=home_data["team"]["id"],
                abbreviation=home_data["team"]["abbreviation"],
                display_name=home_data["team"]["displayName"],
            )
            away_team = Team(
                id=away_data["team"]["id"],
                abbreviation=away_data["team"]["abbreviation"],
                display_name=away_data["team"]["displayName"],
            )

            # Parse scores (default to 0 if not available)
            home_score = int(home_data.get("score", "0") or "0")
            away_score = int(away_data.get("score", "0") or "0")

            # Parse game status
            status_data = event.get("status", {})
            status_type = status_data.get("type", {})
            state = status_type.get("state", "pre")
            status = GameStatus(state)

            # Parse clock and period
            comp_status = competition.get("status", {})
            clock_seconds = float(comp_status.get("clock", 0))
            period = int(comp_status.get("period", 0))

            return GameState(
                event_id=event["id"],
                sport=sport.value,
                home_team=home_team,
                away_team=away_team,
                home_score=home_score,
                away_score=away_score,
                period=period,
                clock_seconds=clock_seconds,
                status=status,
            )

        except (KeyError, ValueError, TypeError) as e:
            # Log parsing error but don't crash
            # In production, use proper logging
            print(f"Warning: Failed to parse event: {e}")
            return None

    async def get_scoreboard(
        self,
        sport: Sport,
        date: str | None = None,
    ) -> list[GameState]:
        """
        Get scoreboard for a sport.

        Args:
            sport: Sport to fetch
            date: Optional date filter (YYYYMMDD format)

        Returns:
            List of GameState objects for current games
        """
        path = f"{self.SPORT_PATHS[sport]}/scoreboard"

        params: dict[str, Any] = {}
        if date:
            params["dates"] = date

        # College football needs FBS filter
        if sport == Sport.COLLEGE_FOOTBALL:
            params["groups"] = "80"

        data = await self._request(path, params=params if params else None)

        games = []
        for event in data.get("events", []):
            game = self._parse_game(event, sport)
            if game:
                games.append(game)

        return games

    async def get_live_games(self, sport: Sport) -> list[GameState]:
        """
        Get only games currently in progress.

        Args:
            sport: Sport to fetch

        Returns:
            List of live GameState objects
        """
        all_games = await self.get_scoreboard(sport)
        return [game for game in all_games if game.is_live]

    async def get_all_live_games(self) -> dict[Sport, list[GameState]]:
        """
        Get all live games across all supported sports.

        Returns:
            Dict mapping sport to list of live games
        """
        result: dict[Sport, list[GameState]] = {}

        for sport in Sport:
            try:
                live_games = await self.get_live_games(sport)
                if live_games:
                    result[sport] = live_games
            except ESPNError:
                # Skip sports with errors, continue with others
                continue

        return result
