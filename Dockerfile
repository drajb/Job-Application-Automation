# Dockerfile — apply-agent.
#
# Build:    docker build -t apply-agent .
# Run:      docker run --rm -it --env-file .env -v $(pwd)/secrets:/app/secrets \
#               -v $(pwd)/resumes:/app/resumes -v $(pwd)/data:/app/data \
#               apply-agent
#
# This image is intentionally for the polling-mode "production" workload (Telegram
# bot + IMAP listener + scheduler). Headed-browser Tier-2 / Tier-3 will not work
# from a container without an X server — run those flows on the host.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        age \
        libreoffice --no-install-recommends \
        ca-certificates \
        curl \
        build-essential \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pre-install dependencies first so layer caching works on code-only changes.
COPY pyproject.toml ./
RUN pip install --upgrade pip \
 && pip install --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install -e .

# Headless Chromium for Tier-2 (best-effort — works in container, not WSLg-style headed).
RUN python -m playwright install --with-deps chromium || true

COPY . .

RUN adduser --disabled-password --gecos "" --uid 10001 agent \
 && chown -R agent:agent /app
USER agent

# Migrations run on every boot — idempotent.
CMD ["bash", "-lc", "alembic upgrade head && python -m src.main"]
