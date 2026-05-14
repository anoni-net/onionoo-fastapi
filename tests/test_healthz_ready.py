"""healthz/ready exercises the upstream connection; healthz stays a static OK."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from tests.conftest import make_summary_envelope


def test_healthz_returns_static_ok(app_client: TestClient) -> None:
    r = app_client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_healthz_ready_passes_when_upstream_ok(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))

    r = app_client.get("/healthz/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


def test_healthz_ready_fails_when_upstream_unreachable(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(side_effect=httpx.ConnectError("boom"))

    # Reset cached result by calling with a fresh state — the app starts with
    # checked_at=0 so the first call exercises the upstream.
    r = app_client.get("/healthz/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert "upstream unreachable" in body["detail"]
