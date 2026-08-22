from __future__ import annotations

import asyncio

from device_tui.interfaces.mcp.server import mcp
from device_tui.interfaces.mcp.server import mcp as packaged_mcp


def test_mcp_server_exposes_canonical_agent_workflow_tools() -> None:
    assert packaged_mcp is mcp
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "task.create",
        "task.get",
        "task.list",
        "task.resume",
        "task.cancel",
        "workflow.list",
        "workflow.plan.validate",
        "workflow.plan.get",
        "workflow.plan.approve",
        "workflow.run",
        "task.replan",
        "decision.get",
        "decision.apply",
        "tool.execute",
    }
    assert not names.intersection({"terminal_run", "terminal_execute", "package_upgrade_start", "ai_execute_command"})
