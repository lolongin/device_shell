"""Vendor ports for generic device Activities.

The Huawei implementation currently delegates the low-level call to the
legacy bridge.  Keeping that delegation here makes the migration boundary
explicit and allows the bridge to be replaced without changing Activities or
Workflow definitions.
"""

from __future__ import annotations

from typing import Any

from device_tui.framework import (
    ActionResult,
    ActionSpec,
    ActionStatus,
    ActivityContext,
    ActivityInvocation,
    ActivityResult,
    ActivityStatus,
    DeviceVendorAdapter,
)


class HuaweiVrpDeviceVendorAdapter:
    """Adapt stable device Activity ids to Huawei VRP operations."""

    id = "huawei.vrp"

    _OPERATIONS = {
        "device.storage.cleanup": "huawei.storage.cleanup",
        "device.storage.sync": "huawei.storage.sync",
        "device.verify_artifact": "device.verify",
        "device.startup.configure": "huawei.startup.configure",
        "device.startup.rollback": "huawei.startup.rollback",
    }
    _UNCERTAIN_OPERATIONS = {"huawei.startup.configure", "huawei.startup.rollback"}

    def __init__(self, legacy_handler: Any) -> None:
        self._legacy = legacy_handler

    async def execute_activity(
        self,
        activity_id: str,
        invocation: ActivityInvocation,
        context: ActivityContext,
        report: Any,
    ) -> ActivityResult:
        operation = self._OPERATIONS.get(activity_id)
        if operation is None:
            return ActivityResult(
                status=ActivityStatus.FAILED,
                error={
                    "code": "unsupported_vendor_activity",
                    "message": f"Huawei adapter does not support {activity_id}.",
                    "class": "deterministic",
                },
            )
        action = ActionSpec(
            id=activity_id,
            operation=operation,
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
            error_class = str(getattr(exc, "error_class", "unknown"))
            code = str(getattr(exc, "code", "activity_failed"))
            uncertain = operation in self._UNCERTAIN_OPERATIONS and (
                error_class in {"unknown", "timeout", "transient", "connection"}
                or any(token in code.casefold() for token in ("timeout", "disconnect", "connection", "interrupted"))
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
        return self._normalize(result)

    async def cancel_activity(
        self,
        activity_id: str,
        invocation: ActivityInvocation,
        context: ActivityContext,
    ) -> None:
        operation = self._OPERATIONS.get(activity_id)
        if operation is None:
            return
        action = ActionSpec(
            id=activity_id,
            operation=operation,
            params=dict(invocation.inputs),
            timeout_seconds=float(
                invocation.inputs.get("activity_timeout_seconds")
                or invocation.inputs.get("timeout_seconds")
                or 30
            ),
        )
        await self._legacy.cancel(action, context.workflow_run)

    @staticmethod
    def _normalize(result: ActionResult) -> ActivityResult:
        outputs = dict(result.facts)
        operation_id = str(outputs.get("operation_id") or outputs.get("execution_id") or "")
        evidence = tuple(item for item in (outputs.get("evidence") or ()) if isinstance(item, dict))
        status = {
            ActionStatus.SUCCEEDED: ActivityStatus.SUCCEEDED,
            ActionStatus.FAILED: ActivityStatus.FAILED,
            ActionStatus.UNKNOWN: ActivityStatus.UNKNOWN,
            ActionStatus.CANCELLED: ActivityStatus.CANCELLED,
        }.get(str(result.status), ActivityStatus.FAILED)
        return ActivityResult(
            status=status,
            outputs=outputs,
            evidence=evidence,
            operation_id=operation_id,
            error=result.error,
        )


class DeviceVendorActivityHandler:
    """Generic Activity handler that delegates to a vendor port."""

    def __init__(self, adapter: DeviceVendorAdapter, activity_id: str) -> None:
        self.activity_id = activity_id
        self._adapter = adapter

    async def execute(
        self,
        invocation: ActivityInvocation,
        context: ActivityContext,
        report: Any,
    ) -> ActivityResult:
        return await self._adapter.execute_activity(
            self.activity_id,
            invocation,
            context,
            report,
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        await self._adapter.cancel_activity(self.activity_id, invocation, context)


__all__ = ["DeviceVendorActivityHandler", "HuaweiVrpDeviceVendorAdapter"]
