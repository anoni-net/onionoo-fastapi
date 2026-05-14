from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.models.weights import WeightsResponse
from app.routers.params import common_query_params, fields_query
from app.routers.proxy import get_onionoo_client, proxy_get_json
from app.services.onionoo_client import OnionooClient

router = APIRouter()


@router.get(
    "/weights",
    response_model=WeightsResponse,
    summary="Get relay consensus weight / path-selection probability over time",
    operation_id="get_weights",
    description=(
        "Returns path-selection probability time series for relays: how likely the relay "
        "is to be chosen as guard/middle/exit by Tor clients. Relays only (bridges have "
        "no weights).\n\n"
        "Use this to evaluate a relay's importance to the network or to detect anomalous "
        "weight changes. Common params: `lookup`, `search`, `flag`, `country`, `limit`.\n\n"
        "Upstream: https://metrics.torproject.org/onionoo.html#weights"
    ),
)
async def get_weights(
    request: Request,
    response: Response,
    params: Annotated[dict[str, Any], Depends(common_query_params)],
    client: Annotated[OnionooClient, Depends(get_onionoo_client)],
    fields: Annotated[str | None, Depends(fields_query)] = None,
    raw: Annotated[
        bool,
        Query(description="Return raw upstream JSON without Pydantic re-validation."),
    ] = False,
) -> WeightsResponse | Response:
    if fields is not None:
        params["fields"] = fields
    return await proxy_get_json(
        method="weights",
        model=WeightsResponse,
        request=request,
        response=response,
        client=client,
        params=params,
        raw=raw,
    )
