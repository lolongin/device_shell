"""Public MCP tool registration.

The stdio server exposes namespaced discovery, terminal, transfer, task,
workflow and decision tools. All execution goes through backend policy.
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
