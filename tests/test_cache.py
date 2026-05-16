"""Cache behavior tests for OnionooClient: TTL, LRU eviction, and key stability."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.onionoo_client import OnionooClient, _cache_key
from tests.conftest import make_summary_envelope, relay


def test_cache_key_is_stable_across_param_order() -> None:
    """Equivalent param dicts must hash to the same cache key regardless of order."""
    k1 = _cache_key("summary", {"limit": "5", "type": "relay"}, None)
    k2 = _cache_key("summary", {"type": "relay", "limit": "5"}, None)
    assert k1 == k2


def test_cache_key_differs_for_different_methods() -> None:
    k1 = _cache_key("summary", {"limit": "5"}, None)
    k2 = _cache_key("details", {"limit": "5"}, None)
    assert k1 != k2


def test_cache_key_differs_for_if_modified_since() -> None:
    base = {"limit": "5"}
    assert _cache_key("summary", base, None) != _cache_key(
        "summary", base, "Thu, 01 Jan 2026 00:00:00 GMT"
    )


def test_cache_ignores_none_and_empty_params() -> None:
    """None and empty-string params are cleaned out, so they don't affect the key."""
    k1 = _cache_key("summary", {"limit": "5", "search": None}, None)
    k2 = _cache_key("summary", {"limit": "5"}, None)
    k3 = _cache_key("summary", {"limit": "5", "search": ""}, None)
    assert k1 == k2 == k3


@pytest.mark.asyncio
async def test_second_call_hits_cache_not_upstream(respx_mock: respx.MockRouter) -> None:
    """Two identical calls in quick succession should only hit upstream once."""
    route = respx_mock.get("/summary").mock(
        return_value=httpx.Response(
            200,
            json=make_summary_envelope(relays=[relay("r1", "a" * 40)]),
        )
    )
    client = OnionooClient()
    try:
        r1 = await client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
        r2 = await client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
    finally:
        await client.aclose()

    assert route.call_count == 1
    assert r1.json_body == r2.json_body


@pytest.mark.asyncio
async def test_different_params_bypass_cache(respx_mock: respx.MockRouter) -> None:
    """Different params produce different cache keys → two upstream calls."""
    route = respx_mock.get("/summary").mock(
        return_value=httpx.Response(200, json=make_summary_envelope())
    )
    client = OnionooClient()
    try:
        await client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
        await client.get(method="summary", params={"limit": "2"}, if_modified_since=None)
    finally:
        await client.aclose()

    assert route.call_count == 2


@pytest.mark.asyncio
async def test_cache_lru_eviction_respects_maxsize(
    monkeypatch: pytest.MonkeyPatch, respx_mock: respx.MockRouter
) -> None:
    """When the cache fills past its maxsize, least-recently-used entries are evicted."""
    from app import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "cache_maxsize", 2)
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))
    client = OnionooClient()
    try:
        await client.get(method="summary", params={"limit": "1"}, if_modified_since=None)
        await client.get(method="summary", params={"limit": "2"}, if_modified_since=None)
        await client.get(method="summary", params={"limit": "3"}, if_modified_since=None)
        assert client.cache_size <= 2
    finally:
        await client.aclose()
