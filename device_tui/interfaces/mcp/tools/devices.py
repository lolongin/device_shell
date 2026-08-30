"""Device discovery MCP tools."""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_device_tools(mcp: Any, gateway: McpGateway) -> None:
    @mcp.tool()
    def device_list() -> dict[str, Any]:
        """List devices visible in OdyTerm, including the simulated device."""
        return gateway.call("device_list")

    @mcp.tool()
    def device_get(device_id: str) -> dict[str, Any]:
        """Get credential-free device details, capabilities, and endpoints."""
        return gateway.call("device_get", device_id)

    @mcp.tool()
    def device_select(device_id: str) -> dict[str, Any]:
        """Select a device by its stable OdyTerm ID."""
        return gateway.call("device_select", device_id)
