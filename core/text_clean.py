"""
LoopHive — Text Cleanup & Editorial Rules

Removes the tell-tale "AI footprints" reviewers flagged (bracket citations,
meta-language about sources, navigational boilerplate) and provides the shared
editorial guardrails injected into every writing prompt so the swarm produces
expert, prescriptive, production-ready content.
"""

from __future__ import annotations

import re

# [1], [2, 3], [4-6] style citation artifacts left over from source-grounded prompts.
_BRACKET = re.compile(r"[ \t]*\[\d+(?:\s*[,\-–]\s*\d+)*\]")

# Whole sentences that reveal the model was reading a source/brief.
_META = re.compile(
    r"(?is)[^.!?\n]*\b("
    r"as inferred from|"
    r"based on (?:the )?(?:provided )?(?:sources?|context|research(?: brief)?)|"
    r"(?:the )?(?:provided )?sources?\s+(?:mention|state|indicate|note|say|suggest|do not|don't|doesn't)|"
    r"while not directly (?:answered|stated|mentioned)[^.!?\n]*|"
    r"according to (?:the )?provided (?:sources?|context)|"
    r"per the research brief|"
    r"the (?:research )?brief (?:mentions|states|notes)"
    r")[^.!?\n]*[.!?]"
)

# Navigational boilerplate at chapter ends.
_PROCEED = re.compile(
    r"(?im)^\s*(?:proceed to|in the next chapter|continue to chapter|onward to chapter|"
    r"stay tuned for|coming up next)\b.*$"
)

_MULTIBLANK = re.compile(r"\n{3,}")
_DOUBLESPACE = re.compile(r"[ \t]{2,}")


def strip_ai_artifacts(text: str) -> str:
    """Remove citation brackets, source meta-language, and nav boilerplate."""
    if not text:
        return text
    t = _BRACKET.sub("", text)
    t = _META.sub("", t)
    t = _PROCEED.sub("", t)
    t = _MULTIBLANK.sub("\n\n", t)
    t = _DOUBLESPACE.sub(" ", t)
    return t.strip()


# Injected into writing prompts to enforce the reviewers' quality bar.
EDITORIAL_RULES = (
    "STRICT EDITORIAL RULES (a paying professional will read this):\n"
    "- Write as the PRIMARY domain expert. Never reference 'the sources', 'provided context', "
    "'the research', or the brief, and never use bracket citations like [1] or [2, 3]. "
    "State facts directly and confidently.\n"
    "- Be PRESCRIPTIVE, not descriptive: don't just define a tool — give exact steps, real "
    "config/commands, when and WHY to choose it, and the trade-offs (cost, latency, scale).\n"
    "- Where the topic is technical, include at least one real, correct, copy-pasteable code block "
    "or config snippet.\n"
    "- Use concrete named tools, real numbers, and specific examples. No placeholders like "
    "'[insert here]' and no beginner filler like 'explain X to a 10-year-old'.\n"
    "- Prefer scannable Markdown: short paragraphs, bullet lists, and comparison tables.\n"
    "- Do NOT add navigational boilerplate ('Proceed to Chapter X', 'In the next chapter…')."
)
