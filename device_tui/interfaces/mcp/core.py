"""Shared constants, protocol types, and action helpers."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Protocol

from device_tui.application.ai.operations import AiDeviceAction, AiDeviceToolResult



MAX_COMMAND_CHARS = 16_384
DEFAULT_OUTPUT_CHARS = 4_096
MAX_OUTPUT_CHARS = 32_768
APPROVAL_TTL_SECONDS = 60
APPROVAL_MODE_DISABLED = "disabled"
APPROVAL_MODE_REQUIRED = "required"
SESSION_ACTIONS = {"open", "status", "reconnect", "disconnect", "close"}
SESSION_PROTOCOLS = {"auto", "telnet", "ssh", "serial", "simulated"}
TERMINAL_PLAN_MODES = {"auto", "sync", "async"}
OPERATION_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "error",
    "success",
    "rolled_back",
}
TERMINAL_EXECUTE_IDLE_SECONDS = 0.8
TERMINAL_EXECUTE_POLL_SECONDS = 0.05

def resolve_approval_mode(value: str | None = None) -> str:
    """Resolve the Device TUI approval policy from an explicit value or env."""
    configured = os.getenv("DEVICE_TUI_APPROVAL_MODE", "") if value is None else value
    if configured.strip().casefold() == APPROVAL_MODE_REQUIRED:
        return APPROVAL_MODE_REQUIRED
    return APPROVAL_MODE_DISABLED

class AppControlBackend(Protocol):
    def execute_ai_device_action(
        self,
        action: AiDeviceAction,
        *,
        approved: bool = False,
    ) -> AiDeviceToolResult:
        ...

    def gateway_service(self) -> Any:
        """Return the app's GatewayService facade (result store + skill registry)."""
        ...

    def gateway_script_style(self, device_id: str) -> str:
        """Return 'linux' (whole-block script) or 'network' (line-by-line)."""
        ...

class AppControlError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}

def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

def normalize_command(command: str) -> str:
    return " ".join(command.strip().split())

def action_fingerprint(action: AiDeviceAction) -> str:
    payload = {
        "kind": action.kind,
        "device_id": action.device_id,
        "command": normalize_command(action.command),
        "params": action.params,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def action_to_dict(action: AiDeviceAction) -> dict[str, Any]:
    payload = asdict(action)
    payload["risk"] = action.risk.name
    return payload

