"""Generic device Activities backed by the existing device-control facade.

This is a migration adapter.  It provides stable Activity semantics while the
vendor command selection remains in ``DeviceExecutionTool`` and its drivers.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from device_tui.application.device_control import ControlContext, DeviceTarget
from device_tui.application.tasking.execution import DeviceExecutionTool, DeviceWorkflowExecutionError
from device_tui.application.tasking.models import WorkflowStep
from device_tui.framework import (
    ActionResult,
    ActionSpec,
    ActionStatus,
    ActivityContext,
    ActivityInvocation,
    ActivityResult,
    ActivityStatus,
    Event,
)


class DeviceActivityHandler:
    """Translate one generic device operation into an Activity result."""

    _UNCERTAIN_OPERATIONS = {"device.reboot", "device.wait_online"}
    _EXECUTION_ACTIONS = {
        "device.reboot": "reboot",
        "device.wait_online": "wait_online",
        "device.info": "verify_version",
        "device.verify_version": "verify_version",
        "terminal.command": "command",
        "terminal.batch": "batch",
        "device.power_off": "power_off",
        "operation.wait": "operation_wait",
    }

    def __init__(self, execution: DeviceExecutionTool, activity_id: str) -> None:
        self.activity_id = activity_id
        self._execution = execution

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        operation = self.activity_id
        inputs = invocation.inputs
        raw_params = inputs.get("params")
        params = dict(raw_params) if isinstance(raw_params, dict) else dict(inputs)
        for key in ("device_id", "session_id", "protocol", "params"):
            params.pop(key, None)
        target_values = self._target_values(invocation, context)
        target = DeviceTarget(
            device_id=str(target_values.get("device_id") or ""),
            session_id=str(target_values.get("session_id") or ""),
            protocol=str(target_values.get("protocol") or "auto"),
            host=str(target_values.get("host") or ""),
            port=int(target_values.get("port") or 0),
        )
        control_context = ControlContext(
            source=str(invocation.context.get("source") or "workflow"),
            request_id=str(invocation.context.get("request_id") or invocation.invocation_id),
            task_id=str(invocation.context.get("task_id") or ""),
            step_id=str(invocation.context.get("step_id") or operation),
            lease_token=str(invocation.context.get("lease_token") or ""),
            actor=str(invocation.context.get("actor") or ""),
        )
        report(self._event("device.activity.dispatching", invocation, {"operation": operation}))
        execution_action = self._EXECUTION_ACTIONS.get(operation, operation)
        try:
            execute_operation = getattr(self._execution, "execute_operation", None)
            if callable(execute_operation):
                data = await execute_operation(
                    target,
                    execution_action,
                    params,
                    context=control_context,
                )
            else:
                # External execution adapters may still implement only the
                # historical WorkflowStep port during migration.
                data = await self._execution.execute(
                    target,
                    WorkflowStep(invocation.activity_id, kind="device", action=execution_action, params=params),
                    context=control_context,
                )
        except DeviceWorkflowExecutionError as exc:
            status = (
                ActivityStatus.UNKNOWN
                if operation in self._UNCERTAIN_OPERATIONS
                else ActivityStatus.FAILED
            )
            error_outputs = self._normalize_outputs(
                dict(exc.details),
                operation=operation,
                target_values=target_values,
                status=status.value,
            )
            return ActivityResult(
                status=status,
                outputs=error_outputs,
                evidence=({"kind": "device_activity_error", "operation": operation, "code": exc.code},),
                error={
                    "code": exc.code,
                    "message": str(exc),
                    "class": exc.error_class,
                    "retryable": exc.retryable,
                },
            )
        except Exception as exc:
            status = ActivityStatus.UNKNOWN if operation in self._UNCERTAIN_OPERATIONS else ActivityStatus.FAILED
            return ActivityResult(
                status=status,
                outputs=self._normalize_outputs(
                    {},
                    operation=operation,
                    target_values=target_values,
                    status=status.value,
                ),
                evidence=({"kind": "device_activity_error", "operation": operation},),
                error={"code": "device_activity_failed", "message": str(exc), "class": "unknown"},
            )

        outputs = self._normalize_outputs(
            dict(data),
            operation=operation,
            target_values=target_values,
        )
        if operation == "device.info":
            device_values = invocation.context.get("device")
            requested_fields = self._requested_info_fields(inputs.get("fields"))
            metadata: dict[str, str] = {
                "name": "",
                "address": "",
                "model": "",
                "version": "",
            }
            if isinstance(device_values, Mapping):
                address = (
                    device_values.get("address")
                    or device_values.get("ssh_endpoint")
                    or device_values.get("telnet_endpoint")
                    or device_values.get("serial_endpoint")
                    or ""
                )
                metadata = {
                    "name": str(device_values.get("name") or ""),
                    "address": str(address or ""),
                    "model": str(device_values.get("model") or ""),
                    "version": str(device_values.get("version") or ""),
                }
                outputs["device_id"] = str(device_values.get("id") or "")
                outputs["status"] = str(device_values.get("status") or outputs.get("status") or "")
            match = re.search(r"\b(?:v|version\s*)?(\d+(?:\.\d+)+)\b", str(outputs.get("output") or ""), re.IGNORECASE)
            if match:
                software_version = match.group(1)
            elif isinstance(device_values, Mapping):
                software_version = str(
                    device_values.get("software_version")
                    or device_values.get("version")
                    or ""
                )
            else:
                software_version = ""
            metadata["software_version"] = software_version
            outputs.update(metadata)
            outputs["requested_fields"] = requested_fields or ["name", "software_version", "status"]
        operation_id = str(outputs.get("operation_id") or outputs.get("execution_id") or "")
        raw_status = str(outputs.get("status") or "completed").casefold()
        succeeded = raw_status in {"success", "succeeded", "completed", "ok", "ready"}
        report(self._event("device.activity.completed", invocation, {
            "operation": operation,
            "operation_id": operation_id,
            "status": raw_status,
        }))
        self._report_compatibility_events(operation, invocation, outputs, report)
        return ActivityResult(
            status=ActivityStatus.SUCCEEDED if succeeded else ActivityStatus.FAILED,
            outputs=outputs,
            evidence=tuple(item for item in outputs.get("evidence", ()) if isinstance(item, dict)),
            operation_id=operation_id,
            error=None if succeeded else {
                "code": str(outputs.get("error_code") or "device_activity_failed"),
                "message": str(outputs.get("output") or "device operation failed"),
                "class": "deterministic",
            },
        )

    @staticmethod
    def _normalize_outputs(
        outputs: dict[str, Any],
        *,
        operation: str,
        target_values: Mapping[str, Any],
        status: str = "completed",
    ) -> dict[str, Any]:
        """Keep the public Activity output contract stable across adapters."""
        normalized = dict(outputs)
        execution_id = str(
            normalized.get("execution_id")
            or normalized.get("probe_execution_id")
            or normalized.get("operation_id")
            or ""
        )
        operation_id = str(normalized.get("operation_id") or execution_id)
        normalized.setdefault("output", normalized.get("probe_output", "") or "")
        normalized.setdefault("status", status)
        normalized.setdefault("execution_id", execution_id)
        normalized.setdefault("operation_id", operation_id)
        normalized.setdefault("session_id", str(target_values.get("session_id") or ""))
        normalized.setdefault("device_id", str(target_values.get("device_id") or ""))
        normalized.setdefault("cli_status", "ready" if operation == "device.wait_online" and normalized["status"] == "completed" else "")
        normalized.setdefault("host", str(target_values.get("host") or ""))
        try:
            normalized.setdefault("port", int(target_values.get("port") or 0))
        except (TypeError, ValueError):
            normalized.setdefault("port", 0)
        normalized.setdefault("evidence", [])
        return normalized

    @staticmethod
    def _requested_info_fields(raw_fields: Any) -> list[str]:
        if isinstance(raw_fields, str):
            fields = [item.strip() for item in raw_fields.split(",") if item.strip()]
        elif isinstance(raw_fields, (list, tuple, set)):
            fields = [str(item).strip() for item in raw_fields if str(item).strip()]
        else:
            fields = []
        return fields or ["name", "software_version", "status"]

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        target_values = self._target_values(invocation, context)
        self._execution.cancel_target(DeviceTarget(
            device_id=str(target_values.get("device_id") or ""),
            session_id=str(target_values.get("session_id") or ""),
            protocol=str(target_values.get("protocol") or "auto"),
            host=str(target_values.get("host") or ""),
            port=int(target_values.get("port") or 0),
        ))

    @staticmethod
    def _target_values(invocation: ActivityInvocation, context: ActivityContext | None = None) -> dict[str, Any]:
        values = invocation.context.get("target")
        target = dict(values) if isinstance(values, dict) else {}
        if not str(target.get("device_id") or "").strip() and context is not None:
            target["device_id"] = str(context.workflow_run.device_id or "")
        for key in ("device_id", "session_id", "protocol", "host", "port"):
            if key in invocation.inputs:
                target[key] = invocation.inputs[key]
        return target

    @classmethod
    def _report_compatibility_events(
        cls,
        operation: str,
        invocation: ActivityInvocation,
        outputs: dict[str, Any],
        report: Any,
    ) -> None:
        """Keep legacy expectations readable while a Workflow is migrating."""
        if operation == "device.reboot" and (
            bool(outputs.get("reboot_disconnect_observed"))
            or bool(outputs.get("reboot_command_sent"))
        ):
            report(cls._event("huawei.reboot.started", invocation, {"compatibility": True}))
        elif operation == "device.wait_online" and str(outputs.get("cli_status") or "").casefold() == "ready":
            report(cls._event("huawei.cli.ready", invocation, {"compatibility": True}))
        elif operation == "device.verify_version":
            fact = str(invocation.inputs.get("fact") or "").casefold()
            event_type = "huawei.startup.package.match" if fact == "startup_package" else "huawei.version.match"
            report(cls._event(event_type, invocation, {"compatibility": True}))

    @staticmethod
    def _event(event_type: str, invocation: ActivityInvocation, payload: dict[str, Any]) -> Event:
        return Event(
            type=event_type,
            run_id=invocation.workflow_run_id,
            action_id=invocation.activity_id,
            source="device.activity",
            payload=payload,
        )


__all__ = ["DeviceActivityHandler"]
