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


def test_healthz_ready_bypasses_response_cache(
    app_client: TestClient,
    respx_mock: respx.MockRouter,
) -> None:
    """A successful /v1/summary call must not paper over a later upstream outage.

    Regression for the case where /healthz/ready piggybacked on OnionooClient's
    TTL cache: a cached 200 could mask an outage for up to TTL seconds.
    """
    # 1) Prime the OnionooClient response cache with a successful summary.
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))
    assert app_client.get("/v1/summary", params={"limit": 1}).status_code == 200

    # 2) Invalidate the readiness short-cache so the next probe actually runs.
    app_client.app.state.ready_cache["checked_at"] = 0.0

    # 3) Upstream now fails. The OnionooClient response cache is still warm,
    #    but ready check must report 503 because it bypasses the cache.
    respx_mock.get("/summary").mock(side_effect=httpx.ConnectError("boom"))

    r = app_client.get("/healthz/ready")
    assert r.status_code == 503, r.text
    assert r.json()["status"] == "degraded"
