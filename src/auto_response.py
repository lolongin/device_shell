"""Generic terminal auto-response rules."""

from __future__ import annotations

from dataclasses import dataclass
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
    trigger_count: int = 0

    def matches(self, output: str) -> bool:
        if not self.enabled or not self.pattern:
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

    return {
        "name": rule.name,
        "pattern": rule.pattern,
        "response": rule.response,
        "response_text": rule.response_text,
        "append_enter": rule.append_enter,
        "enabled": rule.enabled,
        "case_sensitive": rule.case_sensitive,
        "once": rule.once,
    }


def deserialize_auto_response_rule(value: Any) -> AutoResponseRule | None:
    """Load a saved rule template, ignoring malformed entries."""

    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or "").strip() or "自动响应"
    pattern = str(value.get("pattern") or "").strip()
    response_text = str(value.get("response_text") or "")
    if not pattern:
        return None
    response = str(value.get("response") or "")
    if not response and response_text:
        response = decode_response_text(
            response_text,
            append_enter=bool(value.get("append_enter", False)),
        )
    if not response:
        return None
    return AutoResponseRule(
        name=name,
        pattern=pattern,
        response=response,
        response_text=response_text,
        append_enter=bool(value.get("append_enter", False)),
        enabled=bool(value.get("enabled", True)),
        case_sensitive=bool(value.get("case_sensitive", False)),
        once=bool(value.get("once", True)),
        trigger_count=0,
    )


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
