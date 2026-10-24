"""Adapt canonical MCP tool definitions to in-process Agent calls."""

from __future__ import annotations

import inspect
from typing import Any, get_type_hints

from pydantic import ConfigDict, create_model

from device_tui.interfaces.mcp.tools import register_all_tools
from .agent_desktop_tools import DesktopAgentTools, UNAVAILABLE_CAPABILITIES
from .agent_knowledge_tools import AgentKnowledgeTools


AGENT_TOOLS = frozenset("""
app.status device.list device.get device.select device.open device.action
session.open session.list session.manage connection.open profile.list
transfer.files transfer.start operation.get operation.wait operation.cancel
terminal.execute terminal.batch terminal.read terminal.interact.get
terminal.interact.start terminal.interact.send terminal.interact.cancel terminal.interact.resume
workflow.list workflow.authoring.describe workflow.script.list workflow.script.get
workflow.script.create workflow.script.update workflow.script.validate workflow.script.test
workflow.definition.list workflow.definition.get workflow.definition.create
workflow.definition.update workflow.definition.validate workflow.definition.publish workflow.definition.run
workflow.plan.validate workflow.plan.get workflow.run
task.create task.get task.wait task.list task.resume task.pause task.cancel task.replan
task.framework.start task.framework.execute task.framework.get decision.get decision.apply
source.status source.plugins source.switch source.plugin.test profile.delete
command.workspace command.group.save command.group.delete command.group.reorder command.preferences
transfer.settings transfer.service terminal.parallel terminal.interact workflow.script.delete
""".split())


class LocalAgentTools:
    """Shared schemas and argument translation, without HTTP or arbitrary dispatch."""

    def __init__(self, service: Any) -> None:
        self.service = service
        self.context: Any = None
        self.entries: dict[str, tuple[str, Any, Any]] = {}
        register_all_tools(self, self)
        self.desktop_tools = DesktopAgentTools(lambda: self.context)
        self.knowledge_tools = AgentKnowledgeTools(lambda: self.context)

    def tool(self, *, name: str):
        def register(function):
            if name not in AGENT_TOOLS:
                return function
            hints = get_type_hints(function)
            fields = {
                key: (hints[key], ... if value.default is inspect.Parameter.empty else value.default)
                for key, value in inspect.signature(function).parameters.items()
            }
            model = create_model(name.replace(".", "_") + "Arguments", __config__=ConfigDict(extra="forbid", strict=True), **fields)
            self.entries[name.replace(".", "_")] = (name, function, model)
            return function
        return register

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {
            "name": key,
            "description": (inspect.getdoc(function) or name) + " Mutations may return needs_approval; only the user can approve in the application.",
            "parameters": model.model_json_schema(),
        }} for key, (name, function, model) in self.entries.items()] + self.desktop_tools.definitions + self.knowledge_tools.definitions

    @property
    def read_only_tools(self) -> frozenset[str]:
        return self.desktop_tools.read_only_tools | frozenset(self.knowledge_tools.entries) | frozenset({"source_status", "source_plugins", "command_workspace", "transfer_settings"})

    @property
    def unavailable_capabilities(self) -> list[dict[str, str]]:
        return list(UNAVAILABLE_CAPABILITIES)

    def validate(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name in self.knowledge_tools.entries:
            return self.knowledge_tools.validate(name, arguments)
        if name in self.desktop_tools.entries:
            return self.desktop_tools.validate(name, arguments)
        if name not in self.entries:
            raise ValueError(f"Unknown or unavailable Agent tool: {name}")
        return self.entries[name][2].model_validate(arguments).model_dump()

    async def call(self, method: str, tool: str, **params: Any) -> dict[str, Any]:
        if method != "mcp_tool":
            raise ValueError("Only application tools are available")
        _status, response = await self.service.invoke(tool, params)
        return response

    async def invoke(self, name: str, arguments: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        if name in self.knowledge_tools.entries:
            return await self.knowledge_tools.invoke(name, arguments)
        if name in self.desktop_tools.entries:
            return await self.desktop_tools.invoke(name, arguments)
        canonical, function, model = self.entries[name]
        params = dict(arguments)
        if approved:
            for key in ("confirm", "confirmed", "confirmed_risks"):
                if key in model.model_fields:
                    params[key] = True
            if canonical == "workflow.run" and params.get("plan_id"):
                approval = await self.call("mcp_tool", "workflow.plan.approve", plan_id=params["plan_id"], plan_hash=params.get("plan_hash", ""), actor_type="user", reason="Approved in Agent panel")
                if not approval.get("ok"):
                    return approval
        validated = model.model_validate(params)
        return await function(**{key: getattr(validated, key) for key in model.model_fields})

    async def snapshot(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Capture mutable executable resources for approval freshness checks."""
        if name in self.desktop_tools.entries:
            return await self.desktop_tools.snapshot(name, params)
        reads: list[tuple[str, dict[str, Any]]] = []
        if name.startswith("workflow_definition_") and params.get("workflow_id"):
            reads.extend([
                ("workflow.definition.get", {"workflow_id": params["workflow_id"]}),
                ("workflow.script.list", {}), ("workflow.list", {}),
            ])
        elif name == "workflow_script_test":
            reads.append(("workflow.script.get", {"script_id": params["script_id"]}))
        elif name == "workflow_run" and params.get("plan_id"):
            reads.append(("workflow.plan.get", {"plan_id": params["plan_id"]}))
        elif name in {"workflow_run", "task_create", "task_resume", "task_framework_start", "task_framework_execute", "task_replan", "decision_apply"}:
            reads.extend([("workflow.list", {}), ("workflow.script.list", {})])
        snapshot = {}
        for tool, arguments in reads:
            result = await self.call("mcp_tool", tool, **arguments)
            if not result.get("ok"):
                raise ValueError(result.get("message") or "Cannot read executable resource")
            snapshot[tool] = result.get("data", {})
        # Published versions and nested Workflow calls can change independently
        # from the top-level draft. Bind them too before any workflow execution.
        if reads and hasattr(self.service, "desktop"):
            definitions = self.service.desktop.workflow_definitions
            snapshot["studio_versions"] = [item.to_dict() for item in definitions.list_published(latest_only=False)]
        if self.context is not None and name.startswith(("source_", "profile_", "command_", "transfer_")):
            snapshot.update(await self.desktop_tools.snapshot(name, params))
        return snapshot

    async def preview(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        if name == "workflow_import":
            result = await self.desktop_tools.invoke("workflow_import_preview", params)
            if not result["data"].get("valid"):
                raise ValueError("Workflow import is invalid; use workflow_import_preview to inspect validation errors")
            return {"validation": result}
        if name in {"workflow_definition_publish", "workflow_definition_run"}:
            validation = await self.call("mcp_tool", "workflow.definition.validate", workflow_id=params["workflow_id"])
            if not validation.get("ok") or not validation.get("data", {}).get("valid"):
                raise ValueError("Workflow validation failed; fix the draft before requesting approval")
            if name == "workflow_definition_run":
                preview = await self.invoke(name, {**params, "dry_run": True, "confirmed_risks": False})
                if not preview.get("ok"):
                    raise ValueError(preview.get("message") or "Workflow preview failed")
                return {"validation": validation, "preview": preview}
            return {"validation": validation}
        return {}
