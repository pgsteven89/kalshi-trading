# ESPN API Specification

This document specifies our interface with the unofficial ESPN API endpoints.

> **Warning**: These are undocumented endpoints. They may change without notice.

## Base URL

```
https://site.api.espn.com/apis/site/v2/sports
```

## Supported Sports

| Sport | League | Path Segment |
|-------|--------|--------------|
| Football | NFL | `/football/nfl` |
| Football | College | `/football/college-football` |
| Basketball | NBA | `/basketball/nba` |

## Endpoints

### Scoreboard

#### GET /{sport}/{league}/scoreboard
Get live scores for current games.

**Query Parameters:**
- `dates`: Date filter in YYYYMMDD format (optional)
- `groups`: For college football, use `80` for FBS

**Examples:**
```
/football/nfl/scoreboard
/football/college-football/scoreboard?groups=80
/basketball/nba/scoreboard?dates=20260108
```

**Response Structure:**
```python
class ScoreboardResponse:
    events: list[Event]

class Event:
    id: str
    name: str  # "Team A at Team B"
    date: str  # ISO datetime
    status: EventStatus
    competitions: list[Competition]

class EventStatus:
    type: StatusType
    
class StatusType:
    id: str
    name: str       # "STATUS_SCHEDULED", "STATUS_IN_PROGRESS", "STATUS_FINAL"
    state: str      # "pre", "in", "post"
    completed: bool

class Competition:
    id: str
    competitors: list[Competitor]
    status: CompetitionStatus

class Competitor:
    id: str
    team: Team
    score: str
    home_away: str  # "home" or "away"
    winner: bool    # Only present when game is final

class Team:
    id: str
    abbreviation: str  # "KC", "BUF", etc.
    display_name: str  # "Kansas City Chiefs"
    
class CompetitionStatus:
    clock: float        # Game clock in seconds
    display_clock: str  # "12:45"
    period: int         # Quarter/half number
```

### Game Summary

#### GET /{sport}/{league}/summary?event={event_id}
Get detailed game information.

**Response includes:**
- Play-by-play data
- Box scores
- Team and player statistics
- Odds information (when available)

### Teams

#### GET /{sport}/{league}/teams
List all teams in the league.

#### GET /{sport}/{league}/teams/{team_id}
Get specific team information.

## Polling Strategy

Since these are unofficial endpoints with unknown rate limits:

| Data Type | Recommended Interval |
|-----------|---------------------|
| Scoreboard (pre-game) | Every 5 minutes |
| Scoreboard (in-game) | Every 30 seconds |
| Scoreboard (post-game) | Once, then stop |
| Game Summary | Every 60 seconds |

## Error Handling

ESPN typically returns:
- `200 OK` with JSON data on success
- `404 Not Found` for invalid resources
- Empty responses for some error conditions

Our implementation should:
- Retry on 5xx errors
- Gracefully handle empty/malformed responses
- Log warnings for unexpected response shapes
