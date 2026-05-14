"""Unit tests for high-level MCP tools in app/mcp_tools.py.

All upstream Onionoo calls are mocked via respx — these tests run offline.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.mcp_tools import (
    compare_relays,
    country_summary,
    find_relay,
    get_relay_health,
    top_relays_by_bandwidth,
)
from app.services.onionoo_client import OnionooClient

FP_MORIA1 = "9695DFC35FFEB861329B9F1AB04C46397020CE31"
FP_OTHER = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def _details_envelope(relays: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": "9.0",
        "relays_published": "2026-05-15 12:00:00",
        "bridges_published": "2026-05-15 12:00:00",
        "relays": relays,
        "bridges": [],
    }


def _detail_relay(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "nickname": "moria1",
        "fingerprint": FP_MORIA1,
        "or_addresses": ["128.31.0.39:9101"],
        "first_seen": "2007-10-27 03:00:00",
        "last_seen": "2026-05-15 12:00:00",
        "last_changed_address_or_port": "2024-01-01 00:00:00",
        "running": True,
        "consensus_weight": 12345,
        "country": "us",
        "as": "AS3",
        "as_name": "MIT",
        "flags": ["Authority", "Fast", "Guard"],
        "advertised_bandwidth": 1000000,
        "version": "0.4.8.10",
    }
    base.update(overrides)
    return base


@pytest.fixture
async def client() -> OnionooClient:
    c = OnionooClient()
    try:
        yield c
    finally:
        await c.aclose()


@pytest.mark.asyncio
async def test_find_relay_routes_fingerprint_to_lookup(
    client: OnionooClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/details").mock(
        return_value=httpx.Response(200, json=_details_envelope([_detail_relay()]))
    )

    result = await find_relay(client, FP_MORIA1)

    assert result["matched_via"] == "lookup"
    assert result["relays"][0]["fingerprint"] == FP_MORIA1
    sent = route.calls.last.request
    assert sent.url.params["lookup"] == FP_MORIA1
    assert "search" not in sent.url.params


@pytest.mark.asyncio
async def test_find_relay_routes_as_query_to_as_filter(
    client: OnionooClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/details").mock(
        return_value=httpx.Response(200, json=_details_envelope([]))
    )

    result = await find_relay(client, "AS3")

    assert result["matched_via"] == "as"
    assert route.calls.last.request.url.params["as"] == "AS3"


@pytest.mark.asyncio
async def test_find_relay_routes_freeform_to_search(
    client: OnionooClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/details").mock(
        return_value=httpx.Response(200, json=_details_envelope([_detail_relay()]))
    )

    result = await find_relay(client, "moria")

    assert result["matched_via"] == "search"
    assert route.calls.last.request.url.params["search"] == "moria"


@pytest.mark.asyncio
async def test_get_relay_health_fans_out_three_calls(
    client: OnionooClient, respx_mock: respx.MockRouter
) -> None:
    details_route = respx_mock.get("/details").mock(
        return_value=httpx.Response(200, json=_details_envelope([_detail_relay()]))
    )
    uptime_route = respx_mock.get("/uptime").mock(
        return_value=httpx.Response(
            200,
            json={
                "version": "9.0",
                "relays_published": "2026-05-15 12:00:00",
                "bridges_published": "2026-05-15 12:00:00",
                "relays": [
                    {
                        "fingerprint": FP_MORIA1,
                        "uptime": {"1_month": {"first": "...", "values": [1.0]}},
                    }
                ],
                "bridges": [],
            },
        )
    )
    bandwidth_route = respx_mock.get("/bandwidth").mock(
        return_value=httpx.Response(
            200,
            json={
                "version": "9.0",
                "relays_published": "2026-05-15 12:00:00",
                "bridges_published": "2026-05-15 12:00:00",
                "relays": [
                    {
                        "fingerprint": FP_MORIA1,
                        "read_history": {"1_month": {"first": "...", "values": [1]}},
                        "write_history": {"1_month": {"first": "...", "values": [1]}},
                    }
                ],
                "bridges": [],
            },
        )
    )

    result = await get_relay_health(client, FP_MORIA1)

    assert details_route.called and uptime_route.called and bandwidth_route.called
    assert result["found"] is True
    assert result["nickname"] == "moria1"
    assert result["advertised_bandwidth"] == 1000000
    assert result["uptime_periods"] == ["1_month"]
    assert result["bandwidth_periods"]["read"] == ["1_month"]


@pytest.mark.asyncio
async def test_get_relay_health_returns_not_found(
    client: OnionooClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/details").mock(return_value=httpx.Response(200, json=_details_envelope([])))
    respx_mock.get("/uptime").mock(
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
    respx_mock.get("/bandwidth").mock(
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

    result = await get_relay_health(client, FP_MORIA1)
    assert result["found"] is False
    assert result["fingerprint"] == FP_MORIA1


@pytest.mark.asyncio
async def test_get_relay_health_rejects_bad_fingerprint(
    client: OnionooClient,  # noqa: ARG001
) -> None:
    with pytest.raises(ValueError):
        await get_relay_health(client, "not-a-fingerprint")


@pytest.mark.asyncio
async def test_top_relays_by_bandwidth_passes_filters(
    client: OnionooClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get("/details").mock(
        return_value=httpx.Response(200, json=_details_envelope([_detail_relay()]))
    )

    result = await top_relays_by_bandwidth(client, country="us", flag="Exit", limit=5)

    sent = route.calls.last.request
    assert sent.url.params["country"] == "us"
    assert sent.url.params["flag"] == "Exit"
    assert sent.url.params["limit"] == "5"
    assert sent.url.params["order"] == "-consensus_weight"
    assert sent.url.params["running"] == "true"
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_compare_relays_fans_out_per_fingerprint(
    client: OnionooClient, respx_mock: respx.MockRouter
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        fp = request.url.params["lookup"]
        if fp == FP_MORIA1:
            return httpx.Response(200, json=_details_envelope([_detail_relay()]))
        return httpx.Response(200, json=_details_envelope([]))

    route = respx_mock.get("/details").mock(side_effect=handler)

    result = await compare_relays(client, [FP_MORIA1, FP_OTHER])

    assert route.call_count == 2
    by_fp = {r["fingerprint"]: r for r in result["relays"]}
    assert by_fp[FP_MORIA1]["found"] is True
    assert by_fp[FP_MORIA1]["nickname"] == "moria1"
    assert by_fp[FP_OTHER]["found"] is False


@pytest.mark.asyncio
async def test_compare_relays_rejects_invalid_fp(
    client: OnionooClient,  # noqa: ARG001
) -> None:
    with pytest.raises(ValueError):
        await compare_relays(client, [FP_MORIA1, "garbage"])


@pytest.mark.asyncio
async def test_country_summary_aggregates(
    client: OnionooClient, respx_mock: respx.MockRouter
) -> None:
    relays = [
        _detail_relay(flags=["Guard", "Fast"], advertised_bandwidth=1000, consensus_weight=10),
        _detail_relay(
            fingerprint=FP_OTHER,
            nickname="r2",
            flags=["Exit", "Fast"],
            advertised_bandwidth=2000,
            consensus_weight=20,
        ),
    ]
    route = respx_mock.get("/details").mock(
        return_value=httpx.Response(200, json=_details_envelope(relays))
    )

    result = await country_summary(client, "US")

    sent = route.calls.last.request
    assert sent.url.params["country"] == "us"
    assert sent.url.params["running"] == "true"

    assert result["country"] == "us"
    assert result["running_relay_count"] == 2
    assert result["total_advertised_bandwidth_bps"] == 3000
    assert result["total_consensus_weight"] == 30
    # Fast appears in both relays, Guard and Exit in one each.
    assert result["flag_counts"]["Fast"] == 2
    assert result["flag_counts"]["Guard"] == 1
    assert result["flag_counts"]["Exit"] == 1
