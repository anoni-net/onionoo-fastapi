from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.models.details import DetailsResponse
from app.routers.params import common_query_params, fields_query
from app.routers.proxy import get_onionoo_client, proxy_get_json
from app.services.onionoo_client import OnionooClient

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
        "Common params: `search`, `lookup` (40-hex fp), `country`, `as` (e.g. AS1234), "
        "`flag` (e.g. Exit, Guard, Fast), `running`, `version`, `limit`, `offset`, `fields`.\n\n"
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

    return await proxy_get_json(
        method="details",
        model=DetailsResponse,
        request=request,
        response=response,
        client=client,
        params=params,
        raw=raw,
    )
