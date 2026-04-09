# =============================================================================
# Stage 1: base — Python + uv + dependency manifests
# =============================================================================
FROM python:3.12.13-slim AS base

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.10.11 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./

# =============================================================================
# Stage 2: dev — all deps including dev extras, hot reload CMD
# Requires bind mount at /app — use docker-compose.dev.yml, not standalone
# =============================================================================
FROM base AS dev
# Dev runs as root for bind-mount compatibility (see #43)

RUN uv sync --frozen --extra dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]

# =============================================================================
# Stage 3: prod — prod-only deps, non-root user, health check
# =============================================================================
FROM base AS prod

RUN uv sync --frozen --no-dev

RUN mkdir -p /app/data && \
    addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser && \
    chown appuser:appgroup /app /app/data

COPY --chown=appuser:appgroup app/ ./app/

USER appuser
ENV HOME=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
