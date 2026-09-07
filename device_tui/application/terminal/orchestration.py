"""Event-driven terminal interaction plans and per-session execution leases."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from .execution import detect_terminal_prompt, strip_terminal_ansi
from .outcome import (
    INTERACTION_PROMPT_TYPES,
    PromptMatch,
    classify_command_outcome,
    classify_terminal_prompt,
)


MAX_PLAN_STEPS = 100
MAX_MATCH_TEXT = 512
MAX_STEP_OUTPUT_CHARS = 32_768
CONTROL_TEXT = {
    "enter": "\r",
    "space": " ",
    "ctrl_c": "\x03",
    "ctrl_y": "\x19",
}
TERMINAL_STATUSES = {
    "completed",
    "failed",
    "timed_out",
    "cancelled",
    "cancelled_by_user",
    "disconnected",
}
PROMPT_ALIASES = {
    "device_prompt",
    "ftp_prompt",
    "username_prompt",
    "password_prompt",
    "host_key_prompt",
    "pagination_prompt",
    "confirmation_prompt",
}
RESPONSE_RETRY_DELAY_MS = 120
DEFAULT_PAGINATION_MAX_MATCHES = 100
MAX_EXECUTION_EVENTS = 200


class TerminalPlanError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class TerminalInput:
    text: str
    sensitive: bool = False
    secret_ref: str = ""


@dataclass(frozen=True, slots=True)
class ResponseRule:
    match: str
    text: str = ""
    control: str = ""
    secret_ref: str = ""
    append_enter: bool = True
    case_sensitive: bool = False
    max_matches: int = 1


@dataclass(frozen=True, slots=True)
class SendStep:
    text: str = ""
    control: str = ""
    secret_ref: str = ""
    secret_prefix: str = ""
    secret_suffix: str = ""
    append_enter: bool = True
    label: str = ""
    name: str = ""
    next_step: int | None = None


@dataclass(frozen=True, slots=True)
class ExpectStep:
    success: tuple[str, ...] = ()
    pattern: str = ""
    responses: tuple[ResponseRule, ...] = ()
    failures: tuple[str, ...] = ()
    success_markers: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    idle_seconds: float = 0.0
    case_sensitive: bool = False
    max_output_chars: int = 16_384
    timeout_code: str = "step_timeout"
    label: str = ""
    name: str = ""
    on_match: str = ""
    on_failure: str = ""
    max_retries: int = 0
    disconnect_is_success: bool = False
    success_target: int | None = None


@dataclass(frozen=True, slots=True)
class WaitStateStep:
    state: str
    timeout_seconds: float = 60.0
    label: str = ""
    name: str = ""
    on_match: str = ""
    on_failure: str = ""
    max_retries: int = 0
    timeout_code: str = "step_timeout"


TerminalStep = SendStep | ExpectStep | WaitStateStep


@dataclass(frozen=True, slots=True)
class TerminalExecutionPlan:
    steps: tuple[TerminalStep, ...]
    total_timeout_seconds: float = 60.0


@dataclass(slots=True)
class TerminalStepResult:
    index: int
    type: str
    status: str
    label: str
    started_monotonic: float
    completed_monotonic: float = 0.0
    output: str = ""
    matched: str = ""
    response_count: int = 0
    responses_sent: list[str] = field(default_factory=list)
    error_code: str = ""
    message: str = ""

    def public_dict(self, *, secrets: tuple[str, ...] = ()) -> dict[str, Any]:
        output = _redact_values(self.output, secrets)
        return {
            "index": self.index,
            "type": self.type,
            "status": self.status,
            "label": self.label,
            "output": output,
            "matched": self.matched,
            "response_count": self.response_count,
            "responses_sent": list(self.responses_sent),
            "duration_ms": round(
                max(0.0, self.completed_monotonic - self.started_monotonic) * 1000,
                2,
            ),
            "error_code": self.error_code,
            "message": self.message,
        }


def parse_terminal_plan(
    steps: list[dict[str, Any]],
    *,
    total_timeout_seconds: float = 60.0,
) -> TerminalExecutionPlan:
    if not isinstance(steps, list) or not steps:
        raise TerminalPlanError("invalid_plan", "交互计划至少需要一个步骤。")
    if len(steps) > MAX_PLAN_STEPS:
        raise TerminalPlanError(
            "invalid_plan",
            f"交互计划最多允许 {MAX_PLAN_STEPS} 个步骤。",
        )
    total_timeout = _number(
        total_timeout_seconds,
        "total_timeout_seconds",
        minimum=1,
        maximum=3600,
    )
    parsed: list[TerminalStep] = []
    for index, raw in enumerate(_normalize_compat_steps(steps)):
        if not isinstance(raw, dict):
            raise TerminalPlanError("invalid_plan", f"步骤 {index} 必须是对象。")
        kind = str(raw.get("type") or "").strip().casefold()
        if kind == "send":
            parsed.append(_parse_send_step(raw, index))
        elif kind == "expect":
            parsed.append(_parse_expect_step(raw, index))
        elif kind == "wait_state":
            parsed.append(_parse_wait_state_step(raw, index))
        else:
            raise TerminalPlanError(
                "invalid_plan",
                f"步骤 {index} 类型无效: {kind or '<empty>'}",
            )
    _validate_plan_branches(parsed)
    _validate_numeric_transitions(parsed)
    return TerminalExecutionPlan(tuple(parsed), total_timeout)


def _normalize_compat_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept the declarative interaction vocabulary as an input adapter."""
    normalized: list[dict[str, Any]] = []
    for raw in steps:
        item = dict(raw)
        action = str(item.get("action") or item.get("type") or "").strip().casefold()
        if action == "done":
            continue
        if action == "send":
            item["type"] = "send"
            if "enter" in item and "append_enter" not in item:
                item["append_enter"] = bool(item.pop("enter"))
            expected = item.pop("expect_prompt", None)
            normalized.append(item)
            if expected:
                normalized.append({
                    "type": "expect",
                    "pattern": str(expected),
                    "success": [str(expected)],
                    "label": f"expect {expected}",
                })
            continue
        if action == "expect":
            item["type"] = "expect"
            match = item.pop("match", None)
            if match is not None and "pattern" not in item and "success" not in item:
                item["pattern"] = str(match)
            response = item.pop("respond", None)
            if response is not None and "responses" not in item:
                if not isinstance(response, dict):
                    raise TerminalPlanError("invalid_plan", "expect.respond 必须是对象。")
                item["responses"] = [{"match": str(match or item.get("pattern") or ""), **response}]
            normalized.append(item)
            continue
        normalized.append(item)
    return normalized


def build_batch_plan(
    commands: list[str],
    *,
    command_timeout_seconds: float = 30.0,
    total_timeout_seconds: float | None = None,
    max_output_chars: int = 16_384,
    terminal_prompt: str = "",
    failure_patterns: list[str] | tuple[str, ...] = (),
) -> TerminalExecutionPlan:
    if not isinstance(commands, list) or not commands or len(commands) > 50:
        raise TerminalPlanError("invalid_plan", "批量命令数量必须在 1 到 50 之间。")
    timeout = _number(
        command_timeout_seconds,
        "command_timeout_seconds",
        minimum=1,
        maximum=300,
    )
    output_limit = int(
        _number(
            max_output_chars,
            "max_output_chars_per_step",
            minimum=1,
            maximum=MAX_STEP_OUTPUT_CHARS,
        )
    )
    steps: list[TerminalStep] = []
    for index, raw_command in enumerate(commands):
        command = str(raw_command).strip()
        if not command:
            raise TerminalPlanError("invalid_plan", f"命令 {index} 不能为空。")
        if len(command) > 16_384:
            raise TerminalPlanError("invalid_plan", f"命令 {index} 过长。")
        steps.extend(
            (
                SendStep(text=command, append_enter=True, label=command),
                ExpectStep(
                    success=(terminal_prompt or "device_prompt",),
                    responses=(
                        ResponseRule(
                            match="pagination_prompt",
                            control="space",
                            append_enter=False,
                            max_matches=DEFAULT_PAGINATION_MAX_MATCHES,
                        ),
                    ),
                    failures=tuple(failure_patterns) or (
                        "Error:",
                        "Unrecognized command",
                        "Unknown command",
                        "Incomplete command",
                    ),
                    timeout_seconds=timeout,
                    idle_seconds=0 if terminal_prompt or failure_patterns else 0.8,
                    max_output_chars=output_limit,
                    label=command,
                ),
            )
        )
    total = total_timeout_seconds
    if total is None:
        total = 60.0
    total = _number(
        total,
        "total_timeout_seconds",
        minimum=1,
        maximum=3600,
    )
    return TerminalExecutionPlan(tuple(steps), total)


class TerminalExecutionRunner:
    def __init__(
        self,
        *,
        execution_id: str,
        session_id: str,
        device_id: str,
        plan: TerminalExecutionPlan,
        send_input: Callable[[str, TerminalInput, str], None],
        resolve_secret: Callable[[str], str],
        schedule: Callable[[int, Callable[[], None]], None],
        on_finished: Callable[["TerminalExecutionRunner"], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.execution_id = execution_id
        self.session_id = session_id
        self.device_id = device_id
        self.plan = plan
        self.send_input = send_input
        self.resolve_secret = resolve_secret
        self.schedule = schedule
        self.on_finished = on_finished
        self.clock = clock
        self.status = "pending"
        self.error_code = ""
        self.message = ""
        self.current_step = 0
        self.started_monotonic = 0.0
        self.completed_monotonic = 0.0
        self.step_results: list[TerminalStepResult] = []
        self._active_result: TerminalStepResult | None = None
        self._scan_buffer = ""
        self._response_counts: dict[int, int] = {}
        self._branch_counts: dict[tuple[int, int, str], int] = {}
        self._known_secrets: list[str] = []
        self._events: list[dict[str, Any]] = []
        self._event_cursor = 0
        self._last_output = ""
        self._matched_prompt = ""
        self._interaction_prompt: PromptMatch | None = None
        self._answered_interaction_prompt = ""
        self._step_token = 0
        self._last_output_monotonic = 0.0
        self._completion_event = threading.Event()
        self._attention_event = threading.Event()
        self._done_callbacks: list[Callable[["TerminalExecutionRunner"], None]] = []
        self._lock = threading.RLock()
        self._event_condition = threading.Condition(self._lock)

    @property
    def completion_event(self) -> threading.Event:
        return self._completion_event

    @property
    def attention_event(self) -> threading.Event:
        """Signal completion or an unhandled prompt that needs caller input."""
        return self._attention_event

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def start(self) -> None:
        with self._lock:
            if self.status != "pending":
                return
            self.status = "running"
            self.started_monotonic = self.clock()
            self._record_event_locked("started")
            total_token = self._step_token
            self.schedule(
                int(self.plan.total_timeout_seconds * 1000),
                lambda token=total_token: self._on_total_timeout(token),
            )
            self._advance_locked()

    def on_output(self, message: str) -> None:
        if not message:
            return
        with self._lock:
            if self.status != "running":
                return
            step = self._current_plan_step()
            if not isinstance(step, ExpectStep) or self._active_result is None:
                return
            self._last_output_monotonic = self.clock()
            self._active_result.output = (
                self._active_result.output + message
            )[-step.max_output_chars :]
            self._last_output = self._active_result.output
            self._record_event_locked("output", data=message[-4096:])
            self._scan_buffer = (
                self._scan_buffer + strip_terminal_ansi(message)
            )[-step.max_output_chars :]
            # Interaction takes priority over failure matching: a confirmation
            # prompt that itself contains a failure-looking word (e.g. an
            # "error" mention on a "Continue? [Y/N]" line) must still be
            # answered, not aborted. Apply responses first; only when no
            # response was triggered do we treat a failure word as fatal.
            self._interaction_prompt = None
            self._evaluate_expect_locked(step)

    def on_session_state(self, state: str) -> None:
        normalized = str(state).strip().casefold()
        with self._lock:
            if self.status != "running":
                return
            step = self._current_plan_step()
            if isinstance(step, WaitStateStep) and normalized == step.state:
                self._finish_active_step_locked("completed", matched=normalized)
                if not self._take_branch_locked(step, step.on_match, reason="match"):
                    self.current_step += 1
                    self._advance_locked()
                return
            if normalized in {"disconnected", "closed", "failed"} and isinstance(step, ExpectStep) and step.disconnect_is_success:
                self._finish_active_step_locked("completed", matched="disconnected")
                if not self._take_branch_locked(step, step.on_match, reason="disconnect"):
                    self.current_step += 1
                    self._advance_locked()
                return
            if normalized in {"disconnected", "closed", "failed"} and not (
                isinstance(step, WaitStateStep) and step.state == normalized
            ):
                if self._active_result is not None:
                    self._finish_active_step_locked(
                        "disconnected",
                        error_code="session_disconnected",
                        message=f"终端会话状态变为 {normalized}。",
                    )
                self._finish_locked(
                    "disconnected",
                    error_code="session_disconnected",
                    message=f"终端会话状态变为 {normalized}。",
                )

    def cancel(self, *, by_user: bool = False) -> None:
        with self._lock:
            if self.is_terminal:
                return
            status = "cancelled_by_user" if by_user else "cancelled"
            code = "cancelled_by_user" if by_user else "execution_cancelled"
            message = "用户输入已接管终端。" if by_user else "执行已取消。"
            if self._active_result is not None:
                self._finish_active_step_locked(
                    status,
                    error_code=code,
                    message=message,
                )
            self._finish_locked(status, error_code=code, message=message)

    def send_manual_input(
        self,
        *,
        text: str = "",
        control: str = "",
        secret_ref: str = "",
        append_enter: bool = True,
    ) -> None:
        with self._lock:
            if self.status != "running":
                raise TerminalPlanError(
                    "execution_not_running",
                    "终端执行当前不可接收输入。",
                )
            step = self._current_plan_step()
            if not isinstance(step, ExpectStep):
                raise TerminalPlanError(
                    "input_not_expected",
                    "当前步骤不是等待输入的交互步骤。",
                )
            if self._answered_interaction_prompt:
                raise TerminalPlanError(
                    "duplicate_response",
                    "当前交互点已经收到应答。",
                    details={"prompt": self._answered_interaction_prompt},
                )
            normalized_control = str(control or "").strip().casefold()
            values = [bool(str(text or "")), bool(normalized_control), bool(str(secret_ref or ""))]
            if sum(values) != 1:
                raise TerminalPlanError(
                    "invalid_input",
                    "输入必须且只能提供 text、control 或 secret_ref 之一。",
                )
            if normalized_control and normalized_control not in CONTROL_TEXT:
                raise TerminalPlanError(
                    "invalid_input",
                    f"不支持的控制键: {normalized_control}",
                )
            payload = self._input_for(
                text=str(text or ""),
                control=normalized_control,
                secret_ref=str(secret_ref or ""),
                append_enter=append_enter,
            )
            if (
                self._interaction_prompt is not None
                and re.search(r"password|passphrase", self._interaction_prompt.text, re.IGNORECASE)
                and not payload.sensitive
            ):
                raise TerminalPlanError(
                    "secret_required",
                    "密码提示只能使用 secret_ref。",
                )
            self._matched_prompt = ""
            self._record_event_locked(
                "manual_input",
                data="[redacted]" if payload.sensitive else payload.text,
                control=normalized_control,
            )
            self.send_input(self.session_id, payload, self.execution_id)
            prompt = self._interaction_prompt
            self._interaction_prompt = None
            if prompt is not None:
                self._answered_interaction_prompt = prompt.text
            self._attention_event.clear()
            # A plan using indexed success targets treats the answered prompt
            # as the completed expect transition. Legacy plans that wait for
            # ``device_prompt`` remain on the same expect until the device
            # emits its final prompt after the answer.
            if prompt is not None and step.success_target is not None:
                self._complete_expect_locked(step, prompt.text)
                return
            # The prompt that caused the pause has already been consumed by
            # the caller's answer. Do not match that same prompt again.
            self._scan_buffer = ""

    def resume(self) -> None:
        with self._lock:
            if self.status != "cancelled_by_user":
                raise TerminalPlanError(
                    "execution_not_resumable",
                    "只有被用户接管的终端执行可以恢复。",
                )
            if self.step_results and self.step_results[-1].index == self.current_step:
                self.step_results.pop()
            self.status = "running"
            self.error_code = ""
            self.message = ""
            self.completed_monotonic = 0.0
            self._completion_event.clear()
            self.started_monotonic = self.clock()
            self._active_result = None
            self._scan_buffer = ""
            self._response_counts = {}
            self._interaction_prompt = None
            self._answered_interaction_prompt = ""
            self._attention_event.clear()
            self._step_token += 1
            self._record_event_locked("resumed")
            total_token = self._step_token
            self.schedule(
                int(self.plan.total_timeout_seconds * 1000),
                lambda token=total_token: self._on_total_timeout(token),
            )
            self._advance_locked()

    def add_done_callback(
        self,
        callback: Callable[["TerminalExecutionRunner"], None],
    ) -> None:
        with self._lock:
            if self.is_terminal:
                callback(self)
                return
            self._done_callbacks.append(callback)

    def public_dict(self) -> dict[str, Any]:
        return self.snapshot()

    def snapshot(self, *, since_cursor: int = 0) -> dict[str, Any]:
        with self._lock:
            now = self.completed_monotonic or self.clock()
            secrets = tuple(value for value in self._known_secrets if value)
            step_results = [
                result.public_dict(secrets=secrets) for result in self.step_results
            ]
            if (
                self._active_result is not None
                and self._active_result not in self.step_results
            ):
                active = TerminalStepResult(
                    index=self._active_result.index,
                    type=self._active_result.type,
                    status=self._active_result.status,
                    label=self._active_result.label,
                    started_monotonic=self._active_result.started_monotonic,
                    completed_monotonic=now,
                    output=self._active_result.output,
                    matched=self._active_result.matched,
                    response_count=self._active_result.response_count,
                    responses_sent=list(self._active_result.responses_sent),
                    error_code=self._active_result.error_code,
                    message=self._active_result.message,
                )
                step_results.append(active.public_dict(secrets=secrets))
            command_results = self._command_results_locked(
                step_results,
                duration_ms=(
                    round(max(0.0, now - self.started_monotonic) * 1000, 2)
                    if self.started_monotonic
                    else 0.0
                ),
            )
            outcome = self._aggregate_outcome_locked(
                command_results,
                secrets=secrets,
            )
            return {
                "execution_id": self.execution_id,
                "session_id": self.session_id,
                "device_id": self.device_id,
                "status": self.status,
                "phase": self._phase_locked(),
                "current_step": self.current_step,
                "total_steps": len(self.plan.steps),
                "waiting_for": self._waiting_for_locked(),
                "last_output": _redact_values(self._last_output, secrets),
                "matched_prompt": _redact_values(self._matched_prompt, secrets),
                "can_send": self.status == "running" and isinstance(self._current_plan_step(), ExpectStep),
                "can_cancel": not self.is_terminal,
                "can_resume": self.status == "cancelled_by_user",
                "event_cursor": self._event_cursor,
                "events": [
                    self._redacted_event_locked(item, secrets)
                    for item in self._events
                    if int(item.get("cursor", 0)) > since_cursor
                ],
                "steps": step_results,
                "outcome": outcome,
                "command_results": command_results,
                "duration_ms": round(
                    max(0.0, now - self.started_monotonic) * 1000,
                    2,
                )
                if self.started_monotonic
                else 0.0,
                "error_code": self.error_code,
                "message": self.message,
                "failed_step": next(
                    (
                        item for item in reversed(step_results)
                        if item.get("status") in {"timed_out", "failed"}
                    ),
                    None,
                ),
                "lease_released": self.is_terminal,
            }

    def wait_for_event(self, since_cursor: int = 0, timeout_seconds: float = 0.0) -> dict[str, Any]:
        """Wait until a newer event exists or the execution reaches a terminal state."""
        deadline = self.clock() + max(0.0, float(timeout_seconds))
        with self._event_condition:
            while self._event_cursor <= int(since_cursor) and not self.is_terminal:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    break
                self._event_condition.wait(remaining)
            return self.snapshot(since_cursor=since_cursor)

    @staticmethod
    def _redacted_event_locked(
        event: dict[str, Any],
        secrets: tuple[str, ...],
    ) -> dict[str, Any]:
        public = dict(event)
        for key in ("data", "matched", "message"):
            value = public.get(key)
            if isinstance(value, str):
                public[key] = _redact_values(value, secrets)
        return public

    def _record_event_locked(self, event_type: str, *, data: str = "", **fields: Any) -> None:
        self._event_cursor += 1
        event: dict[str, Any] = {
            "cursor": self._event_cursor,
            "type": event_type,
            "timestamp": self.clock(),
        }
        if data:
            event["data"] = data[-4096:]
        event.update({key: value for key, value in fields.items() if value not in ("", None)})
        self._events.append(event)
        if len(self._events) > MAX_EXECUTION_EVENTS:
            del self._events[: len(self._events) - MAX_EXECUTION_EVENTS]
        self._event_condition.notify_all()

    def _phase_locked(self) -> str:
        if self.status != "running":
            return self.status
        step = self._current_plan_step()
        if isinstance(step, ExpectStep):
            return "waiting_for_input" if self._interaction_prompt else "waiting_for_output"
        if isinstance(step, WaitStateStep):
            return "waiting_for_state"
        return "sending"

    def _waiting_for_locked(self) -> str:
        step = self._current_plan_step()
        if isinstance(step, ExpectStep):
            if self._interaction_prompt:
                return self._interaction_prompt.type
            return step.success[0] if step.success else "output"
        if isinstance(step, WaitStateStep):
            return step.state
        return ""

    def _command_results_locked(
        self,
        step_results: list[dict[str, Any]],
        *,
        duration_ms: float,
    ) -> list[dict[str, Any]]:
        results_by_index = {
            int(result.get("index", -1)): result
            for result in step_results
            if isinstance(result, dict)
        }
        command_results: list[dict[str, Any]] = []
        for index, step in enumerate(self.plan.steps):
            if not isinstance(step, ExpectStep):
                continue
            result = results_by_index.get(index)
            if result is None:
                continue
            command = self._command_before_locked(index)
            outcome = classify_command_outcome(
                str(result.get("output") or ""),
                lifecycle_status=str(result.get("status") or self.status),
                command=command,
                matched=str(result.get("matched") or self._matched_prompt),
                duration_ms=float(result.get("duration_ms") or duration_ms),
                failure_patterns=step.failures,
            )
            command_results.append(
                {
                    "step_index": index,
                    "command": command,
                    "outcome": outcome,
                }
            )
        return command_results

    def _command_before_locked(self, step_index: int) -> str:
        for candidate in reversed(self.plan.steps[:step_index]):
            if isinstance(candidate, SendStep):
                return candidate.label or candidate.text
            if isinstance(candidate, ExpectStep):
                break
        return ""

    def _aggregate_outcome_locked(
        self,
        command_results: list[dict[str, Any]],
        *,
        secrets: tuple[str, ...],
    ) -> dict[str, Any]:
        if not command_results:
            return classify_command_outcome(
                _redact_values(self._last_output, secrets),
                lifecycle_status=self.status,
                matched=_redact_values(self._matched_prompt, secrets),
                duration_ms=(
                    max(0.0, (self.completed_monotonic or self.clock()) - self.started_monotonic) * 1000
                    if self.started_monotonic
                    else 0.0
                ),
            )
        outcomes = [item["outcome"] for item in command_results]
        if len(outcomes) == 1:
            return dict(outcomes[0])
        statuses = {str(item.get("status") or "unknown") for item in outcomes}
        if "interaction_required" in statuses:
            status = "interaction_required"
        elif "failure" in statuses:
            status = "failure"
        elif statuses == {"success"} and self.status == "completed":
            status = "success"
        else:
            status = "unknown"
        last = dict(outcomes[-1])
        last.update(
            {
                "status": status,
                "finished": bool(self.status == "completed" and all(item.get("finished") for item in outcomes)),
                "command": "",
                "errors": [error for item in outcomes for error in item.get("errors", [])],
                "basis": f"batch_{status}",
                "duration_ms": round(
                    max(0.0, (self.completed_monotonic or self.clock()) - self.started_monotonic) * 1000,
                    2,
                )
                if self.started_monotonic
                else 0.0,
            }
        )
        return last

    def redact_text(self, text: str) -> str:
        with self._lock:
            return _redact_values(
                text,
                tuple(value for value in self._known_secrets if value),
            )

    def _advance_locked(self) -> None:
        while self.status == "running":
            if self.current_step >= len(self.plan.steps):
                self._finish_locked("completed", message="终端交互执行完成。")
                return
            step = self.plan.steps[self.current_step]
            if isinstance(step, SendStep):
                if self._run_send_locked(step):
                    return
                continue
            self._arm_wait_locked(step)
            return

    def _take_branch_locked(
        self,
        step: ExpectStep | WaitStateStep,
        target: str,
        *,
        reason: str,
    ) -> bool:
        if not target or target == "stop":
            return False
        source_index = self.current_step
        if target == "retry":
            target_index = source_index
        else:
            target_index = next(
                (
                    index
                    for index, candidate in enumerate(self.plan.steps)
                    if candidate.name == target
                ),
                -1,
            )
        if target_index < 0:
            self._finish_locked(
                "failed",
                error_code="invalid_branch",
                message=f"执行时找不到分支步骤: {target}",
            )
            return True
        if target_index <= source_index:
            key = (source_index, target_index, reason)
            count = self._branch_counts.get(key, 0) + 1
            self._branch_counts[key] = count
            if count > step.max_retries:
                self._finish_locked(
                    "failed",
                    error_code="branch_limit_exceeded",
                    message=f"步骤 {source_index} 的分支重试超过上限。",
                )
                return True
        self.current_step = target_index
        self._advance_locked()
        return True

    def _run_send_locked(self, step: SendStep) -> bool:
        result = TerminalStepResult(
            index=self.current_step,
            type="send",
            status="running",
            label=step.label,
            started_monotonic=self.clock(),
        )
        self._active_result = result
        target_step = step.next_step
        next_index = (
            target_step
            if target_step is not None
            else self.current_step + 1
        )
        next_step = (
            self.plan.steps[next_index]
            if next_index < len(self.plan.steps)
            else None
        )
        try:
            payload = self._input_for(
                text=step.text,
                control=step.control,
                secret_ref=step.secret_ref,
                secret_prefix=step.secret_prefix,
                secret_suffix=step.secret_suffix,
                append_enter=step.append_enter,
            )
            self._finish_active_step_locked("completed")
            self.current_step = next_index
            if isinstance(next_step, ExpectStep):
                self._arm_wait_locked(next_step)
            armed_index = self.current_step
            self.send_input(self.session_id, payload, self.execution_id)
            return (
                isinstance(next_step, ExpectStep)
                and self.status == "running"
                and self.current_step == armed_index
            )
        except TerminalPlanError as exc:
            self._finish_active_step_locked(
                "failed",
                error_code=exc.code,
                message=str(exc),
            )
            self._finish_locked("failed", error_code=exc.code, message=str(exc))
            return False

    def _arm_wait_locked(self, step: ExpectStep | WaitStateStep) -> None:
        self._step_token += 1
        self._scan_buffer = ""
        self._response_counts = {}
        self._last_output_monotonic = self.clock()
        kind = "expect" if isinstance(step, ExpectStep) else "wait_state"
        self._active_result = TerminalStepResult(
            index=self.current_step,
            type=kind,
            status="running",
            label=step.label,
            started_monotonic=self.clock(),
        )
        token = self._step_token
        self.schedule(
            int(step.timeout_seconds * 1000),
            lambda token=token: self._on_step_timeout(token),
        )

    def _apply_responses_locked(self, step: ExpectStep) -> None:
        matched_rule: tuple[int, ResponseRule, tuple[str, int]] | None = None
        for index, rule in enumerate(step.responses):
            found = _match_token(
                self._scan_buffer,
                rule.match,
                case_sensitive=rule.case_sensitive,
            )
            if found is None:
                continue
            if matched_rule is None or found[1] < matched_rule[2][1]:
                matched_rule = (index, rule, found)
        if matched_rule is None:
            return
        index, rule, found = matched_rule
        count = self._response_counts.get(index, 0) + 1
        self._response_counts[index] = count
        if count > rule.max_matches:
            self._finish_active_step_locked(
                "failed",
                matched=found[0],
                error_code="response_limit_exceeded",
                message=f"自动响应超过上限: {rule.match}",
            )
            self._finish_locked(
                "failed",
                error_code="response_limit_exceeded",
                message=f"步骤 {self.current_step} 自动响应超过上限。",
            )
            return
        try:
            payload = self._input_for(
                text=rule.text,
                control=rule.control,
                secret_ref=rule.secret_ref,
                append_enter=rule.append_enter,
            )
            if (
                re.search(r"password|passphrase", found[0], re.IGNORECASE)
                and not payload.sensitive
            ):
                self._finish_active_step_locked(
                    "failed",
                    matched=found[0],
                    error_code="secret_required",
                    message="密码提示只能使用 secret_ref。",
                )
                self._finish_locked(
                    "failed",
                    error_code="secret_required",
                    message="密码提示只能使用 secret_ref。",
                )
                return
        except TerminalPlanError as exc:
            self._finish_active_step_locked(
                "failed",
                error_code=exc.code,
                message=str(exc),
            )
            self._finish_locked("failed", error_code=exc.code, message=str(exc))
            return
        assert self._active_result is not None
        self._active_result.response_count += 1
        self._active_result.responses_sent.append(rule.match)
        self._matched_prompt = rule.match
        self._answered_interaction_prompt = rule.match
        self._record_event_locked(
            "auto_response",
            matched=rule.match,
            data="[redacted]" if payload.sensitive else payload.text,
            control=rule.control,
        )
        # Keep a coalesced next prompt as a deferred tail. Huawei VRP can
        # deliver the username and password prompts in one terminal event;
        # dropping the tail leaves the runner waiting forever because the
        # device has no reason to emit the already-delivered prompt again.
        self._scan_buffer = self._scan_buffer[found[1] :]
        self.send_input(self.session_id, payload, self.execution_id)
        if self._has_pending_response_locked(step):
            token = self._step_token
            self.schedule(
                RESPONSE_RETRY_DELAY_MS,
                lambda token=token: self._on_response_retry(token),
            )

    def _evaluate_expect_locked(self, step: ExpectStep) -> None:
        response_counts_before = dict(self._response_counts)
        self._apply_responses_locked(step)
        if self.status != "running":
            return
        responded = self._response_counts != response_counts_before
        prompt = classify_terminal_prompt(self._scan_buffer)
        if prompt is not None and prompt.type == "command_prompt":
            self._answered_interaction_prompt = ""
        elif prompt is not None and prompt.type in INTERACTION_PROMPT_TYPES:
            if prompt.text != self._answered_interaction_prompt:
                self._answered_interaction_prompt = ""
        expected_success = _first_match(
            self._scan_buffer,
            self._success_tokens(step),
            case_sensitive=step.case_sensitive,
        )
        if (
            prompt is not None
            and prompt.type in INTERACTION_PROMPT_TYPES
            and not responded
        ):
            # Indexed plans use the step immediately targeted by ``success``
            # as the confirmation response.  A confirmation prompt therefore
            # advances into that send step automatically; waiting for an
            # external interact_send here would either deadlock the plan or
            # cause the same answer to be sent twice.
            if (
                step.success_target is not None
                and step.success_target > self.current_step
                and isinstance(self.plan.steps[step.success_target], SendStep)
            ):
                self._complete_expect_locked(step, prompt.text)
                return
            if expected_success is None:
                if self._interaction_prompt != prompt:
                    self._interaction_prompt = prompt
                    self._matched_prompt = prompt.text
                    self._record_event_locked(
                        "interaction_required",
                        matched=prompt.text,
                        prompt_type=prompt.type,
                    )
                self._attention_event.set()
                return
        success_marker = _first_match(
            self._scan_buffer,
            step.success_markers,
            case_sensitive=step.case_sensitive,
        )
        if success_marker is not None and not step.disconnect_is_success:
            self._complete_expect_locked(step, success_marker[0])
            return
        failure = None
        if not responded and not step.success_markers:
            failure = _first_match(
                self._scan_buffer,
                step.failures,
                case_sensitive=step.case_sensitive,
            )
        if failure is not None:
            self._finish_active_step_locked(
                "failed",
                matched=failure[0],
                error_code="terminal_failure",
                message=f"终端输出匹配失败条件: {failure[0]}",
            )
            if not self._take_branch_locked(step, step.on_failure, reason="failure"):
                self._finish_locked(
                    "failed",
                    error_code="terminal_failure",
                    message=f"步骤 {self.current_step} 执行失败。",
                )
            return
        if self.status != "running":
            return
        success = expected_success
        if success is not None and not step.disconnect_is_success:
            self._complete_expect_locked(step, success[0])
            return
        if step.idle_seconds > 0:
            token = self._step_token
            self.schedule(
                int(step.idle_seconds * 1000),
                lambda token=token: self._on_idle_timeout(token),
            )

    def _success_tokens(self, step: ExpectStep) -> tuple[str, ...]:
        return (step.pattern,) if step.pattern else (step.success or ("device_prompt",))

    def _complete_expect_locked(self, step: ExpectStep, matched: str) -> None:
        self._matched_prompt = matched
        self._record_event_locked("matched", matched=matched)
        self._finish_active_step_locked("completed", matched=matched)
        target = step.success_target
        if target is not None:
            if target == self.current_step or target >= len(self.plan.steps):
                self._finish_locked("completed", message="终端交互执行完成。")
            else:
                self.current_step = target
                self._advance_locked()
            return
        if not self._take_branch_locked(step, step.on_match, reason="match"):
            self.current_step += 1
            self._advance_locked()

    def _has_pending_response_locked(self, step: ExpectStep) -> bool:
        if not self._scan_buffer:
            return False
        return any(
            self._response_counts.get(index, 0) < rule.max_matches
            and _match_token(
                self._scan_buffer,
                rule.match,
                case_sensitive=rule.case_sensitive,
            )
            is not None
            for index, rule in enumerate(step.responses)
        )

    def _on_response_retry(self, token: int) -> None:
        with self._lock:
            if self.status != "running" or token != self._step_token:
                return
            step = self._current_plan_step()
            if not isinstance(step, ExpectStep):
                return
            self._evaluate_expect_locked(step)

    def _input_for(
        self,
        *,
        text: str,
        control: str,
        secret_ref: str,
        secret_prefix: str = "",
        secret_suffix: str = "",
        append_enter: bool,
    ) -> TerminalInput:
        if control:
            payload = CONTROL_TEXT[control]
            return TerminalInput(payload)
        if secret_ref:
            try:
                value = str(self.resolve_secret(secret_ref))
            except (KeyError, ValueError) as exc:
                raise TerminalPlanError(
                    "secret_unavailable",
                    f"本地凭据不可用: {secret_ref}",
                ) from exc
            if not value:
                raise TerminalPlanError(
                    "secret_unavailable",
                    f"本地凭据为空: {secret_ref}",
                )
            redact_output = _secret_ref_requires_redaction(secret_ref)
            if redact_output:
                self._known_secrets.append(value)
            rendered = f"{secret_prefix}{value}{secret_suffix}"
            return TerminalInput(
                rendered + ("\r" if append_enter else ""),
                sensitive=redact_output,
                secret_ref=secret_ref,
            )
        return TerminalInput(text + ("\r" if append_enter else ""))

    def _finish_active_step_locked(
        self,
        status: str,
        *,
        matched: str = "",
        error_code: str = "",
        message: str = "",
    ) -> None:
        result = self._active_result
        if result is None:
            return
        result.status = status
        result.completed_monotonic = self.clock()
        result.matched = matched
        result.error_code = error_code
        result.message = message
        self.step_results.append(result)
        self._active_result = None

    def _finish_locked(
        self,
        status: str,
        *,
        error_code: str = "",
        message: str = "",
    ) -> None:
        if self.is_terminal:
            return
        self.status = status
        self.error_code = error_code
        self.message = message
        self._record_event_locked(
            "finished",
            status=status,
            error_code=error_code,
            message=message,
        )
        self.completed_monotonic = self.clock()
        self._step_token += 1
        self._completion_event.set()
        self._attention_event.set()
        self.on_finished(self)
        callbacks = list(self._done_callbacks)
        self._done_callbacks.clear()
        for callback in callbacks:
            try:
                callback(self)
            except Exception:
                continue

    def _current_plan_step(self) -> TerminalStep | None:
        if self.current_step >= len(self.plan.steps):
            return None
        return self.plan.steps[self.current_step]

    def _on_step_timeout(self, token: int) -> None:
        with self._lock:
            if self.status != "running" or token != self._step_token:
                return
            step = self._current_plan_step()
            self._finish_active_step_locked(
                "timed_out",
                error_code=(
                    "interaction_timeout"
                    if isinstance(step, ExpectStep) and self._interaction_prompt is not None
                    else step.timeout_code if isinstance(step, (ExpectStep, WaitStateStep)) else "step_timeout"
                ),
                message=f"步骤 {self.current_step}「{step.label or self.current_step}」等待超时。",
            )
            if (
                isinstance(step, (ExpectStep, WaitStateStep))
                and self._take_branch_locked(
                    step,
                    step.on_failure,
                    reason="timeout",
                )
            ):
                return
            self._finish_locked(
                "timed_out",
                error_code=(
                    "interaction_timeout"
                    if isinstance(step, ExpectStep) and self._interaction_prompt is not None
                    else step.timeout_code if isinstance(step, (ExpectStep, WaitStateStep)) else "step_timeout"
                ),
                message=f"步骤 {self.current_step}「{step.label or self.current_step}」等待超时。",
            )

    def _on_idle_timeout(self, token: int) -> None:
        with self._lock:
            if self.status != "running" or token != self._step_token:
                return
            step = self._current_plan_step()
            if not isinstance(step, ExpectStep) or step.idle_seconds <= 0:
                return
            # Once an interactive response has been sent (most importantly a
            # Huawei pager space), idle output is not proof of completion. The
            # device may still be switching pages. Advancing here lets the
            # first byte of the next command get consumed by the pager.
            if self._response_counts:
                return
            if self.clock() - self._last_output_monotonic < step.idle_seconds:
                return
            if self._active_result is None or not self._active_result.output:
                return
            self._finish_active_step_locked("completed", matched="idle")
            if not self._take_branch_locked(step, step.on_match, reason="match"):
                self.current_step += 1
                self._advance_locked()

    def _on_total_timeout(self, token: int) -> None:
        with self._lock:
            if self.status != "running" or token > self._step_token:
                return
            if self._active_result is not None:
                self._finish_active_step_locked(
                    "timed_out",
                    error_code="execution_timeout",
                    message="终端交互总时限已到。",
                )
            self._finish_locked(
                "timed_out",
                error_code="execution_timeout",
                message="终端交互总时限已到。",
            )


class TerminalExecutionCoordinator:
    def __init__(
        self,
        *,
        send_input: Callable[[str, TerminalInput, str], None],
        resolve_secret: Callable[[str], str],
        schedule: Callable[[int, Callable[[], None]], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.send_input = send_input
        self.resolve_secret = resolve_secret
        self.schedule = schedule
        self.clock = clock
        self._executions: dict[str, TerminalExecutionRunner] = {}
        self._session_leases: dict[str, str] = {}
        self._external_lease_cancellers: dict[str, Callable[[], None]] = {}
        self._runner_parent_leases: dict[str, str] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = threading.RLock()

    def start(
        self,
        *,
        session_id: str,
        device_id: str,
        plan: TerminalExecutionPlan,
        execution_id: str | None = None,
        idempotency_key: str = "",
        lease_owner_id: str = "",
    ) -> TerminalExecutionRunner:
        with self._lock:
            if idempotency_key:
                existing_id = self._idempotency.get(idempotency_key)
                if existing_id:
                    return self._executions[existing_id]
            active_id = self._session_leases.get(session_id)
            can_use_parent_lease = bool(
                active_id
                and active_id == lease_owner_id
                and active_id in self._external_lease_cancellers
            )
            if active_id and not can_use_parent_lease:
                raise TerminalPlanError(
                    "session_busy",
                    f"会话正在执行其他任务: {active_id}",
                )
            run_id = execution_id or str(uuid4())
            runner = TerminalExecutionRunner(
                execution_id=run_id,
                session_id=session_id,
                device_id=device_id,
                plan=plan,
                send_input=self.send_input,
                resolve_secret=self.resolve_secret,
                schedule=self.schedule,
                on_finished=self._runner_finished,
                clock=self.clock,
            )
            self._executions[run_id] = runner
            self._session_leases[session_id] = run_id
            if can_use_parent_lease:
                self._runner_parent_leases[run_id] = active_id
            if idempotency_key:
                self._idempotency[idempotency_key] = run_id
        runner.start()
        return runner

    def get(self, execution_id: str) -> TerminalExecutionRunner:
        with self._lock:
            runner = self._executions.get(execution_id)
        if runner is None:
            raise TerminalPlanError(
                "execution_not_found",
                f"未找到终端执行: {execution_id}",
            )
        return runner

    def wait(self, execution_id: str, timeout_seconds: float) -> bool:
        return self.get(execution_id).completion_event.wait(timeout_seconds)

    def cancel(self, execution_id: str, *, by_user: bool = False) -> TerminalExecutionRunner:
        runner = self.get(execution_id)
        runner.cancel(by_user=by_user)
        return runner

    def resume(self, execution_id: str) -> TerminalExecutionRunner:
        runner = self.get(execution_id)
        with self._lock:
            active_id = self._session_leases.get(runner.session_id)
            if active_id and active_id != execution_id:
                raise TerminalPlanError(
                    "session_busy",
                    f"会话正在执行其他任务: {active_id}",
                )
            self._session_leases[runner.session_id] = execution_id
        try:
            runner.resume()
        except Exception:
            with self._lock:
                if self._session_leases.get(runner.session_id) == execution_id:
                    self._session_leases.pop(runner.session_id, None)
            raise
        return runner

    def cancel_for_user_input(self, session_id: str) -> str:
        with self._lock:
            execution_id = self._session_leases.get(session_id, "")
            external_cancel = self._external_lease_cancellers.get(execution_id)
            runner = self._executions.get(execution_id)
            if external_cancel is not None and runner is None:
                self._session_leases.pop(session_id, None)
                self._external_lease_cancellers.pop(execution_id, None)
        if runner is not None:
            self.cancel(execution_id, by_user=True)
        elif external_cancel is not None:
            external_cancel()
        return execution_id

    def acquire_external_lease(
        self,
        session_id: str,
        owner_id: str,
        *,
        on_cancel: Callable[[], None],
    ) -> None:
        with self._lock:
            active_id = self._session_leases.get(session_id)
            if active_id and active_id != owner_id:
                raise TerminalPlanError(
                    "session_busy",
                    f"会话正在执行其他任务: {active_id}",
                )
            self._session_leases[session_id] = owner_id
            self._external_lease_cancellers[owner_id] = on_cancel

    def release_external_lease(self, session_id: str, owner_id: str) -> None:
        with self._lock:
            if self._session_leases.get(session_id) == owner_id:
                self._session_leases.pop(session_id, None)
            self._external_lease_cancellers.pop(owner_id, None)

    def on_output(self, session_id: str, message: str) -> None:
        runner = self._active_for_session(session_id)
        if runner is not None:
            runner.on_output(message)

    def on_session_state(self, session_id: str, state: str) -> None:
        runner = self._active_for_session(session_id)
        if runner is not None:
            runner.on_session_state(state)

    def active_execution_id(self, session_id: str) -> str:
        with self._lock:
            return self._session_leases.get(session_id, "")

    def redact_output(self, session_id: str, message: str) -> str:
        runner = self._active_for_session(session_id)
        return runner.redact_text(message) if runner is not None else message

    def _active_for_session(self, session_id: str) -> TerminalExecutionRunner | None:
        with self._lock:
            execution_id = self._session_leases.get(session_id)
            return self._executions.get(execution_id) if execution_id else None

    def _runner_finished(self, runner: TerminalExecutionRunner) -> None:
        with self._lock:
            if self._session_leases.get(runner.session_id) == runner.execution_id:
                parent_id = self._runner_parent_leases.pop(
                    runner.execution_id,
                    "",
                )
                if parent_id and parent_id in self._external_lease_cancellers:
                    self._session_leases[runner.session_id] = parent_id
                else:
                    self._session_leases.pop(runner.session_id, None)


def _parse_send_step(raw: dict[str, Any], index: int) -> SendStep:
    text, control, secret_ref = _exclusive_input(raw, f"步骤 {index}")
    secret_prefix = str(raw.get("secret_prefix") or "")
    secret_suffix = str(raw.get("secret_suffix") or "")
    if (secret_prefix or secret_suffix) and not secret_ref:
        raise TerminalPlanError(
            "invalid_plan",
            f"步骤 {index} 只能为凭据引用设置 secret_prefix/secret_suffix。",
        )
    if len(secret_prefix) > 1_024 or len(secret_suffix) > 1_024:
        raise TerminalPlanError("invalid_plan", f"步骤 {index} 凭据前后缀过长。")
    return SendStep(
        text=text,
        control=control,
        secret_ref=secret_ref,
        secret_prefix=secret_prefix,
        secret_suffix=secret_suffix,
        append_enter=bool(raw.get("append_enter", True)),
        label=str(raw.get("label") or text or control or secret_ref),
        name=_step_name(raw, index),
        next_step=_numeric_transition(raw.get("success"), index),
    )


def _parse_expect_step(raw: dict[str, Any], index: int) -> ExpectStep:
    pattern = str(raw.get("pattern") or "").strip()
    if pattern:
        _match_text(pattern, f"步骤 {index} pattern")
    raw_success = raw.get("success")
    success_target = _numeric_transition(raw_success, index)
    if success_target is not None:
        success = (pattern,) if pattern else ()
    else:
        success = _match_list(raw_success or [], f"步骤 {index} success")
    failures = _match_list(raw.get("failures", []), f"步骤 {index} failures")
    success_markers = _match_list(
        raw.get("success_markers", []),
        f"步骤 {index} success_markers",
    )
    raw_responses = raw.get("responses", [])
    if not isinstance(raw_responses, list):
        raise TerminalPlanError("invalid_plan", f"步骤 {index} responses 必须是数组。")
    responses: list[ResponseRule] = []
    for response_index, item in enumerate(raw_responses):
        if not isinstance(item, dict):
            raise TerminalPlanError(
                "invalid_plan",
                f"步骤 {index} 响应 {response_index} 必须是对象。",
            )
        match = _match_text(item.get("match"), f"步骤 {index} 响应 {response_index}")
        text, control, secret_ref = _exclusive_input(
            item,
            f"步骤 {index} 响应 {response_index}",
        )
        max_matches = int(
            _number(
                item.get("max_matches", 1),
                "max_matches",
                minimum=1,
                maximum=1000,
            )
        )
        responses.append(
            ResponseRule(
                match=match,
                text=text,
                control=control,
                secret_ref=secret_ref,
                append_enter=bool(item.get("append_enter", True)),
                case_sensitive=bool(item.get("case_sensitive", False)),
                max_matches=max_matches,
            )
        )
    timeout = _number(
        raw.get("timeout_seconds", 30),
        "timeout_seconds",
        minimum=0.05,
        maximum=3600,
    )
    idle = _number(
        raw.get("idle_seconds", 0),
        "idle_seconds",
        minimum=0,
        maximum=60,
    )
    output_limit = int(
        _number(
            raw.get("max_output_chars", 16_384),
            "max_output_chars",
            minimum=1,
            maximum=MAX_STEP_OUTPUT_CHARS,
        )
    )
    timeout_code = _timeout_code(raw.get("timeout_code"), index)
    return ExpectStep(
        success=success,
        pattern=pattern,
        responses=tuple(responses),
        failures=failures,
        success_markers=success_markers,
        timeout_seconds=timeout,
        idle_seconds=idle,
        case_sensitive=bool(raw.get("case_sensitive", False)),
        max_output_chars=output_limit,
        timeout_code=timeout_code,
        label=str(raw.get("label") or ""),
        name=_step_name(raw, index),
        on_match=str(raw.get("on_match") or "").strip(),
        on_failure=str(raw.get("on_failure") or "").strip(),
        max_retries=int(
            _number(
                raw.get("max_retries", 0),
                "max_retries",
                minimum=0,
                maximum=100,
            )
        ),
        disconnect_is_success=bool(raw.get("disconnect_is_success", False)),
        success_target=success_target,
    )


def _numeric_transition(value: Any, index: int) -> int | None:
    """Accept the MCP compatibility form ``success: [next_step_index]``."""
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], int):
        return None
    target = int(value[0])
    if target < 0:
        raise TerminalPlanError(
            "invalid_plan",
            f"步骤 {index} success 目标索引不能为负数。",
        )
    return target


def _parse_wait_state_step(raw: dict[str, Any], index: int) -> WaitStateStep:
    state = str(raw.get("state") or "").strip().casefold()
    if state not in {"connected", "disconnected"}:
        raise TerminalPlanError(
            "invalid_plan",
            f"步骤 {index} wait_state 只支持 connected 或 disconnected。",
        )
    timeout = _number(
        raw.get("timeout_seconds", 60),
        "timeout_seconds",
        minimum=0.05,
        maximum=3600,
    )
    timeout_code = _timeout_code(raw.get("timeout_code"), index)
    return WaitStateStep(
        state=state,
        timeout_seconds=timeout,
        label=str(raw.get("label") or state),
        name=_step_name(raw, index),
        on_match=str(raw.get("on_match") or "").strip(),
        on_failure=str(raw.get("on_failure") or "").strip(),
        max_retries=int(
            _number(
                raw.get("max_retries", 0),
                "max_retries",
                minimum=0,
                maximum=100,
            )
        ),
        timeout_code=timeout_code,
    )


def _timeout_code(value: Any, index: int) -> str:
    code = str(value or "step_timeout").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", code):
        raise TerminalPlanError("invalid_plan", f"步骤 {index} timeout_code 无效。")
    return code


def _step_name(raw: dict[str, Any], index: int) -> str:
    name = str(raw.get("name") or "").strip()
    if name and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", name):
        raise TerminalPlanError(
            "invalid_plan",
            f"步骤 {index} name 必须以字母开头，且只包含字母、数字、点、横线或下划线。",
        )
    return name


def _validate_plan_branches(steps: list[TerminalStep]) -> None:
    names: dict[str, int] = {}
    for index, step in enumerate(steps):
        name = step.name
        if not name:
            continue
        if name in names:
            raise TerminalPlanError("invalid_plan", f"步骤名称重复: {name}")
        names[name] = index
    for index, step in enumerate(steps):
        if not isinstance(step, (ExpectStep, WaitStateStep)):
            continue
        for field_name, target in (
            ("on_match", step.on_match),
            ("on_failure", step.on_failure),
        ):
            if not target or (field_name == "on_failure" and target == "stop"):
                continue
            if field_name == "on_failure" and target == "retry":
                target_index = index
            else:
                if target not in names:
                    raise TerminalPlanError(
                        "invalid_plan",
                        f"步骤 {index} {field_name} 指向未知步骤: {target}",
                    )
                target_index = names[target]
            if target_index <= index and step.max_retries < 1:
                raise TerminalPlanError(
                    "invalid_plan",
                    f"步骤 {index} 的向后跳转必须设置 max_retries。",
                )


def _validate_numeric_transitions(steps: list[TerminalStep]) -> None:
    for index, step in enumerate(steps):
        target = (
            step.next_step
            if isinstance(step, SendStep)
            else step.success_target
            if isinstance(step, ExpectStep)
            else None
        )
        if target is None:
            continue
        if target >= len(steps):
            raise TerminalPlanError(
                "invalid_plan",
                f"步骤 {index} success 目标索引超出计划范围: {target}。",
            )


def _exclusive_input(
    raw: dict[str, Any],
    label: str,
) -> tuple[str, str, str]:
    text = str(raw.get("text") or "")
    control = str(raw.get("control") or "").strip().casefold()
    secret_ref = str(raw.get("secret_ref") or "").strip()
    provided = sum(bool(value) for value in (text, control, secret_ref))
    if provided != 1:
        raise TerminalPlanError(
            "invalid_plan",
            f"{label} 必须且只能包含 text、control、secret_ref 之一。",
        )
    if control and control not in CONTROL_TEXT:
        raise TerminalPlanError("invalid_plan", f"{label} 控制输入无效: {control}")
    runtime_transfer_ref = bool(
        re.fullmatch(
            r"managed_transfer\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(?:username|password|command)",
            secret_ref,
        )
    )
    if secret_ref not in {
        "",
        "transfer.username",
        "transfer.password",
        "file_transfer.username",
        "file_transfer.password",
    } and not runtime_transfer_ref:
        raise TerminalPlanError(
            "secret_ref_not_allowed",
            f"{label} 不允许使用凭据引用: {secret_ref}",
        )
    if len(text) > 16_384:
        raise TerminalPlanError("invalid_plan", f"{label} 文本过长。")
    return text, control, secret_ref


def _match_list(value: Any, label: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TerminalPlanError("invalid_plan", f"{label} 必须是数组。")
    matches = tuple(_match_text(item, label) for item in value)
    if required and not matches:
        raise TerminalPlanError("invalid_plan", f"{label} 不能为空。")
    return matches


def _match_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise TerminalPlanError("invalid_plan", f"{label} 匹配文本不能为空。")
    if len(text) > MAX_MATCH_TEXT:
        raise TerminalPlanError("invalid_plan", f"{label} 匹配文本过长。")
    return text


def _number(
    value: Any,
    label: str,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TerminalPlanError("invalid_plan", f"{label} 必须是数字。") from exc
    if number < minimum or number > maximum:
        raise TerminalPlanError(
            "invalid_plan",
            f"{label} 必须在 {minimum:g} 到 {maximum:g} 之间。",
        )
    return number


def _first_match(
    text: str,
    tokens: tuple[str, ...],
    *,
    case_sensitive: bool,
) -> tuple[str, int] | None:
    best: tuple[str, int] | None = None
    for token in tokens:
        found = _match_token(text, token, case_sensitive=case_sensitive)
        if found is not None and (best is None or found[1] < best[1]):
            best = found
    return best


def _match_token(
    text: str,
    token: str,
    *,
    case_sensitive: bool,
) -> tuple[str, int] | None:
    if token == "device_prompt":
        prompt = detect_terminal_prompt(text)
        return (prompt, len(text)) if prompt else None
    alias_patterns = {
        # Huawei VRP renders the FTP client prompt as ``[ftp]`` while the
        # simulator and several Unix clients use ``ftp>``. Both are the same
        # protocol state and must unlock the following binary/get step.
        "ftp_prompt": r"(?im)(?:^|\n)\s*(?:ftp>|\[ftp\])\s*$",
        "sftp_prompt": r"(?im)(?:^|\n)\s*(?:(?:sftp|sftp-client)>|\[sftp(?:-client)?\])\s*$",
        # Keep the prompt boundary line-local. ``\s*$`` can consume the
        # newline before a following password prompt and then miss the
        # username prompt entirely when a device batches both lines.
        # VRP commonly emits both ``User(10.10.10.1):(none):`` and
        # ``User(10.10.10.1:(none)):``. Keep the body non-greedy so a
        # coalesced prompt does not consume a following password prompt, and
        # accept the extra carriage return used by some Telnet servers.
        "username_prompt": r"(?i)(?:(?:user(?:name)?)[ \t]*\([^()\r\n]*(?:\([^()\r\n]*\)[^()\r\n]*)?\)[ \t]*:(?:[ \t]*\([^()\r\n]*\)[ \t]*:)?|(?:user(?:name)?|name|account|login)[^\r\n]{0,200}?):[ \t]*(?=[ \t]*(?:password[ \t]*:[ \t]*)?(?:\r+$|\r+\n|\n|$))",
        "password_prompt": r"(?i)password[ \t]*:[ \t]*(?=\r+$|\r+\n|\n|$)",
        "host_key_prompt": r"(?i)(?:yes/no|continue connecting).{0,80}$",
        "pagination_prompt": r"(?i)(?:----\s*more\s*----|--more--)\s*$",
        # Match the first complete confirmation line in a coalesced output
        # packet as well as a prompt that is still at the end of the buffer.
        # Using ``$`` here alone skips earlier prompts when VRP sends several
        # confirmations in one event.
        "confirmation_prompt": r"(?i)(?:\[y/n\]|\(y/n\)|yes/no)[ \t]*:?[ \t]*(?=\r?$|\r?\n)",
    }
    if token in alias_patterns:
        match = re.search(alias_patterns[token], text)
        return (match.group(0).strip(), match.end()) if match else None
    haystack = text if case_sensitive else text.casefold()
    needle = token if case_sensitive else token.casefold()
    index = haystack.find(needle)
    if index < 0:
        return None
    return token, index + len(token)


def _redact_values(text: str, values: tuple[str, ...]) -> str:
    redacted = text
    for value in sorted(set(values), key=len, reverse=True):
        if value:
            redacted = redacted.replace(value, "***")
    return redacted


def _secret_ref_requires_redaction(secret_ref: str) -> bool:
    """Usernames are identifiers; passwords and runtime commands are secrets."""
    return not secret_ref.casefold().endswith(".username")
