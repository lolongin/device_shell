"""Compatibility facade mapping the existing MCP tools to desktop application services."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import threading
from typing import Any

from device_tui.application import (
    AiApplicationService,
    Action,
    ApplicationError,
    CommandRequest,
    ControlContext,
    DesktopApplication,
    DeviceTarget,
    Decision,
    DecisionActor,
    TransferRequest,
    TaskCreate,
    WorkflowCatalogError,
    WorkflowTarget,
    WorkflowPlan,
    WorkflowPlanCompiler,
    PlanStore,
)
from device_tui.application.profiles import ConnectionProfileDraft, ProfileEndpoint
from device_tui.application.errors import ResourceNotFoundError, UnsupportedOperationError
from .terminal_executor import BackendTerminalExecutor


class DesktopMcpService:
    """Expose one Backend capability boundary for legacy and Agent MCP tools."""

    def __init__(
        self,
        desktop: DesktopApplication,
        terminal_executor: BackendTerminalExecutor,
        ai: AiApplicationService,
        plan_store: PlanStore | None = None,
        source_service: Any | None = None,
    ) -> None:
        self.desktop = desktop
        self.terminal_executor = terminal_executor
        self.ai = ai
        self.source_service = source_service
        self._selected_device_id = ""
        self._plan_compiler = WorkflowPlanCompiler(catalog=desktop.workflows)
        self._plans: dict[str, tuple[WorkflowPlan, Any]] = {}
        self._approved_plans: set[str] = set()
        self._plan_store = plan_store
        if plan_store is not None:
            for payload in plan_store.list_plans(limit=500):
                restored = self._restore_plan(payload)
                if restored is not None:
                    plan, validation, approved = restored
                    self._plans[plan.plan_id] = (plan, validation)
                    if approved:
                        self._approved_plans.add(plan.plan_id)
        self._idempotency: dict[str, tuple[int, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    async def invoke(self, tool: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        idempotency_key = str(params.get("idempotency_key") or "").strip()
        cache_key = f"{tool}\0{idempotency_key}" if idempotency_key else ""
        if cache_key:
            with self._lock:
                cached = self._idempotency.get(cache_key)
            if cached is not None:
                return cached[0], dict(cached[1])
        # Public MCP names use namespaces (task.create, decision.get, ...),
        # while handlers stay ordinary Python identifiers.  Keep the legacy
        # underscore names working and normalize only at this boundary.
        handler_name = tool.replace(".", "_")
        handler = getattr(self, f"_tool_{handler_name}", None)
        if not callable(handler):
            return self._error(404, "tool_not_found", f"Unsupported MCP tool: {tool}")
        try:
            data = await handler(dict(params))
        except ApplicationError as exc:
            return self._error(409 if exc.code == "conflict" else 400, exc.code, exc.message, exc.details)
        except KeyError as exc:
            return self._error(404, "resource_not_found", f"Unknown resource: {exc}")
        except Exception as exc:  # keep the compatibility envelope stable
            return self._error(400, "mcp_execution_failed", str(exc))
        self.ai.record_mcp_audit(tool, params, status=200)
        response = self._success(data)
        if cache_key:
            with self._lock:
                self._idempotency[cache_key] = (200, dict(response))
        return 200, response

    async def _tool_system_status(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ready",
            "approval_mode": "disabled",
            "selected_device_id": self._selected_device_id,
            "sessions": [self._session_payload(item) for item in self.desktop.sessions.list_sessions()],
            "operations": [asdict(item) for item in self.desktop.control.list_operations(limit=50)],
        }

    async def _tool_app_capabilities(self, _params: dict[str, Any]) -> dict[str, Any]:
        """Describe the supported application control-plane resources."""
        return {
            "resources": {
                "devices": {"read": ["list", "get", "select"], "write": ["open", "action"]},
                "sessions": {"read": ["list", "status"], "write": ["open", "reconnect", "disconnect", "close"]},
                "workflows": {"read": ["list", "plan.get"], "write": ["run", "plan.validate", "plan.approve", "replan"]},
                "tasks": {"read": ["list", "get", "decision.get"], "write": ["create", "resume", "pause", "cancel", "decision.apply"]},
                "terminal": {"read": ["read", "execution.get"], "write": ["execute", "batch", "interact", "execution.cancel"]},
                "profiles": {"read": ["list"], "write": ["save", "delete"]},
                "connections": {"write": ["open"]},
                "commands": {"read": ["workspace"], "write": ["group.save", "group.delete", "group.reorder", "preferences"]},
                "automation": {"read": ["workspace", "preview"], "write": ["rule.save", "rule.delete", "rule.clone", "rule.enable", "rule.trigger", "cancel", "quick_send.save", "quick_send.delete", "quick_send.send"]},
                "transfers": {"read": ["settings", "files", "operation.get", "operation.wait"], "write": ["settings", "service.start", "service.stop", "service.log.clear", "start", "operation.cancel"]},
                "device_sources": {"read": ["status", "plugins"], "write": ["switch", "plugin.update", "plugin.test"]},
                "ai": {"read": ["skills", "result", "approval", "audit"], "write": ["execute", "approval"]},
            },
            "boundaries": {
                "workflow_engine": "task_only",
                "arbitrary_method_dispatch": False,
                "raw_device_commands": "policy_checked_terminal_tools",
                "credentials": "never_returned",
            },
        }

    async def _tool_device_action(self, params: dict[str, Any]) -> dict[str, Any]:
        device_id = self._text(params, "device_id")
        action = self._text(params, "action").casefold()
        if not bool(params.get("confirm", False)):
            raise UnsupportedOperationError("device.action requires confirm=true.")
        operations = {
            "claim": self.desktop.devices.claim,
            "release": self.desktop.devices.release,
            "toggle": self.desktop.devices.toggle,
            "power_off": self.desktop.devices.power_off,
        }
        operation = operations.get(action)
        if operation is None:
            raise UnsupportedOperationError(f"Unsupported device action: {action}")
        result = operation(device_id)
        return {"action": action, "device_id": device_id, "message": result.message, "device": self._device_payload(result.device)}

    async def _tool_device_open(self, params: dict[str, Any]) -> dict[str, Any]:
        device_id = self._text(params, "device_id")
        protocol = str(params.get("protocol") or "auto").casefold()
        if protocol not in {"auto", "ssh", "telnet", "serial", "simulated"}:
            raise UnsupportedOperationError(
                "protocol must be one of auto, ssh, telnet, serial, simulated."
            )
        session, reused = await self._open_or_reuse(device_id, protocol)
        return {
            "device_id": device_id,
            "protocol": session.kind,
            "requested_protocol": protocol,
            "reused": reused,
            "session": self._session_payload(session),
        }

    async def _tool_connection_open(self, params: dict[str, Any]) -> dict[str, Any]:
        profile_id = self._text(params, "profile_id")
        protocol = str(params.get("protocol") or "ssh").casefold()
        if protocol not in {"ssh", "telnet", "serial"}:
            raise UnsupportedOperationError("profile connection protocol must be ssh, telnet, or serial.")
        target = self.desktop.profiles.resolve_target(profile_id, protocol)
        view = await self.desktop.control.open_connection(
            target,
            reuse=True,
            title=str(params.get("title") or ""),
            term_size=(int(params.get("cols") or 160), int(params.get("rows") or 40)),
            context=ControlContext(source="mcp"),
        )
        session = next(
            (item for item in self.desktop.sessions.list_sessions() if item.id == view.session_id),
            None,
        )
        if session is None:
            raise ResourceNotFoundError("Session disappeared after opening", details={"session_id": view.session_id})
        return {
            "profile_id": profile_id,
            "device_id": session.device_id,
            "protocol": session.kind,
            "reused": view.reused,
            "session": self._session_payload(session),
        }

    async def _tool_source_status(self, _params: dict[str, Any]) -> dict[str, Any]:
        service = self._require_source_service()
        return self._source_status_payload(service)

    async def _tool_source_plugins(self, _params: dict[str, Any]) -> dict[str, Any]:
        service = self._require_source_service()
        plugins: list[dict[str, Any]] = []
        for registration in service.registry.registrations():
            descriptor = registration.descriptor
            values = service.registry.configuration(descriptor.id)
            plugins.append({
                "id": descriptor.id,
                "label": descriptor.label,
                "description": descriptor.description,
                "version": descriptor.version,
                "publisher": descriptor.publisher,
                "built_in": registration.built_in,
                "enabled": service.registry.enabled(descriptor.id),
                "available": descriptor.id in service.source_ids(),
                "active": descriptor.id == service.active_source,
                "default": descriptor.id == service.default_source,
                "requires_login": descriptor.requires_login,
                "supports_import": descriptor.supports_import,
                "unavailable_reason": service.registry.unavailable_reason(descriptor.id),
                "config": {item.key: values.get(item.key) for item in registration.config_fields if item.kind != "secret"},
                "secrets_configured": [item.key for item in registration.config_fields if item.kind == "secret" and service.registry.secret_configured(descriptor.id, item.key)],
            })
        return {"plugins": plugins, "warnings": list(service.registry.warnings())}

    async def _tool_source_switch(self, params: dict[str, Any]) -> dict[str, Any]:
        service = self._require_source_service()
        if not service.product_profile.allow_source_switch:
            raise UnsupportedOperationError("The current product policy does not allow source switching.")
        if not bool(params.get("confirm", False)):
            raise UnsupportedOperationError("source.switch requires confirm=true.")
        source_id = self._text(params, "source")
        descriptor = service.activate(source_id)
        return {"active_source": descriptor.id, "source": self._source_status_payload(service)}

    async def _tool_source_plugin_update(self, params: dict[str, Any]) -> dict[str, Any]:
        service = self._require_source_service()
        if not service.product_profile.allow_plugin_management:
            raise UnsupportedOperationError("The current product policy does not allow plugin management.")
        if not bool(params.get("confirm", False)):
            raise UnsupportedOperationError("source.plugin.update requires confirm=true.")
        source_id = self._text(params, "source_id")
        config = params.get("config") if isinstance(params.get("config"), dict) else {}
        secrets = params.get("secrets") if isinstance(params.get("secrets"), dict) else {}
        service.apply_plugin_configuration(source_id, config_updates=config, secret_updates=secrets, enabled=params.get("enabled"))
        return await self._tool_source_plugins({})

    async def _tool_source_plugin_test(self, params: dict[str, Any]) -> dict[str, Any]:
        service = self._require_source_service()
        result = service.test_plugin_configuration(self._text(params, "source_id"))
        return {"success": result.success, "message": result.message}

    async def _tool_profile_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"profiles": [self._profile_payload(item) for item in self.desktop.profiles.list_profiles()], "groups": self.desktop.profiles.list_groups()}

    async def _tool_profile_save(self, params: dict[str, Any]) -> dict[str, Any]:
        profile = self.desktop.profiles.save(self._profile_draft(params), allow_duplicate=bool(params.get("allow_duplicate", False)))
        return {"profile": self._profile_payload(profile)}

    async def _tool_profile_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        profile_id = self._text(params, "profile_id")
        if not bool(params.get("confirm", False)):
            raise UnsupportedOperationError("profile.delete requires confirm=true.")
        self.desktop.profiles.delete(profile_id)
        return {"profile_id": profile_id, "deleted": True}

    async def _tool_command_workspace(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"groups": [asdict(item) for item in self.desktop.commands.list_groups()], "current_group_id": self.desktop.commands.current_group_id(), "enter_sends": self.desktop.commands.enter_sends(), "history": [asdict(item) for item in self.desktop.commands.history(limit=200)]}

    async def _tool_command_group_save(self, params: dict[str, Any]) -> dict[str, Any]:
        group_id = str(params.get("group_id") or "").strip()
        if group_id:
            name = str(params.get("name") or "").strip() or None
            group = self.desktop.commands.update_group(group_id, name=name, content=str(params.get("content") or ""))
        else:
            group = self.desktop.commands.create_group(str(params.get("name") or ""))
            if "content" in params:
                group = self.desktop.commands.update_group(group.id, content=str(params.get("content") or ""))
        return {"group": asdict(group)}

    async def _tool_command_group_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        group_id = self._text(params, "group_id")
        if not bool(params.get("confirm", False)):
            raise UnsupportedOperationError("command.group.delete requires confirm=true.")
        self.desktop.commands.delete_group(group_id)
        return {"group_id": group_id, "deleted": True}

    async def _tool_command_group_reorder(self, params: dict[str, Any]) -> dict[str, Any]:
        group_ids = params.get("group_ids")
        if not isinstance(group_ids, list):
            raise UnsupportedOperationError("group_ids must be a list")
        return {"groups": [asdict(item) for item in self.desktop.commands.reorder_groups([str(item) for item in group_ids]) ]}

    async def _tool_command_preferences(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("current_group_id") is not None:
            self.desktop.commands.set_current_group(str(params["current_group_id"]))
        if params.get("enter_sends") is not None:
            self.desktop.commands.set_enter_sends(bool(params["enter_sends"]))
        return await self._tool_command_workspace({})

    async def _tool_automation_workspace(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"rules": [self._automation_rule_payload(item) for item in self.desktop.automation.list_rules()], "sessions": [asdict(item) for item in self.desktop.automation.statuses()], "quick_send_buttons": [asdict(item) for item in self.desktop.automation.list_quick_send_buttons()], "activity": [asdict(item) for item in self.desktop.automation.activities(limit=100)]}

    async def _tool_automation_rule_save(self, params: dict[str, Any]) -> dict[str, Any]:
        raw = params.get("rule")
        if not isinstance(raw, dict):
            raise UnsupportedOperationError("rule must be an object")
        rule = self.desktop.automation.deserialize_rule(raw)
        rule_id = str(params.get("rule_id") or "").strip()
        record = self.desktop.automation.update_rule(rule_id, rule) if rule_id else self.desktop.automation.create_rule(rule)
        return {"rule": self._automation_rule_payload(record)}

    async def _tool_automation_rule_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        rule_id = self._text(params, "rule_id")
        if not bool(params.get("confirm", False)):
            raise UnsupportedOperationError("automation.rule.delete requires confirm=true.")
        self.desktop.automation.delete_rule(rule_id)
        return {"rule_id": rule_id, "deleted": True}

    async def _tool_automation_rule_clone(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"rule": self._automation_rule_payload(self.desktop.automation.clone_rule(self._text(params, "rule_id")))}

    async def _tool_automation_rule_enable(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"rule": self._automation_rule_payload(self.desktop.automation.set_enabled(self._text(params, "rule_id"), bool(params.get("enabled", True))))}

    async def _tool_automation_rule_trigger(self, params: dict[str, Any]) -> dict[str, Any]:
        rule_id, session_id = self._text(params, "rule_id"), self._text(params, "session_id")
        self.desktop.automation.trigger_rule(rule_id, session_id)
        return {"rule_id": rule_id, "session_id": session_id, "status": "started"}

    async def _tool_automation_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = self._text(params, "session_id")
        self.desktop.automation.cancel_session(session_id, reason="mcp_cancel")
        return {"session_id": session_id, "status": "cancelled"}

    async def _tool_automation_quick_send_save(self, params: dict[str, Any]) -> dict[str, Any]:
        button_id = str(params.get("button_id") or "").strip()
        values = {key: params[key] for key in ("name", "response_text", "append_enter", "sensitive") if key in params}
        button = self.desktop.automation.update_quick_send_button(button_id, **values) if button_id else self.desktop.automation.create_quick_send_button(**values)
        return {"button": asdict(button)}

    async def _tool_automation_quick_send_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        button_id = self._text(params, "button_id")
        if not bool(params.get("confirm", False)):
            raise UnsupportedOperationError("automation.quick_send.delete requires confirm=true.")
        self.desktop.automation.delete_quick_send_button(button_id)
        return {"button_id": button_id, "deleted": True}

    async def _tool_automation_quick_send_send(self, params: dict[str, Any]) -> dict[str, Any]:
        button_id, session_id = self._text(params, "button_id"), self._text(params, "session_id")
        await self.desktop.automation.send_quick_send_button(button_id, session_id)
        return {"button_id": button_id, "session_id": session_id, "status": "sent"}

    async def _tool_transfer_settings(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"settings": asdict(self.desktop.transfers.settings())}

    async def _tool_transfer_service(self, params: dict[str, Any]) -> dict[str, Any]:
        action = self._text(params, "action").casefold()
        if action == "start":
            await self.desktop.transfers.start_service(auto_stop_when_idle=False)
        elif action == "stop":
            await self.desktop.transfers.stop_service()
        elif action == "clear_log":
            self.desktop.transfers.clear_service_log()
        else:
            raise UnsupportedOperationError(f"Unsupported transfer service action: {action}")
        return {"action": action, "settings": asdict(self.desktop.transfers.settings()), "log": self.desktop.transfers.service_log()}

    async def _tool_transfer_files(self, params: dict[str, Any]) -> dict[str, Any]:
        catalog = self.desktop.transfers.list_files(
            relative_path=str(params.get("path") or ""),
            recursive=bool(params.get("recursive", True)),
            limit=min(1_000, max(1, int(params.get("limit") or 200))),
        )
        return {"files": [item.public_dict() for item in catalog.files], "truncated": catalog.truncated}

    async def _tool_transfer_start(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._tool_file_transfer_start(params)

    async def _tool_automation_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        raw = params.get("rule")
        if not isinstance(raw, dict):
            raise UnsupportedOperationError("rule must be an object")
        return self.desktop.automation.preview_rule(
            self.desktop.automation.deserialize_rule(raw),
            session_id=str(params.get("session_id") or ""),
            sample_output=str(params.get("sample_output") or ""),
            max_steps=min(500, max(1, int(params.get("max_steps") or 200))),
        )

    async def _tool_device_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        inventory = self.desktop.devices.list_inventory()
        return {
            "current_user": inventory.current_user,
            "devices": [self._device_payload(item) for item in inventory.devices],
        }

    async def _tool_device_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"device": self._device_payload(self.desktop.devices.require_device(self._text(params, "device_id")))}

    async def _tool_device_select(self, params: dict[str, Any]) -> dict[str, Any]:
        device = self.desktop.devices.require_device(self._text(params, "device_id"))
        self._selected_device_id = device.id
        return {"selected_device_id": device.id, "device": self._device_payload(device)}

    async def _create_task(self, params: dict[str, Any]) -> dict[str, Any]:
        """Build and persist a Task for both task.create and workflow.run."""
        validated_plan_id = str(params.get("validated_plan_id") or params.get("plan_id") or "").strip()
        if validated_plan_id:
            stored = self._plans.get(validated_plan_id)
            if stored is None:
                raise ResourceNotFoundError("Unknown or expired workflow plan.", details={"plan_id": validated_plan_id})
            planned, validation = stored
            expected_hash = str(params.get("expected_plan_hash") or params.get("plan_hash") or "").strip()
            if expected_hash and expected_hash != validation.plan_hash:
                raise UnsupportedOperationError("Workflow plan hash does not match the validated plan.")
            if validation.status != "validated" and validated_plan_id not in self._approved_plans:
                raise UnsupportedOperationError("Workflow plan requires confirmation before it can run.", details={"status": validation.status})
            params = {
                **params,
                "workflow_id": validation.workflow.id if validation.workflow else planned.plan_id,
                "device_id": str(params.get("device_id") or planned.target.get("device_id") or ""),
                "session_id": str(params.get("session_id") or planned.target.get("session_id") or ""),
                "protocol": str(params.get("protocol") or planned.target.get("protocol") or "auto"),
                "steps": [],
            }
            compiled = validation.workflow
            if compiled is None:
                raise UnsupportedOperationError("Validated workflow has no compiled definition.")
        else:
            compiled = None
        device_id = str(params.get("device_id") or "")
        session_id = str(params.get("session_id") or "")
        if session_id:
            session = self._resolve_session(session_id=session_id)
            device_id = session.device_id
        if not device_id:
            raise UnsupportedOperationError("A device_id or session_id is required.")
        if not session_id:
            view = await self.desktop.control.open_session(
                DeviceTarget(device_id=device_id, protocol=str(params.get("protocol") or "auto")),
                reuse=True,
                context=ControlContext(source="mcp"),
            )
            session_id = view.session_id
        workflow_id = str(params.get("workflow_id") or "task")
        if compiled is not None:
            workflow = compiled
        elif self.desktop.workflows.contains(workflow_id):
            parameters = {
                **(dict(params.get("options") or {}) if isinstance(params.get("options"), dict) else {}),
                **(dict(params.get("parameters") or {}) if isinstance(params.get("parameters"), dict) else {}),
            }
            if params.get("package"):
                parameters.setdefault("package_path", str(params["package"]))
            raw_steps = params.get("steps")
            legacy_steps = tuple(item for item in raw_steps if isinstance(item, dict)) if isinstance(raw_steps, list) else ()
            try:
                workflow = self.desktop.workflows.build(
                    workflow_id,
                    WorkflowTarget(device_id=device_id, session_id=session_id, protocol=str(params.get("protocol") or "auto")),
                    parameters,
                    legacy_steps=legacy_steps,
                )
            except WorkflowCatalogError as exc:
                raise UnsupportedOperationError(str(exc)) from exc
        else:
            raise UnsupportedOperationError(
                f"Unknown workflow_id: {workflow_id}. Register a WorkflowProvider or submit a WorkflowPlan."
            )
        source = str(params.get("source") or "mcp").strip() or "mcp"
        task_context = dict(params.get("context") or {}) if isinstance(params.get("context"), dict) else {}
        if validated_plan_id in self._approved_plans:
            task_context["approved_steps"] = [
                item.target_step for item in validation.required_actions
                if getattr(item, "target_step", "")
            ]
        record = self.desktop.tasks.create(TaskCreate(
            workflow=workflow,
            target=DeviceTarget(device_id=device_id, session_id=session_id, protocol=str(params.get("protocol") or "auto")),
            source=source,
            context=task_context,
        ))
        return {"task": self._task_payload(record)}

    async def _tool_task_create(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create a Task through the same backend boundary as Electron."""
        return await self._create_task(params)

    async def _tool_workflow_plan_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        raw = params.get("plan")
        if not isinstance(raw, dict):
            # Accept a flat payload as a convenience for MCP clients.
            raw = {key: value for key, value in params.items() if key not in {"source", "request_id"}}
        plan = WorkflowPlan.from_dict(raw)
        device_id = str(plan.target.get("device_id") or "").strip()
        if device_id:
            self.desktop.devices.require_device(device_id)
        if not plan.plan_id:
            plan = WorkflowPlan(
                plan_id=f"plan-{__import__('uuid').uuid4().hex[:12]}",
                objective=plan.objective,
                target=plan.target,
                steps=plan.steps,
                success_criteria=plan.success_criteria,
                budget=plan.budget,
                parent_task_id=plan.parent_task_id,
                revision=plan.revision,
                metadata=plan.metadata,
            )
        validation = self._plan_compiler.validate(plan)
        if validation.status in {"validated", "requires_confirmation"}:
            self._plans[plan.plan_id] = (plan, validation)
            self._persist_plan(plan, validation)
        return {
            "plan_id": plan.plan_id,
            "plan_hash": validation.plan_hash,
            "status": validation.status,
            "errors": list(validation.errors),
            "warnings": list(validation.warnings),
            "required_actions": [item.to_dict() for item in validation.required_actions],
            "workflow": validation.workflow.to_dict() if validation.workflow is not None else None,
        }

    async def _tool_workflow_plan_get(self, params: dict[str, Any]) -> dict[str, Any]:
        plan_id = self._text(params, "plan_id")
        stored = self._plans.get(plan_id)
        if stored is None:
            raise ResourceNotFoundError("Unknown workflow plan.", details={"plan_id": plan_id})
        plan, validation = stored
        return {
            "plan": plan.to_dict(),
            "plan_hash": validation.plan_hash,
            "status": validation.status,
            "errors": list(validation.errors),
            "warnings": list(validation.warnings),
            "workflow": validation.workflow.to_dict() if validation.workflow else None,
        }

    async def _tool_workflow_plan_approve(self, params: dict[str, Any]) -> dict[str, Any]:
        plan_id = self._text(params, "plan_id")
        stored = self._plans.get(plan_id)
        if stored is None:
            raise ResourceNotFoundError("Unknown workflow plan.", details={"plan_id": plan_id})
        _plan, validation = stored
        expected_hash = str(params.get("plan_hash") or "").strip()
        if expected_hash and expected_hash != validation.plan_hash:
            raise UnsupportedOperationError("Workflow plan hash does not match the validated plan.")
        if validation.status not in {"validated", "requires_confirmation"}:
            raise UnsupportedOperationError("Only a valid plan can be approved.")
        self._approved_plans.add(plan_id)
        self._persist_plan(_plan, validation, approved=True)
        return {"plan_id": plan_id, "approved": True, "reason": str(params.get("reason") or "")}

    async def _tool_task_replan(self, params: dict[str, Any]) -> dict[str, Any]:
        parent_task_id = self._text(params, "parent_task_id")
        parent = self.desktop.tasks.get(parent_task_id)
        raw = params.get("plan")
        if not isinstance(raw, dict):
            raise UnsupportedOperationError("task.replan requires a plan object.")
        plan_raw = dict(raw)
        plan_raw["parent_task_id"] = parent_task_id
        parent_revision = max(1, int(getattr(parent, "plan_revision", 0) or 1))
        plan_raw.setdefault("revision", parent_revision + 1)
        requested_revision = int(plan_raw.get("revision") or 1)
        if requested_revision <= parent_revision:
            raise UnsupportedOperationError("A replanned task must use a newer plan revision.")
        if requested_revision > self._plan_compiler.MAX_REPLANS + 1:
            raise UnsupportedOperationError("The task replan budget has been exhausted.")
        plan = WorkflowPlan.from_dict(plan_raw)
        if not plan.plan_id:
            plan = WorkflowPlan(
                plan_id=f"plan-{__import__('uuid').uuid4().hex[:12]}",
                objective=plan.objective,
                target=plan.target,
                steps=plan.steps,
                success_criteria=plan.success_criteria,
                budget=plan.budget,
                parent_task_id=parent_task_id,
                revision=plan.revision,
                metadata=plan.metadata,
            )
        validation = self._plan_compiler.validate(plan)
        if validation.status != "validated":
            return {"plan": {"plan_id": plan.plan_id, "status": validation.status, "errors": list(validation.errors), "warnings": list(validation.warnings)}}
        self._plans[plan.plan_id] = (plan, validation)
        self._persist_plan(plan, validation)
        return await self._create_task({"plan_id": plan.plan_id, "plan_hash": validation.plan_hash, "source": "agent"})

    def _persist_plan(self, plan: WorkflowPlan, validation: Any, *, approved: bool = False) -> None:
        if self._plan_store is None:
            return
        self._plan_store.upsert_plan({
            "plan_id": plan.plan_id,
            "status": validation.status,
            "approved": approved or plan.plan_id in self._approved_plans,
            "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "plan": plan.to_dict(),
            "plan_hash": validation.plan_hash,
            "errors": list(validation.errors),
            "warnings": list(validation.warnings),
            "required_actions": [item.to_dict() for item in validation.required_actions],
            "workflow": validation.workflow.to_dict() if validation.workflow else None,
        })

    @staticmethod
    def _restore_plan(payload: dict[str, Any]) -> tuple[WorkflowPlan, Any, bool] | None:
        try:
            from device_tui.application.tasking import (
                Action,
                PlanValidationResult,
                WorkflowDefinition,
            )
            raw_plan = payload.get("plan")
            if not isinstance(raw_plan, dict):
                return None
            plan = WorkflowPlan.from_dict(raw_plan)
            raw_workflow = payload.get("workflow")
            workflow = WorkflowDefinition.from_dict(raw_workflow) if isinstance(raw_workflow, dict) else None
            required = tuple(Action.from_dict(item) for item in payload.get("required_actions", ()) if isinstance(item, dict))
            validation = PlanValidationResult(
                str(payload.get("status") or "rejected"),
                plan,
                str(payload.get("plan_hash") or plan.content_hash()),
                workflow=workflow,
                errors=tuple(dict(item) for item in payload.get("errors", ()) if isinstance(item, dict)),
                warnings=tuple(str(item) for item in payload.get("warnings", ()) if str(item)),
                required_actions=required,
            )
            return plan, validation, bool(payload.get("approved", False))
        except (TypeError, ValueError, KeyError):
            return None

    async def _tool_task_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"task": self._task_payload(self.desktop.tasks.get(self._text(params, "task_id")))}

    async def _get_decision(self, params: dict[str, Any]) -> dict[str, Any]:
        decision = self.desktop.tasks.get_decision(self._text(params, "task_id"))
        return {"decision": decision.to_dict() if decision is not None else None}

    async def _tool_task_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"tasks": [self._task_payload(item) for item in self.desktop.tasks.list(limit=int(params.get("limit") or 200))]}

    async def _tool_task_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"task": self._task_payload(self.desktop.tasks.cancel(self._text(params, "task_id")))}

    async def _tool_task_pause(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"task": self._task_payload(self.desktop.tasks.pause(self._text(params, "task_id")))}

    async def _tool_task_resume(self, params: dict[str, Any]) -> dict[str, Any]:
        context = params.get("context")
        return {"task": self._task_payload(self.desktop.tasks.resume(
            self._text(params, "task_id"),
            context=dict(context) if isinstance(context, dict) else {},
            step_id=str(params.get("step_id") or ""),
        ))}

    async def _tool_task_decision(self, params: dict[str, Any]) -> dict[str, Any]:
        action_value = params.get("action")
        if isinstance(action_value, dict):
            action = Action.from_dict(action_value)
        else:
            action = Action(str(action_value or ""), target_step=str(params.get("target_step") or ""), parameters=dict(params.get("parameters") or {}))
        task_id = self._text(params, "task_id")
        decision = Decision(
            decision_id=str(params.get("decision_id") or f"mcp-{task_id}"),
            actor=DecisionActor(type=str(params.get("actor_type") or "agent"), id=str(params.get("actor_id") or "agent")),
            action=action, reason=str(params.get("reason") or ""), task_id=task_id,
            expected_revision=(int(params["expected_revision"]) if params.get("expected_revision") is not None else None),
        )
        return {"task": self._task_payload(self.desktop.tasks.apply_decision(task_id, decision))}

    async def _tool_decision_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._get_decision(params)

    async def _tool_decision_apply(self, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(params.get("action"), dict):
            raise UnsupportedOperationError("decision.apply requires a structured action object.")
        payload = dict(params)
        payload["actor_type"] = "agent"
        payload.setdefault("actor_id", "agent")
        return await self._tool_task_decision(payload)

    async def _tool_workflow_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        workflows = []
        for descriptor in self.desktop.workflows.list():
            workflow = self.desktop.workflows.preview(descriptor.id)
            workflows.append({
                **descriptor.public_dict(),
                "steps": [
                    {"id": step.id, "kind": step.kind, "action": step.action.name if isinstance(step.action, Action) else str(step.action), "depends_on": list(step.depends_on), "params": dict(step.params), "retry_policy": dict(step.retry_policy)}
                    for step in workflow.steps
                ],
            })
        return {
            "workflows": workflows,
            "capabilities": sorted(self._plan_compiler.registered_capability_specs()),
            "capability_specs": self._plan_compiler.registered_capability_specs(),
            "plan_limits": {
                "max_steps": self._plan_compiler.MAX_STEPS,
                "max_replans": self._plan_compiler.MAX_REPLANS,
            },
        }

    async def _tool_workflow_run(self, params: dict[str, Any]) -> dict[str, Any]:
        """Start a workflow as a Task; the Agent never receives an Engine."""
        return await self._create_task(params)

    async def _tool_tool_execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute an existing diagnostic backend tool, without workflow access."""
        tool_name = str(params.get("name") or params.get("tool") or "").strip().replace(".", "_")
        allowed = {"terminal_run", "terminal_execute", "terminal_execute_batch", "terminal_interact", "terminal_read", "file_transfer_list", "execution_get"}
        if tool_name not in allowed:
            raise UnsupportedOperationError(f"tool.execute only allows diagnostic tools: {', '.join(sorted(allowed))}")
        handler = getattr(self, f"_tool_{tool_name}", None)
        if not callable(handler):
            raise UnsupportedOperationError(f"Unknown diagnostic tool: {tool_name}")
        nested = params.get("params")
        payload = dict(nested) if isinstance(nested, dict) else {key: value for key, value in params.items() if key not in {"name", "tool", "params"}}
        return await handler(payload)

    async def _tool_session_open(self, params: dict[str, Any]) -> dict[str, Any]:
        session, reused = await self._open_or_reuse(self._text(params, "device_id"), "auto")
        return {"session": self._session_payload(session), "reused": reused}

    async def _tool_session_list(self, params: dict[str, Any]) -> dict[str, Any]:
        device_id = str(params.get("device_id") or "")
        sessions = [self._session_payload(item) for item in self.desktop.sessions.list_sessions()]
        if device_id:
            sessions = [item for item in sessions if item["device_id"] == device_id]
        return {"sessions": sessions}

    async def _tool_session_manage(self, params: dict[str, Any]) -> dict[str, Any]:
        action = self._text(params, "action").casefold()
        protocol = str(params.get("protocol") or "auto").casefold()
        if protocol not in {"auto", "ssh", "telnet", "serial", "simulated"}:
            raise UnsupportedOperationError("protocol must be one of auto, ssh, telnet, serial, simulated.")
        device_id = str(params.get("device_id") or "")
        session_id = str(params.get("session_id") or "")
        if action == "open":
            session, reused = await self._open_or_reuse(device_id, protocol)
            return {"session": self._session_payload(session), "reused": reused}
        session = self._resolve_session(session_id=session_id, device_id=device_id)
        if action == "status":
            return {"session": self._session_payload(session)}
        if action == "reconnect":
            updated = await self.desktop.control.reconnect_session(
                DeviceTarget(device_id=session.device_id, session_id=session.id),
                context=ControlContext(source="mcp"),
            )
            return {"session": self._session_view_payload(updated)}
        if action == "disconnect":
            self.desktop.tasks.cancel_session(session.id)
            self.desktop.transfers.cancel_session(session.id)
            updated = await self.desktop.control.disconnect_session(
                DeviceTarget(device_id=session.device_id, session_id=session.id),
                context=ControlContext(source="mcp"),
            )
            return {"session": self._session_view_payload(updated)}
        if action == "close":
            self.desktop.automation.cancel_session(session.id, reason="mcp_close")
            self.desktop.tasks.cancel_session(session.id)
            self.desktop.transfers.cancel_session(session.id)
            await self.desktop.control.close_session(
                DeviceTarget(device_id=session.device_id, session_id=session.id),
                context=ControlContext(source="mcp"),
            )
            return {"session_id": session.id, "closed": True}
        raise UnsupportedOperationError(f"Unsupported session action: {action}")

    async def _tool_terminal_run(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=bool(params.get("ensure_session", True)))
        result = await self.ai.run_terminal_batch(
            self._commands(params),
            session_id=session.id,
            command_timeout_seconds=int(params.get("command_timeout_seconds") or 30),
            total_timeout_seconds=params.get("total_timeout_seconds"),
            max_output_chars=int(params.get("max_output_chars_per_step") or 16_384),
            source="mcp",
            kind="terminal_run",
        )
        return self._execution_payload(result)

    async def _tool_terminal_execute(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        result = await self.ai.run_terminal_batch(
            [self._text(params, "command")],
            session_id=session.id,
            command_timeout_seconds=int(params.get("timeout_seconds") or 30),
            total_timeout_seconds=int(params.get("timeout_seconds") or 30) + 5,
            max_output_chars=int(params.get("max_output_chars") or 16_384),
            source="mcp",
            kind="terminal_execute",
        )
        payload = self._execution_payload(result)
        payload["output"] = self.ai._result_output(result)
        payload["completion_reason"] = "prompt" if result.get("status") == "completed" else str(result.get("status") or "failed")
        return payload

    async def _tool_terminal_execute_batch(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        result = await self.ai.run_terminal_batch(
            self._commands(params),
            session_id=session.id,
            command_timeout_seconds=int(params.get("command_timeout_seconds") or 30),
            total_timeout_seconds=params.get("total_timeout_seconds"),
            max_output_chars=int(params.get("max_output_chars_per_step") or 16_384),
            source="mcp",
            kind="terminal_execute_batch",
        )
        return self._execution_payload(result)

    async def _tool_terminal_interact(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        steps = params.get("steps")
        if not isinstance(steps, list):
            raise UnsupportedOperationError("Terminal interaction steps must be a list.")
        result = await self.ai.run_terminal_plan(
            session_id=session.id,
            steps=steps,
            total_timeout_seconds=int(params.get("total_timeout_seconds") or 60),
            source="mcp",
            kind="terminal_interact",
        )
        return self._execution_payload(result)

    async def _tool_terminal_send_command(self, params: dict[str, Any]) -> dict[str, Any]:
        device_id = self._text(params, "device_id")
        session, _ = await self._open_or_reuse(device_id, "auto")
        command = self._text(params, "command")
        result = await self.desktop.control.send_raw(
            DeviceTarget(device_id=device_id, session_id=session.id),
            command,
            context=ControlContext(source="mcp"),
        )
        self.desktop.commands.record_for_session(session.id, command)
        return {
            "session_id": result.session_id,
            "device_id": result.device_id,
            "command": command,
            "sent": result.sent,
        }

    async def _tool_terminal_read(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        log = self.desktop.sessions.read_log(session.id, int(params.get("max_chars") or 4096))
        return {"session_id": session.id, "device_id": session.device_id, "output": log.content, "truncated": log.truncated}

    async def _tool_execution_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._execution_payload(
            self.desktop.control.get_execution(self._text(params, "execution_id"))
        )

    async def _tool_execution_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._execution_payload(
            self.desktop.control.cancel_execution(self._text(params, "execution_id"))
        )

    async def _tool_file_transfer_list(self, params: dict[str, Any]) -> dict[str, Any]:
        catalog = self.desktop.transfers.list_files(
            relative_path=str(params.get("path") or ""),
            recursive=bool(params.get("recursive", True)),
            limit=int(params.get("limit") or 200),
        )
        return {"files": [item.public_dict() for item in catalog.files], "truncated": catalog.truncated}

    async def _tool_file_transfer_start(self, params: dict[str, Any]) -> dict[str, Any]:
        device_id = self._text(params, "device_id")
        session, _ = await self._open_or_reuse(device_id, "auto")
        operation = self.desktop.control.transfer(
            DeviceTarget(device_id=device_id, session_id=session.id),
            TransferRequest(
                direction="upload",
                source_path=self._text(params, "source_path"),
                destination_path=self._text(params, "destination_path"),
                overwrite=bool(params.get("overwrite", False)),
            ),
            context=ControlContext(source="mcp"),
        )
        return {"operation_id": operation.operation_id, "operation": self._operation_view_payload(operation)}

    async def _tool_package_upgrade_start(self, params: dict[str, Any]) -> dict[str, Any]:
        session, _ = await self._open_or_reuse(self._text(params, "device_id"), "auto")
        packages = [item for item in self.desktop.transfers.list_files(limit=1_000).files if item.name.casefold().endswith(".cc")]
        if not packages:
            raise UnsupportedOperationError("No .cc package is available in the managed transfer root.")
        workflow = self.desktop.workflows.build(
            "device_upgrade",
            WorkflowTarget(device_id=session.device_id, session_id=session.id),
            {"package_path": packages[0].relative_path},
        )
        task = self.desktop.tasks.create(TaskCreate(
            workflow=workflow,
            target=DeviceTarget(device_id=session.device_id, session_id=session.id),
            source="mcp",
        ))
        return {"task_id": task.id, "task": task.to_dict()}

    async def _tool_operation_get(self, params: dict[str, Any]) -> dict[str, Any]:
        operation = self.desktop.control.get_operation(self._text(params, "operation_id"))
        return {"operation": self._operation_view_payload(operation)}

    async def _tool_operation_wait(self, params: dict[str, Any]) -> dict[str, Any]:
        operation_id = self._text(params, "operation_id")
        revision = int(params.get("since_revision") or 0)
        deadline = asyncio.get_running_loop().time() + min(60, max(0, int(params.get("timeout_seconds") or 60)))
        while True:
            operation = self.desktop.control.get_operation(operation_id)
            if operation.status in {"completed", "failed", "cancelled"} or operation.revision > revision or asyncio.get_running_loop().time() >= deadline:
                return {"operation": self._operation_view_payload(operation)}
            await asyncio.sleep(0.1)

    async def _tool_operation_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        if not bool(params.get("confirm", False)):
            raise UnsupportedOperationError("operation.cancel requires confirm=true.")
        operation = self.desktop.control.cancel_operation(self._text(params, "operation_id"))
        return {"operation": self._operation_view_payload(operation)}

    async def _tool_ai_create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._tool_session_open(params)

    async def _tool_ai_execute_command(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        return await self.ai.execute_command(self._text(params, "command"), session_id=session.id, source="mcp", idempotency_key=self._optional_text(params, "idempotency_key"))

    async def _tool_ai_execute_batch(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        return await self.ai.execute_batch(self._commands(params), session_id=session.id, command_timeout_seconds=int(params.get("command_timeout_seconds") or 30), source="mcp", idempotency_key=self._optional_text(params, "idempotency_key"))

    async def _tool_ai_execute_script(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        return await self.ai.execute_script(self._text(params, "script"), session_id=session.id, timeout_seconds=int(params.get("timeout_seconds") or 30), source="mcp", idempotency_key=self._optional_text(params, "idempotency_key"))

    async def _tool_ai_upload_file(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._tool_file_transfer_start(params)

    async def _tool_ai_download_file(self, params: dict[str, Any]) -> dict[str, Any]:
        device_id = self._text(params, "device_id")
        session, _ = await self._open_or_reuse(device_id, "auto")
        operation = self.desktop.control.transfer(
            DeviceTarget(device_id=device_id, session_id=session.id),
            TransferRequest(
                direction="download",
                source_path=self._text(params, "source_path"),
                destination_path=self._text(params, "destination_path"),
                overwrite=False,
            ),
            context=ControlContext(source="mcp"),
        )
        return {"operation_id": operation.operation_id, "operation": self._operation_view_payload(operation)}

    async def _tool_ai_get_result(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.ai.get_result(self._text(params, "result_id"), include_raw=bool(params.get("include_raw", False)))

    async def _tool_ai_run_skill(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        raw_params = params.get("params")
        if not isinstance(raw_params, dict):
            raise UnsupportedOperationError("Skill params must be an object.")
        return await self.ai.run_skill(self._text(params, "skill_name"), raw_params, session_id=session.id, source="mcp", idempotency_key=self._optional_text(params, "idempotency_key"))

    async def _tool_ai_list_skills(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"skills": self.ai.list_skills()}

    async def _tool_approval_get(self, _params: dict[str, Any]) -> dict[str, Any]:
        raise UnsupportedOperationError("AI approval is disabled by policy.")

    async def _terminal_target(self, params: dict[str, Any], *, ensure: bool) -> Any:
        session_id = self._optional_text(params, "session_id")
        device_id = self._optional_text(params, "device_id")
        if session_id:
            return self._resolve_session(session_id=session_id)
        if not device_id:
            raise UnsupportedOperationError("A session_id or device_id is required.")
        if ensure:
            return (await self._open_or_reuse(device_id, str(params.get("protocol") or "auto")))[0]
        return self._resolve_session(device_id=device_id)

    async def _open_or_reuse(self, device_id: str, protocol: str) -> tuple[Any, bool]:
        view = await self.desktop.control.open_session(
            DeviceTarget(device_id=device_id, protocol=protocol),
            reuse=True,
            context=ControlContext(source="mcp"),
        )
        session = next(
            (item for item in self.desktop.sessions.list_sessions() if item.id == view.session_id),
            None,
        )
        if session is None:
            raise ResourceNotFoundError("Session disappeared after opening", details={"session_id": view.session_id})
        return session, view.reused

    def _resolve_session(self, *, session_id: str = "", device_id: str = "") -> Any:
        sessions = self.desktop.sessions.list_sessions()
        if session_id:
            session = next((item for item in sessions if item.id == session_id), None)
            if session is None:
                raise ResourceNotFoundError("Unknown session", details={"session_id": session_id})
            if device_id and session.device_id != device_id:
                raise UnsupportedOperationError(
                    "session_id does not belong to device_id.",
                    details={"session_id": session_id, "session_device_id": session.device_id, "device_id": device_id},
                )
            return session
        candidates = [item for item in sessions if item.device_id == device_id]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise UnsupportedOperationError(
                "Multiple sessions exist for device_id; session_id is required.",
                details={"device_id": device_id, "session_ids": [item.id for item in candidates]},
            )
        raise ResourceNotFoundError("Unknown session", details={"device_id": device_id})

    @staticmethod
    def _protocol_for(device: Any) -> str:
        if str(device.device_type).casefold().startswith("mock"):
            return "simulated"
        if device.ssh_endpoint:
            return "ssh"
        if device.telnet_endpoint:
            return "telnet"
        if device.serial_endpoint:
            return "serial"
        return "simulated"

    @staticmethod
    def _device_payload(device: Any) -> dict[str, Any]:
        payload = asdict(device)
        payload["protocols"] = [kind for kind, endpoint in (("ssh", device.ssh_endpoint), ("telnet", device.telnet_endpoint), ("serial", device.serial_endpoint)) if endpoint]
        if str(device.device_type).casefold().startswith("mock"):
            payload["protocols"] = ["simulated"]
        return payload

    @staticmethod
    def _task_payload(record: Any) -> dict[str, Any]:
        payload = asdict(record)
        if payload.get("result") is not None:
            payload["result"] = asdict(record.result)
        return payload

    @staticmethod
    def _session_payload(session: Any) -> dict[str, Any]:
        payload = asdict(session)
        payload["session_id"] = session.id
        return payload

    @staticmethod
    def _session_view_payload(session: Any) -> dict[str, Any]:
        payload = asdict(session)
        payload["session_id"] = session.session_id
        payload["id"] = session.session_id
        payload["kind"] = session.protocol
        return payload

    @staticmethod
    def _operation_view_payload(operation: Any) -> dict[str, Any]:
        payload = asdict(operation)
        payload.setdefault("id", getattr(operation, "operation_id", ""))
        payload.setdefault("direction", "")
        payload.setdefault("bytes_transferred", 0)
        payload.setdefault("total_bytes", 0)
        payload.setdefault("bytes_per_second", 0)
        payload.setdefault("eta_seconds", None)
        payload.setdefault("queue_position", None)
        payload.setdefault("retry_of", None)
        payload.setdefault("cancellable", True)
        payload.setdefault("revision", 0)
        payload.setdefault("created_at", "")
        payload.setdefault("updated_at", "")
        return payload

    @staticmethod
    def _execution_payload(result: dict[str, Any]) -> dict[str, Any]:
        payload = dict(result)
        payload["timing"] = {"total_ms": payload.get("duration_ms", 0)}
        return payload

    def _require_source_service(self) -> Any:
        if self.source_service is None:
            raise UnsupportedOperationError("Device source control is unavailable in this application instance.")
        return self.source_service

    @staticmethod
    def _source_status_payload(service: Any) -> dict[str, Any]:
        metadata = service.imported_store.imported_device_metadata()
        return {
            "active_source": service.active_source,
            "default_source": service.default_source,
            "source_ids": list(service.source_ids()),
            "product_mode": service.product_profile.mode,
            "source_locked": service.product_profile.source_locked,
            "allow_source_switch": service.product_profile.allow_source_switch,
            "allow_plugin_management": service.product_profile.allow_plugin_management,
            "allow_import": service.product_profile.allow_import,
            "imported": {
                "count": metadata.row_count,
                "source_name": metadata.source_name,
                "sheet_name": metadata.sheet_name,
                "imported_at": metadata.imported_at,
            },
        }

    @staticmethod
    def _profile_payload(profile: Any) -> dict[str, Any]:
        def endpoint(value: Any) -> dict[str, Any]:
            return {"host": value.host, "port": value.port, "username": value.username}
        return {
            "id": profile.id,
            "profile_type": profile.profile_type,
            "name": profile.name,
            "group": profile.group,
            "notes": profile.notes,
            "preferred_protocol": profile.preferred_protocol,
            "telnet": endpoint(profile.telnet),
            "ssh": endpoint(profile.ssh),
            "serial": endpoint(profile.serial),
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    @staticmethod
    def _profile_draft(params: dict[str, Any]) -> ConnectionProfileDraft:
        def endpoint(name: str, default_port: int) -> ProfileEndpoint:
            raw = params.get(name)
            value = raw if isinstance(raw, dict) else {}
            return ProfileEndpoint(
                host=str(value.get("host") or ""),
                port=int(value.get("port") or default_port),
                username=str(value.get("username") or ""),
            )
        profile_type = str(params.get("profile_type") or "server")
        if profile_type not in {"temporary", "server"}:
            raise UnsupportedOperationError("profile_type must be temporary or server")
        preferred = str(params.get("preferred_protocol") or "ssh")
        if preferred not in {"simulated", "ssh", "telnet", "serial"}:
            raise UnsupportedOperationError("Unsupported preferred_protocol")
        return ConnectionProfileDraft(
            profile_type=profile_type,  # type: ignore[arg-type]
            profile_id=str(params.get("profile_id") or ""),
            name=str(params.get("name") or ""),
            group=str(params.get("group") or ""),
            notes=str(params.get("notes") or ""),
            preferred_protocol=preferred,  # type: ignore[arg-type]
            telnet=endpoint("telnet", 23),
            ssh=endpoint("ssh", 22),
            serial=endpoint("serial", 23),
            passwords={
                protocol: params[f"{protocol}_password"]
                for protocol in ("telnet", "ssh", "serial")
                if f"{protocol}_password" in params
            },
        )

    def _automation_rule_payload(self, record: Any) -> dict[str, Any]:
        return {
            "id": record.id,
            "rule": self.desktop.automation.serialize_rule(
                self.desktop.automation.public_rule(record)
            ),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    @staticmethod
    def _text(params: dict[str, Any], name: str) -> str:
        value = str(params.get(name) or "").strip()
        if not value:
            raise UnsupportedOperationError(f"{name} is required.")
        return value

    @staticmethod
    def _optional_text(params: dict[str, Any], name: str) -> str:
        return str(params.get(name) or "").strip()

    @staticmethod
    def _commands(params: dict[str, Any]) -> list[str]:
        commands = params.get("commands")
        if not isinstance(commands, list) or not commands:
            raise UnsupportedOperationError("commands must contain at least one entry.")
        return [str(item) for item in commands]

    @staticmethod
    def _success(data: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "message": "ok", "data": data, "approval": None, "error": None}

    @staticmethod
    def _error(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        return status, {"ok": False, "message": message, "data": {}, "approval": None, "error": {"code": code, "message": message, "details": details or {}}}
