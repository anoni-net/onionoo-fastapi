"""`fields=` is forwarded to upstream on every endpoint that accepts it."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tests.conftest import make_summary_envelope


@pytest.mark.parametrize(
    "path",
    [
        "/v1/summary",
        "/v1/details",
        "/v1/bandwidth",
        "/v1/weights",
        "/v1/clients",
        "/v1/uptime",
    ],
)
def test_fields_param_is_forwarded(
    path: str, app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    method = path.rsplit("/", 1)[-1]
    upstream_path = f"/{method}"
    route = respx_mock.get(upstream_path).mock(
        return_value=httpx.Response(200, json=make_summary_envelope())
    )

    r = app_client.get(path, params={"limit": 1, "fields": "fingerprint,nickname"})
    assert r.status_code == 200, r.text
    assert route.calls.last.request.url.params["fields"] == "fingerprint,nickname"


@pytest.mark.parametrize("path", ["/v1/summary", "/v1/details"])
def test_envelope_with_missing_published_timestamps_still_validates(
    path: str, app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """When `fields=` (or a stub upstream) drops `relays_published`/`bridges_published`,
    the response model must still validate so the proxy keeps returning 200."""
    method = path.rsplit("/", 1)[-1]
    respx_mock.get(f"/{method}").mock(
        return_value=httpx.Response(
            200,
            json={"version": "9.0", "relays": [], "bridges": []},
        )
    )

    r = app_client.get(path, params={"limit": 1, "fields": "fingerprint"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "9.0"
    assert body["relays"] == []
    assert body["bridges"] == []


def test_details_fields_projection_with_nonempty_relays_returns_200(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """Regression for issue #2 (1): `fields=` on /details trims every relay object to
    the requested keys. Those trimmed objects can't satisfy the full DetailsRelay model
    (nickname/fingerprint/… are required), so the proxy must pass the projection through
    raw instead of re-validating and raising a 500."""
    trimmed = [
        {"country": "us", "flags": ["Fast", "Running", "Valid"]},
        {"country": "de", "flags": ["Guard", "Running"]},
    ]
    respx_mock.get("/details").mock(
        return_value=httpx.Response(200, json={"version": "9.0", "relays": trimmed, "bridges": []})
    )

    r = app_client.get(
        "/v1/details", params={"running": True, "limit": 5, "fields": "country,flags"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Raw passthrough: the projected keys survive verbatim, no required-field crash.
    assert [x["country"] for x in body["relays"]] == ["us", "de"]
    assert body["relays"][0]["flags"] == ["Fast", "Running", "Valid"]


def test_summary_with_fields_keeps_semantic_shape(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """Onionoo only honours `fields=` on /details; /summary returns full n/f/a/r objects
    either way (verified against live upstream). So the raw passthrough must stay scoped
    to /details, otherwise passing `fields` to /summary would silently swap the documented
    nickname/fingerprint/addresses/running keys back to upstream shorthand and drop
    `_meta`, while the OpenAPI schema still advertises SummaryResponse."""
    full = [
        {
            "n": "moria1",
            "f": "9695DFC35FFEB861329B9F1AB04C46397020CE31",
            "a": ["128.31.0.34"],
            "r": True,
        }
    ]
    respx_mock.get("/summary").mock(
        return_value=httpx.Response(200, json={"version": "9.0", "relays": full, "bridges": []})
    )

    r = app_client.get("/v1/summary", params={"limit": 5, "fields": "nickname,fingerprint"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["relays"][0]["nickname"] == "moria1"
    assert body["relays"][0]["addresses"] == ["128.31.0.34"]
    assert body["relays"][0]["running"] is True
    assert "_meta" in body
