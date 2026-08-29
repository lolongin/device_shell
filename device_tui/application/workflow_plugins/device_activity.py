"""Generic device Activities backed by the existing device-control facade.

This is a migration adapter.  It provides stable Activity semantics while the
vendor command selection remains in ``DeviceExecutionTool`` and its drivers.
"""

from __future__ import annotations

from typing import Any

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
        "device.verify_version": "verify_version",
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
        target_values = self._target_values(invocation)
        target = DeviceTarget(
            device_id=str(target_values.get("device_id") or ""),
            session_id=str(target_values.get("session_id") or ""),
            protocol=str(target_values.get("protocol") or "auto"),
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
            return ActivityResult(
                status=status,
                outputs=dict(exc.details),
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
                evidence=({"kind": "device_activity_error", "operation": operation},),
                error={"code": "device_activity_failed", "message": str(exc), "class": "unknown"},
            )

        outputs = dict(data)
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

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del context
        target_values = self._target_values(invocation)
        self._execution.cancel_target(DeviceTarget(
            device_id=str(target_values.get("device_id") or ""),
            session_id=str(target_values.get("session_id") or ""),
            protocol=str(target_values.get("protocol") or "auto"),
        ))

    @staticmethod
    def _target_values(invocation: ActivityInvocation) -> dict[str, Any]:
        values = invocation.context.get("target")
        target = dict(values) if isinstance(values, dict) else {}
        for key in ("device_id", "session_id", "protocol"):
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


class CompatibilityDeviceActivityHandler:
    """Expose a vendor operation through a generic Activity id.

    This is deliberately a migration adapter.  The Activity boundary owns the
    invocation/result contract, while the supplied plugin handler remains the
    owner of vendor command generation, parsing, and read-back verification.
    Once all callers use the generic adapter contract this class can be
    replaced without changing workflow definitions or the runtime.
    """

    def __init__(self, legacy_handler: Any, activity_id: str, legacy_operation: str) -> None:
        self.activity_id = activity_id
        self._legacy = legacy_handler
        self._legacy_operation = legacy_operation

    _UNCERTAIN_OPERATIONS = {
        "huawei.startup.configure",
        "huawei.startup.rollback",
    }

    async def execute(
        self,
        invocation: ActivityInvocation,
        context: ActivityContext,
        report: Any,
    ) -> ActivityResult:
        action = ActionSpec(
            id=invocation.activity_id,
            operation=self._legacy_operation,
            params=dict(invocation.inputs),
            timeout_seconds=float(
                invocation.inputs.get("activity_timeout_seconds")
                or invocation.inputs.get("timeout_seconds")
                or 30
            ),
        )
        try:
            result: ActionResult = await self._legacy.execute(
                action,
                context.workflow_run,
                report,
            )
        except Exception as exc:
            code = str(getattr(exc, "code", "activity_failed"))
            error_class = str(getattr(exc, "error_class", "unknown"))
            uncertain = (
                self._legacy_operation in self._UNCERTAIN_OPERATIONS
                and (
                    error_class in {"unknown", "timeout", "transient", "connection"}
                    or any(token in code.casefold() for token in ("timeout", "disconnect", "connection", "interrupted"))
                )
            )
            return ActivityResult(
                status=ActivityStatus.UNKNOWN if uncertain else ActivityStatus.FAILED,
                error={
                    "code": code,
                    "message": str(exc),
                    "class": error_class,
                    "retryable": bool(getattr(exc, "retryable", False)),
                },
            )
        outputs = dict(result.facts)
        operation_id = str(outputs.get("operation_id") or outputs.get("execution_id") or "")
        evidence = outputs.get("evidence")
        normalized_evidence = tuple(item for item in (evidence or ()) if isinstance(item, dict))
        status = {
            ActionStatus.SUCCEEDED: ActivityStatus.SUCCEEDED,
            ActionStatus.FAILED: ActivityStatus.FAILED,
            ActionStatus.UNKNOWN: ActivityStatus.UNKNOWN,
            ActionStatus.CANCELLED: ActivityStatus.CANCELLED,
        }.get(str(result.status), ActivityStatus.FAILED)
        return ActivityResult(
            status=status,
            outputs=outputs,
            evidence=normalized_evidence,
            operation_id=operation_id,
            error=result.error,
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        action = ActionSpec(
            id=invocation.activity_id,
            operation=self._legacy_operation,
            params=dict(invocation.inputs),
            timeout_seconds=float(
                invocation.inputs.get("activity_timeout_seconds")
                or invocation.inputs.get("timeout_seconds")
                or 30
            ),
        )
        await self._legacy.cancel(action, context.workflow_run)


__all__ = ["CompatibilityDeviceActivityHandler", "DeviceActivityHandler"]
