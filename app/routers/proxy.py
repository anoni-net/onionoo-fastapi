from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel

from app.services.onionoo_client import OnionooClient


def get_onionoo_client(request: Request) -> OnionooClient:
    return request.app.state.onionoo


async def proxy_get_json[ModelT: BaseModel](
    *,
    method: str,
    model: type[ModelT],
    request: Request,
    response: Response,
    client: OnionooClient,
    params: dict[str, Any],
    raw: bool = False,
) -> ModelT | Response:
    """Fetch from Onionoo and return either a parsed model or a passthrough Response.

    When `raw=True`, the upstream JSON is serialized directly without going through
    Pydantic validation. This is materially cheaper for large `/details` payloads
    but loses the semantic field renaming applied by `/summary`.

    A `fields=` projection forces the same raw passthrough: Onionoo returns only the
    requested keys, so the trimmed relay/bridge objects can no longer satisfy the
    full response model (which marks nickname/fingerprint/… as required). Validating
    them would raise and surface as a 500. Passing the projection through verbatim is
    both correct (the caller asked for exactly those fields) and cheap, matching what
    `app.services.aggregate` already does internally.
    """
    if params.get("fields"):
        raw = True
    if_modified_since = request.headers.get("if-modified-since")
    upstream = await client.get(method=method, params=params, if_modified_since=if_modified_since)

    last_modified = upstream.headers.get("last-modified")

    if upstream.status_code == 304:
        headers: dict[str, str] = {}
        if last_modified:
            headers["Last-Modified"] = last_modified
        return Response(status_code=304, headers=headers)

    if last_modified:
        response.headers["Last-Modified"] = last_modified

    if upstream.json_body is None:
        # This should not happen for Onionoo, but we keep a defensive error.
        raise HTTPException(status_code=502, detail="Upstream did not return JSON")

    if raw:
        payload = json.dumps(upstream.json_body, separators=(",", ":")).encode()
        headers = dict(response.headers)
        return Response(content=payload, media_type="application/json", headers=headers)

    # Inject the proxy meta block before validation so clients see cache age
    # and the upstream Last-Modified marker without an extra round-trip.
    enriched = dict(upstream.json_body)
    enriched["_meta"] = {
        "cache_age_seconds": round(upstream.cache_age_seconds, 3),
        "upstream_last_modified": last_modified,
    }
    return model.model_validate(enriched)
