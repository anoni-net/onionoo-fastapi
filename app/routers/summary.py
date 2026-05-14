from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.models.summary import SummaryResponse
from app.routers.params import common_query_params, fields_query
from app.routers.proxy import get_onionoo_client, proxy_get_json
from app.services.onionoo_client import OnionooClient

router = APIRouter()


@router.get(
    "/summary",
    response_model=SummaryResponse,
    summary="List Tor relays and bridges (minimal fields)",
    operation_id="get_summary",
    description=(
        "Use this to get a lightweight list of Tor relays and bridges. Returns only "
        "nickname, fingerprint, addresses (relays) or hashed_fingerprint (bridges), and "
        "running status. Best when you need to search/enumerate relays without the cost "
        "of full details.\n\n"
        "Common params: `search` (matches nickname/fingerprint/IP), `lookup` (40-hex "
        "fingerprint), `country`, `running`, `type` (relay|bridge), `limit`, `offset`.\n\n"
        "For full attributes (flags, AS, country, contact, etc.) use get_details instead.\n\n"
        "Upstream: https://metrics.torproject.org/onionoo.html#summary"
    ),
)
async def get_summary(
    request: Request,
    response: Response,
    params: Annotated[dict[str, Any], Depends(common_query_params)],
    client: Annotated[OnionooClient, Depends(get_onionoo_client)],
    fields: Annotated[str | None, Depends(fields_query)] = None,
    raw: Annotated[
        bool,
        Query(description="Return raw upstream JSON without Pydantic re-validation."),
    ] = False,
) -> SummaryResponse | Response:
    if fields is not None:
        params["fields"] = fields
    return await proxy_get_json(
        method="summary",
        model=SummaryResponse,
        request=request,
        response=response,
        client=client,
        params=params,
        raw=raw,
    )
