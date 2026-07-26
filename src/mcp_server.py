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
        "session lifecycle control, terminal_execute_batch for multi-command work, "
        "and terminal_interact for prompt-driven local interactions without a "
        "dedicated tool. For requests to transfer or send a file/package only, call "
        "file_transfer_list and then file_transfer_start; Device TUI resolves local "
        "paths and credentials and verifies the exact device-side file size. Never "
        "manually log in to FTP/SFTP or ask for transfer credentials when these tools "
        "apply. Use package_upgrade_start only for replacing/upgrading a package; it "
        "may set startup software or reboot according to App configuration. "
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
def terminal_execute_batch(
    commands: list[str],
    session_id: str | None = None,
    device_id: str | None = None,
    command_timeout_seconds: int = 30,
    total_timeout_seconds: int | None = None,
    max_output_chars_per_step: int = 16_384,
    mode: str = "auto",
    approval_token: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Execute multiple commands locally in one MCP call, waiting for each prompt."""
    return _client().terminal_execute_batch(
        commands,
        session_id=session_id,
        device_id=device_id,
        command_timeout_seconds=command_timeout_seconds,
        total_timeout_seconds=total_timeout_seconds,
        max_output_chars_per_step=max_output_chars_per_step,
        mode=mode,
        approval_token=approval_token,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def terminal_interact(
    steps: list[dict[str, Any]],
    session_id: str | None = None,
    device_id: str | None = None,
    total_timeout_seconds: int = 60,
    mode: str = "auto",
    approval_token: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Run a local send/expect/respond plan without model-paced prompt handling."""
    return _client().terminal_interact(
        steps,
        session_id=session_id,
        device_id=device_id,
        total_timeout_seconds=total_timeout_seconds,
        mode=mode,
        approval_token=approval_token,
        idempotency_key=idempotency_key,
    )


@mcp.tool()
def execution_get(execution_id: str) -> dict[str, Any]:
    """Read a running or completed local terminal execution."""
    return _client().execution_get(execution_id)


@mcp.tool()
def execution_cancel(execution_id: str) -> dict[str, Any]:
    """Cancel a local terminal execution and release its session."""
    return _client().execution_cancel(execution_id)


@mcp.tool()
def file_transfer_list(
    path: str = "",
    recursive: bool = True,
    limit: int = 200,
) -> dict[str, Any]:
    """List non-sensitive files available in Device TUI's transfer share."""
    return _client().file_transfer_list(
        path=path,
        recursive=recursive,
        limit=limit,
    )


@mcp.tool()
def file_transfer_start(
    device_id: str,
    source_path: str,
    destination_path: str,
    overwrite: bool = False,
    approval_token: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Transfer one shared file to a device without upgrading or rebooting it."""
    return _client().file_transfer_start(
        device_id,
        source_path,
        destination_path,
        overwrite=overwrite,
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


@mcp.tool()
def operation_cancel(operation_id: str) -> dict[str, Any]:
    """Cancel a cancellable long-running Device TUI operation."""
    return _client().operation_cancel(operation_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
