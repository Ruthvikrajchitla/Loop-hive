"""
LoopHive — Code Sandbox (real validation)

Three layers, cheapest first, so Otto ships *working* software, not scaffolding:

  1. syntax_check   — byte-compile .py / parse .json / node --check .js / html
  2. static_analysis — AST checks that catch the defects a syntax check misses:
       • module-level side effects (code that runs on import — servers, loops)
       • local imports that don't resolve (missing module or missing symbol)
       • third-party imports not declared in requirements.txt
  3. execution_check — (opt-in) real venv + pip install + import every module +
       run pytest. Catches fabricated library APIs and bad dependency names.

`validate()` runs 1+2 always and 3 when config.execution_sandbox is on.
"""

from __future__ import annotations

import ast
import json as _json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# --- Small-instance safety (e.g. Northflank/Koyeb free tier) --------------------
# The execution sandbox stays fully real (venv + pip install + import + pytest);
# these knobs just keep it memory-frugal so it never OOM-kills the always-on
# agent process. All are env-overridable.

def _env_flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")

# Prefer prebuilt wheels over compiling C extensions from source (the #1 OOM cause).
_PREFER_BINARY = _env_flag("SANDBOX_PREFER_BINARY", True)

# Megaframeworks that reliably blow a 512MB–1GB box even just to install. A product
# that "needs" these is scope-creep for a CLI/tool/site/extension/ebook — the guard
# fails the build with a clear message so the builder finds a lighter approach.
# Set SANDBOX_BLOCKED_PACKAGES="" to disable (e.g. on a bigger paid box).
_DEFAULT_BLOCKED = (
    "torch,torchvision,torchaudio,tensorflow,tensorflow-gpu,tensorflow-cpu,jax,jaxlib,"
    "transformers,sentence-transformers,spacy,cupy,onnxruntime-gpu,vllm,xformers,"
    "accelerate,bitsandbytes,deepspeed,paddlepaddle,mxnet"
)
_BLOCKED_PACKAGES = {
    p.strip().lower().replace("_", "-")
    for p in os.getenv("SANDBOX_BLOCKED_PACKAGES", _DEFAULT_BLOCKED).split(",")
    if p.strip()
}


def _frugal_env() -> dict:
    """Environment for sandbox subprocesses that minimizes memory use."""
    env = dict(os.environ)
    env["PIP_NO_CACHE_DIR"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Cap glibc per-thread arenas — cuts RSS of Python + pip noticeably on small boxes.
    env.setdefault("MALLOC_ARENA_MAX", "2")
    return env


def _pip_install_cmd(py: str, *args: str) -> list[str]:
    cmd = [str(py), "-m", "pip", "install", "-q", "--no-cache-dir"]
    if _PREFER_BINARY:
        cmd.append("--prefer-binary")
    cmd.extend(args)
    return cmd

# Bare module-level calls that are safe/idiomatic (won't be flagged as side effects).
_SAFE_MODULE_CALLS = {
    "basicConfig", "getLogger", "load_dotenv", "filterwarnings",
    "set_start_method", "freeze_support", "setrecursionlimit", "get_logger",
}
# Common import-name → PyPI-name so declared deps resolve.
_IMPORT_ALIASES = {
    "bs4": "beautifulsoup4", "cv2": "opencv-python", "PIL": "pillow",
    "yaml": "pyyaml", "dotenv": "python-dotenv", "sklearn": "scikit-learn",
    "jose": "python-jose", "dateutil": "python-dateutil", "attr": "attrs",
    "haystack": "haystack-ai", "google": "google-genai",
}


def syntax_check(files: dict[str, str], timeout: int = 60) -> tuple[bool, str]:
    """Byte-compile / parse each file by type. Returns (all_ok, log)."""
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
                        r = subprocess.run([sys.executable, "-m", "py_compile", str(fp)],
                                           capture_output=True, text=True, timeout=timeout)
                        if r.returncode != 0:
                            ok = False
                            logs.append(f"[SYNTAX ERROR] {path}:\n{r.stderr.strip()[:600]}")
                    elif path.endswith(".json"):
                        _json.loads(content or "")
                    elif path.endswith((".js", ".mjs", ".cjs", ".ts")) and node:
                        r = subprocess.run([node, "--check", str(fp)],
                                           capture_output=True, text=True, timeout=timeout)
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
                    logs.append(f"[TIMEOUT] {path}")
    except Exception as e:
        return False, f"[SANDBOX ERROR] {str(e)[:300]}"
    return ok, ("\n".join(logs) if logs else "All files validated cleanly.")


def _local_module_names(files: dict[str, str]) -> dict[str, str]:
    """Map importable local module names → file path (for import resolution)."""
    mapping: dict[str, str] = {}
    for path in files:
        if not path.endswith(".py"):
            continue
        parts = path[:-3].split("/")
        # Register progressively shorter suffixes: src.a.b, a.b, b
        for i in range(len(parts)):
            mapping[".".join(parts[i:])] = path
        if parts[-1] == "__init__":  # a package dir
            for i in range(len(parts) - 1):
                mapping[".".join(parts[i:-1])] = path
    return mapping


def strip_stdlib_reqs(requirements: str) -> str:
    """Remove standard-library module names wrongly listed as pip dependencies."""
    stdlib = getattr(sys, "stdlib_module_names", set())
    kept = []
    for line in (requirements or "").splitlines():
        name = line.strip().split("==")[0].split(">=")[0].split("[")[0].split("~")[0].strip().lower().replace("-", "_")
        if line.strip() and not line.strip().startswith("#") and name in stdlib:
            continue  # drop stdlib module (not installable)
        kept.append(line)
    return "\n".join(kept)


def _declared_packages(files: dict[str, str]) -> set[str]:
    reqs = files.get("requirements.txt", "") or ""
    pkgs = set()
    for line in reqs.splitlines():
        name = line.strip().split("==")[0].split(">=")[0].split("[")[0].split("~")[0].strip()
        if name and not name.startswith("#"):
            pkgs.add(name.lower().replace("_", "-"))
    return pkgs


def _top_level_names(src: str) -> set[str]:
    names: set[str] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return names
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
    return names


def static_analysis(files: dict[str, str]) -> tuple[bool, str]:
    """AST checks: import-time side effects, unresolved local imports, undeclared deps."""
    issues: list[str] = []
    local = _local_module_names(files)
    declared = _declared_packages(files)
    stdlib = getattr(sys, "stdlib_module_names", set())

    # requirements.txt must not list standard-library modules (pip can't install them).
    for line in (files.get("requirements.txt", "") or "").splitlines():
        nm = line.strip().split("==")[0].split(">=")[0].split("[")[0].split("~")[0].strip()
        if nm and not nm.startswith("#") and nm.lower().replace("-", "_") in stdlib:
            issues.append(f"requirements.txt: `{nm}` is a standard-library module — remove it (pip can't install it).")

    # Heavy megaframeworks would OOM a small always-on box — and a CLI/tool/site/
    # extension/ebook never needs them. Flag so the builder picks a lighter approach.
    for pkg in sorted(declared & _BLOCKED_PACKAGES):
        issues.append(f"requirements.txt: `{pkg}` is too heavy for the deployment box — "
                      f"use a lighter, dependency-minimal approach (stdlib / a small pure-Python "
                      f"library / call a hosted API) instead of a large ML/native framework.")

    for path, content in files.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(content or "")
        except SyntaxError:
            continue  # syntax_check reports these

        # 1. Module-level side effects (bare calls at top level).
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                fn = node.value.func
                name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                if name not in _SAFE_MODULE_CALLS:
                    issues.append(f"{path}: runs `{name}(...)` at import time — move it into a function "
                                  f"or an `if __name__ == '__main__':` block (importing must not execute work).")

        # 2. Import resolution.
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mod = node.module
                base = mod.split(".")[0]
                if mod in local:
                    defined = _top_level_names(files.get(local[mod], ""))
                    for a in node.names:
                        if a.name != "*" and a.name not in defined:
                            issues.append(f"{path}: imports `{a.name}` from local `{mod}`, but it isn't defined there.")
                elif base in stdlib or base in {"__future__"}:
                    pass
                elif base in local or any(k.split(".")[0] == base for k in local):
                    pass
                elif _IMPORT_ALIASES.get(base, base).lower().replace("_", "-") in declared or base.lower().replace("_", "-") in declared:
                    pass
                else:
                    issues.append(f"{path}: imports `{mod}` — not a standard library module, not a local "
                                  f"module in this project, and not declared in requirements.txt.")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    base = a.name.split(".")[0]
                    if base in stdlib or base in local or a.name in local:
                        continue
                    if _IMPORT_ALIASES.get(base, base).lower().replace("_", "-") in declared or base.lower().replace("_", "-") in declared:
                        continue
                    issues.append(f"{path}: imports `{a.name}` — not stdlib, not local, not in requirements.txt.")

    ok = not issues
    return ok, ("\n".join(f"[STATIC] {i}" for i in issues) if issues else "Static analysis clean.")


def execution_check(files: dict[str, str], install_timeout: int = 300, run_timeout: int = 60) -> tuple[bool, str]:
    """Real run: venv + pip install + import every module + pytest. Opt-in (slow)."""
    py_files = [p for p in files if p.endswith(".py")]
    if not py_files:
        return True, "No Python to execute."
    logs: list[str] = []
    try:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for path, content in files.items():
                fp = base / path
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content or "", encoding="utf-8")

            env = _frugal_env()
            venv = base / ".venv"
            subprocess.run([sys.executable, "-m", "venv", str(venv)],
                           capture_output=True, timeout=120, env=env)
            py = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

            if (base / "requirements.txt").exists():
                r = subprocess.run(_pip_install_cmd(py, "-r", "requirements.txt"),
                                   cwd=str(base), capture_output=True, text=True,
                                   timeout=install_timeout, env=env)
                if r.returncode != 0:
                    return False, f"[INSTALL FAILED] {r.stderr.strip()[-800:]}"

            # Import each module (catches fabricated APIs / import-time crashes).
            for path in py_files:
                if path.endswith("__init__.py") or "/test" in path or path.startswith("test"):
                    continue
                mod_path = path[:-3].replace("/", ".")
                r = subprocess.run([str(py), "-c", f"import importlib; importlib.import_module('{mod_path}')"],
                                   cwd=str(base), capture_output=True, text=True,
                                   timeout=run_timeout, env=env)
                if r.returncode != 0:
                    logs.append(f"[IMPORT FAILED] {path}:\n{r.stderr.strip()[-500:]}")

            # Run tests if any.
            if any("test" in p for p in py_files):
                subprocess.run(_pip_install_cmd(py, "pytest"),
                               cwd=str(base), capture_output=True, timeout=120, env=env)
                r = subprocess.run([str(py), "-m", "pytest", "-q", "--no-header"],
                                   cwd=str(base), capture_output=True, text=True,
                                   timeout=run_timeout * 3, env=env)
                if r.returncode not in (0, 5):  # 5 = no tests collected
                    logs.append(f"[TESTS FAILED]\n{(r.stdout + r.stderr).strip()[-800:]}")
    except subprocess.TimeoutExpired:
        return False, "[EXECUTION TIMEOUT] install/import/test took too long."
    except Exception as e:
        return False, f"[EXECUTION ERROR] {str(e)[:300]}"
    return (not logs), ("\n".join(logs) if logs else "Executed cleanly: imports + tests pass.")


def validate(files: dict[str, str], timeout: int = 60, execution: bool = False,
             install_timeout: int = 300) -> tuple[bool, str]:
    """Full validation: syntax + static, plus real execution when enabled."""
    ok, log = syntax_check(files, timeout=timeout)
    if not ok:
        return False, log
    sok, slog = static_analysis(files)
    if not sok:
        return False, slog
    if execution:
        eok, elog = execution_check(files, install_timeout=install_timeout, run_timeout=timeout)
        if not eok:
            return False, elog
    return True, "Validated: syntax + static" + (" + execution" if execution else "") + " clean."
