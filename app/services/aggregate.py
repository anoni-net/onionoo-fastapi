"""Server-side aggregation over Onionoo /details responses.

The agent-facing REST routes and the MCP tool both call into here so the
bucketing logic stays in one place.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from app.services.onionoo_client import OnionooClient

GroupBy = Literal["country", "as", "flag"]

_AGGREGATE_FIELDS = ",".join(
    [
        "fingerprint",
        "country",
        "as",
        "flags",
        "advertised_bandwidth",
        "consensus_weight",
    ]
)


def _iter_keys(relay: dict[str, Any], group_by: GroupBy) -> Iterable[str]:
    """Yield bucket keys for one relay. A relay can map to multiple flag buckets."""
    if group_by == "flag":
        yield from (relay.get("flags") or [])
        return
    raw = relay.get(group_by)
    if raw is None or raw == "":
        return
    yield str(raw)


async def aggregate_details(
    client: OnionooClient,
    *,
    group_by: GroupBy,
    running: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """Fetch running relays from Onionoo and bucket them by `group_by`.

    Returns:
        {
          "group_by": ...,
          "running": bool,
          "buckets": [
              {"key": "us", "relay_count": 123,
               "total_advertised_bandwidth_bps": ..., "total_consensus_weight": ...},
              ...
          ],
          "relays_truncated": int | None,
        }

    The list is sorted by relay_count desc, then key asc. If `limit` is set,
    only the top-N buckets are returned.
    """
    params: dict[str, Any] = {
        "fields": _AGGREGATE_FIELDS,
        "limit": "10000",
    }
    if running:
        params["running"] = "true"

    resp = await client.get(method="details", params=params, if_modified_since=None)
    body = resp.json_body or {}
    relays = body.get("relays", [])

    buckets: dict[str, dict[str, int]] = {}
    for relay in relays:
        bw = int(relay.get("advertised_bandwidth") or 0)
        weight = int(relay.get("consensus_weight") or 0)
        for key in _iter_keys(relay, group_by):
            slot = buckets.setdefault(
                key,
                {
                    "relay_count": 0,
                    "total_advertised_bandwidth_bps": 0,
                    "total_consensus_weight": 0,
                },
            )
            slot["relay_count"] += 1
            slot["total_advertised_bandwidth_bps"] += bw
            slot["total_consensus_weight"] += weight

    ordered = sorted(
        ({"key": k, **v} for k, v in buckets.items()),
        key=lambda b: (-b["relay_count"], b["key"]),
    )
    if limit is not None and limit > 0:
        ordered = ordered[:limit]

    return {
        "group_by": group_by,
        "running": running,
        "buckets": ordered,
        "relays_truncated": body.get("relays_truncated"),
    }
