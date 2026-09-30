"""Parser and validation for declarative terminal execution plans."""

from __future__ import annotations

import re
from typing import Any

from .plan_models import (
    CONTROL_TEXT,
    DEFAULT_PAGINATION_MAX_MATCHES,
    MAX_MATCH_TEXT,
    MAX_PLAN_STEPS,
    MAX_STEP_OUTPUT_CHARS,
    ExpectStep,
    ResponseRule,
    SendStep,
    TerminalExecutionPlan,
    TerminalPlanError,
    TerminalStep,
    WaitStateStep,
)


def parse_terminal_plan(steps: list[dict[str, Any]], *, total_timeout_seconds: float = 60.0) -> TerminalExecutionPlan:
    if not isinstance(steps, list) or not steps:
        raise TerminalPlanError("invalid_plan", "交互计划至少需要一个步骤。")
    if len(steps) > MAX_PLAN_STEPS:
        raise TerminalPlanError("invalid_plan", f"交互计划最多允许 {MAX_PLAN_STEPS} 个步骤。")
    total_timeout = _number(total_timeout_seconds, "total_timeout_seconds", minimum=1, maximum=3600)
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
            raise TerminalPlanError("invalid_plan", f"步骤 {index} 类型无效: {kind or '<empty>'}")
    _validate_plan_branches(parsed)
    _validate_numeric_transitions(parsed)
    return TerminalExecutionPlan(tuple(parsed), total_timeout)


def build_batch_plan(commands: list[str], *, command_timeout_seconds: float = 30.0,
                     total_timeout_seconds: float | None = None, max_output_chars: int = 16_384,
                     terminal_prompt: str = "", failure_patterns: list[str] | tuple[str, ...] = ()) -> TerminalExecutionPlan:
    if not isinstance(commands, list) or not commands or len(commands) > 50:
        raise TerminalPlanError("invalid_plan", "批量命令数量必须在 1 到 50 之间。")
    timeout = _number(command_timeout_seconds, "command_timeout_seconds", minimum=1, maximum=300)
    output_limit = int(_number(max_output_chars, "max_output_chars_per_step", minimum=1, maximum=MAX_STEP_OUTPUT_CHARS))
    steps: list[TerminalStep] = []
    for index, raw_command in enumerate(commands):
        command = str(raw_command).strip()
        if not command:
            raise TerminalPlanError("invalid_plan", f"命令 {index} 不能为空。")
        if len(command) > 16_384:
            raise TerminalPlanError("invalid_plan", f"命令 {index} 过长。")
        steps.extend((
            SendStep(text=command, append_enter=True, label=command),
            ExpectStep(
                success=(terminal_prompt or "device_prompt",),
                responses=(ResponseRule(match="pagination_prompt", control="space", append_enter=False,
                                         max_matches=DEFAULT_PAGINATION_MAX_MATCHES),),
                failures=tuple(failure_patterns) or ("Error:", "Unrecognized command", "Unknown command", "Incomplete command"),
                timeout_seconds=timeout, idle_seconds=0 if terminal_prompt or failure_patterns else 0.8,
                max_output_chars=output_limit, label=command,
            ),
        ))
    total = _number(60.0 if total_timeout_seconds is None else total_timeout_seconds,
                    "total_timeout_seconds", minimum=1, maximum=3600)
    return TerminalExecutionPlan(tuple(steps), total)


def _normalize_compat_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                normalized.append({"type": "expect", "pattern": str(expected), "success": [str(expected)],
                                   "label": f"expect {expected}"})
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
    return normalized


def _parse_send_step(raw: dict[str, Any], index: int) -> SendStep:
    text, control, secret_ref = _exclusive_input(raw, f"步骤 {index}")
    prefix, suffix = str(raw.get("secret_prefix") or ""), str(raw.get("secret_suffix") or "")
    if (prefix or suffix) and not secret_ref:
        raise TerminalPlanError("invalid_plan", f"步骤 {index} 只能为凭据引用设置 secret_prefix/secret_suffix。")
    if len(prefix) > 1024 or len(suffix) > 1024:
        raise TerminalPlanError("invalid_plan", f"步骤 {index} 凭据前后缀过长。")
    return SendStep(text=text, control=control, secret_ref=secret_ref, secret_prefix=prefix, secret_suffix=suffix,
                    append_enter=bool(raw.get("append_enter", True)), label=str(raw.get("label") or text or control or secret_ref),
                    name=_step_name(raw, index), next_step=_numeric_transition(raw.get("success"), index))


def _parse_expect_step(raw: dict[str, Any], index: int) -> ExpectStep:
    pattern = str(raw.get("pattern") or "").strip()
    if pattern:
        _match_text(pattern, f"步骤 {index} pattern")
    success_target = _numeric_transition(raw.get("success"), index)
    success = (pattern,) if success_target is not None else _match_list(raw.get("success") or [], f"步骤 {index} success")
    responses: list[ResponseRule] = []
    raw_responses = raw.get("responses", [])
    if not isinstance(raw_responses, list):
        raise TerminalPlanError("invalid_plan", f"步骤 {index} responses 必须是数组。")
    for response_index, item in enumerate(raw_responses):
        if not isinstance(item, dict):
            raise TerminalPlanError("invalid_plan", f"步骤 {index} 响应 {response_index} 必须是对象。")
        text, control, secret_ref = _exclusive_input(item, f"步骤 {index} 响应 {response_index}")
        responses.append(ResponseRule(match=_match_text(item.get("match"), f"步骤 {index} 响应 {response_index}"), text=text,
                                      control=control, secret_ref=secret_ref, append_enter=bool(item.get("append_enter", True)),
                                      case_sensitive=bool(item.get("case_sensitive", False)), max_matches=int(_number(item.get("max_matches", 1), "max_matches", minimum=1, maximum=1000))))
    return ExpectStep(success=success, pattern=pattern, responses=tuple(responses),
                      failures=_match_list(raw.get("failures", []), f"步骤 {index} failures"),
                      success_markers=_match_list(raw.get("success_markers", []), f"步骤 {index} success_markers"),
                      timeout_seconds=_number(raw.get("timeout_seconds", 30), "timeout_seconds", minimum=.05, maximum=3600),
                      idle_seconds=_number(raw.get("idle_seconds", 0), "idle_seconds", minimum=0, maximum=60),
                      case_sensitive=bool(raw.get("case_sensitive", False)),
                      max_output_chars=int(_number(raw.get("max_output_chars", 16_384), "max_output_chars", minimum=1, maximum=MAX_STEP_OUTPUT_CHARS)),
                      timeout_code=_timeout_code(raw.get("timeout_code"), index), label=str(raw.get("label") or ""), name=_step_name(raw, index),
                      on_match=str(raw.get("on_match") or "").strip(), on_failure=str(raw.get("on_failure") or "").strip(),
                      max_retries=int(_number(raw.get("max_retries", 0), "max_retries", minimum=0, maximum=100)),
                      disconnect_is_success=bool(raw.get("disconnect_is_success", False)), success_target=success_target)


def _parse_wait_state_step(raw: dict[str, Any], index: int) -> WaitStateStep:
    state = str(raw.get("state") or "").strip().casefold()
    if state not in {"connected", "disconnected"}:
        raise TerminalPlanError("invalid_plan", f"步骤 {index} wait_state 只支持 connected 或 disconnected。")
    return WaitStateStep(state=state, timeout_seconds=_number(raw.get("timeout_seconds", 60), "timeout_seconds", minimum=.05, maximum=3600),
                         label=str(raw.get("label") or state), name=_step_name(raw, index), on_match=str(raw.get("on_match") or "").strip(),
                         on_failure=str(raw.get("on_failure") or "").strip(), max_retries=int(_number(raw.get("max_retries", 0), "max_retries", minimum=0, maximum=100)),
                         timeout_code=_timeout_code(raw.get("timeout_code"), index))


def _exclusive_input(raw: dict[str, Any], label: str) -> tuple[str, str, str]:
    text, control, secret_ref = str(raw.get("text") or ""), str(raw.get("control") or "").strip().casefold(), str(raw.get("secret_ref") or "").strip()
    if sum(bool(v) for v in (text, control, secret_ref)) != 1:
        raise TerminalPlanError("invalid_plan", f"{label} 必须且只能包含 text、control、secret_ref 之一。")
    if control and control not in CONTROL_TEXT:
        raise TerminalPlanError("invalid_plan", f"{label} 控制输入无效: {control}")
    allowed = {"", "transfer.username", "transfer.password", "file_transfer.username", "file_transfer.password"}
    runtime = re.fullmatch(r"managed_transfer\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(?:username|password|command)", secret_ref)
    if secret_ref not in allowed and not runtime:
        raise TerminalPlanError("secret_ref_not_allowed", f"{label} 不允许使用凭据引用: {secret_ref}")
    if len(text) > 16_384:
        raise TerminalPlanError("invalid_plan", f"{label} 文本过长。")
    return text, control, secret_ref


def _match_list(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TerminalPlanError("invalid_plan", f"{label} 必须是数组。")
    return tuple(_match_text(item, label) for item in value)


def _match_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise TerminalPlanError("invalid_plan", f"{label} 匹配文本不能为空。")
    if len(text) > MAX_MATCH_TEXT:
        raise TerminalPlanError("invalid_plan", f"{label} 匹配文本过长。")
    return text


def _numeric_transition(value: Any, index: int) -> int | None:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], int):
        return None
    if value[0] < 0:
        raise TerminalPlanError("invalid_plan", f"步骤 {index} success 目标索引不能为负数。")
    return int(value[0])


def _timeout_code(value: Any, index: int) -> str:
    code = str(value or "step_timeout").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", code):
        raise TerminalPlanError("invalid_plan", f"步骤 {index} timeout_code 无效。")
    return code


def _step_name(raw: dict[str, Any], index: int) -> str:
    name = str(raw.get("name") or "").strip()
    if name and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", name):
        raise TerminalPlanError("invalid_plan", f"步骤 {index} name 必须以字母开头，且只包含字母、数字、点、横线或下划线。")
    return name


def _validate_plan_branches(steps: list[TerminalStep]) -> None:
    names: dict[str, int] = {}
    for index, step in enumerate(steps):
        if step.name:
            if step.name in names:
                raise TerminalPlanError("invalid_plan", f"步骤名称重复: {step.name}")
            names[step.name] = index
    for index, step in enumerate(steps):
        if not isinstance(step, (ExpectStep, WaitStateStep)):
            continue
        for field_name, target in (("on_match", step.on_match), ("on_failure", step.on_failure)):
            if not target or (field_name == "on_failure" and target == "stop"):
                continue
            target_index = index if field_name == "on_failure" and target == "retry" else names.get(target, -1)
            if target_index < 0:
                raise TerminalPlanError("invalid_plan", f"步骤 {index} {field_name} 指向未知步骤: {target}")
            if target_index <= index and step.max_retries < 1:
                raise TerminalPlanError("invalid_plan", f"步骤 {index} 的向后跳转必须设置 max_retries。")


def _validate_numeric_transitions(steps: list[TerminalStep]) -> None:
    for index, step in enumerate(steps):
        target = step.next_step if isinstance(step, SendStep) else step.success_target if isinstance(step, ExpectStep) else None
        if target is not None and target >= len(steps):
            raise TerminalPlanError("invalid_plan", f"步骤 {index} success 目标索引超出计划范围: {target}。")


def _number(value: Any, label: str, *, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TerminalPlanError("invalid_plan", f"{label} 必须是数字。") from exc
    if number < minimum or number > maximum:
        raise TerminalPlanError("invalid_plan", f"{label} 必须在 {minimum:g} 到 {maximum:g} 之间。")
    return number
