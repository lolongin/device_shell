"""Terminal-plan construction and inspection validation for managed transfers."""

from __future__ import annotations

from device_tui.application.terminal.orchestration import TerminalExecutionPlan, parse_terminal_plan
from device_tui.infrastructure.transfers.managed_file_transfer import (
    build_linux_inspection_command,
    destination_storage,
    linux_client_available,
    linux_directory_available,
)
from .transfer_helpers import TransferRunError


def inspection_plan(path: str, terminal_environment: str, protocol: str) -> TerminalExecutionPlan:
    if terminal_environment == "linux":
        return parse_terminal_plan(
            [
                {"type": "send", "text": build_linux_inspection_command(path, protocol), "label": "检查 Linux 文件、空间和传输客户端"},
                {"type": "expect", "success": ["device_prompt"], "timeout_seconds": 30, "label": "等待 Linux 检查结果", "max_output_chars": 32_768},
            ],
            total_timeout_seconds=45,
        )
    return parse_terminal_plan(
        [
            {"type": "send", "text": f"dir {destination_storage(path)}", "label": "读取目录"},
            {
                "type": "expect", "success": ["device_prompt"],
                "responses": [{"match": "pagination_prompt", "control": "space", "append_enter": False, "max_matches": 100}],
                "failures": ["Unrecognized command", "Unknown command"],
                "timeout_seconds": 30, "label": "等待目录输出", "max_output_chars": 32_768,
            },
        ],
        total_timeout_seconds=45,
    )


def require_linux_inspection(output: str, protocol: str) -> None:
    if not linux_client_available(output):
        raise TransferRunError("transfer_client_unavailable", f"Linux Shell 中未找到 {protocol.upper()} 客户端，请安装后重试或切换传输协议。")
    if not linux_directory_available(output):
        raise TransferRunError("transfer_directory_not_found", "Linux 文件路径的父目录不存在。")
