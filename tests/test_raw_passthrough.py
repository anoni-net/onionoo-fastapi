"""raw=true returns the upstream JSON verbatim, skipping Pydantic re-validation.

Verifies (a) extra/unknown upstream keys survive when raw=True, and
(b) raw and non-raw modes return the same data semantics for known fields.
"""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from tests.conftest import make_summary_envelope, relay


def _envelope_with_extras() -> dict:
    env = make_summary_envelope(relays=[relay("r1", "a" * 40)])
    # Add a top-level field the Pydantic model doesn't know about.
    env["future_field"] = "should-survive-raw"
    return env


def test_raw_returns_unknown_upstream_fields(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=_envelope_with_extras()))

    r_raw = app_client.get("/v1/summary", params={"limit": 1, "raw": "true"})
    assert r_raw.status_code == 200
    raw_body = r_raw.json()
    assert raw_body["future_field"] == "should-survive-raw"
    # raw mode does NOT remap short keys → it returns upstream as-is.
    assert raw_body["relays"][0]["n"] == "r1"


def test_non_raw_remaps_keys_and_keeps_extra_via_extra_allow(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """Non-raw mode applies semantic renaming (n→nickname); extras survive due to extra=allow."""
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=_envelope_with_extras()))

    r = app_client.get("/v1/summary", params={"limit": 1})
    assert r.status_code == 200
    body = r.json()
    # Semantic renaming kicks in for the relay.
    assert body["relays"][0]["nickname"] == "r1"
    # Pydantic ConfigDict(extra="allow") preserves unknown top-level keys.
    assert body.get("future_field") == "should-survive-raw"
