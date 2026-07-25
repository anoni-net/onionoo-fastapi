from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.models.details import DetailsResponse
from app.routers.params import common_query_params, fields_query
from app.routers.proxy import get_onionoo_client, proxy_get_json
from app.services.onionoo_client import OnionooClient
from app.settings import settings

router = APIRouter()


@router.get(
    "/details",
    response_model=DetailsResponse,
    summary="Get full attributes for Tor relays and bridges",
    operation_id="get_details",
    description=(
        "Returns the full Onionoo `/details` document for each matching relay/bridge: "
        "nickname, fingerprint, IPs, country, AS, flags, contact, exit policy, advertised "
        "bandwidth, version, platform, first/last seen, and many more fields.\n\n"
        "Use this when the user wants to inspect a specific relay, or filter relays by "
        "country/AS/flags/version. To save tokens, pass `fields=...` (comma-separated) to "
        "limit which top-level fields are returned.\n\n"
        "To retrieve the whole network in one shot, set a high `limit` (e.g. 20000) plus "
        "`fields=...` and read the single response. The projection is required at that "
        f"scale: without `fields` the ceiling is {settings.max_limit_untrimmed}, because an "
        "untrimmed full-corpus document is ~90 MB. Prefer this over walking `offset`: "
        "Onionoo's default ordering is not stable across requests, so offset pagination "
        "can skip relays. If you must paginate, pass an explicit `order` (e.g. "
        "`-consensus_weight`) to keep pages consistent.\n\n"
        "A `fields=` projection is returned as raw upstream JSON (no `_meta` block), "
        "since the trimmed objects no longer satisfy the full response model.\n\n"
        "Common params: `search`, `lookup` (40-hex fp), `country`, `as` (e.g. AS1234), "
        "`flag` (e.g. Exit, Guard, Fast), `running` (JSON boolean true/false, not the "
        'string "true"), `version`, `limit`, `offset`, `fields`.\n\n'
        "Upstream: https://metrics.torproject.org/onionoo.html#details"
    ),
)
async def get_details(
    request: Request,
    response: Response,
    params: Annotated[dict[str, Any], Depends(common_query_params)],
    client: Annotated[OnionooClient, Depends(get_onionoo_client)],
    fields: Annotated[str | None, Depends(fields_query)] = None,
    raw: Annotated[
        bool,
        Query(description="Return raw upstream JSON without Pydantic re-validation."),
    ] = False,
) -> DetailsResponse | Response:
    if fields is not None:
        params["fields"] = fields
    elif int(params["limit"]) > settings.max_limit_untrimmed:
        # `max_limit` is high enough to pull the whole corpus in one call, which is only
        # affordable alongside a projection: untrimmed `/details` at that scale is ~90 MB
        # of JSON per request, and the client caches the parsed body. Fail loudly with an
        # actionable message rather than letting an unbounded request exhaust memory.
        raise HTTPException(
            status_code=422,
            detail=(
                f"limit above {settings.max_limit_untrimmed} requires a `fields=` projection "
                f"on /details (an untrimmed full-corpus document is ~90 MB). Pass the columns "
                f"you need, e.g. fields=fingerprint,nickname,flags."
            ),
        )

    return await proxy_get_json(
        method="details",
        model=DetailsResponse,
        request=request,
        response=response,
        client=client,
        params=params,
        # A projection returns only the requested keys, so the trimmed relay/bridge objects
        # can no longer satisfy `DetailsResponse` (nickname/fingerprint/… are required) and
        # validating them would surface as a 500. Pass them through verbatim instead, which
        # is what `app.services.aggregate` has always done internally.
        raw=raw or fields is not None,
    )
