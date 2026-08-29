from __future__ import annotations

import asyncio

from device_tui.interfaces.mcp.server import mcp
from device_tui.interfaces.mcp.server import mcp as packaged_mcp


def test_mcp_server_exposes_canonical_agent_workflow_tools() -> None:
    assert packaged_mcp is mcp
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "app.capabilities",
        "app.status",
        "device.list",
        "device.get",
        "device.select",
        "device.open",
        "connection.open",
        "device.action",
        "session.open",
        "session.list",
        "session.manage",
        "source.status",
        "source.plugins",
        "source.switch",
        "source.plugin.update",
        "source.plugin.test",
        "profile.list",
        "profile.save",
        "profile.delete",
        "command.workspace",
        "command.group.save",
        "command.group.delete",
        "command.group.reorder",
        "command.preferences",
        "automation.workspace",
        "automation.preview",
        "automation.rule.save",
        "automation.rule.delete",
        "automation.rule.clone",
        "automation.rule.enable",
        "automation.rule.trigger",
        "automation.cancel",
        "automation.quick_send.save",
        "automation.quick_send.delete",
        "automation.quick_send.send",
        "transfer.settings",
        "transfer.service",
        "transfer.files",
        "transfer.start",
        "operation.get",
        "operation.wait",
        "operation.cancel",
        "terminal.execute",
        "terminal.batch",
        "terminal.interact",
        "terminal.read",
        "task.create",
        "task.framework.start",
        "task.framework.execute",
        "task.framework.get",
        "task.get",
        "task.list",
        "task.resume",
        "task.pause",
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
