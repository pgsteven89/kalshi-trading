"""FastAPI web dashboard for Kalshi Trading System."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from kalshi_trading.clients.espn import ESPNClient, Sport
from kalshi_trading.monitoring.database import TradingDatabase


# App state
class AppState:
    db: TradingDatabase
    espn: ESPNClient
    collector_running: bool = False
    trading_running: bool = False
    collector_task: asyncio.Task | None = None
    snapshots_collected: int = 0


state = AppState()


async def collector_loop() -> None:
    """Background task that collects game data."""
    while state.collector_running:
        try:
            games = await state.espn.get_all_live_games()
            for sport, game_list in games.items():
                for game in game_list:
                    state.db.insert_game_state(game)
                    state.snapshots_collected += 1
        except Exception:
            pass
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize app state on startup."""
    state.db = TradingDatabase()
    state.db.initialize()
    state.espn = ESPNClient()
    await state.espn.__aenter__()
    yield
    # Cleanup
    state.collector_running = False
    if state.collector_task:
        state.collector_task.cancel()
    await state.espn.__aexit__(None, None, None)


app = FastAPI(
    title="Kalshi Trading Dashboard",
    lifespan=lifespan,
)

# Templates
templates_dir = Path(__file__).parent / "templates"
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(templates_dir))


# --- Pages ---


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Main dashboard page."""
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "title": "Kalshi Trading Dashboard",
            "collector_running": state.collector_running,
            "trading_running": state.trading_running,
        },
    )


# --- API Endpoints ---


@app.get("/api/games")
async def get_live_games() -> dict:
    """Get current live games from ESPN."""
    try:
        games = await state.espn.get_all_live_games()
        result = {}
        for sport, game_list in games.items():
            result[sport.value] = [
                {
                    "event_id": g.event_id,
                    "matchup": g.matchup,
                    "home_team": g.home_team.abbreviation,
                    "away_team": g.away_team.abbreviation,
                    "home_score": g.home_score,
                    "away_score": g.away_score,
                    "period": g.period,
                    "clock": g.clock_display,
                    "status": g.status.value,
                    "margin": g.margin,
                }
                for g in game_list
            ]
        return {"games": result, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"error": str(e), "games": {}}


@app.get("/api/games/scheduled")
async def get_scheduled_games() -> dict:
    """Get upcoming scheduled games from ESPN."""
    try:
        result = {}
        for sport in [Sport.NFL, Sport.NBA, Sport.COLLEGE_FOOTBALL]:
            try:
                scoreboard = await state.espn.get_scoreboard(sport)
                scheduled = []
                for game in scoreboard:
                    # Include games that haven't started yet
                    if game.status.value == "pre":
                        scheduled.append({
                            "event_id": game.event_id,
                            "matchup": game.matchup,
                            "home_team": game.home_team.abbreviation,
                            "away_team": game.away_team.abbreviation,
                            "status": game.status.value,
                        })
                if scheduled:
                    result[sport.value] = scheduled
            except Exception:
                continue
        return {"games": result, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"error": str(e), "games": {}}


@app.get("/api/trades")
async def get_recent_trades(limit: int = 20) -> dict:
    """Get recent trades from database."""
    trades = state.db.get_recent_trades(limit=limit)
    return {"trades": trades}


@app.get("/api/performance")
async def get_performance() -> dict:
    """Get overall performance metrics."""
    return {
        "overall": state.db.get_strategy_performance(),
        "by_strategy": state.db.get_performance_by_strategy(),
        "by_sport": state.db.get_performance_by_sport(),
        "daily": state.db.get_daily_pnl(days=7),
    }


@app.get("/api/status")
async def get_status() -> dict:
    """Get system status."""
    return {
        "collector_running": state.collector_running,
        "trading_running": state.trading_running,
        "snapshots_collected": state.snapshots_collected,
        "timestamp": datetime.now().isoformat(),
    }


# --- Controls ---


@app.post("/api/collector/start")
async def start_collector() -> dict:
    """Start data collector in background."""
    if state.collector_running:
        return {"status": "already_running"}
    
    state.collector_running = True
    state.collector_task = asyncio.create_task(collector_loop())
    return {"status": "started"}


@app.post("/api/collector/stop")
async def stop_collector() -> dict:
    """Stop data collector."""
    if not state.collector_running:
        return {"status": "already_stopped"}
    
    state.collector_running = False
    if state.collector_task:
        state.collector_task.cancel()
        state.collector_task = None
    return {"status": "stopped"}


@app.post("/api/trading/start")
async def start_trading() -> dict:
    """Start trading engine (dry run mode)."""
    state.trading_running = True
    # TODO: Implement actual trading engine background task
    return {"status": "started", "mode": "dry_run"}


@app.post("/api/trading/stop")
async def stop_trading() -> dict:
    """Stop trading engine."""
    state.trading_running = False
    return {"status": "stopped"}


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the dashboard server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
