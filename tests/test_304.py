"""If-Modified-Since handling: forwarded to upstream and 304 propagated to caller."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient


def test_if_modified_since_is_forwarded_to_upstream(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/summary").mock(
        return_value=httpx.Response(304, headers={"Last-Modified": "Thu, 15 May 2026 12:00:00 GMT"})
    )

    r = app_client.get(
        "/v1/summary",
        params={"limit": 1},
        headers={"If-Modified-Since": "Thu, 15 May 2026 12:00:00 GMT"},
    )

    assert r.status_code == 304
    sent = route.calls.last.request
    assert sent.headers["if-modified-since"] == "Thu, 15 May 2026 12:00:00 GMT"


def test_304_propagates_last_modified_header(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(
        return_value=httpx.Response(304, headers={"Last-Modified": "Thu, 15 May 2026 12:00:00 GMT"})
    )

    r = app_client.get(
        "/v1/summary",
        params={"limit": 1},
        headers={"If-Modified-Since": "Thu, 15 May 2026 12:00:00 GMT"},
    )

    assert r.status_code == 304
    assert r.headers.get("last-modified") == "Thu, 15 May 2026 12:00:00 GMT"


def test_200_response_includes_upstream_last_modified(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """When upstream returns 200, our response should surface Last-Modified for clients."""
    from tests.conftest import make_summary_envelope

    respx_mock.get("/summary").mock(
        return_value=httpx.Response(
            200,
            json=make_summary_envelope(),
            headers={"Last-Modified": "Thu, 15 May 2026 12:00:00 GMT"},
        )
    )

    r = app_client.get("/v1/summary", params={"limit": 1})
    assert r.status_code == 200
    assert r.headers.get("last-modified") == "Thu, 15 May 2026 12:00:00 GMT"
