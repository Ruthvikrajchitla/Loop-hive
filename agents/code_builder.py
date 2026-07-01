"""
LoopHive — Code Builder Agent

Builds real, downloadable developer tools (the high-value assets the reviewers
recommended over static ebooks). Pipeline, per the reviews:
  1. Spec Architect  — a JSON blueprint (files, purpose, dependencies)
  2. Code Engineer   — writes each file in isolation (no token bleeding)
  3. Sandbox         — byte-compiles everything; syntax errors trigger…
  4. Auto-Refiner    — self-heal loop that fixes the failing files
Output is a set of files the orchestrator publishes to a GitHub repo.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from core.agent_base import AgentBase
from core.config import config
from core.loop_engine import ContextWindow, Verification
from core.sandbox import syntax_check

logger = structlog.get_logger(__name__)


class CodeBuilderAgent(AgentBase):
    """Generates and self-validates a small, production-quality code project."""

    def __init__(self, router=None):
        super().__init__(
            name="code_builder",
            description="Builds and sandbox-verifies real developer tools / boilerplates.",
            system_prompt=(
                "You are a senior software engineer who ships clean, correct, production-ready code. "
                "You write complete, runnable files with real logic and error handling — never stubs, "
                "TODOs, or 'implement here' placeholders. You output ONLY code (no prose) when asked for a file."
            ),
            router=router,
        )

    async def perceive(self, context: ContextWindow) -> dict:
        self.mark_running()
        niche = config.forced_niche or "AI developer tools"
        topic = ""
        for entry in reversed(context.entries):
            for line in entry["content"].split("\n"):
                low = line.lower().strip()
                if low.startswith("topic:"):
                    topic = line.split(":", 1)[1].strip() or topic
                elif "Goal:" in line and not topic:
                    topic = line.split("Goal:", 1)[1].strip()
        return {"timestamp": time.time(), "niche": niche, "topic": topic or f"a useful tool for {niche}"}

    async def reason(self, state: dict, goal: str) -> dict:
        """Spec Architect — design the project blueprint."""
        topic = state["topic"]
        spec = await self.ask_llm_json(
            f"Design a SMALL, genuinely useful open-source Python developer tool about: '{topic}'.\n"
            f"It must be shippable in 3-6 files (include README.md and requirements.txt) and provide real, "
            f"working functionality (a CLI, library, or FastAPI micro-service) — not a toy.\n\n"
            f"Output JSON: {{'project_name': str, 'description': str (one line), "
            f"'dependencies': [str], 'files': [{{'path': str, 'purpose': str}}]}}",
            temperature=0.4, max_tokens=2000,
        )
        return {"state": state, "spec": spec}

    async def act(self, plan: dict) -> dict:
        """Engineer each file, sandbox-check, and self-heal."""
        spec = plan.get("spec", {})
        name = spec.get("project_name") or "loophive-tool"
        description = spec.get("description", "")
        deps = spec.get("dependencies", []) or []
        file_specs = spec.get("files", []) or []

        # Ensure the essentials exist.
        paths = {f.get("path") for f in file_specs}
        if "requirements.txt" not in paths:
            file_specs.append({"path": "requirements.txt", "purpose": "Python dependencies"})
        if "README.md" not in paths:
            file_specs.append({"path": "README.md", "purpose": "Usage documentation"})

        files: dict[str, str] = {}
        for fs in file_specs:
            path = fs.get("path")
            if not path:
                continue
            if path == "requirements.txt":
                files[path] = "\n".join(deps) + "\n"
                continue
            code = await self.ask_llm(
                f"Project: {name} — {description}\n"
                f"Declared dependencies: {', '.join(deps) or 'none'}\n\n"
                f"Write the COMPLETE contents of the file '{path}'. Purpose: {fs.get('purpose', '')}\n"
                f"Rules: complete and runnable, real logic + error handling, no placeholders or TODOs. "
                f"Output ONLY the raw file contents (no markdown fences, no commentary).",
                temperature=0.3, max_tokens=4096,
            )
            files[path] = self._strip_fence(code)

        # Sandbox + self-heal loop.
        ok, log = syntax_check(files, timeout=config.sandbox_timeout)
        rounds = 0
        while not ok and rounds < config.code_refine_rounds:
            rounds += 1
            logger.info("code_refine", round=rounds, name=name)
            for path in [p for p in files if p.endswith(".py")]:
                if f"] {path}:" not in log and path not in log:
                    continue
                fixed = await self.ask_llm(
                    f"This file failed to compile. Fix it.\n\nFILE: {path}\n\nCODE:\n{files[path]}\n\n"
                    f"COMPILER ERRORS:\n{log}\n\n"
                    f"Output ONLY the corrected raw file contents (no fences, no commentary).",
                    temperature=0.2, max_tokens=4096,
                )
                files[path] = self._strip_fence(fixed)
            ok, log = syntax_check(files, timeout=config.sandbox_timeout)

        result = {
            "name": name,
            "description": description,
            "files": files,
            "dependencies": deps,
            "sandbox_ok": ok,
            "sandbox_log": log[:1000],
            "file_count": len(files),
        }
        self.logger.info("code_built", name=name, files=len(files), sandbox_ok=ok)
        self.mark_success({"name": name, "files": len(files), "sandbox_ok": ok})
        return result

    async def verify(self, result: Any, goal: str) -> Verification:
        if not isinstance(result, dict) or not result.get("files"):
            return Verification(is_complete=False, should_retry=True,
                                feedback="No files were produced.", reason="Empty build.")
        if result.get("file_count", 0) < 2:
            return Verification(is_complete=False, should_retry=True,
                                feedback="Too few files for a real tool.", reason="Insufficient files.")
        if not result.get("sandbox_ok"):
            return Verification(is_complete=False, should_retry=True,
                                feedback=f"Code still has syntax errors:\n{result.get('sandbox_log', '')}",
                                reason="Sandbox validation failed.")
        return Verification(is_complete=True, score=95.0,
                            feedback=f"Built '{result['name']}' — {result['file_count']} files, sandbox clean.")

    @staticmethod
    def _strip_fence(text: str) -> str:
        """Remove a wrapping ``` fence. Never run prose-cleanup on code (it would
        strip array indices like [0]/[1] and break it)."""
        t = (text or "").strip()
        if t.startswith("```"):
            nl = t.find("\n")
            if nl != -1:
                t = t[nl + 1:]
            if t.rstrip().endswith("```"):
                t = t.rstrip()[:-3]
        return t.strip()
