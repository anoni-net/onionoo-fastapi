"""X-Request-ID middleware honors client-supplied IDs and generates one otherwise."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient


def test_request_id_is_echoed_when_provided(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(
        return_value=httpx.Response(
            200,
            json={
                "version": "9.0",
                "relays_published": "2026-05-15 12:00:00",
                "bridges_published": "2026-05-15 12:00:00",
                "relays": [],
                "bridges": [],
            },
        )
    )

    r = app_client.get(
        "/v1/summary",
        params={"limit": 1},
        headers={"X-Request-ID": "abc-123-test"},
    )
    assert r.status_code == 200
    assert r.headers["X-Request-ID"] == "abc-123-test"


def test_request_id_is_generated_when_missing(app_client: TestClient) -> None:
    """Without an inbound X-Request-ID, the middleware generates one (32-hex uuid4)."""
    r = app_client.get("/healthz")
    assert r.status_code == 200
    rid = r.headers["X-Request-ID"]
    assert len(rid) == 32
    assert all(c in "0123456789abcdef" for c in rid)
