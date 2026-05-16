"""End-to-end test of the MCP server mounted at /mcp.

We speak Streamable HTTP JSON-RPC (MCP 2025-06-18) directly against the FastAPI
TestClient: initialize → notifications/initialized → tools/list → tools/call.
"""

from __future__ import annotations

from typing import Any

import httpx
import respx
from fastapi.testclient import TestClient

from tests.conftest import make_summary_envelope, relay

MCP_ACCEPT = "application/json, text/event-stream"


def _mcp_initialize(client: TestClient) -> str:
    r = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        },
        headers={"Accept": MCP_ACCEPT},
    )
    r.raise_for_status()
    session_id = r.headers["mcp-session-id"]

    # Spec requires notifications/initialized after the handshake.
    client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers={"Accept": MCP_ACCEPT, "mcp-session-id": session_id},
    )
    return session_id


def _mcp_call(client: TestClient, session_id: str, method: str, params: dict[str, Any]) -> Any:
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": method, "params": params},
        headers={"Accept": MCP_ACCEPT, "mcp-session-id": session_id},
    )
    r.raise_for_status()
    # Response may be JSON or SSE depending on content negotiation.
    ct = r.headers.get("content-type", "")
    if "text/event-stream" in ct:
        # Parse single-event SSE: lines starting with "data: " concatenated.
        payload_lines = [
            line.removeprefix("data: ") for line in r.text.splitlines() if line.startswith("data: ")
        ]
        import json as _json

        return _json.loads("".join(payload_lines))
    return r.json()


def test_mcp_tools_list_exposes_six_onionoo_tools(
    app_client: TestClient,
    respx_mock: respx.MockRouter,  # noqa: ARG001
) -> None:
    """All six Onionoo endpoints should be discoverable as MCP tools with clean names."""
    session = _mcp_initialize(app_client)
    resp = _mcp_call(app_client, session, "tools/list", {})

    tool_names = {t["name"] for t in resp["result"]["tools"]}
    assert {
        "get_summary",
        "get_details",
        "get_bandwidth",
        "get_weights",
        "get_clients",
        "get_uptime",
    } <= tool_names

    # Each tool must carry a non-trivial description for LLM tool selection.
    for tool in resp["result"]["tools"]:
        if tool["name"].startswith("get_"):
            assert len(tool.get("description", "")) > 50, f"{tool['name']} has a thin description"


def test_mcp_call_get_summary_routes_through_to_upstream(
    app_client: TestClient,
    respx_mock: respx.MockRouter,
) -> None:
    """tools/call get_summary should hit the upstream (mocked) and return relays."""
    relays = [relay(n="moria1", f="9695DFC35FFEB861329B9F1AB04C46397020CE31")]
    upstream = respx_mock.get("/summary").mock(
        return_value=httpx.Response(200, json=make_summary_envelope(relays=relays))
    )

    session = _mcp_initialize(app_client)
    resp = _mcp_call(
        app_client,
        session,
        "tools/call",
        {"name": "get_summary", "arguments": {"limit": 1, "type": "relay"}},
    )

    assert upstream.called
    assert "result" in resp
    # The tool response should expose the upstream payload (semantic-keyed).
    # fastapi-mcp wraps responses as content blocks; check both shapes.
    result = resp["result"]
    text_blocks = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    payload = "\n".join(text_blocks) or str(result)
    assert "moria1" in payload
    assert "9695DFC35FFEB861329B9F1AB04C46397020CE31" in payload
