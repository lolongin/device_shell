"""Generic terminal auto-response rules."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


CONTROL_KEY_ALIASES = {
    "enter": "\r",
    "return": "\r",
    "esc": "\x1b",
    "escape": "\x1b",
    "tab": "\t",
    "backspace": "\x08",
    "delete": "\x7f",
    "space": " ",
}


@dataclass(slots=True)
class AutoResponseStep:
    """One step in an auto-response workflow."""

    pattern: str
    responses: list[str] = field(default_factory=list)
    response_texts: list[str] = field(default_factory=list)
    response_targets: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AutoResponseRule:
    """A current-session rule that sends text when terminal output matches."""

    name: str
    pattern: str
    response: str
    response_text: str = ""
    append_enter: bool = False
    enabled: bool = True
    case_sensitive: bool = False
    once: bool = True
    match_type: str = "contains"
    delay_ms: int = 0
    max_triggers: int = 0
    trigger_count: int = 0
    steps: list[AutoResponseStep] = field(default_factory=list)

    def matches(self, output: str) -> bool:
        if not self.enabled or not self.pattern:
            return False
        if self.match_type == "regex":
            flags = 0 if self.case_sensitive else re.IGNORECASE
            try:
                return re.search(self.pattern, output, flags) is not None
            except re.error:
                return False
        haystack = output if self.case_sensitive else output.lower()
        needle = self.pattern if self.case_sensitive else self.pattern.lower()
        return needle in haystack

    def mark_triggered(self) -> None:
        self.trigger_count += 1
        if self.once:
            self.enabled = False


@dataclass(slots=True)
class TerminalQuickButton:
    """A remembered button that sends text directly to the selected terminal."""

    name: str
    response: str
    response_text: str = ""
    append_enter: bool = False
    trigger_count: int = 0


def default_quick_send_buttons() -> list[TerminalQuickButton]:
    return [
        TerminalQuickButton(
            name="发送 Ctrl+B",
            response="\x02",
            response_text="Ctrl+B",
        )
    ]


def serialize_auto_response_rule(rule: AutoResponseRule) -> dict[str, object]:
    """Serialize a rule template without current-session trigger state."""

    payload = {
        "name": rule.name,
        "pattern": rule.pattern,
        "response": rule.response,
        "response_text": rule.response_text,
        "append_enter": rule.append_enter,
        "enabled": rule.enabled,
        "case_sensitive": rule.case_sensitive,
        "once": rule.once,
        "match_type": rule.match_type,
        "delay_ms": rule.delay_ms,
        "max_triggers": rule.max_triggers,
    }
    if rule.steps:
        payload["steps"] = [
            {
                "pattern": step.pattern,
                "responses": step.responses,
                "response_texts": step.response_texts,
                "response_targets": step.response_targets,
            }
            for step in rule.steps
        ]
    return payload


def deserialize_auto_response_rule(value: Any) -> AutoResponseRule | None:
    """Load a saved rule template, ignoring malformed entries."""

    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or "").strip() or "自动响应"
    pattern = str(value.get("pattern") or "").strip()
    response_text = str(value.get("response_text") or "")
    response = str(value.get("response") or "")
    if not response and response_text:
        response = decode_response_text(
            response_text,
            append_enter=bool(value.get("append_enter", False)),
        )
    steps = deserialize_auto_response_steps(value.get("steps"))
    if not pattern and steps:
        pattern = steps[0].pattern
    if not response and steps and steps[0].responses:
        response = steps[0].responses[0]
    if not response_text and steps and steps[0].response_texts:
        response_text = steps[0].response_texts[0]
    if not pattern:
        return None
    if not response:
        return None
    match_type = str(value.get("match_type") or "contains").strip().lower()
    if match_type not in {"contains", "regex"}:
        match_type = "contains"
    try:
        delay_ms = max(0, int(value.get("delay_ms", 0)))
    except (TypeError, ValueError):
        delay_ms = 0
    try:
        max_triggers = max(0, int(value.get("max_triggers", 0)))
    except (TypeError, ValueError):
        max_triggers = 0
    return AutoResponseRule(
        name=name,
        pattern=pattern,
        response=response,
        response_text=response_text,
        append_enter=bool(value.get("append_enter", False)),
        enabled=bool(value.get("enabled", True)),
        case_sensitive=bool(value.get("case_sensitive", False)),
        once=bool(value.get("once", True)),
        match_type=match_type,
        delay_ms=delay_ms,
        max_triggers=max_triggers,
        trigger_count=0,
        steps=steps,
    )


def deserialize_auto_response_steps(value: Any) -> list[AutoResponseStep]:
    """Load saved workflow steps, ignoring malformed entries."""

    if not isinstance(value, list):
        return []
    steps: list[AutoResponseStep] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern") or "").strip()
        raw_responses = item.get("responses")
        raw_response_texts = item.get("response_texts")
        raw_response_targets = item.get("response_targets")
        if not pattern or not isinstance(raw_responses, list):
            continue
        responses = [str(response) for response in raw_responses if str(response)]
        response_texts = (
            [str(response_text) for response_text in raw_response_texts]
            if isinstance(raw_response_texts, list)
            else []
        )
        response_targets = (
            [str(response_target) for response_target in raw_response_targets]
            if isinstance(raw_response_targets, list)
            else []
        )
        if len(response_texts) < len(responses):
            response_texts.extend(responses[len(response_texts) :])
        if len(response_targets) < len(responses):
            response_targets.extend(["source"] * (len(responses) - len(response_targets)))
        if responses:
            steps.append(
                AutoResponseStep(
                    pattern=pattern,
                    responses=responses,
                    response_texts=response_texts[: len(responses)],
                    response_targets=response_targets[: len(responses)],
                )
            )
    return steps


def serialize_quick_send_button(button: TerminalQuickButton) -> dict[str, object]:
    """Serialize a direct-send button without current-session click count."""

    return {
        "name": button.name,
        "response": button.response,
        "response_text": button.response_text,
        "append_enter": button.append_enter,
    }


def deserialize_quick_send_button(value: Any) -> TerminalQuickButton | None:
    """Load a saved direct-send button, ignoring malformed entries."""

    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or "").strip() or "快捷发送"
    response_text = str(value.get("response_text") or "")
    response = str(value.get("response") or "")
    append_enter = bool(value.get("append_enter", False))
    if not response and response_text:
        response = decode_response_text(response_text, append_enter=append_enter)
    if not response:
        return None
    return TerminalQuickButton(
        name=name,
        response=response,
        response_text=response_text,
        append_enter=append_enter,
        trigger_count=0,
    )


def decode_response_text(value: str, *, append_enter: bool = False) -> str:
    """Decode a user-facing send value into terminal bytes/text."""

    text = value.strip()
    if not text:
        return "\r" if append_enter else ""

    control = _decode_control_key(text)
    decoded = control if control is not None else _decode_escapes(value)
    if append_enter:
        decoded += "\r"
    return decoded


def _decode_control_key(text: str) -> str | None:
    lowered = text.lower().replace(" ", "")
    if lowered.startswith("ctrl+") and len(lowered) == 6:
        key = lowered[-1]
        if "a" <= key <= "z":
            return chr(ord(key) - ord("a") + 1)
    if lowered in CONTROL_KEY_ALIASES:
        return CONTROL_KEY_ALIASES[lowered]
    return None


def _decode_escapes(value: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\" or index + 1 >= len(value):
            output.append(char)
            index += 1
            continue
        escape = value[index + 1]
        if escape == "x" and index + 3 < len(value):
            digits = value[index + 2 : index + 4]
            try:
                output.append(chr(int(digits, 16)))
                index += 4
                continue
            except ValueError:
                pass
        mapped = {"r": "\r", "n": "\n", "t": "\t", "e": "\x1b", "\\": "\\"}.get(escape)
        if mapped is not None:
            output.append(mapped)
            index += 2
            continue
        output.append(char)
        index += 1
    return "".join(output)
