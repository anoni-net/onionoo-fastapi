"""Verify that limit/offset query parameters are forwarded to upstream and
that the semantic /v1/summary response surfaces the upstream relays."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from app.settings import settings
from tests.conftest import make_summary_envelope, relay


def test_limit_returns_requested_count(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """limit=5 results in 5 relays being returned to the caller."""
    relays = [relay(n=f"relay{i:02d}", f=f"{i:040x}") for i in range(5)]
    respx_mock.get("/summary").mock(
        return_value=httpx.Response(200, json=make_summary_envelope(relays=relays))
    )

    r = app_client.get("/v1/summary", params={"type": "relay", "limit": 5})
    r.raise_for_status()
    body = r.json()
    assert len(body["relays"]) == 5
    assert body["relays"][0]["nickname"] == "relay00"


def test_offset_is_forwarded_to_upstream(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """offset=5 should appear in the outbound request to upstream."""
    route = respx_mock.get("/summary").mock(
        return_value=httpx.Response(200, json=make_summary_envelope(relays=[]))
    )

    app_client.get("/v1/summary", params={"type": "relay", "limit": 5, "offset": 5})

    assert route.called
    sent = route.calls.last.request
    assert sent.url.params["offset"] == "5"
    assert sent.url.params["limit"] == "5"
    assert sent.url.params["type"] == "relay"


def test_limit_up_to_max_is_accepted_and_forwarded(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """Regression for issue #2 (2): a single request must be able to pull the whole
    corpus. `limit=max_limit` plus a projection is accepted (not 422) and forwarded to
    upstream, so callers can avoid offset pagination entirely."""
    assert settings.max_limit >= 10000, "max_limit must allow one-shot full-corpus fetch"
    route = respx_mock.get("/details").mock(
        return_value=httpx.Response(200, json={"version": "9.0", "relays": [], "bridges": []})
    )

    r = app_client.get(
        "/v1/details", params={"limit": settings.max_limit, "fields": "fingerprint,nickname"}
    )
    assert r.status_code == 200, r.text
    assert route.calls.last.request.url.params["limit"] == str(settings.max_limit)


def test_limit_above_max_is_rejected(
    app_client: TestClient,
    respx_mock: respx.MockRouter,  # noqa: ARG001
) -> None:
    """limit past the ceiling is a 422 validation error, not a silent clamp."""
    r = app_client.get("/v1/details", params={"limit": settings.max_limit + 1})
    assert r.status_code == 422


def test_high_limit_without_fields_is_rejected(
    app_client: TestClient,
    respx_mock: respx.MockRouter,  # noqa: ARG001
) -> None:
    """The full-corpus ceiling is only affordable with a projection: untrimmed /details
    at limit=20000 is ~93 MB against live Onionoo, and the client caches the parsed body.
    Without `fields=` the request is refused with an actionable message."""
    r = app_client.get("/v1/details", params={"limit": settings.max_limit_untrimmed + 1})
    assert r.status_code == 422
    assert "fields=" in r.json()["detail"]


def test_untrimmed_limit_at_the_ceiling_is_allowed(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """The guard only kicks in past the ceiling, so existing untrimmed callers keep working."""
    route = respx_mock.get("/details").mock(
        return_value=httpx.Response(200, json={"version": "9.0", "relays": [], "bridges": []})
    )

    r = app_client.get("/v1/details", params={"limit": settings.max_limit_untrimmed})
    assert r.status_code == 200, r.text
    assert route.calls.last.request.url.params["limit"] == str(settings.max_limit_untrimmed)


def test_semantic_keys_are_remapped(app_client: TestClient, respx_mock: respx.MockRouter) -> None:
    """Upstream short keys n/f/a/r get mapped to nickname/fingerprint/addresses/running."""
    relays = [relay(n="moria1", f="9695DFC35FFEB861329B9F1AB04C46397020CE31")]
    respx_mock.get("/summary").mock(
        return_value=httpx.Response(200, json=make_summary_envelope(relays=relays))
    )

    body = app_client.get("/v1/summary", params={"limit": 1}).json()
    item = body["relays"][0]
    assert item["nickname"] == "moria1"
    assert item["fingerprint"] == "9695DFC35FFEB861329B9F1AB04C46397020CE31"
    assert item["running"] is True
    assert isinstance(item["addresses"], list)
