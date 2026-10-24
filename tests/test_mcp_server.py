from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from device_tui.interfaces.mcp.server import mcp
from device_tui.interfaces.mcp.server import mcp as packaged_mcp
from device_tui.interfaces.mcp.tools import register_all_tools


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
        "transfer.settings",
        "transfer.service",
        "transfer.files",
        "transfer.start",
        "operation.get",
        "operation.wait",
        "operation.cancel",
        "terminal.execute",
        "terminal.batch",
        "terminal.parallel",
        "terminal.interact",
        "terminal.interact.start",
        "terminal.interact.get",
        "terminal.interact.send",
        "terminal.interact.cancel",
        "terminal.interact.resume",
        "terminal.read",
        "task.create",
        "task.framework.start",
        "task.framework.execute",
        "task.framework.get",
        "task.get",
        "task.wait",
        "task.list",
        "task.resume",
        "task.pause",
        "task.cancel",
        "workflow.list",
        "workflow.authoring.describe",
        "workflow.script.list",
        "workflow.script.get",
        "workflow.script.create",
        "workflow.script.update",
        "workflow.script.delete",
        "workflow.script.validate",
        "workflow.script.test",
        "workflow.definition.list",
        "workflow.definition.get",
        "workflow.definition.create",
        "workflow.definition.update",
        "workflow.definition.validate",
        "workflow.definition.publish",
        "workflow.definition.run",
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


def test_structured_proposals_and_observation_round_trip_through_mcp() -> None:
    class RecordingGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, Any]]] = []

        def call(self, method: str, tool: str, **params: Any) -> dict[str, Any]:
            self.calls.append((method, tool, params))
            return {"ok": True, "data": {}}

    gateway = RecordingGateway()
    server = FastMCP("transport-test")
    register_all_tools(server, gateway)

    async def exercise() -> None:
        schemas = {tool.name: tool.inputSchema for tool in await server.list_tools()}
        plan_schema = schemas["workflow.plan.validate"]
        # FastMCP may inline models or retain JSON Schema references.
        def resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
            if "$ref" in schema:
                node = root
                for part in schema["$ref"].removeprefix("#/").split("/"):
                    node = node[part]
                return node
            return schema

        plan_model = resolve(plan_schema["properties"]["plan"], plan_schema)
        assert set(plan_model["required"]) == {"objective", "target", "steps"}
        step_model = resolve(plan_model["properties"]["steps"]["items"], plan_schema)
        assert set(step_model["required"]) == {"id", "capability"}
        decision_schema = schemas["decision.apply"]
        assert resolve(decision_schema["properties"]["action"], decision_schema)["required"] == ["name"]

        plan = {
            "id": "legacy-plan", "objective": "Inspect version",
            "target": {"device_id": "device-1"},
            "steps": [{"id": "version", "capability": "terminal.command",
                       "params": {"command": "display version"}, "retry": {"max_attempts": 2}}],
            "extension": {"ticket": "test"},
        }
        for tool, args, expected in [
            ("workflow.plan.validate", {"plan": plan}, {"plan": plan, "source": "agent"}),
            ("task.replan", {"parent_task_id": "parent", "plan": plan},
             {"parent_task_id": "parent", "plan": plan, "source": "agent"}),
            ("decision.apply", {"task_id": "task-1", "action": {"name": "retry", "extension": 1},
                                "reason": "Transient failure", "expected_revision": 3},
             {"task_id": "task-1", "action": {"name": "retry", "extension": 1},
              "reason": "Transient failure", "expected_revision": 3, "actor_type": "agent", "actor_id": "agent"}),
            ("task.wait", {"task_ids": ["task-1"], "after_cursors": {"task-1": "cursor"}, "timeout_seconds": 0},
             {"task_ids": ["task-1"], "after_cursors": {"task-1": "cursor"}, "timeout_seconds": 0}),
        ]:
            await server.call_tool(tool, args)
            assert gateway.calls[-1] == ("mcp_tool", tool, expected)

        await server.call_tool("device.list", {"query": "switch", "device_ids": [], "limit": 10, "offset": 20})
        assert gateway.calls[-1] == ("mcp_tool", "device_list", {
            "query": "switch", "device_ids": [], "owner": "", "status": "", "protocol": "",
            "limit": 10, "offset": 20,
        })

    asyncio.run(exercise())
