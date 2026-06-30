"""
LoopHive — Dashboard App Entrypoint

Initializes the FastAPI application, mounts templates, and sets up SQLite DB schemas.
"""

from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import structlog

import asyncio
from core.config import config
from storage.database import init_db
from dashboard.routes import router
from agents.orchestrator import OrchestratorAgent

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

# Mount static folder
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include routes
app.include_router(router)


async def run_swarm_periodically():
    """Runs the orchestrator agent loop once every 24 hours autonomously."""
    # Wait 60 seconds after dashboard startup to run the first cycle
    await asyncio.sleep(60)
    orchestrator = OrchestratorAgent()
    while True:
        try:
            logger.info("scheduled_swarm_run_started")
            await orchestrator.act({"goal": "Autonomous 24-hour swarm cycle"})
            logger.info("scheduled_swarm_run_completed")
        except Exception as e:
            logger.error("scheduled_swarm_run_failed", error=str(e))
        
        # Sleep for 24 hours (86400 seconds)
        await asyncio.sleep(86400)


@app.on_event("startup")
async def startup_event():
    """Run database schema migration / creations and launch background swarm task."""
    logger.info("dashboard_startup")
    try:
        await init_db()
        logger.info("database_initialized")
        # Start the background autonomous swarm task
        asyncio.create_task(run_swarm_periodically())
        logger.info("background_swarm_task_started")
    except Exception as e:
        logger.error("database_init_failed", error=str(e))


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
