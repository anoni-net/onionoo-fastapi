"""`onionoo_mcp_tool_calls_total` counts /mcp tool calls by tool name and outcome only."""

from __future__ import annotations

import httpx
import respx
from fastapi.testclient import TestClient

from app.observability import MCP_TOOL_CALLS
from tests.conftest import make_summary_envelope, relay
from tests.test_mcp import _mcp_call, _mcp_initialize


def _count(tool: str, outcome: str) -> float:
    return MCP_TOOL_CALLS.labels(tool=tool, outcome=outcome)._value.get()  # type: ignore[attr-defined]


def test_successful_tool_call_is_counted_as_ok(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(
        return_value=httpx.Response(
            200, json=make_summary_envelope(relays=[relay(n="moria1", f="A" * 40)])
        )
    )
    ok_before = _count("get_summary", "ok")
    error_before = _count("get_summary", "error")

    session = _mcp_initialize(app_client)
    resp = _mcp_call(
        app_client,
        session,
        "tools/call",
        {"name": "get_summary", "arguments": {"limit": 1, "type": "relay"}},
    )

    assert "result" in resp
    assert _count("get_summary", "ok") == ok_before + 1
    assert _count("get_summary", "error") == error_before


def test_failed_tool_call_is_counted_as_error(app_client: TestClient) -> None:
    error_before = _count("get_summary", "error")

    session = _mcp_initialize(app_client)
    # `type` only accepts relay|bridge, so the /v1 route rejects this with 422
    # before any upstream request is made.
    _mcp_call(
        app_client,
        session,
        "tools/call",
        {"name": "get_summary", "arguments": {"type": "not-a-type"}},
    )

    assert _count("get_summary", "error") == error_before + 1


def test_unknown_tool_names_collapse_into_one_label(app_client: TestClient) -> None:
    before = _count("unknown", "error")

    session = _mcp_initialize(app_client)
    for name in ("no_such_tool", "another_made_up_tool"):
        _mcp_call(app_client, session, "tools/call", {"name": name, "arguments": {}})

    assert _count("unknown", "error") == before + 2
    body = app_client.get("/metrics").text
    assert "no_such_tool" not in body
    assert "another_made_up_tool" not in body


def test_metrics_expose_every_advertised_tool_and_no_arguments(
    app_client: TestClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get("/summary").mock(return_value=httpx.Response(200, json=make_summary_envelope()))

    session = _mcp_initialize(app_client)
    tools = _mcp_call(app_client, session, "tools/list", {})["result"]["tools"]
    _mcp_call(
        app_client,
        session,
        "tools/call",
        {"name": "get_summary", "arguments": {"search": "distinctive-search-term", "limit": 1}},
    )

    body = app_client.get("/metrics").text
    for tool in tools:
        assert f'onionoo_mcp_tool_calls_total{{outcome="ok",tool="{tool["name"]}"}}' in body
    assert "distinctive-search-term" not in body
