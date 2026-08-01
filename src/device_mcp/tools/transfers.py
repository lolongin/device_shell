"""File transfer and package workflow MCP tools."""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_transfer_tools(mcp: Any, gateway: McpGateway) -> None:
    @mcp.tool()
    def file_transfer_list(
        path: str = "",
        recursive: bool = True,
        limit: int = 200,
    ) -> dict[str, Any]:
        """List non-sensitive files available in Device TUI's transfer share."""
        return gateway.call(
            "file_transfer_list",
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
        """Transfer one shared file to a device without upgrading it."""
        return gateway.call(
            "file_transfer_start",
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
        return gateway.call(
            "package_upgrade_start",
            device_id,
            approval_token=approval_token,
            idempotency_key=idempotency_key,
        )
