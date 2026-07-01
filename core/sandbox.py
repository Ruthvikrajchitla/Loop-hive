"""
LoopHive — Code Sandbox

Validates agent-generated code before it's published — the "Execution Sandbox /
Auto-Refiner" guard from the reviewers. Now multi-language, since the swarm ships
tools, GitHub packs, browser extensions, and websites:

  - .py            → byte-compile (syntax)
  - .json          → JSON parse (e.g. manifest.json, package.json)
  - .js/.mjs/.ts   → `node --check` if Node is installed, else best-effort skip
  - .html/.htm     → basic well-formedness (non-empty, has tags)

Deliberately conservative: it validates that files parse/compile; it does NOT
pip-install or execute arbitrary program logic (that needs container isolation).
"""

from __future__ import annotations

import json as _json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def syntax_check(files: dict[str, str], timeout: int = 60) -> tuple[bool, str]:
    """Validate every file by type. Returns (all_ok, log)."""
    logs: list[str] = []
    ok = True
    try:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for path, content in files.items():
                fp = base / path
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content or "", encoding="utf-8")

            node = shutil.which("node")

            for path, content in files.items():
                fp = base / path
                try:
                    if path.endswith(".py"):
                        r = subprocess.run(
                            [sys.executable, "-m", "py_compile", str(fp)],
                            capture_output=True, text=True, timeout=timeout,
                        )
                        if r.returncode != 0:
                            ok = False
                            logs.append(f"[SYNTAX ERROR] {path}:\n{r.stderr.strip()[:600]}")
                    elif path.endswith(".json"):
                        _json.loads(content or "")
                    elif path.endswith((".js", ".mjs", ".cjs", ".ts")) and node:
                        r = subprocess.run(
                            [node, "--check", str(fp)],
                            capture_output=True, text=True, timeout=timeout,
                        )
                        if r.returncode != 0:
                            ok = False
                            logs.append(f"[JS ERROR] {path}:\n{r.stderr.strip()[:600]}")
                    elif path.endswith((".html", ".htm")):
                        if "<" not in (content or ""):
                            ok = False
                            logs.append(f"[HTML ERROR] {path}: does not look like HTML.")
                except _json.JSONDecodeError as e:
                    ok = False
                    logs.append(f"[JSON ERROR] {path}: {str(e)[:200]}")
                except subprocess.TimeoutExpired:
                    ok = False
                    logs.append(f"[TIMEOUT] {path} took too long to validate.")
    except Exception as e:
        return False, f"[SANDBOX ERROR] {str(e)[:300]}"

    return ok, ("\n".join(logs) if logs else "All files validated cleanly.")
