"""Tests for the stdio MCP server entry (app/mcp_stdio.py).

We don't spawn a real subprocess — instead we build the FastMCP server in
process and exercise `list_tools` / `call_tool` directly. Upstream Onionoo
calls are mocked via respx.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.mcp_stdio import build_server

EXPECTED_TOOLS = {
    "find_relay",
    "get_relay_health",
    "top_relays_by_bandwidth",
    "compare_relays",
    "country_summary",
    "aggregate_relays",
    "onionoo_summary",
    "onionoo_details",
    "onionoo_bandwidth",
    "onionoo_weights",
    "onionoo_clients",
    "onionoo_uptime",
}


@pytest.mark.asyncio
async def test_stdio_server_registers_expected_tools() -> None:
    server, client = build_server()
    try:
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert names == EXPECTED_TOOLS, f"unexpected tools: {names ^ EXPECTED_TOOLS}"
        for t in tools:
            assert t.description and len(t.description) > 40
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_stdio_find_relay_routes_through_onionoo_client(
    respx_mock: respx.MockRouter,
) -> None:
    """call_tool('find_relay', ...) should hit the mocked upstream and return relays."""
    respx_mock.get("/details").mock(
        return_value=httpx.Response(
            200,
            json={
                "version": "9.0",
                "relays_published": "2026-05-15 12:00:00",
                "bridges_published": "2026-05-15 12:00:00",
                "relays": [
                    {
                        "nickname": "moria1",
                        "fingerprint": "9695DFC35FFEB861329B9F1AB04C46397020CE31",
                        "running": True,
                        "country": "us",
                        "as": "AS3",
                        "flags": ["Authority", "Fast"],
                    }
                ],
                "bridges": [],
            },
        )
    )

    server, client = build_server()
    try:
        result = await server.call_tool("find_relay", {"query": "moria"})
    finally:
        await client.aclose()

    # FastMCP returns a list of content blocks; the JSON payload is in `.text`.
    content, _ = result
    text_blocks = [c.text for c in content if hasattr(c, "text")]
    payload = json.loads(text_blocks[0])
    assert payload["matched_via"] == "search"
    assert payload["relays"][0]["nickname"] == "moria1"


@pytest.mark.asyncio
async def test_stdio_onionoo_passthrough_returns_raw_body(
    respx_mock: respx.MockRouter,
) -> None:
    respx_mock.get("/summary").mock(
        return_value=httpx.Response(
            200,
            json={
                "version": "9.0",
                "relays_published": "2026-05-15 12:00:00",
                "bridges_published": "2026-05-15 12:00:00",
                "relays": [{"n": "x", "f": "F" * 40, "a": ["1.1.1.1"], "r": True}],
                "bridges": [],
            },
        )
    )

    server, client = build_server()
    try:
        result = await server.call_tool("onionoo_summary", {"params": {"limit": "1"}})
    finally:
        await client.aclose()

    content, _ = result
    payload = json.loads(content[0].text)
    assert payload["status_code"] == 200
    assert payload["body"]["relays"][0]["n"] == "x"
