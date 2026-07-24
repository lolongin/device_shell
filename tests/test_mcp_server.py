from __future__ import annotations

import asyncio

from src.mcp_server import mcp


def test_mcp_server_exposes_device_control_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "system_status",
        "device_list",
        "device_get",
        "device_select",
        "session_list",
        "session_manage",
        "session_open",
        "terminal_execute",
        "terminal_send_command",
        "terminal_read",
        "package_upgrade_start",
        "approval_get",
        "operation_get",
    }

    send_tool = next(tool for tool in tools if tool.name == "terminal_send_command")
    assert send_tool.inputSchema["required"] == ["device_id", "command"]
    assert "approval_token" in send_tool.inputSchema["properties"]

    execute_tool = next(tool for tool in tools if tool.name == "terminal_execute")
    assert execute_tool.inputSchema["required"] == ["command"]
    assert "session_id" in execute_tool.inputSchema["properties"]
    assert "device_id" in execute_tool.inputSchema["properties"]

    manage_tool = next(tool for tool in tools if tool.name == "session_manage")
    assert manage_tool.inputSchema["required"] == ["action"]
