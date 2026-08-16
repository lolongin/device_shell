"""System-level MCP tools."""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_system_tools(mcp: Any, gateway: McpGateway) -> None:
    @mcp.tool()
    def system_status() -> dict[str, Any]:
        """Inspect Device TUI readiness, approval mode, sessions, and operations."""
        return gateway.call("system_status")
