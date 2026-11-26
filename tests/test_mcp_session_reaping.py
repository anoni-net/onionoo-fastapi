"""Stateful /mcp sessions must expire once idle (CVE-2026-59951).

fastapi-mcp runs the Streamable HTTP transport in stateful mode and never
passes `session_idle_timeout`, so the mcp SDK default is what protects the
hosted endpoint. Before mcp 1.30.0 that default was None (no timeout), so
every `initialize` left a session in memory for the life of the process. These
tests pin both halves: the manager fastapi-mcp builds carries a finite
default, and an idle session really is reaped and its id refused afterwards.
"""

from __future__ import annotations

import math
import time
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient
from fastapi_mcp.transport import http as fastapi_mcp_http
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from app.main import create_app
from tests.test_mcp import MCP_ACCEPT, _mcp_initialize


def _record_managers(
    monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> list[StreamableHTTPSessionManager]:
    """Wrap the manager class fastapi-mcp instantiates, keeping every instance."""
    built: list[StreamableHTTPSessionManager] = []

    def factory(*args: Any, **kwargs: Any) -> StreamableHTTPSessionManager:
        manager = StreamableHTTPSessionManager(*args, **{**kwargs, **overrides})
        built.append(manager)
        return manager

    monkeypatch.setattr(fastapi_mcp_http, "StreamableHTTPSessionManager", factory)
    return built


def _ping(client: TestClient, session_id: str) -> int:
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 9, "method": "ping", "params": {}},
        headers={"Accept": MCP_ACCEPT, "mcp-session-id": session_id},
    )
    return r.status_code


def test_hosted_mcp_session_manager_has_finite_idle_timeout(
    respx_mock: respx.MockRouter,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _record_managers(monkeypatch)

    with TestClient(create_app()) as client:
        _mcp_initialize(client)

    assert len(built) == 1
    timeout = built[0].session_idle_timeout
    assert timeout is not None
    assert math.isfinite(timeout)
    assert timeout > 0


def test_idle_mcp_session_is_reaped(
    respx_mock: respx.MockRouter,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_managers(monkeypatch, session_idle_timeout=0.3)

    with TestClient(create_app()) as client:
        session_id = _mcp_initialize(client)
        assert _ping(client, session_id) == 200

        # Each ping resets the idle clock, so wait well past the timeout
        # between attempts instead of polling tightly.
        status = 200
        deadline = time.monotonic() + 5
        while status == 200 and time.monotonic() < deadline:
            time.sleep(0.8)
            status = _ping(client, session_id)

        assert status == 404
