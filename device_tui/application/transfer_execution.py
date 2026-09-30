"""Execution strategies for managed file transfers."""

from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
from collections.abc import Awaitable, Callable
from typing import Protocol

from device_tui.application.terminal.orchestration import (
    TerminalPlanError,
    parse_terminal_plan,
)
from device_tui.application.terminal.plan_models import TerminalExecutionPlan
from device_tui.infrastructure.transfers.file_transfer_service import TransferServiceConfig
from device_tui.infrastructure.transfers.managed_file_transfer import (
    ManagedTransferError,
    _validate_relative_path,
    build_ftpget_command,
    build_ftpget_transfer_steps,
    build_managed_transfer_download_steps,
    build_managed_transfer_steps,
    destination_entry,
    destination_matches,
    linux_file_size,
    linux_free_space_bytes,
    resolve_shared_file,
    source_fingerprint,
    TransferInteractionProfile,
)

from .errors import TransferOperationError
from .operations import OperationManager, OperationRecord
from .sessions import SessionRecord
from .transfer_execution_context import prepare_transfer_execution
from .transfer_helpers import (
    TransferRunError,
    environment_label,
    interaction_profile,
    require_completed,
)
from .transfer_planning import inspection_plan, require_linux_inspection
from .transfer_ports import TerminalPlanExecutor


class TransferExecutionHost(Protocol):
    _operations: OperationManager
    _executor: TerminalPlanExecutor

    async def _ensure_service(self) -> TransferServiceConfig: ...
    def _saved_config(self) -> dict[str, object]: ...
    def _device_host(self, session: SessionRecord, config: TransferServiceConfig) -> str: ...
    def _register_runtime_credentials(self, operation_id: str, username: str, password: str) -> tuple[str, str]: ...
    def _register_runtime_command(self, operation_id: str, command: str) -> str: ...
    def _clear_runtime_credentials(self, operation_id: str) -> None: ...
    async def _run_plan(self, session: SessionRecord, owner_id: str, plan: TerminalExecutionPlan) -> dict[str, object]: ...
    def _record_progress(self, operation_id: str, transferred: int, *, force: bool = False) -> None: ...
    def _cancel_active(self, operation_id: str, session_id: str, *, pause_queue: bool) -> None: ...
    def _mark_cancelled(self, operation_id: str) -> None: ...
    def _mark_failed(self, operation_id: str, code: str, message: str) -> None: ...


class TransferExecutionRunner:
    """Owns transport-plan execution while the application service owns queueing."""

    def __init__(self, host: TransferExecutionHost, controller: object) -> None:
        self._host = host
        self._controller = controller

    async def upload(self, operation_id: str, session: SessionRecord) -> None:
        await self._execute(operation_id, session, self._run_upload)

    async def ftpget_upload(self, operation_id: str, session: SessionRecord) -> None:
        await self._execute(operation_id, session, self._run_ftpget_upload)

    async def download(self, operation_id: str, session: SessionRecord) -> None:
        await self._execute(operation_id, session, self._run_download)

    async def _execute(
        self,
        operation_id: str,
        session: SessionRecord,
        action: Callable[[str, SessionRecord, str], Awaitable[str]],
    ) -> None:
        owner_id = f"managed-transfer:{operation_id}"
        acquired = False
        managed_username = ""
        try:
            self._host._executor.acquire(
                session.id,
                owner_id,
                on_cancel=lambda: self._host._cancel_active(operation_id, session.id, pause_queue=True),
            )
            acquired = True
            managed_username = await action(operation_id, session, owner_id)
        except asyncio.CancelledError:
            self._host._mark_cancelled(operation_id)
        except (ManagedTransferError, TerminalPlanError, TransferOperationError, TransferRunError, RuntimeError, OSError) as exc:
            current = self._host._operations.get(operation_id)
            if current.status == "cancelled":
                return
            self._host._mark_failed(operation_id, getattr(exc, "code", "transfer_failed"), str(exc))
        finally:
            if managed_username:
                self._controller.unregister_managed_transfer(managed_username)
            self._host._clear_runtime_credentials(operation_id)
            if acquired:
                self._host._executor.release(session.id, owner_id)

    async def _run_upload(self, operation_id: str, session: SessionRecord, owner_id: str) -> str:
        host = self._host
        current = host._operations.get(operation_id)
        source, info = resolve_shared_file(
            Path(str(host._saved_config()["root"])),
            str(current.data["source_path"]),
        )
        initial_fingerprint = source_fingerprint(source)
        operation = host._operations.update(
            operation_id,
            stage="prechecking",
            message="正在检查设备目标路径和可用空间。",
            progress_percent=0,
            total_bytes=info.size_bytes,
            bytes_transferred=0,
            bytes_per_second=0,
            clear_eta=True,
        )
        destination = str(operation.data["destination_path"])
        terminal_environment = str(operation.data.get("terminal_environment") or "vrp")
        protocol = str(host._saved_config()["protocol"])
        output = require_completed(
            await host._run_plan(
                session,
                owner_id,
                inspection_plan(destination, terminal_environment, protocol),
            ),
            "prechecking",
        )
        if terminal_environment == "linux":
            require_linux_inspection(output, protocol)
            existing_size = linux_file_size(output)
            free_bytes = linux_free_space_bytes(output)
        else:
            from device_tui.infrastructure.vendor_adapters.huawei_vrp.parsers import find_free_space_bytes
            existing = destination_entry(output, destination)
            existing_size = existing.size_bytes if existing is not None else None
            free_bytes = find_free_space_bytes(output)
        if existing_size is not None and not bool(operation.data["overwrite"]):
            raise TransferRunError("destination_exists", f"设备目标文件已存在，大小为 {existing_size} 字节。")
        source_size = int(operation.data["source_size"])
        required = max(0, source_size - (existing_size or 0))
        if free_bytes is None:
            raise TransferRunError("storage_space_indeterminate", "设备目录输出未包含可识别的可用空间，未开始传输。")
        if free_bytes < required:
            raise TransferRunError("insufficient_space", f"设备可用空间不足，需要 {required} 字节，可用 {free_bytes} 字节。")
        if source_fingerprint(source) != initial_fingerprint:
            raise TransferRunError("transfer_source_changed", "传输前源文件发生变化。")
        context = await prepare_transfer_execution(
            host,
            operation_id=operation_id,
            session=session,
            terminal_environment=terminal_environment,
            source_path=str(operation.data["source_path"]),
            source_size=source_size,
            destination_path=destination,
        )
        host._operations.update(operation_id, data={"service_host": context.host})
        steps, timeout = build_managed_transfer_steps(
            protocol=context.config.protocol,
            host=context.host,
            port=self._controller.bound_port or context.config.port,
            source_path=str(operation.data["source_path"]),
            destination_path=destination,
            source_size=source_size,
            overwrite=bool(operation.data.get("overwrite", False)),
            username_secret_ref=context.username_ref,
            password_secret_ref=context.password_ref,
            terminal_environment=terminal_environment,
            connect_secret_ref=context.connect_secret_ref,
            profile=interaction_profile(current.data.get("interaction_profile")),
        )
        host._operations.update(
            operation_id,
            stage="transferring",
            message=f"正在通过 {context.config.protocol.upper()}（{environment_label(terminal_environment)}）传输文件。",
            progress_percent=0,
        )
        result = await host._run_plan(session, owner_id, parse_terminal_plan(steps, total_timeout_seconds=timeout))
        require_completed(result, "transferring")
        host._record_progress(operation_id, source_size, force=True)
        if source_fingerprint(source) != initial_fingerprint:
            raise TransferRunError("transfer_source_changed", "传输期间源文件发生变化。")
        host._operations.update(operation_id, stage="verifying", message="正在核对设备端文件名和精确字节数。", progress_percent=100, bytes_per_second=0, clear_eta=True)
        verify_output = require_completed(
            await host._run_plan(session, owner_id, inspection_plan(destination, terminal_environment, context.config.protocol)),
            "verifying",
        )
        verified_size = linux_file_size(verify_output) if terminal_environment == "linux" else None
        verified_matches = verified_size == source_size if terminal_environment == "linux" else destination_matches(verify_output, destination, source_size)
        if not verified_matches:
            raise TransferRunError("transfer_verification_failed", "设备端文件不存在，或字节数与源文件不一致。")
        host._operations.update(operation_id, status="completed", stage="completed", message=f"文件已传到 {destination}，并确认 {source_size} 字节完全匹配。", progress_percent=100, bytes_transferred=source_size, total_bytes=source_size, bytes_per_second=0, clear_eta=True, error_code="")
        return context.managed_username

    async def _run_ftpget_upload(self, operation_id: str, session: SessionRecord, owner_id: str) -> str:
        host = self._host
        operation = host._operations.get(operation_id)
        source, info = resolve_shared_file(Path(str(host._saved_config()["root"])), str(operation.data["source_path"]))
        initial_fingerprint = source_fingerprint(source)
        saved_config = host._saved_config()
        if str(saved_config["protocol"]).casefold() != "ftp":
            raise TransferRunError("ftpget_requires_ftp", "ftpget 单命令需要将本机文件服务协议设置为 FTP。")
        if int(saved_config["port"]) != 21:
            raise TransferRunError("ftpget_requires_port_21", "当前 ftpget 语法不包含端口参数，请将 FTP 服务端口设置为 21。")
        host._operations.update(operation_id, stage="prechecking", message="正在检查 ftpget 命令和本机 FTP 服务配置。", progress_percent=0, total_bytes=info.size_bytes, bytes_transferred=0, bytes_per_second=0, clear_eta=True)
        config = await host._ensure_service()
        bound_port = self._controller.bound_port or config.port
        if bound_port != 21:
            raise TransferRunError("ftpget_requires_port_21", f"当前 FTP 服务实际端口为 {bound_port}，ftpget 单命令需要端口 21。")
        context = await prepare_transfer_execution(host, operation_id=operation_id, session=session, terminal_environment=str(operation.data.get("terminal_environment") or "vrp"), source_path=info.relative_path, source_size=info.size_bytes, destination_path=info.relative_path)
        command = build_ftpget_command(username=context.managed_username, password=context.managed_password, host=context.host, source_path=info.relative_path)
        command_ref = host._register_runtime_command(operation_id, command)
        steps, timeout = build_ftpget_transfer_steps(command_secret_ref=command_ref, source_size=info.size_bytes)
        host._operations.update(operation_id, stage="transferring", message="已向当前终端发送 ftpget，正在等待 FTP 数据传输完成。", progress_percent=0, data={"service_host": context.host, "service_port": bound_port, "command_preview": f"ftpget -u <临时账号> -p ****** {context.host} {info.relative_path}", "verification": "ftp_server_and_terminal_completion"})
        require_completed(await host._run_plan(session, owner_id, parse_terminal_plan(steps, total_timeout_seconds=timeout)), "transferring")
        host._record_progress(operation_id, info.size_bytes, force=True)
        if source_fingerprint(source) != initial_fingerprint:
            raise TransferRunError("transfer_source_changed", "传输期间源文件发生变化。")
        host._operations.update(operation_id, status="completed", stage="completed", message=f"ftpget 已完成 {info.relative_path}，本机 FTP 服务共发送 {info.size_bytes} 字节。", progress_percent=100, bytes_transferred=info.size_bytes, total_bytes=info.size_bytes, bytes_per_second=0, clear_eta=True, error_code="")
        return context.managed_username

    async def _run_download(self, operation_id: str, session: SessionRecord, owner_id: str) -> str:
        host = self._host
        operation = host._operations.update(operation_id, stage="prechecking", message="正在检查设备源文件和 PC 目标空间。", progress_percent=0, bytes_transferred=0, bytes_per_second=0, clear_eta=True)
        source_path = str(operation.data["source_path"])
        terminal_environment = str(operation.data.get("terminal_environment") or "vrp")
        protocol = str(host._saved_config()["protocol"])
        output = require_completed(await host._run_plan(session, owner_id, inspection_plan(source_path, terminal_environment, protocol)), "prechecking")
        if terminal_environment == "linux":
            require_linux_inspection(output, protocol)
            source_size = linux_file_size(output)
        else:
            entry = destination_entry(output, source_path)
            source_size = entry.size_bytes if entry is not None else None
        if source_size is None:
            raise TransferRunError("transfer_source_not_found", "设备端源文件不存在。")
        root = Path(str(host._saved_config()["root"]))
        relative = str(operation.data["destination_path"])
        destination = root.joinpath(*_validate_relative_path(relative, label="destination_path").parts)
        existing_size = destination.stat().st_size if destination.is_file() else 0
        if destination.exists() and not bool(operation.data["overwrite"]):
            raise TransferRunError("destination_exists", "PC 目标文件已存在。")
        if shutil.disk_usage(root).free < max(0, source_size - existing_size):
            raise TransferRunError("insufficient_space", "PC 共享目录可用空间不足。")
        operation = host._operations.update(operation_id, total_bytes=source_size, data={"source_size": source_size})
        config = await host._ensure_service()
        if not config.writable:
            raise TransferRunError("transfer_service_read_only", "设备下载到 PC 时文件服务必须允许写入。")
        context = await prepare_transfer_execution(host, operation_id=operation_id, session=session, terminal_environment=terminal_environment, source_path=source_path, source_size=source_size, destination_path=relative)
        host._operations.update(operation_id, data={"service_host": context.host})
        steps, timeout = build_managed_transfer_download_steps(protocol=context.config.protocol, host=context.host, port=self._controller.bound_port or context.config.port, source_path=source_path, destination_path=relative, source_size=source_size, username_secret_ref=context.username_ref, password_secret_ref=context.password_ref, terminal_environment=terminal_environment, connect_secret_ref=context.connect_secret_ref, profile=interaction_profile(operation.data.get("interaction_profile")))
        host._operations.update(operation_id, stage="transferring", message=f"正在通过 {context.config.protocol.upper()}（{environment_label(terminal_environment)}）下载文件。", progress_percent=0)
        require_completed(await host._run_plan(session, owner_id, parse_terminal_plan(steps, total_timeout_seconds=timeout)), "transferring")
        host._record_progress(operation_id, source_size, force=True)
        host._operations.update(operation_id, stage="verifying", message="正在核对 PC 端文件名和精确字节数。", progress_percent=100, bytes_per_second=0, clear_eta=True)
        if not destination.is_file() or destination.stat().st_size != source_size:
            raise TransferRunError("transfer_verification_failed", "PC 目标文件不存在，或字节数与设备源文件不一致。")
        host._operations.update(operation_id, status="completed", stage="completed", message=f"文件已下载到 {relative}，并确认 {source_size} 字节完全匹配。", progress_percent=100, bytes_transferred=source_size, total_bytes=source_size, bytes_per_second=0, clear_eta=True, error_code="")
        return context.managed_username
