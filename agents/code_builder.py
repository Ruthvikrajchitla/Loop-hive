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

    # Build type -> guidance + the files it must include.
    BUILD_TYPES: dict[str, str] = {
        "developer tool": "a small but genuinely useful Python CLI or micro-service tool. Include real "
                          "logic, argument parsing, error handling, requirements.txt, and README.md.",
        "python package": "a small, installable Python package/library. Include the package module(s), a "
                          "usage example, a pyproject.toml, and README.md.",
        "browser extension": "a Chrome Manifest V3 browser extension. REQUIRED files: manifest.json (valid "
                            "MV3 with name, version, and \"manifest_version\": 3), the JavaScript "
                            "(background.js and/or content.js and/or popup.js), popup.html if it has UI, and "
                            "README.md. Real, working behavior — no stubs.",
        "static website": "a small, polished static website. REQUIRED files: index.html, style.css, and "
                          "script.js only if needed, plus README.md. Responsive, real copy (no lorem ipsum).",
        "github starter kit": "a ready-to-use starter/boilerplate repo. Sensible folder structure, config "
                             "files, ONE complete working example, and a README with setup + usage steps.",
    }

    async def perceive(self, context: ContextWindow) -> dict:
        self.mark_running()
        import json
        niche = config.forced_niche or "AI developer tools"
        topic = ""
        build_type = "developer tool"
        plan = None
        feedback = ""
        for entry in reversed(context.entries):
            c = entry["content"]
            if "PLAN:" in c and plan is None:
                try:
                    plan = json.loads(c.split("PLAN:", 1)[1].strip())
                except Exception:
                    plan = None
            if "CRITIC FEEDBACK:" in c and not feedback:
                feedback = c.split("CRITIC FEEDBACK:", 1)[1].strip()[:4000]
            for line in c.split("\n"):
                low = line.lower().strip()
                if low.startswith("topic:"):
                    topic = line.split(":", 1)[1].strip() or topic
                elif low.startswith("build_type:"):
                    build_type = line.split(":", 1)[1].strip() or build_type
                elif "Goal:" in line and not topic:
                    topic = line.split("Goal:", 1)[1].strip()
        if plan and plan.get("build_type"):
            build_type = plan["build_type"]
        return {
            "timestamp": time.time(),
            "niche": niche,
            "topic": topic or f"a useful tool for {niche}",
            "build_type": build_type,
            "plan": plan,
            "feedback": feedback,
        }

    async def reason(self, state: dict, goal: str) -> dict:
        """Use the Planner's plan if provided; otherwise act as the Spec Architect."""
        # Plan-driven mode (product pipeline): the Planner already designed the spec.
        if state.get("plan") and state["plan"].get("files"):
            return {"state": state, "spec": state["plan"], "build_type": state.get("build_type", "developer tool")}

        topic = state["topic"]
        build_type = state.get("build_type", "developer tool")
        guidance = self.BUILD_TYPES.get(build_type.lower(), self.BUILD_TYPES["developer tool"])
        spec = await self.ask_llm_json(
            f"Design {guidance}\n\n"
            f"It must be about: '{topic}', shippable in 3-8 files, genuinely useful (not a toy), and "
            f"include a README.md. Use file paths with correct extensions for the languages involved.\n\n"
            f"Output JSON: {{'project_name': str, 'description': str (one line), "
            f"'dependencies': [str], 'files': [{{'path': str, 'purpose': str}}]}}",
            temperature=0.4, max_tokens=2000,
        )
        return {"state": state, "spec": spec, "build_type": build_type}

    async def act(self, plan: dict) -> dict:
        """Engineer each file, sandbox-check, and self-heal."""
        spec = plan.get("spec", {})
        build_type = plan.get("build_type", "developer tool")
        name = spec.get("project_name") or spec.get("product_name") or "loophive-tool"
        description = spec.get("description", "")
        deps = spec.get("dependencies", []) or []
        file_specs = spec.get("files", []) or []

        # Ensure a README always exists; requirements.txt only for Python builds.
        paths = {f.get("path") for f in file_specs}
        has_python = any(str(p).endswith(".py") for p in paths)
        if has_python and deps and "requirements.txt" not in paths:
            file_specs.append({"path": "requirements.txt", "purpose": "Python dependencies"})
        if "README.md" not in paths:
            file_specs.append({"path": "README.md", "purpose": "Setup and usage documentation"})

        state = plan.get("state", {})
        feedback = state.get("feedback", "")
        features = spec.get("features", []) or []
        criteria = spec.get("acceptance_criteria", []) or []
        context_block = ""
        if features:
            context_block += "Features to implement across the project: " + "; ".join(map(str, features)) + "\n"
        if criteria:
            context_block += "Acceptance criteria (the build must satisfy these): " + "; ".join(map(str, criteria)) + "\n"
        if feedback:
            context_block += f"ADDRESS THIS REVIEWER FEEDBACK from the last round: {feedback}\n"

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
                f"Declared dependencies: {', '.join(deps) or 'none'}\n"
                f"{context_block}\n"
                f"Write the COMPLETE contents of the file '{path}'. Purpose: {fs.get('purpose', '')}\n"
                f"Rules: complete and runnable, real logic + error handling, no placeholders or TODOs. "
                f"Output ONLY the raw file contents (no markdown fences, no commentary).",
                temperature=0.3, max_tokens=4096,
            )
            files[path] = self._strip_fence(code)

        # Sandbox + self-heal loop (any file type: py / json / js / html).
        ok, log = syntax_check(files, timeout=config.sandbox_timeout)
        rounds = 0
        while not ok and rounds < config.code_refine_rounds:
            rounds += 1
            logger.info("code_refine", round=rounds, name=name)
            for path in list(files):
                if path not in log:
                    continue
                fixed = await self.ask_llm(
                    f"This file failed validation. Fix it.\n\nFILE: {path}\n\nCONTENT:\n{files[path]}\n\n"
                    f"VALIDATION ERRORS:\n{log}\n\n"
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
            "build_type": build_type,
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
        bt = str(result.get("build_type", "")).lower()
        paths = list(result.get("files", {}))
        if "extension" in bt and not any(p.endswith("manifest.json") for p in paths):
            return Verification(is_complete=False, should_retry=True,
                                feedback="A browser extension must include a manifest.json.",
                                reason="Missing manifest.json.")
        if "website" in bt and not any(p.endswith((".html", ".htm")) for p in paths):
            return Verification(is_complete=False, should_retry=True,
                                feedback="A website must include an index.html.",
                                reason="Missing HTML.")
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
