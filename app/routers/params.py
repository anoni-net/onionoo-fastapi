from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import Query

from app.settings import settings


def _bool_str(v: bool) -> str:
    return "true" if v else "false"


def common_query_params(
    type: Annotated[
        str | None,
        Query(
            description="Return only relay ('relay') or only bridge ('bridge') documents.",
        ),
    ] = None,
    running: Annotated[
        bool | None,
        Query(
            description=(
                "Return only running relays/bridges (true) or only non-running (false). "
                'Pass a JSON boolean (true/false), not the string "true".'
            ),
        ),
    ] = None,
    search: Annotated[
        str | None,
        Query(
            description=(
                "Search term. Matches (parts of) nicknames, fingerprint prefixes, IP prefixes, or "
                "qualified terms like 'key:value'. Multiple terms (space-separated) are ANDed."
            ),
        ),
    ] = None,
    lookup: Annotated[
        str | None,
        Query(
            description=(
                "Lookup a specific relay/bridge by (hashed) fingerprint. Must be 40 hex chars. "
                "Case-insensitive."
            ),
        ),
    ] = None,
    country: Annotated[
        str | None,
        Query(description="Filter relays by 2-letter country code (case-insensitive)."),
    ] = None,
    as_: Annotated[
        str | None,
        Query(
            alias="as",
            description=(
                "Filter relays by autonomous system number (e.g. 'AS1234' or '1234'). "
                "Supports comma-separated lists."
            ),
        ),
    ] = None,
    as_name: Annotated[
        str | None,
        Query(description="Filter relays by (part of) autonomous system name (case-insensitive)."),
    ] = None,
    flag: Annotated[
        str | None,
        Query(description="Filter relays by a directory authority flag (case-insensitive)."),
    ] = None,
    contact: Annotated[
        str | None,
        Query(description="Filter relays by (part of) contact line (case-insensitive)."),
    ] = None,
    family: Annotated[
        str | None,
        Query(
            description=(
                "Filter relays by mutual family relationship for the given relay fingerprint "
                "(40 hex chars, NOT hashed)."
            ),
        ),
    ] = None,
    host_name: Annotated[
        str | None,
        Query(
            description=(
                "Filter relays by reverse DNS host name suffix (case-insensitive). "
                "For subdomains, prefix with '.' (e.g. '.example.org')."
            ),
        ),
    ] = None,
    first_seen_days: Annotated[
        str | None,
        Query(
            description=(
                "Filter by range of days ago the relay/bridge was first seen. "
                "Forms: 'x-y', 'x', 'x-', or '-y'."
            ),
        ),
    ] = None,
    last_seen_days: Annotated[
        str | None,
        Query(
            description=(
                "Filter by range of days ago the relay/bridge was last seen. "
                "Forms: 'x-y', 'x', 'x-', or '-y'."
            ),
        ),
    ] = None,
    first_seen_since: Annotated[
        date | None,
        Query(description="Filter by first seen after date (YYYY-MM-DD)."),
    ] = None,
    last_seen_since: Annotated[
        date | None,
        Query(description="Filter by last seen after date (YYYY-MM-DD)."),
    ] = None,
    version: Annotated[
        str | None,
        Query(
            description=(
                "Filter by Tor version without leading 'Tor'. Supports lists and ranges "
                "('x,y' or 'x..y' or mixed)."
            ),
        ),
    ] = None,
    os: Annotated[
        str | None,
        Query(description="Filter by operating system prefix (case-insensitive)."),
    ] = None,
    recommended_version: Annotated[
        bool | None,
        Query(description="Filter by whether the Tor version is recommended by authorities."),
    ] = None,
    order: Annotated[
        str | None,
        Query(
            description=(
                "Order results by comma-separated fields. Supported fields include "
                "'consensus_weight' and 'first_seen'. Prefix with '-' for descending."
            ),
        ),
    ] = None,
    offset: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Skip the given number of relays/bridges (relays first). Onionoo's default "
                "ordering is not stable across requests, so paging with offset alone can skip "
                "entries. Pass an explicit `order`, or fetch everything in one request with a "
                "high `limit`, when you need the complete set."
            ),
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(
            ge=0,
            le=settings.max_limit,
            description=(
                f"Limit number of relays/bridges returned (relays first). "
                f"Default: {settings.default_limit}, max: {settings.max_limit}."
            ),
        ),
    ] = settings.default_limit,
) -> dict[str, Any]:
    """
    Common Onionoo query parameters (documented in Onionoo spec).

    We convert some types (bool/date) to the string representation Onionoo expects.
    """

    params: dict[str, Any] = {}

    if type is not None:
        params["type"] = type
    if running is not None:
        params["running"] = _bool_str(running)
    if search is not None:
        params["search"] = search
    if lookup is not None:
        params["lookup"] = lookup
    if country is not None:
        params["country"] = country
    if as_ is not None:
        params["as"] = as_
    if as_name is not None:
        params["as_name"] = as_name
    if flag is not None:
        params["flag"] = flag
    if contact is not None:
        params["contact"] = contact
    if family is not None:
        params["family"] = family
    if host_name is not None:
        params["host_name"] = host_name
    if first_seen_days is not None:
        params["first_seen_days"] = first_seen_days
    if last_seen_days is not None:
        params["last_seen_days"] = last_seen_days
    if first_seen_since is not None:
        params["first_seen_since"] = first_seen_since.isoformat()
    if last_seen_since is not None:
        params["last_seen_since"] = last_seen_since.isoformat()
    if version is not None:
        params["version"] = version
    if os is not None:
        params["os"] = os
    if recommended_version is not None:
        params["recommended_version"] = _bool_str(recommended_version)
    if order is not None:
        params["order"] = order
    if offset is not None:
        params["offset"] = str(offset)
    params["limit"] = str(limit)
    return params


def fields_query(
    fields: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated list of fields to include in the response. Useful "
                "for trimming large payloads (e.g. `fields=nickname,fingerprint`). "
                "On `/summary` and `/details` this filters top-level relay/bridge "
                "attributes. On history endpoints (bandwidth/weights/clients/uptime) "
                "Onionoo applies it where supported and otherwise ignores it."
            ),
        ),
    ] = None,
) -> str | None:
    return fields
