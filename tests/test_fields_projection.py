"""`fields=` is forwarded to upstream on every endpoint that accepts it."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from tests.conftest import make_summary_envelope


@pytest.mark.parametrize(
    "path",
    [
        "/v1/summary",
        "/v1/details",
        "/v1/bandwidth",
        "/v1/weights",
        "/v1/clients",
        "/v1/uptime",
    ],
)
def test_fields_param_is_forwarded(
    path: str, app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    method = path.rsplit("/", 1)[-1]
    upstream_path = f"/{method}"
    route = respx_mock.get(upstream_path).mock(
        return_value=httpx.Response(200, json=make_summary_envelope())
    )

    r = app_client.get(path, params={"limit": 1, "fields": "fingerprint,nickname"})
    assert r.status_code == 200, r.text
    assert route.calls.last.request.url.params["fields"] == "fingerprint,nickname"
