# syntax=docker/dockerfile:1
# Multi-stage build: keeps final image small (~120 MB)

# ── Stage 1: Dependency builder ─────────────────────────────────────────
FROM python:3.11-slim AS builder

# Install UV for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./

# Install deps into /app/.venv (not system Python)
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: Application ─────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy venv from builder (no build tools in runtime image)
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy application source
COPY src/ ./src/

# SQLite data directory (mapped to Cloud Storage volume in GCP)
RUN mkdir /data && chown appuser:appuser /data
VOLUME /data
ENV DB_PATH=/data/life_os.db

# Structured JSON logs in production
ENV LOG_FORMAT=json

USER appuser

# Cloud Run sets PORT env var; default 8080
ENV PORT=8080
EXPOSE $PORT

CMD uvicorn life_os.telegram.webhook:app \
    --host 0.0.0.0 \
    --port $PORT \
    --workers 1 \
    --log-level warning
