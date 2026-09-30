"""Pure validation and result helpers for managed transfers."""

from __future__ import annotations

from dataclasses import fields

from device_tui.infrastructure.transfers.managed_file_transfer import (
    ManagedTransferError,
    TransferInteractionProfile,
)


class TransferRunError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def environment_label(terminal_environment: str) -> str:
    return "Linux Shell" if terminal_environment == "linux" else "Huawei VRP"


def normalize_command_mode(command_mode: str) -> str:
    normalized = str(command_mode or "vrp").strip().casefold()
    if normalized not in {"vrp", "ftpget"}:
        raise ManagedTransferError("invalid_request", f"不支持的设备 FTP 命令方式: {command_mode}")
    return normalized


def interaction_profile(value: object) -> TransferInteractionProfile | None:
    if not isinstance(value, dict) or not value:
        return None
    valid_fields = {item.name for item in fields(TransferInteractionProfile)}
    values = {str(key): str(raw) for key, raw in value.items() if str(key) in valid_fields and isinstance(raw, str)}
    return TransferInteractionProfile(**values) if values else None


def require_completed(result: dict[str, object], stage: str) -> str:
    status = str(result.get("status") or "")
    if status != "completed":
        if status in {"cancelled", "cancelled_by_user"}:
            raise TransferRunError("transfer_cancelled", "文件传输已取消。")
        if status == "timed_out":
            raise TransferRunError("transfer_timeout", f"{stage} 阶段超时。")
        raise TransferRunError("transfer_command_failed", str(result.get("message") or f"{stage} 阶段失败。"))
    return "".join(str(step.get("output") or "") for step in result.get("steps", []) if isinstance(step, dict))
