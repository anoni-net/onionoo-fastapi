FROM python:3.14.2-alpine3.23

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Runtime deps: TLS certs; curl for installing uv
RUN apk add --no-cache ca-certificates curl \
  && update-ca-certificates

# Install uv (used to sync from uv.lock). Use official installer to avoid
# Python-version-specific wheels on Alpine.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies first (better layer caching). `--no-install-project`
# avoids invoking the hatchling build backend at this step, so the layer
# survives changes to app/ source.
COPY pyproject.toml uv.lock /app/
RUN /root/.local/bin/uv sync --frozen --no-install-project

# Copy application code + metadata referenced by pyproject (license, readme),
# then run sync again so the project itself is installed (this is what makes
# the `onionoo-mcp` console script appear on PATH).
COPY app /app/app
COPY README.md LICENSE /app/
RUN /root/.local/bin/uv sync --frozen

# Non-root user (Alpine)
RUN adduser -D -u 10001 appuser \
  && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

