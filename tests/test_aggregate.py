"""/v1/aggregate/* endpoints: bucket math + parameter forwarding."""

from __future__ import annotations

from typing import Any

import httpx
import respx
from fastapi.testclient import TestClient


def _detail(country: str, asn: str, flags: list[str], bw: int, weight: int) -> dict[str, Any]:
    return {
        "nickname": "r",
        "fingerprint": "A" * 40,
        "or_addresses": ["1.1.1.1:9001"],
        "first_seen": "2025-01-01 00:00:00",
        "last_seen": "2026-05-15 12:00:00",
        "last_changed_address_or_port": "2025-01-01 00:00:00",
        "running": True,
        "consensus_weight": weight,
        "country": country,
        "as": asn,
        "flags": flags,
        "advertised_bandwidth": bw,
    }


def _details_envelope(relays: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": "9.0",
        "relays_published": "2026-05-15 12:00:00",
        "bridges_published": "2026-05-15 12:00:00",
        "relays": relays,
        "bridges": [],
    }


def test_aggregate_countries_buckets_correctly(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/details").mock(
        return_value=httpx.Response(
            200,
            json=_details_envelope(
                [
                    _detail("us", "AS1", ["Fast"], 100, 10),
                    _detail("us", "AS2", ["Fast"], 200, 20),
                    _detail("de", "AS3", ["Guard"], 50, 5),
                ]
            ),
        )
    )

    r = app_client.get("/v1/aggregate/countries")
    assert r.status_code == 200
    body = r.json()
    assert body["group_by"] == "country"
    by_key = {b["key"]: b for b in body["buckets"]}
    assert by_key["us"]["relay_count"] == 2
    assert by_key["us"]["total_advertised_bandwidth_bps"] == 300
    assert by_key["us"]["total_consensus_weight"] == 30
    assert by_key["de"]["relay_count"] == 1
    # Sort order: us (2 relays) before de (1 relay).
    assert body["buckets"][0]["key"] == "us"


def test_aggregate_flags_double_counts_multi_flag_relays(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    """A relay with two flags increments both flag buckets."""
    respx_mock.get("/details").mock(
        return_value=httpx.Response(
            200,
            json=_details_envelope(
                [
                    _detail("us", "AS1", ["Guard", "Fast"], 100, 10),
                    _detail("us", "AS2", ["Exit", "Fast"], 200, 20),
                ]
            ),
        )
    )

    r = app_client.get("/v1/aggregate/flags")
    assert r.status_code == 200
    counts = {b["key"]: b["relay_count"] for b in r.json()["buckets"]}
    assert counts["Fast"] == 2
    assert counts["Guard"] == 1
    assert counts["Exit"] == 1


def test_aggregate_forwards_running_filter_and_fields(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/details").mock(
        return_value=httpx.Response(200, json=_details_envelope([]))
    )

    app_client.get("/v1/aggregate/as")
    sent = route.calls.last.request
    assert sent.url.params["running"] == "true"
    # The aggregator trims response with a fields= projection to save bytes.
    assert "advertised_bandwidth" in sent.url.params["fields"]
    assert "country" in sent.url.params["fields"]


def test_aggregate_top_truncates_buckets(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/details").mock(
        return_value=httpx.Response(
            200,
            json=_details_envelope(
                [
                    _detail("us", "AS1", ["Fast"], 1, 1),
                    _detail("us", "AS1", ["Fast"], 1, 1),
                    _detail("de", "AS2", ["Fast"], 1, 1),
                    _detail("fr", "AS3", ["Fast"], 1, 1),
                ]
            ),
        )
    )

    r = app_client.get("/v1/aggregate/countries", params={"top": 2})
    assert r.status_code == 200
    buckets = r.json()["buckets"]
    assert len(buckets) == 2
    assert {b["key"] for b in buckets} == {"us", "de"}
