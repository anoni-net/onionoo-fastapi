"""tenacity-driven retry: transient 5xx and httpx.RequestError should be retried;
client errors (4xx) and successes should not be."""

from __future__ import annotations

from itertools import cycle

import httpx
import pytest
import respx

from app.services.onionoo_client import OnionooClient, UpstreamError
from tests.conftest import make_summary_envelope


@pytest.mark.asyncio
async def test_5xx_is_retried_until_success(respx_mock: respx.MockRouter) -> None:
    """First call returns 503, second returns 200 → caller sees success."""
    responses = iter(
        [
            httpx.Response(503, text="busy"),
            httpx.Response(200, json=make_summary_envelope()),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        return next(responses)

    route = respx_mock.get("/summary").mock(side_effect=handler)
    client = OnionooClient()
    try:
        resp = await client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
    finally:
        await client.aclose()

    assert resp.status_code == 200
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_4xx_is_not_retried(respx_mock: respx.MockRouter) -> None:
    """404 must propagate immediately without retry."""
    route = respx_mock.get("/summary").mock(return_value=httpx.Response(404, text="not found"))
    client = OnionooClient()
    try:
        with pytest.raises(UpstreamError) as exc_info:
            await client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
    finally:
        await client.aclose()

    assert exc_info.value.status_code == 404
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_retry_exhaustion_raises_last_error(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    """Persistent 500s exhaust retry attempts and raise UpstreamError."""
    from app import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "upstream_retry_attempts", 2)

    route = respx_mock.get("/summary").mock(side_effect=cycle([httpx.Response(500, text="boom")]))
    client = OnionooClient()
    try:
        with pytest.raises(UpstreamError) as exc_info:
            await client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
    finally:
        await client.aclose()

    assert exc_info.value.status_code == 500
    assert route.call_count == 3  # 1 initial + 2 retries


@pytest.mark.asyncio
async def test_connect_error_is_retried(respx_mock: respx.MockRouter) -> None:
    """Transport-level failures (ConnectError) are transient → retry."""
    responses = iter(
        [
            httpx.ConnectError("network down"),
            httpx.Response(200, json=make_summary_envelope()),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        nxt = next(responses)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    route = respx_mock.get("/summary").mock(side_effect=handler)
    client = OnionooClient()
    try:
        resp = await client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
    finally:
        await client.aclose()

    assert resp.status_code == 200
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_non_transient_httpx_error_is_not_retried(
    respx_mock: respx.MockRouter,
) -> None:
    """Deterministic client-side errors (e.g. TooManyRedirects) must not retry —
    retrying just delays the same failure."""

    def handler(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        raise httpx.TooManyRedirects("loop detected")

    route = respx_mock.get("/summary").mock(side_effect=handler)
    client = OnionooClient()
    try:
        with pytest.raises(httpx.TooManyRedirects):
            await client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
    finally:
        await client.aclose()

    assert route.call_count == 1
