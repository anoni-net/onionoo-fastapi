from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.models.bandwidth import BandwidthResponse
from app.routers.params import common_query_params, fields_query
from app.routers.proxy import get_onionoo_client, proxy_get_json
from app.services.onionoo_client import OnionooClient

router = APIRouter()


@router.get(
    "/bandwidth",
    response_model=BandwidthResponse,
    summary="Get bandwidth history time series for relays/bridges",
    operation_id="get_bandwidth",
    description=(
        "Returns read/write bandwidth time series for matching relays/bridges across "
        "multiple periods (1 month, 6 months, 1 year, 5 years). Each series has a fixed "
        "interval and counts in bytes per second.\n\n"
        "Use this for charts, traffic analysis, or to compute average throughput. Pair "
        "with `lookup=<fingerprint>` to fetch one relay's history.\n\n"
        "Common params: `lookup`, `search`, `country`, `flag`, `limit`. Returns no "
        "individual relay attributes — combine with get_details when needed.\n\n"
        "Upstream: https://metrics.torproject.org/onionoo.html#bandwidth"
    ),
)
async def get_bandwidth(
    request: Request,
    response: Response,
    params: Annotated[dict[str, Any], Depends(common_query_params)],
    client: Annotated[OnionooClient, Depends(get_onionoo_client)],
    fields: Annotated[str | None, Depends(fields_query)] = None,
    raw: Annotated[
        bool,
        Query(description="Return raw upstream JSON without Pydantic re-validation."),
    ] = False,
) -> BandwidthResponse | Response:
    if fields is not None:
        params["fields"] = fields
    return await proxy_get_json(
        method="bandwidth",
        model=BandwidthResponse,
        request=request,
        response=response,
        client=client,
        params=params,
        raw=raw,
    )
