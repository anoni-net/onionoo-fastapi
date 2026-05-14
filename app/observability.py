"""Structured logging, request correlation, and Prometheus metrics.

This module is the single point of truth for observability concerns. Import
`logger` for structlog-based logging that automatically carries the request id.

Public surface:
- `configure_logging()` — call once at startup
- `RequestIdMiddleware` — assigns/echoes X-Request-ID, binds it to the log context
- `CACHE_HITS`, `CACHE_MISSES`, `UPSTREAM_LATENCY`, `UPSTREAM_ERRORS` — metrics
- `logger` — module-level structlog BoundLogger
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

import structlog
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.settings import settings

REQUEST_ID_HEADER = "X-Request-ID"

# Request-id is set by middleware and read by the structlog processor below.
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def _add_request_id(
    _logger: object, _name: str, event_dict: dict[str, object]
) -> dict[str, object]:
    rid = _request_id_var.get()
    if rid is not None:
        event_dict.setdefault("request_id", rid)
    return event_dict


def configure_logging() -> None:
    """Initialize structlog + stdlib logging. Idempotent."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
        force=True,
    )
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.log_format.lower() == "console":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


logger = structlog.get_logger("app")


# --- Prometheus metrics -----------------------------------------------------
# These register on the default prometheus_client.REGISTRY so the FastAPI
# instrumentator's /metrics endpoint picks them up automatically.
CACHE_HITS = Counter(
    "onionoo_cache_hits_total",
    "Number of times the upstream cache returned a stored response.",
)
CACHE_MISSES = Counter(
    "onionoo_cache_misses_total",
    "Number of times the upstream cache did not contain a response.",
)
UPSTREAM_LATENCY = Histogram(
    "onionoo_upstream_seconds",
    "Latency of an upstream Onionoo request (in seconds).",
    labelnames=("method",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
UPSTREAM_ERRORS = Counter(
    "onionoo_upstream_errors_total",
    "Upstream request errors grouped by HTTP status (or 'network').",
    labelnames=("method", "status"),
)


# --- Middleware -------------------------------------------------------------


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Ensure every request has a stable X-Request-ID, echoed on the response.

    Client-supplied IDs are honored if present; otherwise a UUIDv4 is generated.
    The id is bound to the structlog context for the duration of the request.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = _request_id_var.set(rid)
        structlog.contextvars.bind_contextvars(request_id=rid)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            _request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = rid
        return response


def current_request_id() -> str | None:
    """Return the request id bound to the current task, if any."""
    return _request_id_var.get()
