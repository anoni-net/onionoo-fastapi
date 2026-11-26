"""Streamable HTTP MCP server (`/mcp`) with per-tool call counting.

fastapi-mcp turns each tool call into an in-process HTTP request against the
`/v1/*` routes, so the request metrics cannot distinguish an MCP tool call
from a direct REST call. This subclass counts calls at the point where
fastapi-mcp dispatches them, labelled only by tool name and outcome.

`_execute_api_tool` is a private fastapi-mcp method. fastapi-mcp is pinned to
the 0.4 line and is due to be replaced when the server moves to mcp 2.x;
`tests/test_mcp_tool_metrics.py` exercises the full `/mcp` path, so a change in
fastapi-mcp internals fails the suite instead of silently stopping the count.
"""

from __future__ import annotations

from typing import Any

from fastapi_mcp import FastApiMCP

from app.observability import MCP_TOOL_CALLS

UNKNOWN_TOOL = "unknown"
OUTCOMES = ("ok", "error")


class CountingFastApiMCP(FastApiMCP):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Pre-create every series at zero so "never called" shows up as 0
        # rather than as a missing series.
        for tool in [*self.operation_map, UNKNOWN_TOOL]:
            for outcome in OUTCOMES:
                MCP_TOOL_CALLS.labels(tool=tool, outcome=outcome)

    async def _execute_api_tool(
        self,
        client: Any,
        tool_name: str,
        arguments: dict[str, Any],
        operation_map: dict[str, dict[str, Any]],
        http_request_info: Any = None,
    ) -> Any:
        tool = tool_name if tool_name in operation_map else UNKNOWN_TOOL
        try:
            result = await super()._execute_api_tool(
                client=client,
                tool_name=tool_name,
                arguments=arguments,
                operation_map=operation_map,
                http_request_info=http_request_info,
            )
        except Exception:
            MCP_TOOL_CALLS.labels(tool=tool, outcome="error").inc()
            raise
        MCP_TOOL_CALLS.labels(tool=tool, outcome="ok").inc()
        return result
