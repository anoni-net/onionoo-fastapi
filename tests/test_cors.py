"""CORS wiring: the allowlist, the headers browser fetches need, and cache safety.

The relay globe on the docs site fetches this service straight from the browser,
so these assertions stand in for a real cross-origin fetch.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings, settings
from tests.conftest import make_summary_envelope, relay

ALLOWED_ORIGIN = "https://anoni.net"
REJECTED_ORIGIN = "https://example.com"

# The endpoints the docs-site front end actually calls.
BROWSER_ENDPOINTS = [
    "/v1/details",
    "/v1/aggregate/countries",
    "/v1/aggregate/as",
    "/v1/aggregate/flags",
]


def _details_relay() -> dict[str, Any]:
    return {
        "nickname": "moria1",
        "fingerprint": "A" * 40,
        "or_addresses": ["128.31.0.34:9101"],
        "first_seen": "2025-01-01 00:00:00",
        "last_seen": "2026-05-15 12:00:00",
        "last_changed_address_or_port": "2025-01-01 00:00:00",
        "running": True,
        "consensus_weight": 20,
        "country": "us",
        "as": "AS3",
        "flags": ["Fast", "Running"],
        "advertised_bandwidth": 1000,
    }


@pytest.fixture
def cors_enabled_client(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> Iterator[TestClient]:
    monkeypatch.setattr(settings, "cors_allow_origins", [ALLOWED_ORIGIN])
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))
    respx_mock.get("/details").mock(
        return_value=httpx.Response(
            200,
            json={
                "version": "9.0",
                "relays_published": "2026-05-15 12:00:00",
                "bridges_published": "2026-05-15 12:00:00",
                "relays": [_details_relay()],
                "bridges": [],
            },
        )
    )
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cors_disabled_client(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> Iterator[TestClient]:
    """Whether CORSMiddleware gets mounted is decided inside `create_app`, so the
    allowlist has to be emptied before the app is built rather than in the test body."""
    monkeypatch.setattr(settings, "cors_allow_origins", [])
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))
    with TestClient(create_app()) as c:
        yield c


def _header_names(response: httpx.Response) -> set[str]:
    return {k.lower() for k in response.headers}


# --- the allowlist ----------------------------------------------------------


def test_default_allowlist_covers_docs_site_and_local_mkdocs() -> None:
    """A fresh deploy must serve the docs site without extra configuration, and a docs
    checkout must work against `mkdocs serve` on either loopback spelling.

    The clearnet and onion spellings are deliberately asymmetric. Clearnet docs are a
    path under the apex (https://anoni.net/docs/), so the origin is the bare apex, and
    `docs.anoni.net` does not exist. The onion mirror is a subdomain of the onion key,
    which is a separate origin and has to be listed on its own.
    """
    assert Settings.model_fields["cors_allow_origins"].default == [
        "https://anoni.net",
        "http://docs.anoninetru5tflukgfaehun7q6khowgmymcff3gtk5oyesqazhmfxtyd.onion",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]


def test_onion_mirror_origin_is_allowed(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    """Readers on the onion mirror are a big part of who this site is for, and Tor
    Browser sends the onion host as the origin. Its scheme is plain http, which is
    normal for an onion service, so the allowlist has to carry it verbatim."""
    onion = "http://docs.anoninetru5tflukgfaehun7q6khowgmymcff3gtk5oyesqazhmfxtyd.onion"
    monkeypatch.setattr(
        settings, "cors_allow_origins", Settings.model_fields["cors_allow_origins"].default
    )
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))
    with TestClient(create_app()) as client:
        r = client.get("/v1/summary", params={"limit": 1}, headers={"Origin": onion})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == onion

        preflight = client.options(
            "/v1/details",
            headers={"Origin": onion, "Access-Control-Request-Method": "GET"},
        )
        assert preflight.status_code in (200, 204)
        assert preflight.headers["access-control-allow-origin"] == onion


def test_legacy_env_var_name_is_still_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    """`CORS_ALLOWED_ORIGINS` was the 1.0.0 name. `extra="ignore"` would swallow it
    without a word, so a self-hoster upgrading would lose their allowlist and see only
    a browser-side CORS failure. Keep it working, and warn from `create_app`."""
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://legacy.example")
    assert Settings(_env_file=None).cors_allow_origins == ["https://legacy.example"]


def test_new_env_var_name_wins_when_both_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://legacy.example")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://current.example")
    assert Settings(_env_file=None).cors_allow_origins == ["https://current.example"]


def test_origins_parse_from_a_comma_separated_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`CORS_ALLOW_ORIGINS` follows pulse/backend's comma-separated convention. Without
    the `NoDecode` annotation pydantic-settings would try `json.loads` on this value
    and raise before the field validator ran."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", " https://a.example , https://b.example ,, ")
    assert Settings(_env_file=None).cors_allow_origins == [
        "https://a.example",
        "https://b.example",
    ]


def test_empty_env_var_disables_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    """docker-compose passes the variable through verbatim, so `CORS_ALLOW_ORIGINS=""`
    has to be the documented off switch rather than an empty-but-truthy value."""
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "")
    assert Settings(_env_file=None).cors_allow_origins == []


# --- request/response headers ----------------------------------------------


@pytest.mark.parametrize("path", BROWSER_ENDPOINTS)
def test_listed_origin_gets_allow_origin_on_every_browser_endpoint(
    cors_enabled_client: TestClient, path: str
) -> None:
    """CORSMiddleware is global, so cover the routes the front end actually uses."""
    r = cors_enabled_client.get(path, params={"limit": 1}, headers={"Origin": ALLOWED_ORIGIN})
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


@pytest.mark.parametrize("path", BROWSER_ENDPOINTS)
def test_preflight_succeeds_for_every_browser_endpoint(
    cors_enabled_client: TestClient, path: str
) -> None:
    r = cors_enabled_client.options(
        path,
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code in (200, 204), r.text
    assert r.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    allowed_methods = r.headers["access-control-allow-methods"]
    assert "GET" in allowed_methods
    assert "OPTIONS" in allowed_methods
    # Read-only service: nothing that mutates should be advertised.
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert verb not in allowed_methods


def test_unlisted_origin_gets_no_allow_origin(cors_enabled_client: TestClient) -> None:
    r = cors_enabled_client.get(
        "/v1/summary", params={"limit": 1}, headers={"Origin": REJECTED_ORIGIN}
    )
    assert r.status_code == 200
    assert "access-control-allow-origin" not in _header_names(r)


def test_preflight_from_unlisted_origin_gets_no_allow_origin(
    cors_enabled_client: TestClient,
) -> None:
    r = cors_enabled_client.options(
        "/v1/summary",
        headers={"Origin": REJECTED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in _header_names(r)


def test_credentials_are_never_allowed(cors_enabled_client: TestClient) -> None:
    """No route reads cookies or Authorization. Leaving credentials off keeps browsers
    from attaching ambient auth, and keeps a future wildcard allowlist usable."""
    simple = cors_enabled_client.get(
        "/v1/summary", params={"limit": 1}, headers={"Origin": ALLOWED_ORIGIN}
    )
    preflight = cors_enabled_client.options(
        "/v1/summary",
        headers={"Origin": ALLOWED_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    for r in (simple, preflight):
        assert "access-control-allow-credentials" not in _header_names(r)


def test_expose_headers_lets_js_read_request_id_and_last_modified(
    cors_enabled_client: TestClient,
) -> None:
    r = cors_enabled_client.get(
        "/v1/summary", params={"limit": 1}, headers={"Origin": ALLOWED_ORIGIN}
    )
    exposed = r.headers.get("access-control-expose-headers", "")
    assert "X-Request-ID" in exposed
    assert "Last-Modified" in exposed


# --- Vary: Origin, i.e. shared-cache safety ---------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"Origin": ALLOWED_ORIGIN}, id="listed-origin"),
        pytest.param({"Origin": REJECTED_ORIGIN}, id="unlisted-origin"),
        pytest.param({}, id="no-origin-header"),
    ],
)
def test_vary_origin_is_present_regardless_of_origin(
    cors_enabled_client: TestClient, headers: dict[str, str]
) -> None:
    """Starlette only adds `Vary: Origin` on the allowed-origin branch. The other two
    cases share a cache key with it, so behind Cloudflare a copy stored for a crawler
    (no `Origin`, therefore no ACAO) could be replayed to a browser fetch from the docs
    site, which the browser then blocks. `VaryOriginMiddleware` closes that gap."""
    r = cors_enabled_client.get("/v1/summary", params={"limit": 1}, headers=headers)
    assert r.status_code == 200
    varies = {v.strip().lower() for v in r.headers["vary"].split(",")}
    assert "origin" in varies


def test_vary_origin_is_present_when_cors_is_disabled(
    cors_disabled_client: TestClient,
) -> None:
    """The cache hazard does not depend on CORS being on: an instance running with
    CORS off can still sit behind the same cache as one that has it on."""
    r = cors_disabled_client.get("/v1/summary", params={"limit": 1})
    varies = {v.strip().lower() for v in r.headers["vary"].split(",")}
    assert "origin" in varies


def test_vary_origin_is_not_duplicated(cors_enabled_client: TestClient) -> None:
    """CORSMiddleware already set it on this branch, so the middleware must not append
    a second copy."""
    r = cors_enabled_client.get(
        "/v1/summary", params={"limit": 1}, headers={"Origin": ALLOWED_ORIGIN}
    )
    values = [v.strip().lower() for v in r.headers["vary"].split(",")]
    assert values.count("origin") == 1


# --- interaction with the rest of the middleware stack ----------------------


def test_gzip_still_applies_to_a_cross_origin_fetch(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    """The front end relies on compression: the full-corpus projection is ~1.9 MB raw
    and ~118 KB gzipped. Adding CORS and Vary must not cost that, and `Vary` has to
    carry both keys so a cache cannot serve gzip to a client that did not ask for it."""
    monkeypatch.setattr(settings, "cors_allow_origins", [ALLOWED_ORIGIN])
    big = make_summary_envelope(relays=[relay(f"relay{i:04d}", f"{i:040X}") for i in range(400)])
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=big))
    with TestClient(create_app()) as client:
        r = client.get(
            "/v1/summary",
            params={"limit": 400},
            headers={"Origin": ALLOWED_ORIGIN, "Accept-Encoding": "gzip"},
        )
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    varies = {v.strip().lower() for v in r.headers["vary"].split(",")}
    assert varies == {"origin", "accept-encoding"}
    assert len(r.json()["relays"]) == 400


def test_health_endpoints_keep_working_with_cors_enabled(
    cors_enabled_client: TestClient,
) -> None:
    """The middleware is global, so it also wraps the probes. They must stay plain 200s
    that a container healthcheck (which sends no `Origin`) can still read."""
    for path in ("/healthz", "/metrics"):
        r = cors_enabled_client.get(path)
        assert r.status_code == 200, path
        assert "access-control-allow-origin" not in _header_names(r), path

    probed = cors_enabled_client.get("/healthz", headers={"Origin": ALLOWED_ORIGIN})
    assert probed.status_code == 200
    assert probed.json() == {"status": "ok"}


def test_cors_disabled_when_origins_empty(cors_disabled_client: TestClient) -> None:
    """With `cors_allow_origins = []` the middleware is not mounted; no ACAO."""
    r = cors_disabled_client.get(
        "/v1/summary",
        params={"limit": 1},
        headers={"Origin": ALLOWED_ORIGIN},
    )
    assert r.status_code == 200
    assert "access-control-allow-origin" not in _header_names(r)
