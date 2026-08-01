"""Terminal execution MCP tools."""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_terminal_tools(mcp: Any, gateway: McpGateway) -> None:
    @mcp.tool()
    def terminal_run(
        commands: list[str],
        session_id: str | None = None,
        device_id: str | None = None,
        ensure_session: bool = True,
        protocol: str = "auto",
        command_timeout_seconds: int = 30,
        total_timeout_seconds: int | None = None,
        max_output_chars_per_step: int = 16_384,
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Prepare a session and event-drive one or more ordinary commands."""
        return gateway.call(
            "terminal_run",
            commands,
            session_id=session_id,
            device_id=device_id,
            ensure_session=ensure_session,
            protocol=protocol,
            command_timeout_seconds=command_timeout_seconds,
            total_timeout_seconds=total_timeout_seconds,
            max_output_chars_per_step=max_output_chars_per_step,
            approval_token=approval_token,
            idempotency_key=idempotency_key,
        )

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
        return gateway.call(
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
        """Execute multiple commands locally, waiting for each device prompt."""
        return gateway.call(
            "terminal_execute_batch",
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
        """Run a local send, expect, response, and state-driven terminal plan."""
        return gateway.call(
            "terminal_interact",
            steps,
            session_id=session_id,
            device_id=device_id,
            total_timeout_seconds=total_timeout_seconds,
            mode=mode,
            approval_token=approval_token,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def terminal_send_command(
        device_id: str,
        command: str,
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility tool that sends a command without waiting for output."""
        return gateway.call(
            "terminal_send_command",
            device_id,
            command,
            approval_token=approval_token,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def terminal_read(device_id: str, max_chars: int = 4096) -> dict[str, Any]:
        """Compatibility tool that reads recent output for a device."""
        return gateway.call("terminal_read", device_id, max_chars=max_chars)

    @mcp.tool()
    def execution_get(execution_id: str) -> dict[str, Any]:
        """Read a running or completed local terminal execution."""
        return gateway.call("execution_get", execution_id)

    @mcp.tool()
    def execution_cancel(execution_id: str) -> dict[str, Any]:
        """Cancel a local terminal execution and release its session."""
        return gateway.call("execution_cancel", execution_id)
