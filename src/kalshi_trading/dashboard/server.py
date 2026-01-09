"""FastAPI web dashboard for Kalshi Trading System."""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from kalshi_trading.clients.espn import ESPNClient, Sport
from kalshi_trading.clients.kalshi import KalshiClient
from kalshi_trading.monitoring.database import TradingDatabase


# App state
class AppState:
    db: TradingDatabase
    espn: ESPNClient
    kalshi: KalshiClient | None = None
    collector_running: bool = False
    trading_running: bool = False
    collector_task: asyncio.Task | None = None
    snapshots_collected: int = 0
    market_snapshots_collected: int = 0


state = AppState()


def get_kalshi_credentials() -> tuple[str | None, Path | None, str]:
    """Get Kalshi credentials from environment."""
    key_id = os.environ.get("KALSHI_API_KEY_ID")
    key_path_str = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    env = os.environ.get("KALSHI_ENVIRONMENT", "sandbox")
    
    key_path = Path(key_path_str) if key_path_str else None
    
    return key_id, key_path, env


async def collector_loop() -> None:
    """Background task that collects game data and market prices."""
    while state.collector_running:
        try:
            games = await state.espn.get_all_live_games()
            for sport, game_list in games.items():
                for game in game_list:
                    state.db.insert_game_state(game)
                    state.snapshots_collected += 1
                    
                    # Collect Kalshi prices if available
                    if state.kalshi:
                        try:
                            markets = await state.kalshi.get_markets(status="open")
                            for market in markets.markets:
                                # Match by team abbreviation
                                ticker_upper = market.ticker.upper()
                                if (game.home_team.abbreviation.upper() in ticker_upper or 
                                    game.away_team.abbreviation.upper() in ticker_upper):
                                    state.db.insert_market_snapshot(
                                        event_id=game.event_id,
                                        ticker=market.ticker,
                                        sport=sport.value,
                                        yes_bid=market.yes_bid,
                                        yes_ask=market.yes_ask,
                                        no_bid=market.no_bid,
                                        no_ask=market.no_ask,
                                        volume=market.volume,
                                        open_interest=market.open_interest,
                                    )
                                    state.market_snapshots_collected += 1
                        except Exception:
                            pass  # Continue even if Kalshi fails
        except Exception:
            pass
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize app state on startup."""
    # Initialize database
    state.db = TradingDatabase()
    state.db.initialize()
    
    # Initialize ESPN client
    state.espn = ESPNClient()
    await state.espn.__aenter__()
    
    # Initialize Kalshi client if credentials available
    key_id, key_path, env = get_kalshi_credentials()
    if key_id and key_path and key_path.exists():
        try:
            state.kalshi = KalshiClient(
                api_key_id=key_id,
                private_key_path=key_path,
                environment=env,
            )
            await state.kalshi.__aenter__()
        except Exception as e:
            print(f"Warning: Could not initialize Kalshi client: {e}")
            state.kalshi = None
    
    yield
    
    # Cleanup
    state.collector_running = False
    if state.collector_task:
        state.collector_task.cancel()
    await state.espn.__aexit__(None, None, None)
    if state.kalshi:
        await state.kalshi.__aexit__(None, None, None)


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
                    "matchup": f"{g.away_team.abbreviation} @ {g.home_team.abbreviation}",
                    "home_team": g.home_team.abbreviation,
                    "away_team": g.away_team.abbreviation,
                    "home_score": g.home_score,
                    "away_score": g.away_score,
                    "period": g.period,
                    "clock": f"{int(g.clock_seconds // 60)}:{int(g.clock_seconds % 60):02d}",
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
        total_checked = 0
        for sport in [Sport.NFL, Sport.NBA, Sport.COLLEGE_FOOTBALL]:
            try:
                scoreboard = await state.espn.get_scoreboard(sport)
                total_checked += len(scoreboard)
                scheduled = []
                for game in scoreboard:
                    # Include games that haven't finished
                    if game.status.value in ["pre", "in"]:
                        scheduled.append({
                            "event_id": game.event_id,
                            "matchup": f"{game.away_team.abbreviation} @ {game.home_team.abbreviation}",
                            "home_team": game.home_team.abbreviation,
                            "away_team": game.away_team.abbreviation,
                            "status": game.status.value,
                            "home_score": game.home_score,
                            "away_score": game.away_score,
                        })
                if scheduled:
                    result[sport.value] = scheduled
            except Exception as e:
                print(f"Error fetching {sport.value}: {e}")
                continue
        return {
            "games": result,
            "total_checked": total_checked,
            "timestamp": datetime.now().isoformat(),
        }
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
        "market_snapshots_collected": state.market_snapshots_collected,
        "kalshi_connected": state.kalshi is not None,
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
    return {"status": "started", "kalshi_enabled": state.kalshi is not None}


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
