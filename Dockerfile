# Dockerfile — apply-agent (published as ghcr.io/drajb/job-application-automation).
#
# Build:    docker build -t apply-agent .
# Run:      docker compose up -d          (see docker-compose.yml)
#
# The container runs the daemon: Telegram bot + inbox monitor + scheduler +
# job discovery. Browsers run HEADLESS here (APPLY_HEADLESS=1) — /apply still
# tailors, fills and screenshots the form for your Telegram approval, but a
# Tier-3 "take over in the browser window" handoff needs a desktop, so run the
# agent on the host (WSL2 / Linux / macOS) if you want that.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HF_HOME=/app/data/hf-cache \
    APPLY_HEADLESS=1 \
    APPLY_AGENT_DB=/app/data/apply_agent.db \
    APPLY_BROWSER_PROFILE=/app/data/chrome-profile

RUN apt-get update && apt-get install -y --no-install-recommends \
        age \
        libreoffice-writer-nogui \
        fonts-liberation \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so layer caching works on code-only changes. Only the
# dependency list is read from pyproject.toml here; the package itself is
# installed after the source is copied in. CPU-only torch keeps the image small.
COPY pyproject.toml ./
RUN pip install --upgrade pip \
 && pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt \
 && python -m playwright install --with-deps chromium \
 && chmod -R a+rX /ms-playwright

COPY . .
RUN pip install --no-deps -e .

# UID 1000 matches the first user on most Linux hosts, so the mounted
# ./data and ./secrets folders stay writable without chown games.
RUN useradd --create-home --uid 1000 agent \
 && mkdir -p /app/data /app/secrets \
 && chown -R agent:agent /app
USER agent

# Migrations run on every boot — idempotent.
CMD ["sh", "-c", "alembic upgrade head && python -m src.main"]
