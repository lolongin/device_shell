"""Small vendor-neutral utility Activities used by Workflow Studio."""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, Mapping

from device_tui.framework.activity import ActivityContext, ActivityInvocation, ActivityResult, ActivityStatus
from device_tui.framework.events import Event
from device_tui.application.workflow_studio.expression import evaluate_expression
from device_tui.application.workflow_runtime.runner import wait_for_output
from device_tui.application.workflow_runtime.value_extraction import extract_value


class VariableSetActivityHandler:
    activity_id = "variable.set"

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        del context, report
        name = str(invocation.inputs.get("name") or "").strip()
        if not name or not name.replace("_", "a").isalnum() or name[0].isdigit():
            return ActivityResult(ActivityStatus.FAILED, outputs={"name": "", "value": None, "matched": False, "source": None, "status": "failed"}, error={"code": "variable_name_invalid", "message": "variable name is invalid", "class": "deterministic"})
        value = invocation.inputs.get("value")
        extract = invocation.inputs.get("extract")
        if isinstance(extract, Mapping) and extract:
            source = value
            try:
                value, matched = extract_value(source, extract)
            except ValueError as exc:
                return ActivityResult(
                    ActivityStatus.FAILED,
                    outputs={"name": name, "value": None, "matched": False, "source": source, "status": "failed"},
                    error={"code": "variable_extract_invalid", "message": str(exc), "class": "deterministic"},
                )
            return ActivityResult(
                ActivityStatus.SUCCEEDED,
                outputs={"name": name, "value": value, "matched": matched, "source": source},
                evidence=({"kind": "variable_set", "name": name, "matched": matched},),
            )
        return ActivityResult(ActivityStatus.SUCCEEDED, outputs={"name": name, "value": value}, evidence=({"kind": "variable_set", "name": name},))

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


class ExpressionActivityHandler:
    activity_id = "expression.evaluate"

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        del context, report
        try:
            value = evaluate_expression(str(invocation.inputs.get("expression") or ""), invocation.inputs.get("values") if isinstance(invocation.inputs.get("values"), Mapping) else {})
        except ValueError as exc:
            return ActivityResult(ActivityStatus.FAILED, outputs={"value": None, "status": "failed"}, error={"code": "expression_invalid", "message": str(exc), "class": "deterministic"})
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
            return ActivityResult(ActivityStatus.FAILED, outputs={"items": [], "results": [], "count": 0, "status": "failed"}, error={"code": "loop_items_invalid", "message": "loop.for_each items must be a list", "class": "deterministic"})
        action_id = str(invocation.inputs.get("action_id") or "").strip()
        if not action_id or self._child_runner is None:
            return ActivityResult(ActivityStatus.FAILED, outputs={"items": list(raw_items), "results": [], "count": 0, "status": "failed"}, error={"code": "loop_action_invalid", "message": "loop.for_each requires an executable action", "class": "deterministic"})
        results: list[dict[str, Any]] = []
        for index, item in enumerate(raw_items):
            try:
                child_inputs = self._resolve_inputs(dict(invocation.inputs.get("action_inputs") or {}), {"item": item, "index": index})
            except ValueError as exc:
                return ActivityResult(
                    ActivityStatus.FAILED,
                    error={
                        "code": "loop_child_input_invalid",
                        "message": str(exc),
                        "class": "deterministic",
                        "index": index,
                        "action_id": action_id,
                    },
                    outputs={"items": list(raw_items), "results": results, "count": index, "status": "failed"},
                )
            child_inputs.update({"item": item, "index": index})
            try:
                result = await self._child_runner(action_id, child_inputs, context, report)
            except Exception as exc:
                return ActivityResult(ActivityStatus.FAILED, error={"code": "loop_child_failed", "message": str(exc), "class": "deterministic", "index": index, "action_id": action_id}, outputs={"items": list(raw_items), "results": results, "count": index, "status": "failed"})
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
                        raise ValueError(f"unresolved loop input: {value}; missing local field: {segment}")
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
                outputs={"seconds": 0, "status": "failed"},
                error={"code": "wait_invalid", "message": "seconds must be a number", "class": "deterministic"},
            )
        if seconds < 0 or seconds > 86_400:
            return ActivityResult(
                status=ActivityStatus.FAILED,
                outputs={"seconds": seconds, "status": "failed"},
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


class TerminalWaitActivityHandler:
    """Wait for a device terminal to emit a matching output fragment."""

    activity_id = "terminal.wait"

    def __init__(self, terminal_hub: Any | None = None) -> None:
        self._terminal_hub = terminal_hub

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        if self._terminal_hub is None:
            return ActivityResult(
                ActivityStatus.FAILED,
                outputs={"status": "failed", "matched": False, "output": "", "sequence": 0, "session_id": ""},
                error={"code": "terminal_hub_unavailable", "message": "terminal.wait requires a terminal session hub", "class": "deterministic"},
            )
        target = invocation.context.get("target")
        target_values = dict(target) if isinstance(target, Mapping) else {}
        for key in ("device_id", "session_id"):
            if key in invocation.inputs:
                target_values[key] = invocation.inputs[key]
        if not str(target_values.get("device_id") or "").strip():
            target_values["device_id"] = str(context.workflow_run.device_id or "")
        session_id = str(invocation.inputs.get("session_id") or target_values.get("session_id") or "").strip()
        if not session_id:
            list_sessions = getattr(self._terminal_hub, "list_sessions", None)
            candidates = []
            if callable(list_sessions):
                candidates = [
                    item for item in list_sessions()
                    if str(getattr(item, "device_id", "")) == str(target_values.get("device_id") or "")
                    and str(getattr(item, "status", "")).casefold() == "connected"
                ]
            if len(candidates) == 1:
                session_id = str(getattr(candidates[0], "id", "")).strip()
            if not session_id:
                return ActivityResult(
                    ActivityStatus.FAILED,
                    outputs={"status": "failed", "matched": False, "output": "", "sequence": 0, "session_id": ""},
                    error={
                        "code": "session_required",
                        "message": "未找到该设备对应的已连接终端，请先打开终端会话或执行连接设备步骤。",
                        "class": "deterministic",
                    },
                )
        pattern = str(invocation.inputs.get("pattern") or "")
        mode = str(invocation.inputs.get("mode") or "contains")
        try:
            timeout_seconds = float(invocation.inputs.get("timeout_seconds", 30))
            after_sequence = int(invocation.inputs.get("after_sequence", 0) or 0)
        except (TypeError, ValueError):
            return ActivityResult(
                ActivityStatus.FAILED,
                outputs={"status": "failed", "matched": False, "output": "", "sequence": 0, "session_id": session_id},
                error={"code": "terminal_wait_invalid", "message": "timeout_seconds and after_sequence must be numbers", "class": "deterministic"},
            )
        if timeout_seconds <= 0 or timeout_seconds > 86_400:
            return ActivityResult(
                ActivityStatus.FAILED,
                outputs={"status": "failed", "matched": False, "output": "", "sequence": 0, "session_id": session_id},
                error={"code": "terminal_wait_invalid", "message": "timeout_seconds must be between 0 and 86400", "class": "deterministic"},
            )
        if after_sequence <= 0:
            managed_get = getattr(self._terminal_hub, "get", None)
            if callable(managed_get):
                try:
                    after_sequence = int(getattr(managed_get(session_id), "sequence", 0) or 0)
                except (KeyError, TypeError, ValueError):
                    pass
        if bool(invocation.inputs.get("send_enter", True)):
            write = getattr(self._terminal_hub, "write", None)
            if callable(write):
                try:
                    sent = write(session_id, "\r", origin="workflow")
                    if inspect.isawaitable(sent):
                        await sent
                except (KeyError, TypeError, ValueError) as exc:
                    return ActivityResult(
                        ActivityStatus.FAILED,
                        outputs={"status": "failed", "matched": False, "output": "", "sequence": 0, "session_id": session_id},
                        error={"code": "terminal_wait_input_failed", "message": str(exc), "class": "transient"},
                    )
        report(Event(
            type="terminal.wait.started",
            run_id=invocation.workflow_run_id,
            action_id=invocation.activity_id,
            source="workflow.terminal",
            payload={"session_id": session_id, "mode": mode, "pattern": pattern, "timeout_seconds": timeout_seconds},
        ))
        try:
            result = await wait_for_output(
                self._terminal_hub,
                session_id,
                mode=mode,
                pattern=pattern,
                case_sensitive=bool(invocation.inputs.get("case_sensitive", False)),
                timeout_seconds=timeout_seconds,
                after_sequence=after_sequence,
            )
        except (KeyError, ValueError) as exc:
            return ActivityResult(
                ActivityStatus.FAILED,
                error={"code": "terminal_wait_invalid", "message": str(exc), "class": "deterministic"},
            )
        status = str(result.status)
        if status == "matched":
            report(Event(
                type="terminal.wait.matched",
                run_id=invocation.workflow_run_id,
                action_id=invocation.activity_id,
                source="workflow.terminal",
                payload={"session_id": session_id, "sequence": result.sequence},
            ))
            return ActivityResult(
                ActivityStatus.SUCCEEDED,
                outputs={"status": status, "matched": True, "output": result.output, "sequence": result.sequence, "session_id": session_id},
                evidence=({"kind": "terminal_match", "session_id": session_id, "sequence": result.sequence},),
            )
        error_code = {
            "timeout": "terminal_wait_timeout",
            "disconnected": "terminal_disconnected",
            "cancelled": "terminal_wait_cancelled",
            "error": "terminal_wait_error",
        }.get(status, "terminal_wait_failed")
        return ActivityResult(
            ActivityStatus.CANCELLED if status == "cancelled" else ActivityStatus.FAILED,
            outputs={"status": status, "matched": False, "output": result.output, "sequence": result.sequence, "session_id": session_id},
            error={"code": error_code, "message": result.reason or status, "class": "timeout" if status == "timeout" else "transient" if status in {"disconnected", "error"} else "deterministic"},
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


class UntilActivityHandler:
    """Run one child Activity until a bounded condition becomes true."""

    activity_id = "loop.until"

    def __init__(self, child_runner: ChildRunner | None = None) -> None:
        self._child_runner = child_runner

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        action_id = str(invocation.inputs.get("action_id") or "").strip()
        condition = str(invocation.inputs.get("condition") or "").strip()
        if not action_id or not condition or self._child_runner is None:
            return ActivityResult(ActivityStatus.FAILED, outputs={"status": "failed", "matched": False, "iterations": 0, "result": {}, "results": []}, error={"code": "loop_until_invalid", "message": "loop.until requires action_id, condition, and an executable action", "class": "deterministic"})
        try:
            max_iterations = int(invocation.inputs.get("max_iterations", 10))
            interval_seconds = float(invocation.inputs.get("interval_seconds", 1))
        except (TypeError, ValueError):
            return ActivityResult(ActivityStatus.FAILED, outputs={"status": "failed", "matched": False, "iterations": 0, "result": {}, "results": []}, error={"code": "loop_until_invalid", "message": "max_iterations and interval_seconds must be numbers", "class": "deterministic"})
        if max_iterations < 1 or max_iterations > 100 or interval_seconds < 0 or interval_seconds > 86_400:
            return ActivityResult(ActivityStatus.FAILED, outputs={"status": "failed", "matched": False, "iterations": 0, "result": {}, "results": []}, error={"code": "loop_until_invalid", "message": "max_iterations must be 1-100 and interval_seconds must be 0-86400", "class": "deterministic"})
        try:
            from device_tui.framework.expression import validate_expression
            validate_expression(condition)
        except ValueError as exc:
            return ActivityResult(ActivityStatus.FAILED, outputs={"status": "failed", "matched": False, "iterations": 0, "result": {}, "results": []}, error={"code": "loop_until_invalid", "message": str(exc), "class": "deterministic"})
        results: list[dict[str, Any]] = []
        raw_action_inputs = dict(invocation.inputs.get("action_inputs") or {})
        previous_result: dict[str, Any] = {}
        for iteration in range(1, max_iterations + 1):
            try:
                child_inputs = ForEachActivityHandler._resolve_inputs(
                    raw_action_inputs,
                    {"iteration": iteration, "result": previous_result, "outputs": previous_result},
                )
            except ValueError as exc:
                return ActivityResult(
                    ActivityStatus.FAILED,
                    outputs={"status": "failed", "matched": False, "iterations": iteration - 1, "result": results[-1] if results else {}, "results": results},
                    error={
                        "code": "loop_until_input_invalid",
                        "message": str(exc),
                        "class": "deterministic",
                        "iteration": iteration,
                        "action_id": action_id,
                    },
                )
            try:
                child_result = dict(await self._child_runner(action_id, child_inputs, context, report))
            except Exception as exc:
                return ActivityResult(ActivityStatus.FAILED, outputs={"status": "failed", "matched": False, "iterations": iteration - 1, "result": results[-1] if results else {}, "results": results}, error={"code": "loop_until_child_failed", "message": str(exc), "class": "deterministic", "iteration": iteration})
            results.append(child_result)
            previous_result = child_result
            values = {"result": child_result, "iteration": iteration, "outputs": child_result}
            try:
                done = bool(evaluate_expression(condition, values))
            except ValueError as exc:
                return ActivityResult(ActivityStatus.FAILED, outputs={"status": "failed", "matched": False, "iterations": iteration, "result": child_result, "results": results}, error={"code": "loop_until_condition_invalid", "message": str(exc), "class": "deterministic"})
            if done:
                return ActivityResult(ActivityStatus.SUCCEEDED, outputs={"status": "matched", "matched": True, "iterations": iteration, "result": child_result, "results": results}, evidence=({"kind": "until", "iterations": iteration},))
            if iteration < max_iterations and interval_seconds:
                await asyncio.sleep(interval_seconds)
        return ActivityResult(ActivityStatus.FAILED, outputs={"status": "exhausted", "matched": False, "iterations": max_iterations, "result": results[-1] if results else {}, "results": results}, error={"code": "loop_until_exhausted", "message": "loop.until reached max_iterations without matching condition", "class": "timeout"})

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
                outputs={"device_id": "", "status": "failed"},
                error={"code": "device_required", "message": "device.select requires a device_id", "class": "deterministic"},
            )
        target_device = str(target_values.get("device_id") or "").strip()
        if target_device and selected != target_device:
            return ActivityResult(
                status=ActivityStatus.FAILED,
                outputs={"device_id": selected, "status": "failed"},
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


__all__ = ["DeviceSelectActivityHandler", "ExpressionActivityHandler", "ForEachActivityHandler", "ResultSaveActivityHandler", "TerminalWaitActivityHandler", "UntilActivityHandler", "VariableSetActivityHandler", "WaitActivityHandler"]
