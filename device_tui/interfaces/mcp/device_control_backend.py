"""Adapter from the legacy MCP action protocol to DeviceControlService.

The MCP service is intentionally synchronous for compatibility.  This adapter
keeps that protocol stable while making DeviceControlService the only device
operation boundary used by new callers.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import threading
from typing import Any

from device_tui.application import (
    CommandRequest,
    ControlContext,
    DeviceTarget,
    DesktopApplication,
    TaskCreate,
    TransferRequest,
    WorkflowTarget,
)
from device_tui.application.ai.gateway.service import GatewayService
from device_tui.application.ai.operations import AiDeviceAction, AiDeviceToolResult
from device_tui.application.errors import ApplicationError
from device_tui.framework.errors import ResourceConflictError
from .core import AppControlBackend


class DeviceControlAppBackend(AppControlBackend):
    """Synchronous legacy-MCP adapter backed by the unified control facade."""

    def __init__(self, desktop: DesktopApplication, gateway: GatewayService | None = None) -> None:
        self.desktop = desktop
        self._gateway = gateway or GatewayService()
        self._selected_device_id = ""

    def execute_ai_device_action(
        self,
        action: AiDeviceAction,
        *,
        approved: bool = False,
    ) -> AiDeviceToolResult:
        del approved
        try:
            data = self._execute(action)
            return AiDeviceToolResult(action, ok=True, message="设备动作执行完成。", data=data)
        except (ApplicationError, ResourceConflictError) as exc:
            return AiDeviceToolResult(
                action,
                ok=False,
                message=exc.message,
                error_code=exc.code,
                http_status=409 if exc.code == "conflict" else 400,
                data=dict(exc.details),
            )
        except Exception as exc:
            return AiDeviceToolResult(
                action,
                ok=False,
                message=str(exc),
                error_code="device_control_failed",
                http_status=400,
            )

    def gateway_service(self) -> GatewayService:
        return self._gateway

    def gateway_script_style(self, device_id: str) -> str:
        device = self.desktop.devices.require_device(device_id)
        return "linux" if str(getattr(device, "device_type", "")).casefold() in {"linux", "unix"} else "network"

    def _execute(self, action: AiDeviceAction) -> dict[str, Any]:
        kind = action.kind
        params = action.params
        if kind == "system_status":
            return {
                "status": "ready",
                "sessions": [asdict(item) for item in self.desktop.sessions.list_sessions()],
                "operations": [asdict(item) for item in self.desktop.control.list_operations(limit=50)],
            }
        if kind == "list_devices":
            inventory = self.desktop.devices.list_inventory()
            return {"current_user": inventory.current_user, "devices": [asdict(item) for item in inventory.devices]}
        if kind == "device_get":
            return {"device": asdict(self.desktop.devices.require_device(action.device_id))}
        if kind == "select_device":
            device = self.desktop.devices.require_device(action.device_id)
            self._selected_device_id = device.id
            return {"selected_device_id": device.id, "device": asdict(device)}
        if kind == "session_list":
            device_id = str(params.get("device_id") or action.device_id)
            sessions = [item for item in self.desktop.sessions.list_sessions() if not device_id or item.device_id == device_id]
            return {"sessions": [asdict(item) for item in sessions]}
        if kind == "list_managed_transfer_files":
            catalog = self.desktop.transfers.list_files(
                relative_path=str(params.get("path") or ""),
                recursive=bool(params.get("recursive", True)),
                limit=int(params.get("limit") or 200),
            )
            return {"files": [item.public_dict() for item in catalog.files], "truncated": catalog.truncated}
        if kind == "open_session":
            protocol = str(params.get("protocol") or "auto").casefold()
            view = self._run(self.desktop.control.open_session(
                DeviceTarget(device_id=action.device_id, protocol=protocol),
                reuse=True,
                context=ControlContext(source="stdio-mcp"),
            ))
            return {"session": asdict(view), "reused": view.reused}
        if kind == "session_manage":
            operation = str(params.get("action") or "status")
            target = DeviceTarget(device_id=action.device_id, session_id=str(params.get("session_id") or ""), protocol=str(params.get("protocol") or "auto"))
            if operation == "open":
                view = self._run(self.desktop.control.open_session(target, reuse=True, context=ControlContext(source="stdio-mcp")))
            elif operation == "reconnect":
                view = self._run(self.desktop.control.reconnect_session(target, context=ControlContext(source="stdio-mcp")))
            elif operation == "disconnect":
                view = self._run(self.desktop.control.disconnect_session(target, context=ControlContext(source="stdio-mcp")))
            elif operation == "close":
                self._run(self.desktop.control.close_session(target, context=ControlContext(source="stdio-mcp")))
                return {"session_id": target.session_id, "closed": True}
            else:
                view = self._session_view(target)
            return {"session": asdict(view), "reused": view.reused}
        if kind in {"send_command", "terminal_send_command"}:
            session = self._session_record(action.device_id, str(params.get("session_id") or ""), ensure=True)
            result = self._run(self.desktop.control.send_raw(
                DeviceTarget(device_id=session.device_id, session_id=session.id),
                action.command,
                context=ControlContext(source="stdio-mcp"),
            ))
            self.desktop.commands.record_for_session(session.id, action.command)
            return {"session_id": result.session_id, "device_id": result.device_id, "sent": result.sent, "command": action.command}
        if kind in {"terminal_plan_start", "terminal_execute_start"}:
            session = self._session_record(action.device_id, str(params.get("session_id") or ""), ensure=True)
            commands = tuple(str(item) for item in params.get("commands", []) if str(item).strip())
            request = CommandRequest(
                mode="interactive" if params.get("plan_kind") == "interactive" else "batch",
                commands=commands or ((action.command,) if action.command else ()),
                steps=tuple(item for item in params.get("steps", []) if isinstance(item, dict)),
                timeout_seconds=int(params.get("command_timeout_seconds") or params.get("timeout_seconds") or 30),
                total_timeout_seconds=params.get("total_timeout_seconds"),
                max_output_chars=int(params.get("max_output_chars_per_step") or params.get("max_output_chars") or 16_384),
            )
            result = self._run(self.desktop.control.execute(DeviceTarget(device_id=session.device_id, session_id=session.id), request, context=ControlContext(source="stdio-mcp")))
            return dict(result.data)
        if kind == "terminal_execution_get":
            return self.desktop.control.get_execution(str(params.get("execution_id") or ""))
        if kind == "terminal_execution_cancel":
            return self.desktop.control.cancel_execution(str(params.get("execution_id") or ""))
        if kind == "read_terminal":
            session = self._session_record(action.device_id, str(params.get("session_id") or ""), ensure=True)
            log = self.desktop.sessions.read_log(session.id, int(params.get("max_chars") or 4_096))
            return {"session_id": session.id, "device_id": session.device_id, "output": log.content, "truncated": log.truncated}
        if kind in {"start_managed_file_transfer", "ai_gateway_upload_file", "ai_gateway_download_file"}:
            session = self._session_record(action.device_id, str(params.get("session_id") or ""), ensure=True)
            direction = "download" if kind.endswith("download_file") else "upload"
            task_run, operation_id = self._run(self.desktop.task_service.start_file_transfer(
                device_id=session.device_id,
                session_id=session.id,
                direction=direction,
                source_path=str(params.get("source_path") or ""),
                destination_path=str(params.get("destination_path") or ""),
                overwrite=bool(params.get("overwrite", False)),
                protocol=str(params.get("protocol") or "auto"),
                context={"source": "stdio-mcp"},
            ))
            self.desktop.operations.update(
                operation_id,
                data={"task_run_id": task_run.id, "task_plan_id": task_run.plan_id},
            )
            operation = self.desktop.control.get_operation(operation_id)
            payload = asdict(operation)
            payload["task_run_id"] = task_run.id
            payload["task_plan_id"] = task_run.plan_id
            return payload
        if kind == "run_package_upgrade":
            protocol = str(params.get("protocol") or "telnet").casefold()
            session = self._session_record(
                action.device_id,
                str(params.get("session_id") or ""),
                ensure=True,
                protocol=protocol,
            )
            package_path = str(params.get("package_path") or "")
            if not package_path:
                packages = [
                    item for item in self.desktop.transfers.list_files(limit=1_000).files
                    if item.name.casefold().endswith(".cc")
                ]
                if packages:
                    package_path = packages[0].relative_path
            workflow = self.desktop.workflows.build(
                "device_upgrade",
                WorkflowTarget(device_id=session.device_id, session_id=session.id, protocol=session.kind),
                {"package_path": package_path},
            )
            task = self.desktop.task_service.create(TaskCreate(
                workflow=workflow,
                target=DeviceTarget(device_id=session.device_id, session_id=session.id, protocol=session.kind),
                source="stdio-mcp",
            ))
            return {"task_id": task.id, "task": asdict(task)}
        if kind == "get_managed_file_transfer":
            operation_id = str(params.get("operation_id") or "")
            return asdict(self.desktop.control.get_operation(operation_id))
        if kind == "cancel_managed_file_transfer":
            operation_id = str(params.get("operation_id") or "")
            return asdict(self.desktop.control.cancel_operation(operation_id))
        raise ValueError(f"Unsupported DeviceControl action: {kind}")

    def _session_record(
        self,
        device_id: str,
        session_id: str,
        *,
        ensure: bool = False,
        protocol: str = "auto",
    ):
        sessions = self.desktop.sessions.list_sessions()
        if session_id:
            session = next((item for item in sessions if item.id == session_id), None)
            if session is None:
                raise ValueError("Unknown session")
            if device_id and session.device_id != device_id:
                raise ValueError("session_id does not belong to device_id")
            return session
        if not device_id:
            raise ValueError("device_id or session_id is required")
        candidates = [item for item in sessions if item.device_id == device_id]
        if len(candidates) == 1:
            return candidates[0]
        if ensure:
            view = self._run(self.desktop.control.open_session(
                DeviceTarget(device_id=device_id, protocol=protocol),
                reuse=True,
                context=ControlContext(source="stdio-mcp"),
            ))
            return next(item for item in self.desktop.sessions.list_sessions() if item.id == view.session_id)
        if len(candidates) > 1:
            raise ValueError("Multiple sessions exist for device_id; session_id is required")
        raise ValueError("Unknown session")

    def _session_view(self, target: DeviceTarget):
        session = self._session_record(target.device_id, target.session_id)
        from device_tui.application.device_control.models import SessionView
        return SessionView(session.id, session.device_id, session.kind, session.status, session.title, session.sequence, session.generation)

    def _run(self, awaitable):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        result: list[Any] = []
        failure: list[BaseException] = []

        def runner() -> None:
            try:
                result.append(asyncio.run(awaitable))
            except BaseException as exc:  # propagate the original application error
                failure.append(exc)

        thread = threading.Thread(target=runner, name="device-control-sync-bridge")
        thread.start()
        thread.join()
        if failure:
            raise failure[0]
        return result[0]
