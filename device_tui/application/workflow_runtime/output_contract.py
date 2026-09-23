"""Shared output contracts for generic Workflow command nodes."""

from __future__ import annotations

from typing import Any, Mapping


COMMAND_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "output": {"type": "string"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "exitCode": {"type": ["integer", "null"]},
        "exit_code": {"type": ["integer", "null"]},
        "status": {"type": "string"},
        "duration": {"type": "number"},
        "data": {"type": "object"},
        "error": {"type": ["object", "null"]},
    },
}

_SUCCESS_STATUSES = frozenset({"success", "succeeded", "completed", "ok", "ready"})


def normalize_command_output(
    values: Mapping[str, Any] | None = None,
    *,
    status: str = "completed",
    exit_code: int | None = None,
    duration: float | int | None = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one backward-compatible command result shape across adapters."""
    source = dict(values or {})
    normalized = dict(source)

    raw_status = str(source.get("status") or status)
    raw_output = source.get("output", source.get("probe_output", source.get("stdout", "")))
    output = "" if raw_output is None else str(raw_output)
    stdout = source.get("stdout", output)

    raw_error = source.get("error")
    error_value = dict(error) if isinstance(error, Mapping) else None
    if error_value is None and isinstance(raw_error, Mapping):
        error_value = dict(raw_error)
    if error_value is None and (
        str(source.get("error_code") or "").strip()
        or str(source.get("error_message") or "").strip()
    ):
        error_value = {
            "code": str(source.get("error_code") or "command_failed"),
            "message": str(source.get("error_message") or raw_error or output or "command failed"),
            "class": str(source.get("error_class") or "deterministic"),
        }

    raw_stderr = source.get("stderr")
    if raw_stderr is None:
        raw_stderr = raw_error if isinstance(raw_error, str) else source.get("error_message", "")
    stderr = "" if raw_stderr is None else str(raw_stderr)

    resolved_exit_code = source.get("exitCode", source.get("exit_code", exit_code))
    if resolved_exit_code is None and str(raw_status).casefold() in _SUCCESS_STATUSES:
        resolved_exit_code = 0
    elif resolved_exit_code is None and error_value is not None:
        resolved_exit_code = 1
    if resolved_exit_code is not None:
        try:
            resolved_exit_code = int(resolved_exit_code)
        except (TypeError, ValueError):
            resolved_exit_code = None

    raw_duration = source.get("duration", duration)
    if raw_duration in (None, ""):
        try:
            resolved_duration = float(source.get("duration_ms") or 0) / 1000
        except (TypeError, ValueError):
            resolved_duration = 0.0
    else:
        try:
            resolved_duration = float(raw_duration)
        except (TypeError, ValueError):
            resolved_duration = 0.0

    raw_data = source.get("data")
    data = dict(raw_data) if isinstance(raw_data, Mapping) else dict(source)
    normalized.update({
        "output": output,
        "stdout": "" if stdout is None else str(stdout),
        "stderr": stderr,
        "exitCode": resolved_exit_code,
        "exit_code": resolved_exit_code,
        "status": raw_status,
        "duration": round(max(0.0, resolved_duration), 6),
        "data": data,
        "error": error_value,
    })
    return normalized


__all__ = ["COMMAND_OUTPUT_SCHEMA", "normalize_command_output"]
