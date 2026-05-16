"""The proxy-injected `_meta` block carries cache age + upstream Last-Modified."""

from __future__ import annotations

import time

import httpx
import respx
from fastapi.testclient import TestClient

from tests.conftest import make_summary_envelope


def test_meta_block_present_with_upstream_last_modified(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(
        return_value=httpx.Response(
            200,
            json=make_summary_envelope(),
            headers={"Last-Modified": "Thu, 15 May 2026 12:00:00 GMT"},
        )
    )

    body = app_client.get("/v1/summary", params={"limit": 1}).json()
    meta = body["_meta"]
    assert meta["upstream_last_modified"] == "Thu, 15 May 2026 12:00:00 GMT"
    assert meta["cache_age_seconds"] == 0.0  # first fetch, not from cache


def test_meta_cache_age_advances_between_calls(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))

    # First call seeds cache (age=0).
    first = app_client.get("/v1/summary", params={"limit": 1, "search": "metatest"}).json()
    assert first["_meta"]["cache_age_seconds"] == 0.0

    time.sleep(0.02)

    # Second call should be served from cache and report a non-zero age.
    second = app_client.get("/v1/summary", params={"limit": 1, "search": "metatest"}).json()
    assert second["_meta"]["cache_age_seconds"] > 0.0


def test_meta_absent_in_raw_passthrough(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """Raw mode forwards upstream JSON verbatim; the proxy must not inject _meta."""
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))

    body = app_client.get("/v1/summary", params={"limit": 1, "raw": "true"}).json()
    assert "_meta" not in body
