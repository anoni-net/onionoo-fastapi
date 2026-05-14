"""Concurrent identical requests should collapse to a single upstream call."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from app.services.onionoo_client import OnionooClient
from tests.conftest import make_summary_envelope


@pytest.mark.asyncio
async def test_concurrent_identical_requests_hit_upstream_once(
    respx_mock: respx.MockRouter,
) -> None:
    """While one in-flight request is outstanding, identical concurrent requests
    must wait on the same future, not fire fresh requests."""

    async def slow_response(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        await asyncio.sleep(0.05)
        return httpx.Response(200, json=make_summary_envelope())

    route = respx_mock.get("/summary").mock(side_effect=slow_response)

    client = OnionooClient()
    try:
        results = await asyncio.gather(
            *[
                client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
                for _ in range(8)
            ]
        )
    finally:
        await client.aclose()

    assert route.call_count == 1
    assert all(r.status_code == 200 for r in results)
    assert all(r.json_body == results[0].json_body for r in results)


@pytest.mark.asyncio
async def test_dedup_propagates_exceptions_to_all_waiters(
    respx_mock: respx.MockRouter,
) -> None:
    """If the owning request fails, all waiters see the same failure."""

    async def slow_500(request: httpx.Request) -> httpx.Response:  # noqa: ARG001
        await asyncio.sleep(0.05)
        return httpx.Response(500, text="upstream broke")

    respx_mock.get("/summary").mock(side_effect=slow_500)

    client = OnionooClient()
    try:
        tasks = [
            asyncio.create_task(
                client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
            )
            for _ in range(4)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await client.aclose()

    assert len(results) == 4
    assert all(isinstance(r, Exception) for r in results)
