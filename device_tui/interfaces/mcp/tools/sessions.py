"""Terminal session lifecycle MCP tools."""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_session_tools(mcp: Any, gateway: McpGateway) -> None:
    @mcp.tool()
    def session_open(device_id: str) -> dict[str, Any]:
        """Open or reuse a terminal session for a device."""
        return gateway.call("session_open", device_id)

    @mcp.tool()
    def session_list(device_id: str | None = None) -> dict[str, Any]:
        """List runtime terminal sessions, optionally filtered by device."""
        return gateway.call("session_list", device_id)

    @mcp.tool()
    def session_manage(
        action: str,
        device_id: str | None = None,
        session_id: str | None = None,
        protocol: str = "auto",
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        """Open, inspect, reconnect, disconnect, or close a terminal session."""
        return gateway.call(
            "session_manage",
            action,
            device_id=device_id,
            session_id=session_id,
            protocol=protocol,
            timeout_seconds=timeout_seconds,
        )
