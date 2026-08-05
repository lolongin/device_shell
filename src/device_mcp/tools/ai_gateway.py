"""AI Device Gateway MCP tools."""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_ai_gateway_tools(mcp: Any, gateway: McpGateway) -> None:
    @mcp.tool()
    def ai_create_session(device_id: str) -> dict[str, Any]:
        """Create or reuse a gateway session for a device."""
        return gateway.call("ai_create_session", device_id)

    @mcp.tool()
    def ai_execute_command(
        session_id: str,
        command: str,
        timeout_seconds: int = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Execute one command on a device and return a summarized result."""
        return gateway.call(
            "ai_execute_command",
            session_id=session_id,
            command=command,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def ai_execute_batch(
        commands: list[str],
        session_id: str | None = None,
        device_id: str | None = None,
        command_timeout_seconds: int = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Execute multiple commands in order. Pass session_id (preferred) or device_id."""
        return gateway.call(
            "ai_execute_batch",
            commands=commands,
            session_id=session_id,
            device_id=device_id,
            command_timeout_seconds=command_timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def ai_execute_script(
        script: str,
        session_id: str | None = None,
        device_id: str | None = None,
        shell: str | None = None,
        timeout_seconds: int = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Execute a script. Linux: whole block; network devices: line-by-line. Pass session_id (preferred) or device_id."""
        return gateway.call(
            "ai_execute_script",
            script=script,
            session_id=session_id,
            device_id=device_id,
            shell=shell,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def ai_upload_file(
        device_id: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Upload one shared file to a device."""
        return gateway.call(
            "ai_upload_file",
            device_id,
            source_path,
            destination_path,
            overwrite=overwrite,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def ai_download_file(
        device_id: str,
        source_path: str,
        destination_path: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Download one file from a device to the PC."""
        return gateway.call(
            "ai_download_file",
            device_id,
            source_path,
            destination_path,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def ai_get_result(result_id: str, include_raw: bool = False) -> dict[str, Any]:
        """Fetch a gateway execution result, optionally including raw output."""
        return gateway.call(
            "ai_get_result",
            result_id=result_id,
            include_raw=include_raw,
        )

    @mcp.tool()
    def ai_run_skill(
        skill_name: str,
        params: dict[str, Any],
        session_id: str | None = None,
        device_id: str | None = None,
        timeout_seconds: int = 60,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Run a parameterized skill (a reusable flow) on a device. Pass session_id (preferred) or device_id."""
        return gateway.call(
            "ai_run_skill",
            skill_name=skill_name,
            params=params,
            session_id=session_id,
            device_id=device_id,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )
