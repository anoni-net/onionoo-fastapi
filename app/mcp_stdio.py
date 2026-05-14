"""Stdio MCP server entry point — `onionoo-mcp` console script.

Exposes both the six low-level Onionoo endpoints (`onionoo_summary`, ...,
`onionoo_uptime`) AND the high-level task-oriented tools defined in
`app.mcp_tools` (find_relay, get_relay_health, top_relays_by_bandwidth,
compare_relays, country_summary).

Use this when you want an MCP-native client like Claude Desktop or Cursor to
spawn a local subprocess and talk to it over stdio. For Streamable HTTP, run
the FastAPI app instead and connect to `/mcp`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from app.mcp_tools import (
    aggregate_relays,
    compare_relays,
    country_summary,
    find_relay,
    get_relay_health,
    top_relays_by_bandwidth,
)
from app.services.onionoo_client import OnionooClient

_INSTRUCTIONS = """\
This server wraps the Tor Onionoo API. Use the high-level tools first:
- `find_relay` for free-form discovery
- `get_relay_health` for a single relay's status snapshot
- `top_relays_by_bandwidth` for ranking
- `compare_relays` for side-by-side
- `country_summary` for aggregates

Drop down to the low-level tools (onionoo_summary, onionoo_details, ...) when
you need raw Onionoo response shapes or filters that aren't covered above.
"""


def build_server() -> FastMCP:
    """Build (but do not run) the stdio MCP server, wired to a fresh OnionooClient."""
    server = FastMCP("onionoo-mcp", instructions=_INSTRUCTIONS)
    client = OnionooClient()
    server._onionoo_client = client  # type: ignore[attr-defined]

    # --- High-level tools ----------------------------------------------------

    @server.tool(
        name="find_relay",
        description=(
            "Find Tor relays or bridges by free-form query. Auto-detects whether the "
            "query is a 40-hex fingerprint (uses lookup), an AS number like 'AS3' "
            "(uses as filter), an IP address (uses search), or otherwise a "
            "nickname/substring (uses search). Returns a compact list with nickname, "
            "fingerprint, country, AS, flags, and addresses."
        ),
    )
    async def _find_relay(query: str, limit: int = 10) -> dict[str, Any]:
        return await find_relay(client, query, limit=limit)

    @server.tool(
        name="get_relay_health",
        description=(
            "Snapshot the health of one relay: details (flags, country, AS, version, "
            "advertised bandwidth) plus the available uptime and bandwidth history "
            "periods. Requires a 40-hex relay fingerprint."
        ),
    )
    async def _get_relay_health(fingerprint: str) -> dict[str, Any]:
        return await get_relay_health(client, fingerprint)

    @server.tool(
        name="top_relays_by_bandwidth",
        description=(
            "List the top N running relays sorted by consensus weight. Optional "
            "filters: country (two-letter code), flag (e.g. Exit, Guard, Fast). "
            "Returns minimal fields suitable for ranking."
        ),
    )
    async def _top_relays_by_bandwidth(
        country: str | None = None,
        flag: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        return await top_relays_by_bandwidth(client, country=country, flag=flag, limit=limit)

    @server.tool(
        name="compare_relays",
        description=(
            "Compare several relays side-by-side by fetching their details in parallel. "
            "Pass a list of 40-hex fingerprints. Missing relays are reported with "
            "found=False rather than silently dropped."
        ),
    )
    async def _compare_relays(fingerprints: list[str]) -> dict[str, Any]:
        return await compare_relays(client, fingerprints)

    @server.tool(
        name="country_summary",
        description=(
            "Aggregate stats for running relays in one country: total count, "
            "total advertised bandwidth, total consensus weight, and a flag "
            "distribution histogram. Country is a two-letter ISO code."
        ),
    )
    async def _country_summary(country: str) -> dict[str, Any]:
        return await country_summary(client, country)

    @server.tool(
        name="aggregate_relays",
        description=(
            "Group all running Tor relays by country, AS, or flag. Returns "
            "buckets sorted by relay count (desc) with totals for advertised "
            "bandwidth and consensus weight. Use group_by='flag' to discover "
            "which roles dominate (Guard/Exit/Fast) — note a relay can belong "
            "to multiple flag buckets. Set top=N to keep only the largest N."
        ),
    )
    async def _aggregate_relays(
        group_by: Literal["country", "as", "flag"],
        running: bool = True,
        top: int | None = None,
    ) -> dict[str, Any]:
        return await aggregate_relays(client, group_by=group_by, running=running, top=top)

    # --- Low-level Onionoo passthrough --------------------------------------

    def _make_passthrough(method: str, description: str):
        @server.tool(name=f"onionoo_{method}", description=description)
        async def _passthrough(params: dict[str, Any] | None = None) -> dict[str, Any]:
            resp = await client.get(method=method, params=params or {}, if_modified_since=None)
            return {"status_code": resp.status_code, "body": resp.json_body}

        return _passthrough

    _make_passthrough(
        "summary",
        "Raw Onionoo /summary: lightweight relay/bridge list. Pass Onionoo query "
        "parameters as a dict (e.g. {'search': 'moria', 'limit': '1'}). See "
        "https://metrics.torproject.org/onionoo.html",
    )
    _make_passthrough(
        "details",
        "Raw Onionoo /details: full attributes (flags, AS, country, contact, …). "
        "Pass a params dict (e.g. {'lookup': '<40-hex fp>'}). Supports `fields=` "
        "to trim response. See https://metrics.torproject.org/onionoo.html",
    )
    _make_passthrough(
        "bandwidth",
        "Raw Onionoo /bandwidth: bandwidth time series for relays and bridges.",
    )
    _make_passthrough(
        "weights",
        "Raw Onionoo /weights: consensus weight / path-selection probability "
        "time series (relays only).",
    )
    _make_passthrough(
        "clients",
        "Raw Onionoo /clients: estimated daily client counts (bridges only).",
    )
    _make_passthrough(
        "uptime",
        "Raw Onionoo /uptime: fractional uptime time series.",
    )

    return server


async def _run_async() -> None:
    server = build_server()
    try:
        await server.run_stdio_async()
    finally:
        client: OnionooClient = server._onionoo_client  # type: ignore[attr-defined]
        await client.aclose()


def main() -> None:
    asyncio.run(_run_async())


if __name__ == "__main__":
    main()
