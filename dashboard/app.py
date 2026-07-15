"""
LoopHive — Dashboard App Entrypoint

Initializes the FastAPI application, mounts templates, and sets up SQLite DB schemas.
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import base64
import secrets
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import uvicorn
import structlog

import asyncio
from core.config import config
from storage.database import init_db
from dashboard.routes import router

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="LoopHive Swarm Dashboard",
    description="Autonomous money-making AI agent swarm mission control center.",
    version="0.1.0",
)

# CORS config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Password-protect the dashboard when DASHBOARD_PASSWORD is set.

    Uses HTTP Basic auth so it works from any browser with no login page to build.
    If DASHBOARD_PASSWORD is unset/blank, the middleware is a no-op (open dashboard).
    /health stays open so uptime checks don't need credentials.
    """

    def __init__(self, app, username: str, password: str):
        super().__init__(app)
        self._user = username
        self._password = password

    async def dispatch(self, request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
                user, _, pwd = decoded.partition(":")
                if secrets.compare_digest(user, self._user) and secrets.compare_digest(
                    pwd, self._password
                ):
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Otto"'},
            content="Authentication required.",
        )


_dash_password = os.getenv("DASHBOARD_PASSWORD", "").strip()
if _dash_password:
    app.add_middleware(
        BasicAuthMiddleware,
        username=os.getenv("DASHBOARD_USER", "otto").strip() or "otto",
        password=_dash_password,
    )
    logger.info("dashboard_auth_enabled")
else:
    logger.warning("dashboard_auth_disabled_no_password")

# Mount static folder
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include routes
app.include_router(router)


async def run_swarm_background():
    """Run the full autonomous swarm loop (MicroLoop + weekly/monthly tiers).

    Reuses the same code path as `python main.py --swarm` so the dashboard and the
    CLI behave identically. Gate with RUN_SWARM_IN_DASHBOARD=false on Render if you
    prefer to run the swarm as a separate background worker.
    """
    # Small delay so the web server is serving before the first heavy cycle.
    await asyncio.sleep(float(os.getenv("SWARM_START_DELAY_SECONDS", "30")))
    try:
        from main import run_swarm
        await run_swarm(continuous=True)
    except Exception as e:
        logger.error("background_swarm_failed", error=str(e))


@app.on_event("startup")
async def startup_event():
    """Create DB schema and (optionally) launch the background autonomous swarm."""
    logger.info("dashboard_startup")
    try:
        await init_db()
        logger.info("database_initialized")
    except Exception as e:
        logger.error("database_init_failed", error=str(e))

    if os.getenv("RUN_SWARM_IN_DASHBOARD", "true").lower() in ("1", "true", "yes"):
        asyncio.create_task(run_swarm_background())
        logger.info("background_swarm_task_started")
    else:
        logger.info("background_swarm_disabled")


@app.get("/health")
def health_check():
    return {"status": "ok", "app": "loophive"}


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=config.dashboard_host,
        port=config.dashboard_port,
        reload=True,
    )
