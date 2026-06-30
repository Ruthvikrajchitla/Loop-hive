"""
LoopHive — Main Runner

Provides CLI commands to run the mission control dashboard or trigger the agent swarm loop.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uvicorn
from dotenv import load_dotenv

# Ensure local imports work
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.config import config
from agents.orchestrator import OrchestratorAgent
from storage.database import init_db


async def run_swarm():
    """Run a single iteration of the autonomous agent swarm pipeline."""
    print("\n[LoopHive] Initializing Swarm Orchestrator...")
    await init_db()
    
    orchestrator = OrchestratorAgent()
    print("[LoopHive] Swarm initialized. Running end-to-end loop...")
    
    # Run the orchestrator E2E
    result = await orchestrator.act({"goal": "Run E2E pipeline for autonomous monetization"})
    
    print("\n[LoopHive] Swarm cycle completed!")
    print(f"Niche Target: {result.get('niche', {}).get('name', 'Unknown')}")
    print(f"Article Written: {result.get('article_written', False)}")
    print(f"Product Created: {result.get('product_created', False)}")
    print(f"Marketing Channels: {result.get('marketing_channels', 0)}")
    print(f"Decision: {result.get('eval_decision', 'continue')}")


def run_dashboard():
    """Start the mission control dashboard FastAPI application."""
    print("\n[LoopHive] Starting Swarm Dashboard at http://127.0.0.1:8000 ...")
    uvicorn.run(
        "dashboard.app:app",
        host=config.dashboard_host,
        port=config.dashboard_port,
        reload=True,
    )


if __name__ == "__main__":
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="LoopHive Command Line Interface")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--swarm",
        action="store_true",
        help="Run a single cycle of the autonomous agent swarm pipeline",
    )
    group.add_argument(
        "--dashboard",
        action="store_true",
        help="Start the mission control dashboard (default)",
    )
    
    args = parser.parse_args()
    
    if args.swarm:
        asyncio.run(run_swarm())
    else:
        # Default behavior: run dashboard
        run_dashboard()
