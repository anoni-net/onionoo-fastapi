"""CORSMiddleware is only mounted when `cors_allowed_origins` is non-empty,
and the headers it returns must match what browser-side fetches need."""

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
def cors_enabled_client(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "cors_allowed_origins", ["https://docs.anoni.net"])
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_cors_preflight_returns_allow_origin_for_listed_origin(
    cors_enabled_client: TestClient,
) -> None:
    """An OPTIONS preflight from the configured origin yields ACAO + ACAM."""
    r = cors_enabled_client.options(
        "/v1/summary",
        headers={
            "Origin": "https://docs.anoni.net",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204), r.text
    assert r.headers["access-control-allow-origin"] == "https://docs.anoni.net"
    assert "GET" in r.headers["access-control-allow-methods"]


def test_cors_preflight_rejects_unlisted_origin(
    cors_enabled_client: TestClient,
) -> None:
    """An origin not in the allowlist must NOT receive an ACAO header."""
    r = cors_enabled_client.options(
        "/v1/summary",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_cors_simple_request_exposes_proxy_headers(
    cors_enabled_client: TestClient,
) -> None:
    """The middleware must expose X-Request-ID + Last-Modified so JS can read them."""
    r = cors_enabled_client.get(
        "/v1/summary",
        params={"limit": 1},
        headers={"Origin": "https://docs.anoni.net"},
    )
    assert r.status_code == 200
    exposed = r.headers.get("access-control-expose-headers", "")
    assert "X-Request-ID" in exposed
    assert "Last-Modified" in exposed


def test_cors_disabled_when_origins_empty(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """With cors_allowed_origins = [] the middleware is not mounted; no ACAO."""
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))
    r = app_client.get(
        "/v1/summary",
        params={"limit": 1},
        headers={"Origin": "https://docs.anoni.net"},
    )
    assert r.status_code == 200
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}
