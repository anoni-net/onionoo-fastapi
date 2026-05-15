from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from cachetools import TTLCache
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.observability import (
    CACHE_HITS,
    CACHE_MISSES,
    UPSTREAM_ERRORS,
    UPSTREAM_LATENCY,
)
from app.settings import settings

logger = structlog.get_logger(__name__)


class UpstreamError(RuntimeError):
    def __init__(self, *, status_code: int, body: str | None):
        super().__init__(f"Onionoo upstream error: {status_code}")
        self.status_code = status_code
        self.body = body


class _OwnerCancelled(RuntimeError):
    """Signal that a deduped owner was cancelled; waiters should re-issue."""


@dataclass
class UpstreamResponse:
    status_code: int
    headers: Mapping[str, str]
    json_body: Any | None
    text_body: str | None
    cache_age_seconds: float = 0.0


def _clean_params(params: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, str) and v == "":
            continue
        out[k] = v
    return out


def _cache_key(method: str, params: Mapping[str, Any], if_modified_since: str | None) -> str:
    payload = json.dumps(
        {
            "method": method,
            "params": _clean_params(params),
            "ims": if_modified_since,
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# Transient transport errors worth retrying. We deliberately exclude
# `httpx.InvalidURL`, `httpx.UnsupportedProtocol`, `httpx.TooManyRedirects`, and
# similar deterministic client-side failures — retrying those just delays the
# inevitable.
_RETRYABLE_HTTPX_ERRORS = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


def _is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, _RETRYABLE_HTTPX_ERRORS):
        return True
    if isinstance(exc, UpstreamError) and exc.status_code >= 500:
        return True
    return False


class OnionooClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.onionoo_base_url.rstrip("/"),
            timeout=httpx.Timeout(
                connect=10.0,
                read=settings.onionoo_timeout_seconds,
                write=10.0,
                pool=30.0,
            ),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
            ),
            headers={
                "Accept-Encoding": "gzip",
                "User-Agent": settings.user_agent,
            },
        )
        self._cache: TTLCache[str, tuple[UpstreamResponse, float]] = TTLCache(
            maxsize=settings.cache_maxsize,
            ttl=settings.cache_default_ttl_seconds,
        )
        self._lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[UpstreamResponse]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    async def ping(
        self, *, method: str = "summary", params: Mapping[str, Any] | None = None
    ) -> int:
        """Probe upstream without consulting the cache.

        Used by `/healthz/ready` so a cached payload can't mask an outage. Raises
        `httpx.RequestError` on transport failures and `UpstreamError` on >=400.
        Returns the upstream status code on success.
        """
        return (
            await self._fetch_once(
                method=method, params=params or {"limit": "1"}, if_modified_since=None
            )
        ).status_code

    async def get(
        self,
        *,
        method: str,
        params: Mapping[str, Any],
        if_modified_since: str | None,
    ) -> UpstreamResponse:
        key = _cache_key(method, params, if_modified_since)

        async with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                CACHE_HITS.inc()
                cached_resp, inserted_at = cached
                age = max(0.0, time.monotonic() - inserted_at)
                # Each caller observes its own `cache_age_seconds`; the response
                # body/headers are shared (treat them as immutable).
                return UpstreamResponse(
                    status_code=cached_resp.status_code,
                    headers=cached_resp.headers,
                    json_body=cached_resp.json_body,
                    text_body=cached_resp.text_body,
                    cache_age_seconds=age,
                )
            existing = self._pending.get(key)
            if existing is not None:
                future = existing
                is_owner = False
            else:
                future = asyncio.get_running_loop().create_future()
                self._pending[key] = future
                is_owner = True
                CACHE_MISSES.inc()

        if not is_owner:
            try:
                return await future
            except _OwnerCancelled:
                # Owner was cancelled before completing; re-enter as a fresh
                # caller. Whoever wins the race becomes the new owner.
                return await self.get(
                    method=method, params=params, if_modified_since=if_modified_since
                )

        try:
            response = await self._fetch_with_retry(
                method=method, params=params, if_modified_since=if_modified_since
            )
        except asyncio.CancelledError:
            # The owning request was cancelled (e.g. client disconnect). Drop the
            # pending slot and signal waiters with a sentinel so they re-issue
            # instead of inheriting our cancellation.
            async with self._lock:
                self._pending.pop(key, None)
            if not future.done():
                future.set_exception(_OwnerCancelled())
                future.exception()
            raise
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
            # Mark the exception as retrieved on the owning side; waiters that
            # `await future` will still see it raised normally.
            future.exception()
            async with self._lock:
                self._pending.pop(key, None)
            raise

        async with self._lock:
            self._cache[key] = (response, time.monotonic())
            self._pending.pop(key, None)
        if not future.done():
            future.set_result(response)
        return response

    async def _fetch_with_retry(
        self,
        *,
        method: str,
        params: Mapping[str, Any],
        if_modified_since: str | None,
    ) -> UpstreamResponse:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(settings.upstream_retry_attempts + 1),
            wait=wait_exponential_jitter(initial=0.2, max=2.0),
            retry=retry_if_exception(_is_retryable_exception),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await self._fetch_once(
                        method=method, params=params, if_modified_since=if_modified_since
                    )
        except RetryError as exc:  # pragma: no cover - reraise=True bypasses this
            raise exc.last_attempt.exception() from exc
        raise RuntimeError("unreachable")  # pragma: no cover

    async def _fetch_once(
        self,
        *,
        method: str,
        params: Mapping[str, Any],
        if_modified_since: str | None,
    ) -> UpstreamResponse:
        url_path = f"/{method.lstrip('/')}"
        headers: dict[str, str] = {}
        if if_modified_since:
            headers["If-Modified-Since"] = if_modified_since

        start = time.perf_counter()
        try:
            resp = await self._client.get(url_path, params=_clean_params(params), headers=headers)
        except httpx.RequestError:
            UPSTREAM_ERRORS.labels(method=method, status="network").inc()
            logger.warning("onionoo.upstream.network_error", method=method)
            raise
        finally:
            UPSTREAM_LATENCY.labels(method=method).observe(time.perf_counter() - start)

        if resp.status_code == 304:
            return UpstreamResponse(
                status_code=resp.status_code,
                headers=resp.headers,
                json_body=None,
                text_body=None,
            )

        json_body: Any | None = None
        text_body: str | None = None
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                json_body = resp.json()
            except ValueError:
                text_body = resp.text
        else:
            text_body = resp.text

        if resp.status_code >= 400:
            UPSTREAM_ERRORS.labels(method=method, status=str(resp.status_code)).inc()
            logger.warning(
                "onionoo.upstream.http_error",
                method=method,
                status=resp.status_code,
            )
            raise UpstreamError(status_code=resp.status_code, body=text_body or None)

        return UpstreamResponse(
            status_code=resp.status_code,
            headers=resp.headers,
            json_body=json_body,
            text_body=text_body,
        )
