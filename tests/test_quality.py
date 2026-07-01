"""
LoopHive — Quality & Safety Unit Tests

Deterministic (no LLM / no network): the artifact stripper, the code sandbox,
and the "inert without keys" behavior of the publishers.
"""

from __future__ import annotations

import pytest

from core.text_clean import strip_ai_artifacts
from core.sandbox import syntax_check


# --- AI footprint stripping -------------------------------------------------

def test_strips_bracket_citations():
    assert "[" not in strip_ai_artifacts("Prompt engineering is critical [2, 3, 6].")


def test_strips_source_meta_language():
    out = strip_ai_artifacts(
        "As inferred from the provided sources, teams adopt it. This real sentence must stay."
    )
    assert "provided sources" not in out.lower()
    assert "real sentence must stay" in out


def test_strips_proceed_boilerplate():
    assert "proceed to chapter" not in strip_ai_artifacts("Body.\nProceed to Chapter 3 now.").lower()


def test_preserves_normal_text():
    text = "This is a clean, expert sentence about LangChain and Promptfoo."
    assert strip_ai_artifacts(text) == text


# --- Code sandbox -----------------------------------------------------------

def test_sandbox_passes_valid_code_with_indexing():
    # Array indexing (x[0]) must NOT be treated as an artifact.
    ok, log = syntax_check({"a.py": "x = [1, 2, 3]\nprint(x[0])\n"})
    assert ok, log


def test_sandbox_flags_syntax_error():
    ok, log = syntax_check({"b.py": "def f(:\n    pass\n"})
    assert not ok
    assert "SYNTAX" in log


def test_sandbox_handles_no_python():
    ok, _ = syntax_check({"README.md": "# hello"})
    assert ok


# --- Publishers are inert without keys --------------------------------------

@pytest.mark.asyncio
async def test_telegram_skips_without_keys(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    from publishers.telegram_poster import post_to_telegram
    assert (await post_to_telegram("hi"))["status"] == "skipped"


@pytest.mark.asyncio
async def test_github_skips_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    from publishers.github_publisher import publish_repo
    assert (await publish_repo("t", {"a.py": "x = 1"}))["status"] == "skipped"


@pytest.mark.asyncio
async def test_email_skips_without_smtp(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    from publishers.email_sender import send_email
    assert (await send_email("a@b.com", "s", "b"))["status"] == "skipped"
