# Deploy Otto on Northflank — Forever Free, 24/7

No terminal, no SSH, no networking setup. You connect the GitHub repo, paste your
env vars into a web form, and Northflank builds the Docker image and runs it 24/7.

Otto runs as **one service**: the dashboard process also runs the autonomous swarm
in the background (`RUN_SWARM_IN_DASHBOARD=true`). Memory (jobs, products) lives in
SQLite on a **persistent volume**, so nothing is lost on restart.

---

## What makes it fit the free tier (already built into the code)
- The "thinking" (MoA fusion, deep research) runs on the **external LLM APIs**, not
  your box — so it's weightless here and **uncompromised**.
- The only heavy step is the real build sandbox (`venv` + `pip install` + `pytest`).
  It now installs **prefer-binary / no-cache** and runs under `MALLOC_ARENA_MAX=2`,
  and a guard blocks megaframeworks (torch/tensorflow/…) that don't belong in a
  CLI/tool/site/extension/ebook anyway. So a runaway install can't OOM the agent.

---

## 1. Create the service
1. Sign up at **https://northflank.com** (free plan, no card).
2. **Create new → Service → Deployment.**
3. **Source:** connect GitHub → pick the **`Loop-hive`** repo, branch `main`.
4. **Build:** choose **Dockerfile**, path **`deployment/Dockerfile`**.
5. **Instance / plan:** pick the **free plan** (the largest free option — more RAM
   is better for the build sandbox).
6. **Port:** add port **8000**, protocol **HTTP**, and make it **public**. Northflank
   gives you a URL like `https://otto-xxxx.code.run`.

## 2. Add a persistent volume (so memory survives restarts)
1. In the service, add a **Volume**: size **1 GB** is plenty, mount path **`/data`**.
2. Otto will keep its database there (set in the env vars below).

> No volume on your plan? Skip this and use a free **Neon Postgres**
> (https://neon.tech) instead — set `DATABASE_URL` to the Neon connection string
> (Otto auto-normalizes it to async). Everything else is identical.

## 3. Add environment variables
In the service's **Environment / Secrets**, add these (copy the values from your
local `.env`). Set the DB URL to the volume path:

```
DATABASE_URL=sqlite+aiosqlite:////data/loophive.db     # 4 slashes = absolute /data path
RUN_SWARM_IN_DASHBOARD=true

# --- Dashboard login (keeps it private even though the URL is public) ---
DASHBOARD_USER=otto
DASHBOARD_PASSWORD=<your password>

# --- LLM providers ---
GEMINI_API_KEY=...
GROQ_API_KEY=...
NVIDIA_API_KEY=...
CEREBRAS_API_KEY=...      CEREBRAS_MODEL=gpt-oss-120b
OPENROUTER_API_KEY=...
TAVILY_API_KEY=...
PEXELS_API_KEY=...

# --- Identity / boss / email ---
BRAND_NAME=Otto
BOSS_NAME=Ruthvik
BOSS_EMAIL=chruthvikraj@gmail.com
SMTP_HOST=smtp.gmail.com   SMTP_PORT=587
SMTP_USER=agentotto09@gmail.com   SMTP_PASSWORD=<gmail app password>
EMAIL_ENABLED=true   EMAIL_AUTO_REPLY=false
IMAP_HOST=imap.gmail.com   IMAP_PORT=993

# --- GitHub + social ---
GITHUB_TOKEN=...   GITHUB_ORG=
TWITTER_API_KEY=...   TWITTER_API_SECRET=...
TWITTER_ACCESS_TOKEN=...   TWITTER_ACCESS_SECRET=...

# --- Deep-build behavior (the vision, uncompromised) ---
PRODUCT_MODE=true
EXECUTION_SANDBOX=true
MAX_DAILY_PRODUCTS=1
BUILD_ROUNDS=12   BUILD_ROUNDS_PER_CYCLE=3
RESEARCH_ROUNDS=5   RESEARCH_DEPTH=8   RESEARCH_MAX_SOURCES=16
FUSION_ENABLED=true   FUSION_WAIT=true   FUSION_ALL_MODELS=true   FUSION_MAX_WAIT_SECONDS=300
```

> Tip: Northflank lets you **bulk-import** env vars — paste your whole `.env` and it
> parses `KEY=value` lines. Just remember to change `DATABASE_URL` to the `/data` path.

## 4. Deploy
Click **Deploy / Create**. Northflank builds the image (~2–4 min) and starts Otto.

## 5. Open the dashboard
Visit your Northflank URL: **`https://otto-xxxx.code.run/dashboard`**
The browser asks for a login → enter **DASHBOARD_USER / DASHBOARD_PASSWORD**. Done.

- Health check (no login): `…/health` → `{"status":"ok"}` — point Northflank's
  health check here.
- Live work: `/jobs`, `/activity`, `/notifications`.

## 6. Updating later
Push to `main` → Northflank auto-rebuilds and redeploys. Your volume (memory) persists.

---

## Notes
- **Private:** the URL is public but every page requires the dashboard password
  (`/health` is the only open path, and it exposes nothing sensitive).
- **First cycle takes hours** (deep research + iterate-to-perfection + real sandbox) —
  that's intended. It checkpoints each stage and resumes after any restart.
- **RAM ceiling:** lightweight products (CLIs, tools, sites, extensions, ebooks —
  what Otto builds) install and test fine. If a build ever needs something heavy,
  the guard fails that build cleanly rather than shipping broken or crashing Otto.
