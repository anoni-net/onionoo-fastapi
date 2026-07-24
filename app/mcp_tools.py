"""High-level, task-oriented MCP tools.

Each function composes one or more Onionoo endpoints into an LLM-friendly result.
These are *not* thin REST wrappers — they pick the right endpoint, fan out
requests in parallel, and aggregate. Use them when an agent should accomplish
a goal ("how healthy is this relay?") in a single tool call.

All tools operate against an injected `OnionooClient` so they can be tested
without network access via respx.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal

from app.services.aggregate import aggregate_details
from app.services.onionoo_client import OnionooClient, UpstreamError
from app.settings import settings

FINGERPRINT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
AS_RE = re.compile(r"^AS\d+$", re.IGNORECASE)


def _looks_like_fingerprint(query: str) -> bool:
    return bool(FINGERPRINT_RE.match(query.strip()))


def _looks_like_as(query: str) -> bool:
    return bool(AS_RE.match(query.strip()))


async def find_relay(client: OnionooClient, query: str, *, limit: int = 10) -> dict[str, Any]:
    """Find relays/bridges by free-form query.

    Auto-detects whether `query` is a 40-hex fingerprint (uses lookup), an IPv4/IPv6
    address (uses search), an AS number (uses as filter), or otherwise a nickname/
    substring (uses search). Returns a compact list of matches.
    """
    q = query.strip()
    params: dict[str, Any] = {"limit": str(limit)}

    if _looks_like_fingerprint(q):
        params["lookup"] = q.upper()
    elif _looks_like_as(q):
        params["as"] = q.upper()
    else:
        params["search"] = q

    resp = await client.get(method="details", params=params, if_modified_since=None)
    body = resp.json_body or {}

    def _shape(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "nickname": item.get("nickname"),
            "fingerprint": item.get("fingerprint") or item.get("hashed_fingerprint"),
            "running": item.get("running"),
            "country": item.get("country"),
            "as": item.get("as"),
            "flags": item.get("flags"),
            "or_addresses": item.get("or_addresses"),
        }

    return {
        "query": q,
        "matched_via": "lookup" if "lookup" in params else "as" if "as" in params else "search",
        "relays": [_shape(r) for r in body.get("relays", [])],
        "bridges": [_shape(b) for b in body.get("bridges", [])],
    }


async def get_relay_health(client: OnionooClient, fingerprint: str) -> dict[str, Any]:
    """Composite health snapshot for a single relay: details + uptime + bandwidth.

    Fires three Onionoo queries in parallel and condenses the response into a
    short, LLM-readable dict. Raises UpstreamError if any sub-fetch fails.
    """
    fp = fingerprint.strip().upper()
    if not _looks_like_fingerprint(fp):
        raise ValueError(f"fingerprint must be 40 hex chars, got {fingerprint!r}")

    params = {"lookup": fp, "limit": "1"}

    details_resp, uptime_resp, bandwidth_resp = await asyncio.gather(
        client.get(method="details", params=params, if_modified_since=None),
        client.get(method="uptime", params=params, if_modified_since=None),
        client.get(method="bandwidth", params=params, if_modified_since=None),
    )

    relays = (details_resp.json_body or {}).get("relays", [])
    if not relays:
        return {"fingerprint": fp, "found": False}

    relay = relays[0]
    uptime = ((uptime_resp.json_body or {}).get("relays") or [{}])[0]
    bw = ((bandwidth_resp.json_body or {}).get("relays") or [{}])[0]

    return {
        "fingerprint": fp,
        "found": True,
        "nickname": relay.get("nickname"),
        "running": relay.get("running"),
        "country": relay.get("country"),
        "as": relay.get("as"),
        "as_name": relay.get("as_name"),
        "flags": relay.get("flags"),
        "first_seen": relay.get("first_seen"),
        "last_seen": relay.get("last_seen"),
        "advertised_bandwidth": relay.get("advertised_bandwidth"),
        "consensus_weight": relay.get("consensus_weight"),
        "version": relay.get("version"),
        "recommended_version": relay.get("recommended_version"),
        "uptime_periods": sorted((uptime.get("uptime") or {}).keys()),
        "bandwidth_periods": {
            "read": sorted((bw.get("read_history") or {}).keys()),
            "write": sorted((bw.get("write_history") or {}).keys()),
        },
    }


async def top_relays_by_bandwidth(
    client: OnionooClient,
    *,
    country: str | None = None,
    flag: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Return the top N running relays by consensus weight, optionally filtered.

    Onionoo's `order=-consensus_weight` puts the highest-weight relays first.
    """
    params: dict[str, Any] = {
        "running": "true",
        "order": "-consensus_weight",
        "limit": str(limit),
        "fields": ",".join(
            [
                "nickname",
                "fingerprint",
                "country",
                "as",
                "as_name",
                "flags",
                "advertised_bandwidth",
                "consensus_weight",
                "consensus_weight_fraction",
            ]
        ),
    }
    if country:
        params["country"] = country
    if flag:
        params["flag"] = flag

    resp = await client.get(method="details", params=params, if_modified_since=None)
    relays = (resp.json_body or {}).get("relays", [])
    return {
        "country": country,
        "flag": flag,
        "count": len(relays),
        "relays": relays,
    }


async def compare_relays(client: OnionooClient, fingerprints: list[str]) -> dict[str, Any]:
    """Fetch details for several fingerprints in parallel and return a comparison.

    Each fingerprint becomes one Onionoo lookup; missing relays are reported
    rather than dropped.
    """
    if not fingerprints:
        return {"relays": []}

    normalized = [fp.strip().upper() for fp in fingerprints]
    for fp in normalized:
        if not _looks_like_fingerprint(fp):
            raise ValueError(f"invalid fingerprint: {fp!r}")

    async def _one(fp: str) -> dict[str, Any]:
        try:
            r = await client.get(
                method="details",
                params={"lookup": fp, "limit": "1"},
                if_modified_since=None,
            )
        except UpstreamError as exc:
            return {"fingerprint": fp, "found": False, "error": str(exc)}
        relays = (r.json_body or {}).get("relays", [])
        if not relays:
            return {"fingerprint": fp, "found": False}
        relay = relays[0]
        return {
            "fingerprint": fp,
            "found": True,
            "nickname": relay.get("nickname"),
            "running": relay.get("running"),
            "country": relay.get("country"),
            "as": relay.get("as"),
            "flags": relay.get("flags"),
            "advertised_bandwidth": relay.get("advertised_bandwidth"),
            "consensus_weight": relay.get("consensus_weight"),
            "version": relay.get("version"),
        }

    rows = await asyncio.gather(*[_one(fp) for fp in normalized])
    return {"relays": rows}


async def country_summary(client: OnionooClient, country: str) -> dict[str, Any]:
    """Aggregate Tor relays for one country: total count, flag distribution, weight.

    Pulls a single Onionoo /details query with country filter (up to MAX_LIMIT
    relays) and computes counts client-side.
    """
    country_code = country.strip().lower()
    params = {
        "country": country_code,
        "running": "true",
        # A single country can hold thousands of relays (e.g. US ~3000+); a hardcoded
        # cap of 200 silently under-counted large countries. Fetch up to MAX_LIMIT so
        # the aggregate reflects the whole country in one pass (fields= keeps it cheap).
        "limit": str(settings.max_limit),
        "fields": "fingerprint,nickname,flags,advertised_bandwidth,consensus_weight",
    }
    resp = await client.get(method="details", params=params, if_modified_since=None)
    body = resp.json_body or {}
    relays = body.get("relays", [])

    total_advertised_bw = 0
    total_weight = 0
    flag_counts: dict[str, int] = {}
    for relay in relays:
        total_advertised_bw += int(relay.get("advertised_bandwidth") or 0)
        total_weight += int(relay.get("consensus_weight") or 0)
        for f in relay.get("flags") or []:
            flag_counts[f] = flag_counts.get(f, 0) + 1

    return {
        "country": country_code,
        "running_relay_count": len(relays),
        "truncated": body.get("relays_truncated"),
        "total_advertised_bandwidth_bps": total_advertised_bw,
        "total_consensus_weight": total_weight,
        "flag_counts": dict(sorted(flag_counts.items(), key=lambda kv: kv[1], reverse=True)),
    }


_AGGREGATE_GROUP_BY_ALIASES = {
    "countries": "country",
    "country": "country",
    "as": "as",
    "flags": "flag",
    "flag": "flag",
}


async def aggregate_relays(
    client: OnionooClient,
    *,
    group_by: Literal["countries", "as", "flags"],
    running: bool = True,
    top: int | None = None,
) -> dict[str, Any]:
    """Group all running Tor relays by country / AS / flag.

    Thin wrapper over `app.services.aggregate.aggregate_details`. The public
    label set (`countries`/`as`/`flags`) matches the REST endpoint paths
    (`/v1/aggregate/{countries,as,flags}`); singular forms remain accepted for
    backwards compatibility with the original tool signature.
    """
    internal = _AGGREGATE_GROUP_BY_ALIASES.get(group_by)
    if internal is None:
        raise ValueError(
            f"group_by must be one of {sorted(_AGGREGATE_GROUP_BY_ALIASES)}, got {group_by!r}"
        )
    return await aggregate_details(client, group_by=internal, running=running, limit=top)
