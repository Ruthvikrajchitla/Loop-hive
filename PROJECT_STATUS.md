# Otto — Project Status & Handoff

_Last updated: 2026-07-14. Read this first to continue without losing context._

---

## 1. What this project is

**Otto** is an **autonomous, AI-run product-building agency**. A team of persona-driven
AI agents watches the market, researches deeply, plans, **builds real software**,
validates it actually runs, ships it to GitHub, markets it, and takes tasks from
the boss (you) by email — all on free LLM tiers, reporting to you.

- **Repo:** https://github.com/Ruthvikrajchitla/Loop-hive (branch `main`, auto-deploys where configured)
- **Internal codename in module headers:** "LoopHive"; **public brand:** "Otto"
- **Owner / boss:** Ruthvik (chruthvikraj@gmail.com)
- **Was:** an ebook/content shop. **Pivoted** (2026-07-01) to product-building.

---

## 2. How to run it (local dev)

```bash
# Windows, from the repo root
.venv/Scripts/python.exe -m pytest -q          # run the test suite (should be 19 passed)
.venv/Scripts/python.exe main.py --dashboard   # dashboard at http://localhost:8000
.venv/Scripts/python.exe main.py --swarm --once # run ONE product cycle
.venv/Scripts/python.exe main.py --swarm        # run continuously (the autonomous loop)
```

- Python **3.14** venv at `.venv/`. Deps in `pyproject.toml` (`pip install .`).
- Config is all env-driven via `.env` (gitignored). `.env.example` documents every var.
- DB: SQLite `loophive.db` (gitignored). Auto-creates tables + light migrations on start.

---

## 3. Otto's identity & credentials (ALL WIRED & VERIFIED, in `.env`)

| Capability | Account / provider | Status |
|---|---|---|
| LLMs | Gemini, Groq, **NVIDIA Nemotron-49B + 550B** | ✅ working |
| Web research | Tavily | ✅ |
| Images | Pexels | ✅ |
| Email (send + read) | **agentotto09@gmail.com** (Gmail app password, IMAP+SMTP) | ✅ verified |
| Ships code | GitHub **@agentotto09** (classic token, scope `repo`) | ✅ verified (pushed a real repo) |
| Marketing | Twitter/X **@theagentotto** | ⚠️ auth OK, **POST fails 402** (X free tier now gates writes) |
| Boss email | chruthvikraj@gmail.com | ✅ |

**Dead/unused keys** (ignore or remove from `.env`): OpenRouter, Cerebras, xAI (401/404/400).
Telegram: not set (we chose X). Gumroad: optional (only for paid digital products).

> ⚠️ The Gmail app password and all keys live in `.env` (gitignored — never committed).
> The Gmail app password appeared in the chat transcript; rotate it if you want to be safe.

---

## 4. The team & pipeline (product mode = default, `PRODUCT_MODE=true`)

**Core build pipeline** — `agents/product_orchestrator.py` runs it as a **resumable state machine**:

```
analyze → research → plan → build ⇄ review → ship → market/deliver → done
         (each stage checkpointed to the Job table after it completes)
```

| Agent (file) | Persona | Role |
|---|---|---|
| `analyzer_agent.py` | Nova | Scans web/Reddit/X/Quora (Tavily) → market brief + picks a product |
| `research_agent.py` | Aria | **Deep iterative research** (`RESEARCH_ROUNDS` passes: search→synthesize→find gaps→dig deeper) |
| `planner_agent.py` | Piper | Architecture + file list + features + **acceptance criteria** |
| `code_builder.py` | Cody | Builds each file (**MoA fusion**) to the plan; **validates** (see §5); self-heals |
| `product_critic_agent.py` | Quill | Re-validates vs acceptance criteria + real checks; rates production-ready or sends back |
| `marketing_agent.py` | Remy | Launch copy → X post + SEO blog |

**Other agents:** `outreach_agent.py` (Bex — 1 transparent client outreach/day), `email_agent.py`
(Sol — reads inbox, understands intent, **boss tasks + client builds + replies**),
`monthly_evaluator.py` (Kai — KPIs). Legacy content agents (niche_scout, legal_researcher,
content_writer, content_critic, plagiarism_checker, compliance_agent, product_creator) still
exist for `PRODUCT_MODE=false`.

**Daily rhythm** (`main.py run_swarm`): boss tasks jump the queue → resume any active job →
mornings (UTC<12) build Otto's own product → afternoons (UTC≥12) build for a client (found via
public requests, delivered by email). MicroLoop (per task) / MesoLoop (weekly) / MacroLoop (monthly).

---

## 5. Build quality — THE key recent work (real validation)

The big lesson: a syntax-check let Otto ship a **non-functional façade** (a repo with fabricated
imports + invented README metrics). Fixed in `core/sandbox.py`:

- **`syntax_check`** — compile/parse per file type (py/json/js/html)
- **`static_analysis`** (AST) — catches: import-time side effects (servers/loops at module top
  level), local imports that don't resolve, undeclared/stdlib deps, undefined symbols
- **`execution_check`** (opt-in, `EXECUTION_SANDBOX=true`) — **real venv + pip install + import
  every module + run pytest**. Catches fabricated APIs & bad dep names.
- **`validate()`** = syntax + static (+ execution). Builder + critic both use it.
- Builder uses **MoA fusion** per file + strict discipline (real APIs only, correct PyPI names,
  no import-time execution, no invented claims). `strip_stdlib_reqs()` drops stdlib from requirements.

**Verified live:** with `EXECUTION_SANDBOX=true`, Otto built `WordFrequencyCLI` that passed the full
venv→install→import→tests validation. (Earlier `AutoPrompt Architect` repo was the façade that
exposed the gap.)

---

## 6. Memory (resumable jobs) — recent work

- **`Job` table** + `core/jobs.py`: every unit of work persists its stage + ALL intermediate outputs
  (market brief, research, plan, files, feedback, round, product_name, requester_email, target_stage).
- **`ProductOrchestrator.run_next()`** resumes the active job from its saved stage after any
  interruption/restart instead of starting over. Boss tasks are prioritized.
- **Boss delegation:** email Otto (from `BOSS_EMAIL`) → `email_agent._handle_boss_task` classifies how
  far to go (research/plan/build/full), queues a `boss_task` Job, acknowledges, then the pipeline runs
  to that stage and **emails you the report/result**.
- Dashboard **`/jobs`** shows the queue + each job's stage.

---

## 7. Dashboard (full visibility)

`main.py --dashboard` → FastAPI + HTMX, dark glass UI. Pages:
`/dashboard` (live overview + 6-stage pipeline tracker), `/jobs` (memory), `/activity` (every
artifact in full), `/agents` + `/agents/{name}` (per-agent runs + outputs), `/products`, `/content`,
`/earnings`, `/inbox` (Sol), `/outreach` (Bex), `/notifications` (Boss Inbox — escalations),
`/niches`, `/compliance`, `/onboarding`. Boss badge (top-right) shows unread escalation count.

The dashboard's background task runs the swarm (`RUN_SWARM_IN_DASHBOARD=true`) OR run
`main.py --swarm` as a separate worker.

---

## 8. WHAT'S LEFT (prioritized)

1. **🚀 Oracle 24/7 deployment (NEXT).** Not deployed. See `DEPLOY_ORACLE.md`. Steps: create an
   Always-Free Ubuntu VM → open port 8000 → clone + `pip install .` → put `.env` on the VM →
   install `deploy/loophive.service` (systemd) → set **`EXECUTION_SANDBOX=true`** (real build
   validation) + **Postgres or persistent disk** so the DB/memory survives restarts
   (`core/config._resolve_db_url()` already normalizes `DATABASE_URL` for Postgres; `asyncpg` is a dep).
2. **🐦 Twitter posting is 402-blocked.** X free tier now gates writes. Either check the X portal for a
   Free plan that allows POST, or **switch marketing to Telegram** (free — code already tries both;
   just add `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`). Blog is built regardless.
3. **Phase 2 (client builds) not yet live-tested** end-to-end (finding a brief → build → email delivery).
   Code is wired; needs a real run.
4. **Revenue** stays $0 until a Gumroad webhook feeds sales (only relevant if selling paid products;
   `/webhooks/gumroad` exists).
5. **Optional polish:** run a full product cycle with production settings
   (`FUSION_ENABLED=true`, `FINALIZE_ENABLED=true`, `BUILD_ROUNDS=4`, `EXECUTION_SANDBOX=true`) and
   review the shipped repo quality; remove dead LLM keys.

---

## 9. Key config knobs (`.env`, documented in `.env.example`)

```
PRODUCT_MODE=true            # product pipeline (vs legacy content)
BUILD_ROUNDS=4               # builder↔critic loops
RESEARCH_ROUNDS=3            # deep-research passes
RESEARCH_DEPTH=8  RESEARCH_MAX_SOURCES=16
FUSION_ENABLED=true          # MoA (several models draft, aggregator fuses)
FUSION_AGGREGATOR=nvidia-ultra   FINALIZE_PROVIDER=nvidia-ultra (550B)
EXECUTION_SANDBOX=false      # ← set TRUE on the VM for real venv/install/import/test validation
CLIENT_WORK_ENABLED=true     # afternoons build for clients
EMAIL_ENABLED=true  EMAIL_AUTO_REPLY=false   # reads inbox; drafts unless auto-reply on
OUTREACH_ENABLED=false  OUTREACH_DRY_RUN=true  # off + draft-only by default
BRAND_NAME=Otto  BOSS_NAME=Ruthvik  BOSS_EMAIL=chruthvikraj@gmail.com
```

---

## 10. Gotchas & conventions

- **`.env` keys must be `UPPER_SNAKE=value`** (no spaces, not "x api key = ..."). This tripped us up
  repeatedly. `.env` and `*.db` are gitignored — never commit them.
- **Never run `strip_ai_artifacts` on code** (it removes `[0]`/`[1]` indices). It's for prose only.
- SQLAlchemy async: read-then-write in one route must use `session.execute(select)` +
  `session.execute(update)` + `session.commit()`, NOT a nested `session.begin()`.
- Working NVIDIA model ids: `nvidia/llama-3.3-nemotron-super-49b-v1` (workhorse),
  `nvidia/nemotron-3-ultra-550b-a55b` (premium final pass). The 70B/Qwen ids are dead.
- A full product cycle with deep settings takes ~15–40 min (that's intended — quality over speed).
- Auto-memory for future Claude sessions lives in `~/.claude/projects/.../memory/` (architecture file
  has the full running history).

---

## 11. Recent commits (newest first)
```
73825fb Fix execution-sandbox convergence: strip stdlib from requirements
501bf12 Real build validation (static + execution) + MoA + builder discipline
d9a6f38 Persistent job memory (resumable) + boss task delegation by email
519a914 Brand as Otto, Twitter marketing, deep iterative research
77ece48 Fix product pipeline: critic verdict, builder naming, quality routing
c866f60 Pivot to product-building agency
ee743a9 Full-visibility dashboard + boss identity + escalation
1d565a6 Two-way email agent
2806a50 Multi-type code products (tools/packs/extensions/websites)
```

**Immediate next action:** deploy to Oracle (`DEPLOY_ORACLE.md`) with `EXECUTION_SANDBOX=true` and a
persistent DB, and decide Telegram-vs-Twitter for marketing. Everything else is built and tested.
