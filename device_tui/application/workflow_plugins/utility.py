"""Small vendor-neutral utility Activities used by Workflow Studio."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from typing import Any, Awaitable, Callable, Mapping

from device_tui.framework.activity import ActivityContext, ActivityInvocation, ActivityResult, ActivityStatus
from device_tui.framework.events import Event
from device_tui.framework.orchestrator import TaskOrchestrator
from device_tui.framework.resources import ResourceCoordinator, ResourceRequest
from device_tui.framework.targets import bind_device_target, device_id_value
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
        return ActivityResult(ActivityStatus.SUCCEEDED, outputs={"name": name, "value": value, "matched": False, "source": None}, evidence=({"kind": "variable_set", "name": name},))

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
        steps = invocation.inputs.get("action_steps")
        if (not action_id and not steps) or self._child_runner is None:
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
            try:
                if steps:
                    result = await self._run_steps(steps, {"item": item, "index": index}, context, report, invocation)
                else:
                    child_inputs.update({"item": item, "index": index})
                    result = await self._child_runner(action_id, child_inputs, context, report)
            except Exception as exc:
                return ActivityResult(ActivityStatus.FAILED, error={"code": "loop_child_failed", "message": str(exc), "class": "deterministic", "index": index, "action_id": action_id}, outputs={"items": list(raw_items), "results": results, "count": index, "status": "failed"})
            results.append(dict(result))
        return ActivityResult(ActivityStatus.SUCCEEDED, outputs={"items": list(raw_items), "results": results, "count": len(results), "status": "completed"}, evidence=({"kind": "for_each", "count": len(results)},))

    @staticmethod
    def _resolve_inputs(values: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
        def resolve(value: Any) -> Any:
            if isinstance(value, Mapping):
                return {str(key): resolve(item) for key, item in value.items()}
            if isinstance(value, list):
                return [resolve(item) for item in value]
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                return TaskOrchestrator._resolve_inputs({"value": value}, local)["value"]
            return value
        return {key: resolve(value) for key, value in values.items()}

    async def _run_steps(
        self, steps: list[dict[str, Any]], local: dict[str, Any], context: ActivityContext,
        report: Any, invocation: ActivityInvocation,
    ) -> dict[str, Any]:
        outputs = dict(invocation.inputs.get("scope_outputs") or {})
        step_results: dict[str, Any] = {}
        result: dict[str, Any] = {}
        for step in steps:
            inputs = TaskOrchestrator._resolve_inputs(
                step.get("action_inputs") or {}, {**outputs, **local, "outputs": outputs},
            )
            result = dict(await self._child_runner(str(step["action_id"]), inputs, context, report))
            step_id = str(step["id"])
            outputs[step_id] = result
            step_results[step_id] = result
        return {**result, "steps": step_results}

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


class DeviceForEachActivityHandler(ForEachActivityHandler):
    """Run one action for each device, preserving per-device results."""

    activity_id = "device.for_each"

    def __init__(self, child_runner: ChildRunner | None = None, resources: ResourceCoordinator | None = None) -> None:
        super().__init__(child_runner)
        self._resources = resources

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        devices = invocation.inputs.get("devices")
        if not isinstance(devices, (list, tuple)) or not devices:
            return ActivityResult(ActivityStatus.FAILED, outputs={"devices": [], "results": [], "count": 0, "succeeded": 0, "failed": 0, "status": "failed"}, error={"code": "device_list_invalid", "message": "device.for_each requires a non-empty devices list", "class": "deterministic"})
        action_id = str(invocation.inputs.get("action_id") or "").strip()
        steps = invocation.inputs.get("action_steps")
        if (not action_id and not steps) or self._child_runner is None:
            return ActivityResult(ActivityStatus.FAILED, outputs={"devices": list(devices), "results": [], "count": 0, "succeeded": 0, "failed": 0, "status": "failed"}, error={"code": "device_action_invalid", "message": "device.for_each requires an executable action", "class": "deterministic"})
        concurrency = invocation.inputs.get("concurrency", 1)
        if not isinstance(concurrency, int) or isinstance(concurrency, bool) or not 1 <= concurrency <= 32:
            return ActivityResult(ActivityStatus.FAILED, outputs={"devices": list(devices), "results": [], "count": 0, "succeeded": 0, "failed": 0, "status": "failed"}, error={"code": "device_concurrency_invalid", "message": "concurrency must be an integer between 1 and 32", "class": "deterministic"})
        failure_strategy = invocation.inputs.get("failure_strategy", "continue")
        if failure_strategy not in {"stop", "continue"}:
            return ActivityResult(ActivityStatus.FAILED, error={"code": "device_failure_strategy_invalid", "message": "failure_strategy must be stop or continue", "class": "deterministic"})

        async def run_device(index: int, device: Any) -> tuple[dict[str, Any], bool]:
            device_id = ""
            lease = None
            try:
                device_id = device_id_value(device)
                if not device_id:
                    raise ValueError("device ID must not be empty")
                parent_values = dict(context.invocation.context)
                parent_values.setdefault("target", {"device_id": context.workflow_run.device_id})
                child_values = bind_device_target(parent_values, device_id)
                child_values.pop("lease_token", None)
                if self._resources is not None:
                    owner = str(child_values.get("resource_owner_id") or context.workflow_run.id)
                    lease = self._resources.acquire(ResourceRequest("device", device_id, owner))
                    child_values["lease_token"] = lease.token
                child_context = ActivityContext(
                    replace(context.workflow_run, device_id=device_id, context=child_values),
                    replace(context.invocation, context=child_values),
                )
                device_values = dict(device) if isinstance(device, Mapping) else {}
                local = {"device": {**device_values, "id": device_id, "device_id": device_id}, "device_id": device_id, "index": index}
                if steps:
                    result = await self._run_steps(steps, local, child_context, report, invocation)
                else:
                    child_inputs = self._resolve_inputs(dict(invocation.inputs.get("action_inputs") or {}), local)
                    child_inputs["device_id"] = device_id
                    result = await self._child_runner(action_id, child_inputs, child_context, report)
                step_failed = any(
                    str(step.get("execution_status") or step.get("status") or "").casefold() in {"failed", "unknown", "cancelled"}
                    for step in result.get("steps", {}).values() if isinstance(step, Mapping)
                )
                child_failed = step_failed or str(result.get("execution_status") or result.get("status") or "").casefold() in {"failed", "unknown", "cancelled"}
                return {**dict(result), "device_id": device_id, "execution_status": "failed" if child_failed else "succeeded"}, child_failed
            except Exception as exc:
                return {"device_id": device_id, "status": "failed", "execution_status": "failed", "error": {"message": str(exc)}}, True
            finally:
                if lease is not None:
                    self._resources.release(lease)
        rows: dict[int, tuple[dict[str, Any], bool]] = {}
        next_index = 0
        stopped = False
        device_locks: dict[str, asyncio.Lock] = {}

        async def worker() -> None:
            nonlocal next_index, stopped
            while not stopped and next_index < len(devices):
                index = next_index
                next_index += 1
                device = devices[index]
                try:
                    lock_key = device_id_value(device)
                except ValueError:
                    lock_key = f"invalid-device-{index}"
                lock = device_locks.setdefault(lock_key, asyncio.Lock())
                # Duplicate device IDs must never share a terminal concurrently.
                async with lock:
                    if stopped:
                        return
                    row = await run_device(index, device)
                rows[index] = row
                if row[1] and failure_strategy == "stop":
                    stopped = True

        workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, len(devices)))]
        try:
            await asyncio.gather(*workers)
        finally:
            for worker_task in workers:
                if not worker_task.done():
                    worker_task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        results = [row[0] for _, row in sorted(rows.items())]
        failed = sum(row[1] for row in rows.values())
        succeeded = len(results) - failed
        status = ActivityStatus.FAILED if failed and failure_strategy == "stop" else ActivityStatus.SUCCEEDED
        return ActivityResult(status, outputs={"devices": list(devices), "results": results, "count": len(results), "succeeded": succeeded, "failed": failed, "status": "partial_failure" if failed else "completed"}, error={"code": "device_child_failed", "message": "device iteration failed", "class": "deterministic"} if status == ActivityStatus.FAILED else None)

    async def _run_steps(
        self, steps: list[dict[str, Any]], local: dict[str, Any], context: ActivityContext,
        report: Any, invocation: ActivityInvocation,
    ) -> dict[str, Any]:
        outputs = dict(invocation.inputs.get("scope_outputs") or {})
        step_results: dict[str, Any] = {}
        result: dict[str, Any] = {}
        for step in steps:
            step_id = str(step["id"])
            inputs = TaskOrchestrator._resolve_inputs(
                step.get("action_inputs") or {}, {**outputs, **local, "outputs": outputs},
            )
            inputs.setdefault("device_id", local["device_id"])
            if device_id_value(inputs["device_id"]) != local["device_id"]:
                raise ValueError(f"step {step_id} must target the current loop device")
            inputs["device_id"] = local["device_id"]
            retry = step.get("retry_policy") or {}
            repeat = step.get("repeat_policy") or {}
            attempts = int(retry.get("max_attempts", 1))
            for _iteration in range(int(repeat.get("max_iterations", 1))):
                for attempt in range(attempts):
                    try:
                        report(Event(type="device.for_each.step.started", run_id=invocation.workflow_run_id,
                                     action_id=step_id, source="workflow.utility",
                                     payload={"step_id": step_id, "device_id": local["device_id"], "index": local["index"]}))
                        values = {**context.invocation.context, "step_id": step_id}
                        child_context = replace(context, invocation=replace(context.invocation, context=values))
                        result = dict(await self._child_runner(str(step["action_id"]), inputs, child_context, report))
                        break
                    except Exception as exc:
                        if attempt + 1 < attempts:
                            await asyncio.sleep(float(retry.get("backoff_seconds", 0)))
                        elif retry.get("on_failure") == "continue":
                            result = {"status": "failed", "error": {"message": str(exc)}}
                        else:
                            raise RuntimeError(f"step {step_id}: {exc}") from exc
            outputs[step_id] = result
            step_results[step_id] = result
            if step["action_id"] == "variable.set" and result.get("name"):
                outputs[str(result["name"])] = result.get("value")
            values = TaskOrchestrator._context_with_target_output(context.invocation.context, result)
            context = replace(context, invocation=replace(context.invocation, context=values))
        return {**result, "steps": step_results}


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
        if timeout_seconds < 0 or timeout_seconds > 86_400:
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
        if bool(invocation.inputs.get("send_enter", False)):
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
        steps = invocation.inputs.get("action_steps")
        condition = str(invocation.inputs.get("condition") or "").strip()
        if (not action_id and not steps) or not condition or self._child_runner is None:
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
                if steps:
                    child_result = await self._run_steps(
                        steps,
                        {"iteration": iteration, "result": previous_result, "outputs": previous_result},
                        context,
                        report,
                        invocation,
                    )
                else:
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
                    child_result = dict(await self._child_runner(action_id, child_inputs, context, report))
            except Exception as exc:
                child_result = {"status": "failed", "output": "", "error": {"message": str(exc)}}
                try:
                    failure_matched = bool(evaluate_expression(condition, {"result": child_result, "iteration": iteration, "outputs": child_result}))
                except ValueError:
                    failure_matched = False
                if failure_matched:
                    results.append(child_result)
                    return ActivityResult(ActivityStatus.SUCCEEDED, outputs={"status": "matched", "matched": True, "iterations": iteration, "result": child_result, "results": results})
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
        if condition.lower() in {"false", "0"}:
            return ActivityResult(
                ActivityStatus.SUCCEEDED,
                outputs={
                    "status": "max_iterations",
                    "matched": False,
                    "iterations": max_iterations,
                    "result": results[-1] if results else {},
                    "results": results,
                },
                evidence=({"kind": "until", "iterations": max_iterations},),
            )
        return ActivityResult(ActivityStatus.FAILED, outputs={"status": "exhausted", "matched": False, "iterations": max_iterations, "result": results[-1] if results else {}, "results": results}, error={"code": "loop_until_exhausted", "message": "loop.until reached max_iterations without matching condition", "class": "timeout"})

    async def _run_steps(
        self, steps: list[dict[str, Any]], local: dict[str, Any], context: ActivityContext,
        report: Any, invocation: ActivityInvocation,
    ) -> dict[str, Any]:
        outputs = dict(invocation.inputs.get("scope_outputs") or {})
        step_results: dict[str, Any] = {}
        result: dict[str, Any] = {}
        for step in steps:
            inputs = TaskOrchestrator._resolve_inputs(
                step.get("action_inputs") or {}, {**outputs, **local, "outputs": outputs},
            )
            result = dict(await self._child_runner(str(step["action_id"]), inputs, context, report))
            step_id = str(step["id"])
            outputs[step_id] = result
            step_results[step_id] = result
        return {**result, "steps": step_results}

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
        key = str(invocation.inputs.get("key") or "").strip()
        if not key:
            key = str(invocation.context.get("node_id") or invocation.context.get("step_id") or "result").strip() or "result"
        value = invocation.inputs.get("value", invocation.inputs.get("data"))
        return ActivityResult(
            status=ActivityStatus.SUCCEEDED,
            outputs={"status": "saved", "key": key, "value": value},
            evidence=({"kind": "result_saved", "key": key},),
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


class WorkflowOutputsActivityHandler:
    """Project a child Workflow's declared outputs onto its call node."""

    activity_id = "workflow.outputs"

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        del context, report
        raw_values = invocation.inputs.get("values")
        values = dict(raw_values) if isinstance(raw_values, Mapping) else {}
        workflow_id = str(invocation.inputs.get("workflow_id") or "")
        try:
            version = int(invocation.inputs.get("version"))
        except (TypeError, ValueError):
            return ActivityResult(
                ActivityStatus.FAILED,
                outputs={"status": "failed", "workflow_id": workflow_id, "version": 0, "outputs": {}},
                error={"code": "workflow_outputs_invalid", "message": "workflow output version must be an integer", "class": "deterministic"},
            )
        projected = {
            "status": "succeeded",
            "workflow_id": workflow_id,
            "version": version,
            "outputs": values,
            **values,
        }
        return ActivityResult(
            ActivityStatus.SUCCEEDED,
            outputs=projected,
            evidence=({"kind": "workflow_outputs", "workflow_id": workflow_id, "version": version},),
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del invocation, context


__all__ = ["DeviceSelectActivityHandler", "ExpressionActivityHandler", "ForEachActivityHandler", "ResultSaveActivityHandler", "TerminalWaitActivityHandler", "UntilActivityHandler", "VariableSetActivityHandler", "WaitActivityHandler", "WorkflowOutputsActivityHandler"]
