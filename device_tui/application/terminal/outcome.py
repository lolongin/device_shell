"""Deterministic terminal prompt and command-outcome classification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable

from .execution import strip_terminal_ansi


INTERACTION_PROMPT_TYPES = {
    "confirmation_prompt",
    "pagination_prompt",
    "credential_prompt",
    "unknown_input_prompt",
}

_CONFIRMATION_RE = re.compile(
    r"(?i)(?:\[\s*[yn](?:\s*/\s*[yn])+\s*\]|"
    r"\(\s*[yn](?:\s*/\s*[yn])+\s*\)|yes\s*/\s*no)\s*:?[ \t]*$"
)
_PAGINATION_RE = re.compile(r"(?i)(?:----\s*more\s*----|--more--)\s*$")
_HOST_KEY_RE = re.compile(
    r"(?i)(?:continue\s+connecting|authenticity\s+of\s+host).{0,160}"
    r"(?:yes\s*/\s*no|\[fingerprint\])[^\r\n]*[?:]?\s*$"
)
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:user(?:name)?|login|account|password|passphrase|token)"
    r"[^\r\n]*:\s*$"
)
_COMMAND_PROMPT_PATTERNS = (
    re.compile(r"<[^<>\r\n]{1,128}>"),
    re.compile(r"\[[^\[\]\r\n]{1,128}\]"),
    re.compile(r"[^\s\r\n]{1,160}[$#]"),
)
_UNKNOWN_INPUT_RE = re.compile(
    r"(?i)(?:press\s+(?:enter|return|any key|ctrl\+[a-z])[^\r\n]*|"
    r"select\s+option\s*:|continue\?)\s*$"
)
_FAILURE_PATTERNS = (
    (
        "command_rejected",
        "common.unrecognized_command",
        re.compile(r"(?im)^.*(?:unrecognized|unknown)\s+command.*$"),
    ),
    (
        "incomplete_command",
        "common.incomplete_command",
        re.compile(r"(?im)^.*incomplete\s+command.*$"),
    ),
    (
        "invalid_input",
        "common.invalid_input",
        re.compile(r"(?im)^\s*%\s*(?:invalid|unknown|ambiguous|incomplete).*$"),
    ),
    ("command_rejected", "common.error", re.compile(r"(?im)^\s*error\s*:.*$")),
)


@dataclass(frozen=True, slots=True)
class PromptMatch:
    type: str
    text: str
    view: str = ""

    def public_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value}


@dataclass(frozen=True, slots=True)
class OutcomeError:
    code: str
    text: str
    pattern_id: str

    def public_dict(self) -> dict[str, str]:
        return asdict(self)


def classify_terminal_prompt(text: str) -> PromptMatch | None:
    """Classify only the active prompt on the final non-empty output line."""
    normalized = strip_terminal_ansi(text)
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]
    if not lines:
        return None
    candidate = lines[-1]
    if _CONFIRMATION_RE.search(candidate):
        return PromptMatch("confirmation_prompt", candidate)
    if _PAGINATION_RE.search(candidate):
        return PromptMatch("pagination_prompt", candidate)
    if _HOST_KEY_RE.search(candidate):
        return PromptMatch("credential_prompt", candidate)
    if _CREDENTIAL_RE.search(candidate):
        return PromptMatch("credential_prompt", candidate)
    if _UNKNOWN_INPUT_RE.search(candidate):
        return PromptMatch("unknown_input_prompt", candidate)
    for pattern in _COMMAND_PROMPT_PATTERNS:
        if pattern.fullmatch(candidate):
            return PromptMatch(
                "command_prompt",
                candidate,
                _prompt_view(candidate),
            )
    return None


def detect_outcome_errors(
    text: str,
    extra_patterns: Iterable[str] = (),
) -> list[OutcomeError]:
    normalized = strip_terminal_ansi(text)
    errors: list[OutcomeError] = []
    seen: set[str] = set()
    patterns = list(_FAILURE_PATTERNS)
    for index, value in enumerate(extra_patterns):
        token = str(value).strip()
        if token:
            patterns.append(
                (
                    "command_failed",
                    f"configured.failure.{index}",
                    re.compile(re.escape(token), re.IGNORECASE),
                )
            )
    for code, pattern_id, pattern in patterns:
        for match in pattern.finditer(normalized):
            evidence = match.group(0).strip()
            key = evidence.casefold()
            if evidence and key not in seen:
                seen.add(key)
                errors.append(OutcomeError(code, evidence, pattern_id))
    return errors


def classify_command_outcome(
    output: str,
    *,
    lifecycle_status: str,
    command: str = "",
    matched: str = "",
    duration_ms: float = 0.0,
    failure_patterns: Iterable[str] = (),
) -> dict[str, Any]:
    """Return stable command-result semantics from observable evidence."""
    prompt = classify_terminal_prompt(output)
    errors = detect_outcome_errors(output, failure_patterns)
    normalized_status = str(lifecycle_status or "running").casefold()
    finished = False
    confidence = "medium"

    # A completed indexed expect may have been completed by consuming a
    # confirmation prompt and advancing to its plan-owned send step.  Do not
    # reclassify that historical prompt as an unresolved interaction.
    if (
        prompt is not None
        and prompt.type in INTERACTION_PROMPT_TYPES
        and normalized_status not in {"completed", "failed", "timed_out", "cancelled", "cancelled_by_user", "disconnected"}
    ):
        status = "interaction_required"
        basis = prompt.type
        confidence = "high"
    elif errors:
        status = "failure"
        finished = bool(prompt and prompt.type == "command_prompt") or normalized_status == "completed"
        basis = errors[0].pattern_id
        confidence = "high"
    elif normalized_status == "completed" and (
        (prompt is not None and prompt.type == "command_prompt")
        or (matched and matched not in {"idle", ""})
    ):
        status = "success"
        finished = True
        basis = "command_prompt_and_no_error" if prompt else "explicit_success_match"
        confidence = "high"
    elif normalized_status == "failed":
        status = "failure"
        basis = "execution_failed"
    else:
        status = "unknown"
        basis = {
            "timed_out": "execution_timeout",
            "disconnected": "session_disconnected",
            "cancelled": "execution_cancelled",
            "cancelled_by_user": "cancelled_by_user",
            "completed": "completion_without_terminal_evidence",
        }.get(normalized_status, "execution_in_progress")

    return {
        "status": status,
        "finished": finished,
        "command": command,
        "prompt": prompt.public_dict() if prompt is not None else {},
        "result_text": _result_text(output, prompt, errors, command),
        "errors": [item.public_dict() for item in errors],
        "basis": basis,
        "confidence": confidence,
        "duration_ms": round(max(0.0, float(duration_ms)), 2),
    }


def _prompt_view(prompt: str) -> str:
    if prompt.startswith("<"):
        return "user"
    if prompt.startswith("["):
        return "interface" if "-" in prompt else "system"
    return "shell"


def _result_text(
    output: str,
    prompt: PromptMatch | None,
    errors: list[OutcomeError],
    command: str,
) -> str:
    if errors:
        return errors[0].text[:512]
    prompt_text = prompt.text if prompt is not None else ""
    lines = [line.strip() for line in strip_terminal_ansi(output).split("\n")]
    meaningful = [
        line
        for line in lines
        if line
        and line != prompt_text
        and line != command.strip()
        and not _is_interaction_line(line)
    ]
    return meaningful[-1][:512] if meaningful else ""


def _is_interaction_line(line: str) -> bool:
    prompt = classify_terminal_prompt(line)
    return bool(prompt and prompt.type in INTERACTION_PROMPT_TYPES)
