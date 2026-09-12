"""Small vendor-neutral utility Activities used by Workflow Studio."""

from __future__ import annotations

import asyncio
from typing import Any

from device_tui.framework.activity import ActivityContext, ActivityInvocation, ActivityResult, ActivityStatus
from device_tui.framework.events import Event


class WaitActivityHandler:
    """Wait for a bounded duration without occupying a device transport."""

    activity_id = "utility.wait"

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        del context
        try:
            seconds = float(invocation.inputs.get("seconds", 0))
        except (TypeError, ValueError) as exc:
            return ActivityResult(
                status=ActivityStatus.FAILED,
                error={"code": "wait_invalid", "message": "seconds must be a number", "class": "deterministic"},
            )
        if seconds < 0 or seconds > 86_400:
            return ActivityResult(
                status=ActivityStatus.FAILED,
                error={"code": "wait_invalid", "message": "seconds must be between 0 and 86400", "class": "deterministic"},
            )
        report(Event(
            type="utility.wait.started",
            run_id=invocation.workflow_run_id,
            action_id=invocation.activity_id,
            source="workflow.utility",
            payload={"seconds": seconds},
        ))
        await asyncio.sleep(seconds)
        return ActivityResult(
            status=ActivityStatus.SUCCEEDED,
            outputs={"seconds": seconds, "status": "completed"},
            evidence=({"kind": "wait", "seconds": seconds},),
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


class DeviceSelectActivityHandler:
    """Select the task target without opening a transport session."""

    activity_id = "device.select"

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        del report
        target = invocation.context.get("target")
        target_values = dict(target) if isinstance(target, dict) else {}
        selected = str(invocation.inputs.get("device_id") or target_values.get("device_id") or "").strip()
        if not selected:
            return ActivityResult(
                status=ActivityStatus.FAILED,
                error={"code": "device_required", "message": "device.select requires a device_id", "class": "deterministic"},
            )
        target_device = str(target_values.get("device_id") or "").strip()
        if target_device and selected != target_device:
            return ActivityResult(
                status=ActivityStatus.FAILED,
                error={
                    "code": "device_mismatch",
                    "message": f"selected device {selected} does not match task target {target_device}",
                    "class": "deterministic",
                },
            )
        return ActivityResult(
            status=ActivityStatus.SUCCEEDED,
            outputs={"device_id": selected, "status": "selected"},
            evidence=({"kind": "device_selection", "device_id": selected},),
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


__all__ = ["DeviceSelectActivityHandler", "WaitActivityHandler"]
