ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-alpine AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    PATH="/root/.local/bin:/app/.venv/bin:$PATH"

WORKDIR /app

# Build-only deps: curl pulls the uv installer; ca-certificates makes the TLS
# handshake to astral.sh / PyPI work. These stay in the builder stage and never
# reach the runtime image.
RUN apk add --no-cache ca-certificates curl \
  && update-ca-certificates \
  && curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies first (better layer caching). `--no-install-project`
# skips the hatchling build step here so this layer survives changes to app/.
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-install-project --no-dev

# Then install the project itself; this is what places the `onionoo-mcp`
# console script on PATH.
COPY app /app/app
COPY README.md LICENSE /app/
RUN uv sync --frozen --no-dev


FROM python:${PYTHON_VERSION}-alpine AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Runtime needs CA bundle for outbound HTTPS to Onionoo, plus wget for the
# HEALTHCHECK probe. No uv, no curl, no toolchain in the final image.
RUN apk add --no-cache ca-certificates wget \
  && update-ca-certificates \
  && adduser -D -u 10001 appuser

COPY --from=builder --chown=appuser:appuser /app /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O- http://127.0.0.1:8000/healthz >/dev/null || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
