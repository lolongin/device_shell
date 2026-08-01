"""FastMCP entry point for the Device TUI desktop application."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .gateway import McpGateway
from .tools import register_all_tools


INSTRUCTIONS = (
    "Operate devices through the running Device TUI application. "
    "Use terminal_run as the default tool for one or more ordinary commands; "
    "it can prepare or reuse the target session in the same call. Use "
    "terminal_interact for prompt-driven terminal workflows. For requests to "
    "transfer a file only, call file_transfer_list and file_transfer_start. "
    "Use package_upgrade_start for guarded package replacement and "
    "operation_wait to wait for long-running work without repeated polling. "
    "The older terminal_send_command, terminal_read, terminal_execute, and "
    "terminal_execute_batch tools remain available for compatibility. Use "
    "stable device_id and session_id values. Device TUI retains risk "
    "classification, audit logging, terminal leases, local secret handling, "
    "and guarded package-upgrade workflows."
)


gateway = McpGateway()
mcp = FastMCP("Device TUI", instructions=INSTRUCTIONS)
register_all_tools(mcp, gateway)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
