# Otto — production image (Northflank / Koyeb / any container host)
FROM python:3.11-slim

WORKDIR /app

# System deps:
#  - build-essential: fallback for the rare source-built wheel in the sandbox
#  - nodejs: lets the sandbox validate extension/website JS (node --check)
#  - git: some pip installs / product builds expect it
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    nodejs \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies first (better layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source code (.dockerignore keeps .env / *.db / .git out of the image)
COPY . .

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Trim glibc arenas so Python + the sandbox stay light on a small free box
    MALLOC_ARENA_MAX=2

# Production ASGI server (no --reload). Honors $PORT if the platform injects one.
CMD ["sh", "-c", "uvicorn dashboard.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
