"""Data contracts shared by terminal plan parsing and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


MAX_PLAN_STEPS = 100
MAX_MATCH_TEXT = 512
MAX_STEP_OUTPUT_CHARS = 32_768
CONTROL_TEXT = {
    "enter": "\r",
    "space": " ",
    "ctrl_c": "\x03",
    "ctrl_y": "\x19",
}
DEFAULT_PAGINATION_MAX_MATCHES = 100


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
