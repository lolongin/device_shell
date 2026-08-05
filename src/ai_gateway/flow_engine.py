"""Flow orchestration: sequential steps with dependency gating, wait conditions, bounded retry."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_FLOW_STEPS = 20
MAX_RETRIES = 5
MAX_WAIT_ATTEMPTS = 60


class FlowPlanError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class FlowStep:
    id: str
    command: str
    depends_on: list[str] = field(default_factory=list)
    retry: dict[str, Any] | None = None
    wait_condition: dict[str, Any] | None = None
    timeout_seconds: int = 30


@dataclass(slots=True)
class FlowStepResult:
    id: str
    status: str  # success | failed | skipped
    output: str = ""
    error_code: str = ""
    message: str = ""
    attempt_count: int = 1


@dataclass(slots=True)
class FlowPlan:
    steps: list[FlowStep]
    max_steps: int = MAX_FLOW_STEPS


def parse_flow(data: dict[str, Any]) -> FlowPlan:
    if not isinstance(data, dict):
        raise FlowPlanError("invalid_flow", "Flow 必须是对象。")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise FlowPlanError("invalid_flow", "Flow 至少需要一个步骤。")
    if len(raw_steps) > MAX_FLOW_STEPS:
        raise FlowPlanError("too_many_steps", f"Flow 最多允许 {MAX_FLOW_STEPS} 个步骤。")
    ids = set()
    steps: list[FlowStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise FlowPlanError("invalid_flow", "Flow 步骤必须是对象。")
        step_id = str(raw.get("id") or "").strip()
        if not step_id:
            raise FlowPlanError("invalid_flow", "Flow 步骤缺少 id。")
        if step_id in ids:
            raise FlowPlanError("duplicate_step", f"Flow 步骤 id 重复: {step_id}")
        ids.add(step_id)
        command = str(raw.get("command") or "").strip()
        if not command:
            raise FlowPlanError("invalid_flow", f"步骤 {step_id} 缺少 command。")
        depends_on = [
            str(dep).strip()
            for dep in (raw.get("depends_on") or [])
            if isinstance(dep, str)
        ]
        retry = raw.get("retry")
        if retry is not None:
            retry = _validate_retry(retry, step_id)
        wait_condition = raw.get("wait_condition")
        if wait_condition is not None:
            wait_condition = _validate_wait_condition(wait_condition, step_id)
        timeout_seconds = _bounded_int(
            raw.get("timeout_seconds", 30),
            1,
            300,
            f"步骤 {step_id} timeout_seconds",
        )
        steps.append(
            FlowStep(
                id=step_id,
                command=command,
                depends_on=depends_on,
                retry=retry,
                wait_condition=wait_condition,
                timeout_seconds=timeout_seconds,
            )
        )
    for step in steps:
        for dep in step.depends_on:
            if dep not in ids:
                raise FlowPlanError(
                    "unknown_dependency",
                    f"步骤 {step.id} 依赖未知步骤: {dep}",
                )
    return FlowPlan(steps)


def _validate_retry(raw: Any, step_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FlowPlanError("invalid_flow", f"步骤 {step_id} retry 必须是对象。")
    if str(raw.get("on_status") or "") != "failed":
        raise FlowPlanError(
            "invalid_flow",
            f"步骤 {step_id} retry.on_status 目前只支持 failed。",
        )
    max_retries = _bounded_int(raw.get("max", 0), 0, MAX_RETRIES, f"步骤 {step_id} retry.max")
    interval_ms = _bounded_int(raw.get("interval_ms", 1000), 1, 60_000, f"步骤 {step_id} retry.interval_ms")
    return {"max": max_retries, "interval_ms": interval_ms, "on_status": "failed"}


def _validate_wait_condition(raw: Any, step_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FlowPlanError("invalid_flow", f"步骤 {step_id} wait_condition 必须是对象。")
    if str(raw.get("type") or "") != "command_output_contains":
        raise FlowPlanError(
            "invalid_flow",
            f"步骤 {step_id} wait_condition 类型目前只支持 command_output_contains。",
        )
    command = str(raw.get("command") or "").strip()
    expected = str(raw.get("expected") or "").strip()
    if not command or not expected:
        raise FlowPlanError(
            "invalid_flow",
            f"步骤 {step_id} wait_condition 需要 command 和 expected。",
        )
    interval_ms = _bounded_int(raw.get("interval_ms", 2000), 1, 60_000, f"步骤 {step_id} wait_condition.interval_ms")
    max_attempts = _bounded_int(raw.get("max_attempts", 15), 1, MAX_WAIT_ATTEMPTS, f"步骤 {step_id} wait_condition.max_attempts")
    return {
        "type": "command_output_contains",
        "command": command,
        "expected": expected,
        "interval_ms": interval_ms,
        "max_attempts": max_attempts,
    }


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise FlowPlanError("invalid_flow", f"{label} 必须是整数。") from exc
    if number < minimum or number > maximum:
        raise FlowPlanError(
            "invalid_flow",
            f"{label} 必须在 {minimum} 到 {maximum} 之间。",
        )
    return number


class FlowEngine:
    def run(
        self,
        plan: FlowPlan,
        *,
        session_id: str,
        device_id: str,
        execute_step: Callable[[str, str, int], tuple[str, str]],
        wait_for_condition: Callable[[dict[str, Any], str, str], tuple[str, str]],
        clock: Callable[[], float] = time.monotonic,
    ) -> list[FlowStepResult]:
        results: list[FlowStepResult] = []
        completed: set[str] = set()
        failed: set[str] = set()
        for step in plan.steps:
            deps = set(step.depends_on)
            if deps & failed:
                results.append(FlowStepResult(step.id, "skipped", message="依赖步骤失败。"))
                continue
            missing = deps - completed
            if missing:
                results.append(FlowStepResult(step.id, "skipped", message="依赖步骤未完成。"))
                continue
            result = self._run_step(step, session_id, device_id, execute_step, wait_for_condition, clock)
            results.append(result)
            if result.status == "success":
                completed.add(step.id)
            else:
                failed.add(step.id)
        return results

    def _run_step(
        self,
        step: FlowStep,
        session_id: str,
        device_id: str,
        execute_step: Callable[[str, str, int], tuple[str, str]],
        wait_for_condition: Callable[[dict[str, Any], str, str], tuple[str, str]],
        clock: Callable[[], float],
    ) -> FlowStepResult:
        if step.wait_condition is not None:
            attempts = 0
            max_attempts = int(step.wait_condition.get("max_attempts", 15))
            interval_ms = int(step.wait_condition.get("interval_ms", 2000))
            status, output = "", ""
            while attempts < max_attempts:
                attempts += 1
                status, output = wait_for_condition(step.wait_condition, session_id, device_id)
                if status == "success":
                    break
                if attempts < max_attempts and interval_ms > 0:
                    clock()  # placeholder; real sleep is supplied by the coordinator
            if status != "success":
                return FlowStepResult(
                    step.id,
                    "failed",
                    output=output,
                    error_code="condition_timeout",
                    message="等待条件超时。",
                )
        attempts = 0
        max_retries = int((step.retry or {}).get("max", 0))
        interval_ms = int((step.retry or {}).get("interval_ms", 1000))
        last_status, last_output, last_error, last_message = "failed", "", "", ""
        while attempts <= max_retries:
            attempts += 1
            status, output = execute_step(step.command, session_id, step.timeout_seconds)
            if status == "success":
                return FlowStepResult(step.id, "success", output=output, attempt_count=attempts)
            last_status, last_output = status, output
            last_error = "execution_failed"
            last_message = f"步骤 {step.id} 执行失败。"
            if attempts > max_retries:
                break
            if interval_ms > 0:
                clock()  # placeholder; real sleep uses the same schedule mechanism as executor
        return FlowStepResult(
            step.id,
            "failed",
            output=last_output,
            error_code=last_error,
            message=last_message,
            attempt_count=attempts,
        )
