"""FastAPI web dashboard for Kalshi Trading System."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
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


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize app state on startup."""
    state.db = TradingDatabase()
    state.db.initialize()
    state.espn = ESPNClient()
    await state.espn.__aenter__()
    yield
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
        "timestamp": datetime.now().isoformat(),
    }


# --- Server-Sent Events for Live Updates ---


@app.get("/api/stream/games")
async def stream_games(request: Request) -> EventSourceResponse:
    """Stream live game updates."""

    async def event_generator() -> AsyncGenerator[dict, None]:
        while True:
            if await request.is_disconnected():
                break
            try:
                games = await state.espn.get_all_live_games()
                data = {}
                for sport, game_list in games.items():
                    data[sport.value] = [
                        {
                            "matchup": g.matchup,
                            "home_score": g.home_score,
                            "away_score": g.away_score,
                            "period": g.period,
                            "clock": g.clock_display,
                            "margin": g.margin,
                        }
                        for g in game_list
                    ]
                yield {"event": "games", "data": str(data)}
            except Exception:
                pass
            await asyncio.sleep(10)

    return EventSourceResponse(event_generator())


# --- Controls ---


@app.post("/api/collector/start")
async def start_collector() -> dict:
    """Start data collector."""
    state.collector_running = True
    return {"status": "started"}


@app.post("/api/collector/stop")
async def stop_collector() -> dict:
    """Stop data collector."""
    state.collector_running = False
    return {"status": "stopped"}


@app.post("/api/trading/start")
async def start_trading() -> dict:
    """Start trading engine."""
    state.trading_running = True
    return {"status": "started"}


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
