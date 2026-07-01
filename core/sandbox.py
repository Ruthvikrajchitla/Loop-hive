"""
LoopHive — Code Sandbox

Safely validates agent-generated code before it's published. This is the
"Execution Sandbox / Auto-Refiner" guard from the reviewers: it byte-compiles
every Python file in an isolated temp directory and reports syntax errors so the
Code Builder can self-heal.

Deliberately conservative: it does NOT pip-install or execute arbitrary program
logic (that requires container isolation and is a security risk). It validates
that the code parses/compiles cleanly, which catches the errors that matter for
a shippable boilerplate. Full run-in-container execution is a future upgrade.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def syntax_check(files: dict[str, str], timeout: int = 60) -> tuple[bool, str]:
    """Byte-compile every .py file. Returns (all_ok, log)."""
    logs: list[str] = []
    ok = True
    try:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for path, content in files.items():
                fp = base / path
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content or "", encoding="utf-8")

            py_files = [p for p in files if p.endswith(".py")]
            if not py_files:
                return True, "No Python files to compile."

            for path in py_files:
                fp = base / path
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "py_compile", str(fp)],
                        capture_output=True, text=True, timeout=timeout,
                    )
                    if result.returncode != 0:
                        ok = False
                        logs.append(f"[SYNTAX ERROR] {path}:\n{result.stderr.strip()[:600]}")
                except subprocess.TimeoutExpired:
                    ok = False
                    logs.append(f"[TIMEOUT] {path} took too long to compile.")
    except Exception as e:
        return False, f"[SANDBOX ERROR] {str(e)[:300]}"

    return ok, ("\n".join(logs) if logs else "All Python files compiled cleanly.")
