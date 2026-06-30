"""
LoopHive — Agent Base Class

All specialist agents inherit from this base.
Provides LLM access, logging, memory, and standard lifecycle methods.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

from core.llm_router import LLMRouter, llm_router
from core.loop_engine import ContextWindow, Verification

logger = structlog.get_logger(__name__)


@dataclass
class AgentState:
    """Current state of an agent."""
    status: str = "idle"  # idle, running, error, paused
    last_run: float | None = None
    last_result: dict | None = None
    total_runs: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_tokens_used: int = 0
    error_message: str = ""


class AgentBase(ABC):
    """
    Base class for all LoopHive agents.

    Every agent has:
    - A name and description
    - Access to the shared LLM router
    - A system prompt defining its role
    - Standard perceive/reason/act/verify lifecycle
    - State tracking for the dashboard
    """

    def __init__(
        self,
        name: str,
        description: str,
        system_prompt: str,
        router: LLMRouter | None = None,
    ):
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.router = router or llm_router
        self.state = AgentState()
        self.logger = structlog.get_logger(agent=name)

    # -------------------------------------------------------------------
    # Lifecycle methods — subclasses must implement these
    # -------------------------------------------------------------------

    @abstractmethod
    async def perceive(self, context: ContextWindow) -> dict:
        """Gather current state — what does the world look like right now?"""
        ...

    @abstractmethod
    async def reason(self, state: dict, goal: str) -> dict:
        """Given the state and goal, decide what action to take."""
        ...

    @abstractmethod
    async def act(self, plan: dict) -> Any:
        """Execute the planned action."""
        ...

    @abstractmethod
    async def verify(self, result: Any, goal: str) -> Verification:
        """Check if the goal has been achieved."""
        ...

    # -------------------------------------------------------------------
    # LLM helper methods — convenient wrappers for agents
    # -------------------------------------------------------------------

    async def ask_llm(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
        context: list[dict] | None = None,
    ) -> str:
        """
        Ask the LLM a question. Includes the agent's system prompt.

        Returns the text response.
        """
        messages = [{"role": "system", "content": self.system_prompt}]

        if context:
            messages.extend(context)

        messages.append({"role": "user", "content": prompt})

        result = await self.router.generate(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            task_type=self.name,
        )

        self.state.total_tokens_used += result.get("tokens_used", 0)
        return result["content"]

    async def ask_llm_json(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        context: list[dict] | None = None,
    ) -> dict:
        """
        Ask the LLM a question and parse the response as JSON.

        The prompt should instruct the LLM to respond in JSON format.
        """
        response = await self.ask_llm(
            prompt=prompt + "\n\nRespond ONLY with valid JSON, no markdown or explanation.",
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            context=context,
        )

        # Try to parse JSON, handling common issues
        text = response.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object/array in the response
            for start_char, end_char in [("{", "}"), ("[", "]")]:
                start = text.find(start_char)
                end = text.rfind(end_char)
                if start != -1 and end != -1 and end > start:
                    try:
                        return json.loads(text[start:end + 1])
                    except json.JSONDecodeError:
                        continue

            self.logger.error("json_parse_failed", response=text[:200])
            return {"error": "Failed to parse JSON", "raw_response": text[:500]}

    # -------------------------------------------------------------------
    # State management
    # -------------------------------------------------------------------

    def mark_running(self):
        self.state.status = "running"
        self.state.last_run = time.time()
        self.state.total_runs += 1

    def mark_success(self, result: dict | None = None):
        self.state.status = "idle"
        self.state.total_successes += 1
        self.state.last_result = result
        self.state.error_message = ""

    def mark_failed(self, error: str = ""):
        self.state.status = "error"
        self.state.total_failures += 1
        self.state.error_message = error

    def get_status(self) -> dict:
        """Get agent status for the dashboard."""
        return {
            "name": self.name,
            "description": self.description,
            "status": self.state.status,
            "last_run": self.state.last_run,
            "total_runs": self.state.total_runs,
            "success_rate": (
                f"{self.state.total_successes / max(1, self.state.total_runs) * 100:.0f}%"
            ),
            "total_tokens": self.state.total_tokens_used,
            "error": self.state.error_message,
        }
