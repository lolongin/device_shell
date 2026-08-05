"""Domain-oriented MCP tool registration."""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_all_tools(mcp: Any, gateway: McpGateway) -> None:
    from .ai_gateway import register_ai_gateway_tools
    from .devices import register_device_tools
    from .operations import register_operation_tools
    from .sessions import register_session_tools
    from .system import register_system_tools
    from .terminal import register_terminal_tools
    from .transfers import register_transfer_tools

    register_system_tools(mcp, gateway)
    register_device_tools(mcp, gateway)
    register_session_tools(mcp, gateway)
    register_terminal_tools(mcp, gateway)
    register_transfer_tools(mcp, gateway)
    register_operation_tools(mcp, gateway)
    register_ai_gateway_tools(mcp, gateway)


__all__ = ["register_all_tools"]
