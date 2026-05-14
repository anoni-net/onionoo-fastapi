from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.models.clients import ClientsResponse
from app.routers.params import common_query_params, fields_query
from app.routers.proxy import get_onionoo_client, proxy_get_json
from app.services.onionoo_client import OnionooClient

router = APIRouter()


@router.get(
    "/clients",
    response_model=ClientsResponse,
    summary="Get estimated daily client counts for bridges",
    operation_id="get_clients",
    description=(
        "Returns estimated daily client connection counts per bridge, including a "
        "country/transport breakdown. Bridges only (relays do not publish this).\n\n"
        "Use this for bridge usage analysis. Common params: `lookup` (hashed fingerprint), "
        "`search`, `country`, `limit`.\n\n"
        "Upstream: https://metrics.torproject.org/onionoo.html#clients"
    ),
)
async def get_clients(
    request: Request,
    response: Response,
    params: Annotated[dict[str, Any], Depends(common_query_params)],
    client: Annotated[OnionooClient, Depends(get_onionoo_client)],
    fields: Annotated[str | None, Depends(fields_query)] = None,
    raw: Annotated[
        bool,
        Query(description="Return raw upstream JSON without Pydantic re-validation."),
    ] = False,
) -> ClientsResponse | Response:
    if fields is not None:
        params["fields"] = fields
    return await proxy_get_json(
        method="clients",
        model=ClientsResponse,
        request=request,
        response=response,
        client=client,
        params=params,
        raw=raw,
    )
