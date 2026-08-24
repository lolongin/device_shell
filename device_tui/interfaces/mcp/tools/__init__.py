"""Public MCP tool registration.

The stdio MCP server intentionally exposes one small, namespaced surface for
Agent/Operator use.  Device/session/terminal/transfer helpers remain backend
implementation and HTTP compatibility details; exposing all of them here made
the same capability appear under several names and encouraged Agents to bypass
the Task/Decision boundary.
"""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_all_tools(mcp: Any, gateway: McpGateway) -> None:
    from .app_control import register_app_control_tools
    from .workflow_tasks import register_workflow_task_tools

    register_app_control_tools(mcp, gateway)
    register_workflow_task_tools(mcp, gateway)


__all__ = ["register_all_tools"]
