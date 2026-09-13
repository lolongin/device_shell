"""Small vendor-neutral utility Activities used by Workflow Studio."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Mapping

from device_tui.framework.activity import ActivityContext, ActivityInvocation, ActivityResult, ActivityStatus
from device_tui.framework.events import Event
from device_tui.application.workflow_studio.expression import evaluate_expression


class VariableSetActivityHandler:
    activity_id = "variable.set"

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        del context, report
        name = str(invocation.inputs.get("name") or "").strip()
        if not name or not name.replace("_", "a").isalnum() or name[0].isdigit():
            return ActivityResult(ActivityStatus.FAILED, error={"code": "variable_name_invalid", "message": "variable name is invalid", "class": "deterministic"})
        return ActivityResult(ActivityStatus.SUCCEEDED, outputs={"name": name, "value": invocation.inputs.get("value")}, evidence=({"kind": "variable_set", "name": name},))

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


class ExpressionActivityHandler:
    activity_id = "expression.evaluate"

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        del context, report
        try:
            value = evaluate_expression(str(invocation.inputs.get("expression") or ""), invocation.inputs.get("values") if isinstance(invocation.inputs.get("values"), Mapping) else {})
        except ValueError as exc:
            return ActivityResult(ActivityStatus.FAILED, error={"code": "expression_invalid", "message": str(exc), "class": "deterministic"})
        return ActivityResult(ActivityStatus.SUCCEEDED, outputs={"value": value, "status": "evaluated"}, evidence=({"kind": "expression", "result": value},))

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


ChildRunner = Callable[[str, dict[str, Any], ActivityContext, Any], Awaitable[dict[str, Any]]]


class ForEachActivityHandler:
    activity_id = "loop.for_each"

    def __init__(self, child_runner: ChildRunner | None = None) -> None:
        self._child_runner = child_runner

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        raw_items = invocation.inputs.get("items")
        if not isinstance(raw_items, (list, tuple)):
            return ActivityResult(ActivityStatus.FAILED, error={"code": "loop_items_invalid", "message": "loop.for_each items must be a list", "class": "deterministic"})
        action_id = str(invocation.inputs.get("action_id") or "").strip()
        if not action_id or self._child_runner is None:
            return ActivityResult(ActivityStatus.FAILED, error={"code": "loop_action_invalid", "message": "loop.for_each requires an executable action", "class": "deterministic"})
        results: list[dict[str, Any]] = []
        for index, item in enumerate(raw_items):
            child_inputs = self._resolve_inputs(dict(invocation.inputs.get("action_inputs") or {}), {"item": item, "index": index})
            child_inputs.update({"item": item, "index": index})
            try:
                result = await self._child_runner(action_id, child_inputs, context, report)
            except Exception as exc:
                return ActivityResult(ActivityStatus.FAILED, error={"code": "loop_child_failed", "message": str(exc), "class": "deterministic", "index": index, "action_id": action_id}, outputs={"results": results, "count": index})
            results.append(dict(result))
        return ActivityResult(ActivityStatus.SUCCEEDED, outputs={"items": list(raw_items), "results": results, "count": len(results)}, evidence=({"kind": "for_each", "count": len(results)},))

    @staticmethod
    def _resolve_inputs(values: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
        def resolve(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {str(key): resolve(item) for key, item in value.items()}
            if isinstance(value, list):
                return [resolve(item) for item in value]
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                current: Any = local
                for segment in value[2:-1].split("."):
                    if not isinstance(current, Mapping) or segment not in current:
                        return value
                    current = current[segment]
                return current
            return value
        return {key: resolve(value) for key, value in values.items()}

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


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


class ResultSaveActivityHandler:
    """Persist a business-facing result in the task output projection."""

    activity_id = "result.save"

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        del context, report
        key = str(invocation.inputs.get("key") or invocation.invocation_id).strip()
        value = invocation.inputs.get("value", invocation.inputs.get("data"))
        return ActivityResult(
            status=ActivityStatus.SUCCEEDED,
            outputs={"status": "saved", "key": key, "value": value},
            evidence=({"kind": "result_saved", "key": key},),
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


__all__ = ["DeviceSelectActivityHandler", "ResultSaveActivityHandler", "WaitActivityHandler"]
