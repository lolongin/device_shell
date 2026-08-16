"""Approval and long-running operation MCP tools."""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_operation_tools(mcp: Any, gateway: McpGateway) -> None:
    @mcp.tool()
    def approval_get(approval_id: str) -> dict[str, Any]:
        """Poll an approval when compatibility approval mode is enabled."""
        return gateway.call("approval_get", approval_id)

    @mcp.tool()
    def operation_get(operation_id: str) -> dict[str, Any]:
        """Read a long-running Device TUI operation."""
        return gateway.call("operation_get", operation_id)

    @mcp.tool()
    def operation_wait(
        operation_id: str,
        timeout_seconds: int = 60,
        since_revision: int = 0,
    ) -> dict[str, Any]:
        """Wait until an operation changes, completes, or the timeout expires."""
        return gateway.call(
            "operation_wait",
            operation_id,
            timeout_seconds=timeout_seconds,
            since_revision=since_revision,
        )

    @mcp.tool()
    def operation_cancel(operation_id: str) -> dict[str, Any]:
        """Cancel a cancellable long-running Device TUI operation."""
        return gateway.call("operation_cancel", operation_id)
