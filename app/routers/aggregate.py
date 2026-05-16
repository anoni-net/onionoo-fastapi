"""Server-side aggregate endpoints for agent-friendly group-by queries.

Each route fetches a single Onionoo /details payload (with a trimmed `fields`
list) and aggregates client-side. Cached responses come for free via
`OnionooClient`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.routers.proxy import get_onionoo_client
from app.services.aggregate import aggregate_details
from app.services.onionoo_client import OnionooClient

router = APIRouter()


@router.get(
    "/aggregate/countries",
    operation_id="aggregate_countries",
    summary="Count relays grouped by country (with bandwidth and consensus weight totals)",
    description=(
        "Returns running relays bucketed by two-letter country code, sorted by "
        "relay count (descending). Each bucket carries relay count, total "
        "advertised bandwidth (bytes/sec), and total consensus weight. Use this "
        "for country-level concentration analysis."
    ),
)
async def aggregate_countries(
    request: Request,  # noqa: ARG001
    client: Annotated[OnionooClient, Depends(get_onionoo_client)],
    running: Annotated[
        bool,
        Query(
            description="If true (default), only count relays the directory authorities see as running."
        ),
    ] = True,
    top: Annotated[
        int | None,
        Query(ge=1, le=500, description="Optional: return only the top-N buckets by relay count."),
    ] = None,
) -> dict[str, Any]:
    return await aggregate_details(client, group_by="country", running=running, limit=top)


@router.get(
    "/aggregate/as",
    operation_id="aggregate_as",
    summary="Count relays grouped by autonomous system",
    description=(
        "Returns running relays bucketed by AS number (e.g. 'AS3'), sorted by "
        "relay count. Useful for spotting infrastructure concentration."
    ),
)
async def aggregate_as(
    request: Request,  # noqa: ARG001
    client: Annotated[OnionooClient, Depends(get_onionoo_client)],
    running: Annotated[bool, Query(description="Filter to running relays.")] = True,
    top: Annotated[
        int | None,
        Query(ge=1, le=500, description="Optional: return only the top-N buckets."),
    ] = None,
) -> dict[str, Any]:
    return await aggregate_details(client, group_by="as", running=running, limit=top)


@router.get(
    "/aggregate/flags",
    operation_id="aggregate_flags",
    summary="Count relays grouped by directory-authority flag",
    description=(
        "Returns running relays bucketed by each flag they carry (Guard, Exit, "
        "Fast, Stable, …). Note: a single relay can fall into multiple buckets, "
        "so bucket counts will not sum to the total relay count."
    ),
)
async def aggregate_flags(
    request: Request,  # noqa: ARG001
    client: Annotated[OnionooClient, Depends(get_onionoo_client)],
    running: Annotated[bool, Query(description="Filter to running relays.")] = True,
) -> dict[str, Any]:
    return await aggregate_details(client, group_by="flag", running=running)
