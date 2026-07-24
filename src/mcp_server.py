"""MCP tool facade for a running Device TUI desktop application."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .app_control_client import AppControlClient, AppControlClientError


mcp = FastMCP(
    "Device TUI",
    instructions=(
        "Operate devices through the running Device TUI application. "
        "Use system_status and device_get for discovery, session_manage for reliable "
        "session lifecycle control, and terminal_execute for command-specific output. "
        "Use stable device_id and session_id values. Device TUI retains risk "
        "classification, audit logging, and guarded package-upgrade workflows."
    ),
)


def _client() -> AppControlClient:
    client = AppControlClient.from_state_file()
    client.health()
    return client


def _call(method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return getattr(_client(), method)(*args, **kwargs)
    except AppControlClientError as exc:
        if exc.response:
            return exc.response
        return {
            "ok": False,
            "message": str(exc),
            "data": {},
            "approval": None,
            "error": {"code": "app_unavailable", "message": str(exc), "details": {}},
        }


@mcp.tool()
def system_status() -> dict[str, Any]:
    """Inspect Device TUI readiness, approval mode, sessions, and operations."""
    return _call("system_status")


@mcp.tool()
def device_list() -> dict[str, Any]:
    """List devices visible in Device TUI, including the simulated device."""
    return _call("device_list")


@mcp.tool()
def device_get(device_id: str) -> dict[str, Any]:
    """Get credential-free device details, capabilities, and endpoints."""
    return _call("device_get", device_id)


@mcp.tool()
def device_select(device_id: str) -> dict[str, Any]:
    """Select a device by its stable Device TUI ID."""
    return _call("device_select", device_id)


@mcp.tool()
def session_open(device_id: str) -> dict[str, Any]:
    """Open or reuse a terminal session for a device."""
    return _call("session_open", device_id)


@mcp.tool()
def session_list(device_id: str | None = None) -> dict[str, Any]:
    """List runtime terminal sessions, optionally filtered by device."""
    return _call("session_list", device_id)


@mcp.tool()
def session_manage(
    action: str,
    device_id: str | None = None,
    session_id: str | None = None,
    protocol: str = "auto",
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    """Open, inspect, reconnect, disconnect, or close a terminal session."""
    return _call(
        "session_manage",
        action,
        device_id=device_id,
        session_id=session_id,
        protocol=protocol,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool()
def terminal_send_command(
    device_id: str,
    command: str,
    approval_token: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Send a terminal command through the app's risk and audit controls."""
    return _call(
        "terminal_send_command",
        device_id,
        command,
        approval_token=approval_token,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def terminal_read(device_id: str, max_chars: int = 4096) -> dict[str, Any]:
    """Read recent terminal output for a device."""
    return _call("terminal_read", device_id, max_chars=max_chars)


@mcp.tool()
def terminal_execute(
    command: str,
    session_id: str | None = None,
    device_id: str | None = None,
    timeout_seconds: int = 30,
    max_output_chars: int = 16_384,
    approval_token: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Execute one command and return only its incremental terminal output."""
    return _call(
        "terminal_execute",
        command,
        session_id=session_id,
        device_id=device_id,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
        approval_token=approval_token,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def package_upgrade_start(
    device_id: str,
    approval_token: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Start the guarded package-upgrade state machine for a device."""
    return _call(
        "package_upgrade_start",
        device_id,
        approval_token=approval_token,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def approval_get(approval_id: str) -> dict[str, Any]:
    """Poll an approval when Device TUI compatibility approval mode is enabled."""
    return _call("approval_get", approval_id)


@mcp.tool()
def operation_get(operation_id: str) -> dict[str, Any]:
    """Poll a long-running Device TUI operation."""
    return _call("operation_get", operation_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
