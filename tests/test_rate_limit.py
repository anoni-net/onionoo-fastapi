"""When RATE_LIMIT_ENABLED is true, the SlowAPI middleware actually enforces 429."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import settings
from tests.conftest import make_summary_envelope


@pytest.fixture
def rate_limited_client(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_rate_limit_emits_429_when_exceeded(rate_limited_client: TestClient) -> None:
    """Sending more requests than the per-minute limit returns 429.

    SlowAPIMiddleware short-circuits the response itself (rather than going
    through the FastAPI exception handler), so we just verify a 429 lands.
    """
    statuses = [
        rate_limited_client.get("/v1/summary", params={"limit": 1}).status_code for _ in range(5)
    ]
    assert 200 in statuses, f"expected at least one 200, got {statuses}"
    assert 429 in statuses, f"expected at least one 429, got {statuses}"


def test_rate_limit_disabled_does_not_block(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """Without RATE_LIMIT_ENABLED the middleware is not mounted; no 429."""
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))
    for _ in range(10):
        r = app_client.get("/v1/summary", params={"limit": 1})
        assert r.status_code == 200


def test_rate_limit_exempts_health_and_metrics(rate_limited_client: TestClient) -> None:
    """Health probes and Prometheus scrapes must not eat the per-IP budget.

    Hammer the exempt paths well past the configured per-minute cap and verify
    every response stays 200.
    """
    cap = 2
    for path in ("/healthz", "/metrics"):
        statuses = [rate_limited_client.get(path).status_code for _ in range(cap * 5)]
        assert all(s == 200 for s in statuses), f"{path} statuses: {statuses}"
