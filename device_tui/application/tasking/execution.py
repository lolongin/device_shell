"""Workflow execution tools backed by the unified DeviceControlService."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from device_tui.application.device_control import (
    CommandRequest,
    ControlContext,
    DeviceControlService,
    DeviceTarget,
    TransferRequest,
)
from device_tui.application.errors import UnsupportedOperationError
from device_tui.application.upgrades.commands import HuaweiVrpCommandSet

from .models import WorkflowStep


class ExecutionTool(Protocol):
    async def execute(
        self,
        target: DeviceTarget,
        step: WorkflowStep,
        *,
        context: ControlContext,
    ) -> dict[str, Any]: ...


class DeviceWorkflowExecutionError(RuntimeError):
    """Structured failure returned by a DeviceControlService workflow step."""

    def __init__(self, code: str, message: str, *, error_class: str = "unknown", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.error_class = error_class
        self.retryable = retryable


class DeviceExecutionTool:
    """Translate workflow actions into DeviceControlService calls."""

    def __init__(self, control: DeviceControlService) -> None:
        self._control = control

    async def execute(
        self,
        target: DeviceTarget,
        step: WorkflowStep,
        *,
        context: ControlContext,
    ) -> dict[str, Any]:
        params = step.params
        action = (step.action or step.kind).casefold()
        if action in {"precheck", "backup", "verify", "activate", "verify_version", "validation"}:
            commands = params.get("commands")
            if not isinstance(commands, (list, tuple)):
                commands = (str(params.get("command") or self._default_command(action, params)),)
            result = await self._control.execute(
                target,
                CommandRequest(
                    commands=tuple(str(item) for item in commands),
                    mode=str(params.get("mode") or "batch"),
                    timeout_seconds=int(params.get("timeout_seconds") or 30),
                    total_timeout_seconds=params.get("total_timeout_seconds"),
                    max_output_chars=int(params.get("max_output_chars") or 16_384),
                    steps=tuple(item for item in params.get("steps", []) if isinstance(item, dict)),
                ),
                context=context,
            )
            self._notify(context, "execution", result.execution_id)
            self._raise_for_failed_result(result.status, result.error_code, result.output or "Device command failed.")
            expected = str(params.get("expected_version") or "")
            if action == "verify_version" and expected and expected not in result.output:
                raise DeviceWorkflowExecutionError("version_mismatch", f"Expected version {expected!r} was not observed.")
            return {
                **dict(result.data),
                "output": result.output,
                "status": result.status,
                "execution_id": result.execution_id,
                "evidence": ({"kind": "terminal_execution", "execution_id": result.execution_id, "steps": list(result.steps)},),
            }
        if action == "upload":
            package = str(params.get("source_path") or params.get("package") or "")
            destination = str(params.get("destination_path") or "")
            if not package or not destination:
                raise DeviceWorkflowExecutionError("upload_invalid", "Upload source and destination are required.")
            operation = self._control.transfer(
                target,
                TransferRequest(
                    direction="upload", source_path=package, destination_path=destination,
                    overwrite=bool(params.get("overwrite", False)),
                    command_mode=str(params.get("command_mode") or "vrp"),
                    interaction_profile={
                        str(key): str(value)
                        for key, value in dict(params.get("interaction_profile") or {}).items()
                    },
                ),
                context=context,
            )
            self._notify(context, "operation", operation.operation_id)
            return await self._wait_operation(operation.operation_id, timeout_seconds=int(params.get("timeout_seconds") or 300))
        if action == "wait_online":
            recovery_protocol = str(params.get("recovery_protocol") or "").strip().casefold()
            recovery_target = target
            if recovery_protocol and recovery_protocol != "same":
                recovery_target = DeviceTarget(
                    device_id=target.device_id,
                    protocol=recovery_protocol,
                )
            timeout = max(1, min(int(params.get("timeout_seconds") or 180), 3_600))
            deadline = asyncio.get_running_loop().time() + timeout
            view = await self._control.open_session(recovery_target, reuse=True, context=context)
            # A newly created or reconnected session is returned before its
            # transport handshake finishes. Keep polling that same session;
            # otherwise every retry creates another connection and the task
            # eventually reports a misleading signal/online timeout.
            while str(view.status).casefold() not in {"connected", "ready", "open"}:
                if asyncio.get_running_loop().time() >= deadline:
                    raise DeviceWorkflowExecutionError(
                        "device_offline",
                        "Device did not return online before the recovery timeout.",
                        error_class="transient",
                        retryable=True,
                    )
                await asyncio.sleep(0.2)
                view = await self._control.open_session(
                    DeviceTarget(session_id=view.session_id),
                    reuse=True,
                    context=context,
                )
            return {
                "session_id": view.session_id,
                "device_id": view.device_id,
                "status": view.status,
                "recovery_protocol": recovery_protocol if recovery_protocol and recovery_protocol != "same" else view.protocol,
            }
        if action in {"command", "execute", "batch"}:
            mode = str(params.get("mode") or "batch").casefold()
            commands = params.get("commands")
            if not isinstance(commands, (list, tuple)):
                commands = (str(params.get("command") or ""),)
            if mode != "interactive" and (not commands or not any(str(item).strip() for item in commands)):
                raise UnsupportedOperationError("Command execution requires a non-empty command.")
            result = await self._control.execute(
                target,
                CommandRequest(
                    commands=tuple(str(item) for item in commands),
                    mode=mode,
                    timeout_seconds=int(params.get("timeout_seconds") or 30),
                    total_timeout_seconds=params.get("total_timeout_seconds"),
                    max_output_chars=int(params.get("max_output_chars") or 16_384),
                    steps=tuple(item for item in params.get("steps", []) if isinstance(item, dict)),
                ),
                context=context,
            )
            self._notify(context, "execution", result.execution_id)
            self._raise_for_failed_result(result.status, result.error_code, result.output or "Device command failed.")
            return {
                **dict(result.data),
                "output": result.output,
                "status": result.status,
                "execution_id": result.execution_id,
                "evidence": ({"kind": "terminal_execution", "execution_id": result.execution_id, "steps": list(result.steps)},),
            }
        if action in {"send", "raw", "send_raw"}:
            text = str(params.get("text") or params.get("command") or "")
            if not text.strip():
                raise UnsupportedOperationError("Raw command text cannot be empty.")
            result = await self._control.send_raw(
                target,
                text,
                context=context,
            )
            return {"session_id": result.session_id, "device_id": result.device_id, "sent": result.sent}
        if action == "reboot":
            result = await self._control.reboot(
                target,
                timeout_seconds=int(params.get("timeout_seconds") or 190),
                steps=tuple(item for item in params.get("steps", []) if isinstance(item, dict)),
                context=context,
            )
            self._raise_for_failed_result(result.status, result.error_code, result.output or "Reboot failed.")
            return dict(result.data)
        if action == "power_off":
            result = self._control.power_off(target.device_id, context=context)
            return {"device_id": target.device_id, "status": result.status, "message": result.message}
        if action in {"upload", "download", "transfer"}:
            direction = str(params.get("direction") or ("upload" if action != "download" else "download"))
            source_path = str(params.get("source_path") or "")
            destination_path = str(params.get("destination_path") or "")
            if not source_path.strip() or not destination_path.strip():
                raise UnsupportedOperationError("Transfer source_path and destination_path are required.")
            operation = self._control.transfer(
                target,
                TransferRequest(
                    direction=direction,
                    source_path=source_path,
                    destination_path=destination_path,
                    overwrite=bool(params.get("overwrite", False)),
                    command_mode=str(params.get("command_mode") or "vrp"),
                    interaction_profile={
                        str(key): str(value)
                        for key, value in dict(params.get("interaction_profile") or {}).items()
                    },
                ),
                context=context,
            )
            self._notify(context, "operation", operation.operation_id)
            return {
                "operation_id": operation.operation_id,
                "status": operation.status,
                "data": operation.data,
                "evidence": (self._operation_evidence(operation),),
            }
        if action in {"operation_wait", "wait_operation"}:
            operation_id = str(params.get("operation_id") or "")
            if not operation_id:
                raise UnsupportedOperationError("operation_wait requires operation_id.")
            operation = await self._wait_operation(
                operation_id,
                timeout_seconds=int(params.get("timeout_seconds") or 900),
            )
            return {
                "operation_id": operation_id,
                "operation": operation,
                "evidence": ({"kind": "operation", **operation},),
            }
        raise ValueError(f"Unsupported workflow action: {step.action or step.kind}")

    @staticmethod
    def _notify(context: ControlContext, kind: str, resource_id: str) -> None:
        callback = context.operation_callback
        if callback is not None and str(resource_id).strip():
            callback(kind, str(resource_id))

    def cancel_resource(self, kind: str, resource_id: str) -> dict[str, object]:
        """Cancel a resource registered by a running workflow step."""
        if str(kind) == "execution":
            return self._control.cancel_execution(str(resource_id))
        return self._control.cancel_operation(str(resource_id))

    def cancel_target(self, target: DeviceTarget) -> str:
        """Fallback cancellation for a terminal run still being registered."""
        return self._control.cancel_active_execution(target)

    def get_resource(self, kind: str, resource_id: str) -> dict[str, Any]:
        """Return a redacted resource snapshot used during restart reconcile."""
        if str(kind) == "execution":
            return self._control.get_execution(str(resource_id))
        operation = self._control.get_operation(str(resource_id))
        return {
            "operation_id": operation.operation_id,
            "kind": operation.kind,
            "status": operation.status,
            "stage": operation.stage,
            "message": operation.message,
            "error_code": operation.error_code,
            "revision": operation.revision,
            "data": dict(operation.data),
        }

    @staticmethod
    def _default_command(action: str, params: dict[str, Any]) -> str:
        commands = HuaweiVrpCommandSet()
        defaults = {
            "precheck": commands.version_query(),
            "backup": commands.startup_query(),
            "verify": commands.storage_query("flash:/"),
            "activate": str(
                params.get("activate_command")
                or (
                    commands.activation(str(params.get("destination_path") or ""), "", False)[0][0]
                    if str(params.get("destination_path") or "").strip()
                    else commands.activation("", "", False)[0][0]
                )
            ),
            "verify_version": commands.version_query(),
            "validation": str(params.get("validation_command") or commands.version_query()),
        }
        return defaults[action]

    @staticmethod
    def _raise_for_failed_result(status: str, error_code: str, message: str) -> None:
        if str(status).casefold() not in {"success", "succeeded", "completed", "ok"}:
            code = error_code or str(status or "device_operation_failed")
            timeout = "timeout" in code.casefold() or "timeout" in message.casefold()
            human_review = "unknown command" in message.casefold() or "unrecognized command" in message.casefold() or code.casefold() == "terminal_failure"
            error_class = "deterministic" if timeout else "ambiguous" if human_review else "unknown"
            raise DeviceWorkflowExecutionError(code, message, error_class=error_class, retryable=timeout)

    async def _wait_operation(self, operation_id: str, *, timeout_seconds: int) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + max(1, min(timeout_seconds, 3_600))
        while True:
            operation = self._control.get_operation(operation_id)
            status = str(operation.status).casefold()
            if status in {"completed", "success", "succeeded"}:
                return {
                    "operation_id": operation.operation_id,
                    "status": operation.status,
                    "data": operation.data,
                    "evidence": (self._operation_evidence(operation),),
                }
            if status in {"failed", "cancelled", "canceled", "timeout", "timed_out", "interrupted"}:
                timeout = "timeout" in status or "timeout" in str(operation.error_code).casefold()
                raise DeviceWorkflowExecutionError(
                    str(operation.error_code or status), str(operation.message or "Device operation failed."),
                    error_class="deterministic" if timeout else "unknown", retryable=timeout,
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise DeviceWorkflowExecutionError("upload_timeout", "Upload operation timed out.", error_class="deterministic", retryable=True)
            await asyncio.sleep(0.1)

    @staticmethod
    def _operation_evidence(operation: Any) -> dict[str, Any]:
        return {
            "kind": "operation",
            "operation_id": str(operation.operation_id),
            "operation_kind": str(operation.kind),
            "status": str(operation.status),
            "stage": str(operation.stage),
            "progress_percent": int(operation.progress_percent),
            "revision": int(operation.revision),
            "data": dict(operation.data),
        }
