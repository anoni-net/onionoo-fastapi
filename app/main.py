from contextlib import asynccontextmanager
from time import monotonic

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi_mcp import FastApiMCP
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.observability import RequestIdMiddleware, configure_logging, logger
from app.routers import aggregate, bandwidth, clients, details, summary, uptime, weights
from app.services.onionoo_client import OnionooClient, UpstreamError
from app.settings import settings


def create_app() -> FastAPI:
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.onionoo = OnionooClient()
        app.state.ready_cache = {"checked_at": 0.0, "ok": False, "detail": ""}
        logger.info("app.startup", base_url=settings.onionoo_base_url)
        try:
            yield
        finally:
            await app.state.onionoo.aclose()
            logger.info("app.shutdown")

    app = FastAPI(
        title="Onionoo FastAPI Proxy",
        version="1.0.0",
        description="Semantic/OpenAPI proxy for Tor Onionoo (data is fetched from Onionoo upstream).",
        lifespan=lifespan,
    )

    # Order matters: request-id should wrap everything; CORS before GZip.
    app.add_middleware(RequestIdMiddleware)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "Last-Modified"],
            allow_credentials=False,
        )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # The limiter is always constructed so `@limiter.exempt` decorators on the
    # health endpoints remain valid even when rate limiting is toggled off.
    # SlowAPIMiddleware is what actually enforces `default_limits`; without it
    # the limiter object is inert.
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[f"{settings.rate_limit_per_minute}/minute"],
    )
    app.state.limiter = limiter
    if settings.rate_limit_enabled:
        from slowapi.middleware import SlowAPIMiddleware

        app.add_middleware(SlowAPIMiddleware)

    if settings.metrics_enabled:
        Instrumentator().instrument(app).expose(app, endpoint="/metrics", tags=["health"])
        # Prometheus scrapes shouldn't compete with end-user traffic for the
        # per-IP rate budget. Mark the route exempt regardless of toggle.
        for route in app.routes:
            if isinstance(route, APIRoute) and route.path == "/metrics":
                limiter.exempt(route.endpoint)
                break

    @app.get("/healthz", tags=["health"], summary="Liveness probe (static)")
    @limiter.exempt
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/healthz/ready", tags=["health"], summary="Readiness probe (pings upstream)")
    @limiter.exempt
    async def healthz_ready(request: Request) -> Response:
        cache = request.app.state.ready_cache
        now = monotonic()
        if now - cache["checked_at"] < settings.healthz_ready_cache_seconds and cache["checked_at"]:
            payload = {"status": "ok" if cache["ok"] else "degraded", "detail": cache["detail"]}
            status = 200 if cache["ok"] else 503
            return JSONResponse(status_code=status, content=payload)

        client: OnionooClient = request.app.state.onionoo
        try:
            # Bypass the response cache: a cached 200 can mask a live outage.
            await client.ping()
            cache["ok"] = True
            cache["detail"] = "upstream reachable"
        except (UpstreamError, httpx.RequestError) as exc:
            cache["ok"] = False
            cache["detail"] = f"upstream unreachable: {exc}"
        cache["checked_at"] = now

        payload = {"status": "ok" if cache["ok"] else "degraded", "detail": cache["detail"]}
        return JSONResponse(status_code=200 if cache["ok"] else 503, content=payload)

    @app.exception_handler(UpstreamError)
    async def upstream_error_handler(_request: Request, exc: UpstreamError) -> Response:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "upstream_error",
                "upstream_status": exc.status_code,
                "upstream_body": exc.body,
            },
        )

    @app.exception_handler(httpx.RequestError)
    async def httpx_error_handler(_request: Request, exc: httpx.RequestError) -> Response:
        return JSONResponse(
            status_code=502,
            content={
                "error": "bad_gateway",
                "message": str(exc),
            },
        )

    app.include_router(summary.router, prefix="/v1", tags=["onionoo"])
    app.include_router(details.router, prefix="/v1", tags=["onionoo"])
    app.include_router(bandwidth.router, prefix="/v1", tags=["onionoo"])
    app.include_router(weights.router, prefix="/v1", tags=["onionoo"])
    app.include_router(clients.router, prefix="/v1", tags=["onionoo"])
    app.include_router(uptime.router, prefix="/v1", tags=["onionoo"])
    app.include_router(aggregate.router, prefix="/v1", tags=["aggregate"])

    mcp = FastApiMCP(
        app,
        name="Onionoo MCP",
        description=(
            "Tor Onionoo data exposed as MCP tools. Read-only proxy: each tool wraps an "
            "Onionoo endpoint (summary, details, bandwidth, weights, clients, uptime) and "
            "accepts the same query parameters as the Onionoo spec."
        ),
        include_tags=["onionoo", "aggregate"],
    )
    mcp.mount_http()

    return app


app = create_app()
