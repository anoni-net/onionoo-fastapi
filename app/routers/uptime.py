from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.models.uptime import UptimeResponse
from app.routers.params import common_query_params, fields_query
from app.routers.proxy import get_onionoo_client, proxy_get_json
from app.services.onionoo_client import OnionooClient

router = APIRouter()


@router.get(
    "/uptime",
    response_model=UptimeResponse,
    summary="Get uptime fraction time series for relays/bridges",
    operation_id="get_uptime",
    description=(
        "Returns fractional uptime (0.0 to 1.0) over time for matching relays/bridges, "
        "plus optional per-flag uptime fractions for relays. Useful for assessing "
        "reliability or detecting recent outages.\n\n"
        "Common params: `lookup`, `search`, `country`, `flag`, `limit`, `offset`.\n\n"
        "Upstream: https://metrics.torproject.org/onionoo.html#uptime"
    ),
)
async def get_uptime(
    request: Request,
    response: Response,
    params: Annotated[dict[str, Any], Depends(common_query_params)],
    client: Annotated[OnionooClient, Depends(get_onionoo_client)],
    fields: Annotated[str | None, Depends(fields_query)] = None,
    raw: Annotated[
        bool,
        Query(description="Return raw upstream JSON without Pydantic re-validation."),
    ] = False,
) -> UptimeResponse | Response:
    if fields is not None:
        params["fields"] = fields
    return await proxy_get_json(
        method="uptime",
        model=UptimeResponse,
        request=request,
        response=response,
        client=client,
        params=params,
        raw=raw,
    )
