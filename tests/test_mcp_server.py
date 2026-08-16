from __future__ import annotations

import asyncio

from device_tui.interfaces.mcp.server import mcp
from device_tui.interfaces.mcp.server import mcp as packaged_mcp


def test_mcp_server_exposes_device_control_tools() -> None:
    assert packaged_mcp is mcp
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "ai_create_session",
        "ai_download_file",
        "ai_execute_batch",
        "ai_execute_command",
        "ai_execute_script",
        "ai_get_result",
        "ai_list_skills",
        "ai_run_skill",
        "ai_upload_file",
        "system_status",
        "device_list",
        "device_get",
        "device_select",
        "session_list",
        "session_manage",
        "session_open",
        "terminal_execute",
        "terminal_execute_batch",
        "terminal_run",
        "terminal_interact",
        "terminal_send_command",
        "terminal_read",
        "execution_get",
        "execution_cancel",
        "file_transfer_list",
        "file_transfer_start",
        "package_upgrade_start",
        "approval_get",
        "operation_get",
        "operation_wait",
        "operation_cancel",
    }

    send_tool = next(tool for tool in tools if tool.name == "terminal_send_command")
    assert send_tool.inputSchema["required"] == ["device_id", "command"]
    assert "approval_token" in send_tool.inputSchema["properties"]

    execute_tool = next(tool for tool in tools if tool.name == "terminal_execute")
    assert execute_tool.inputSchema["required"] == ["command"]
    assert "session_id" in execute_tool.inputSchema["properties"]
    assert "device_id" in execute_tool.inputSchema["properties"]

    batch_tool = next(tool for tool in tools if tool.name == "terminal_execute_batch")
    assert batch_tool.inputSchema["required"] == ["commands"]
    assert "mode" in batch_tool.inputSchema["properties"]

    interact_tool = next(tool for tool in tools if tool.name == "terminal_interact")
    assert interact_tool.inputSchema["required"] == ["steps"]
    assert "total_timeout_seconds" in interact_tool.inputSchema["properties"]

    manage_tool = next(tool for tool in tools if tool.name == "session_manage")
    assert manage_tool.inputSchema["required"] == ["action"]

    transfer_tool = next(tool for tool in tools if tool.name == "file_transfer_start")
    assert transfer_tool.inputSchema["required"] == [
        "device_id",
        "source_path",
        "destination_path",
    ]
    assert "overwrite" in transfer_tool.inputSchema["properties"]

    run_tool = next(tool for tool in tools if tool.name == "terminal_run")
    assert run_tool.inputSchema["required"] == ["commands"]
    assert "ensure_session" in run_tool.inputSchema["properties"]
    assert "session_id" in run_tool.inputSchema["properties"]

    wait_tool = next(tool for tool in tools if tool.name == "operation_wait")
    assert wait_tool.inputSchema["required"] == ["operation_id"]
    assert "since_revision" in wait_tool.inputSchema["properties"]
