"""App-owned, verifiable file transfer operations."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import shutil
import time
from typing import Any
from uuid import uuid4

try:
    from PySide6.QtCore import QTimer
except ModuleNotFoundError:
    QTimer = None

from ..ai_device_ops import AiDeviceAction, RiskLevel
from ..file_transfer_service import TransferServiceConfig, TransferServiceController
from ..managed_file_transfer import (
    ManagedTransferError,
    _validate_relative_path,
    build_managed_transfer_download_steps,
    build_managed_transfer_steps,
    destination_entry,
    destination_matches,
    list_shared_files,
    resolve_shared_file,
    source_fingerprint,
    validate_destination_path,
)
from ..package_upgrade import parse_free_space_bytes
from ..terminal_orchestration import TerminalPlanError, parse_terminal_plan


class ManagedFileTransferOpsMixin:
    """Run transfer-only operations without model-paced FTP interaction."""

    MANAGED_TRANSFER_SESSION_TIMEOUT_MS = 15_000

    def managed_transfer_file_list(
        self,
        *,
        relative_path: str = "",
        recursive: bool = True,
        limit: int = 200,
    ) -> dict[str, Any]:
        config = self._managed_transfer_config()
        catalog = list_shared_files(
            config.root,
            relative_path=relative_path,
            recursive=recursive,
            limit=limit,
        )
        return {
            "files": [item.public_dict() for item in catalog.files],
            "count": len(catalog.files),
            "truncated": catalog.truncated,
            "protocol": config.protocol,
            "service_running": bool(
                self.transfer_service and self.transfer_service.is_running
            ),
        }

    def start_managed_file_transfer(
        self,
        *,
        device_id: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        config = self._managed_transfer_config()
        source, source_info = resolve_shared_file(config.root, source_path)
        destination = validate_destination_path(destination_path)
        device = self._ai_device(device_id)
        if device is None:
            raise ManagedTransferError(
                "device_not_found",
                f"未找到设备: {device_id}",
            )
        operation_id = str(uuid4())
        started = time.monotonic()
        runs = self._managed_transfer_runs()
        runs[operation_id] = {
            "operation_id": operation_id,
            "kind": "managed_file_transfer",
            "device_id": device_id,
            "source_path": source_info.relative_path,
            "source_name": source_info.name,
            "source_size": source_info.size_bytes,
            "destination_path": destination,
            "overwrite": bool(overwrite),
            "status": "running",
            "stage": "opening_session",
            "message": "正在打开或复用设备终端会话。",
            "created_monotonic": started,
            "updated_monotonic": started,
            "source_absolute": source,
            "source_fingerprint": source_fingerprint(source),
            "session_id": "",
            "lease_owner_id": f"managed-transfer:{operation_id}",
            "execution_id": "",
            "lease_acquired": False,
            "error_code": "",
        }
        open_action = AiDeviceAction(
            "session_manage",
            "为托管文件传输打开终端",
            RiskLevel.LOW,
            device_id=device_id,
            params={"action": "open", "protocol": "auto"},
        )
        opened = self._ai_open_managed_session(open_action)
        if not opened.ok:
            self._managed_transfer_fail(
                operation_id,
                opened.error_code or "session_open_failed",
                opened.message,
            )
            return self.managed_transfer_status_snapshot(operation_id)
        session = opened.data.get("session")
        session_id = str(session.get("session_id") if isinstance(session, dict) else "")
        runs[operation_id]["session_id"] = session_id
        self._wait_for_managed_transfer_session(operation_id, 0)
        return self.managed_transfer_status_snapshot(operation_id)

    def start_managed_transfer_download(
        self,
        *,
        device_id: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Start a managed device->PC transfer (device `put` to the PC server)."""
        config = self._managed_transfer_config()
        source = validate_destination_path(source_path)
        destination = _validate_relative_path(
            destination_path,
            label="destination_path",
        ).as_posix()
        device = self._ai_device(device_id)
        if device is None:
            raise ManagedTransferError(
                "device_not_found",
                f"未找到设备: {device_id}",
            )
        operation_id = str(uuid4())
        started = time.monotonic()
        runs = self._managed_transfer_runs()
        runs[operation_id] = {
            "operation_id": operation_id,
            "kind": "managed_file_transfer",
            "direction": "download",
            "device_id": device_id,
            "source_path": source,
            "source_name": PurePosixPath(source).name,
            "source_size": 0,
            "destination_path": destination,
            "overwrite": bool(overwrite),
            "status": "running",
            "stage": "opening_session",
            "message": "正在打开或复用设备终端会话。",
            "created_monotonic": started,
            "updated_monotonic": started,
            "source_absolute": "",
            "source_fingerprint": (),
            "root": config.root,
            "session_id": "",
            "lease_owner_id": f"managed-transfer:{operation_id}",
            "execution_id": "",
            "lease_acquired": False,
            "error_code": "",
        }
        open_action = AiDeviceAction(
            "session_manage",
            "为托管文件传输打开终端",
            RiskLevel.LOW,
            device_id=device_id,
            params={"action": "open", "protocol": "auto"},
        )
        opened = self._ai_open_managed_session(open_action)
        if not opened.ok:
            self._managed_transfer_fail(
                operation_id,
                opened.error_code or "session_open_failed",
                opened.message,
            )
            return self.managed_transfer_status_snapshot(operation_id)
        session = opened.data.get("session")
        session_id = str(session.get("session_id") if isinstance(session, dict) else "")
        runs[operation_id]["session_id"] = session_id
        self._wait_for_managed_transfer_session(operation_id, 0)
        return self.managed_transfer_status_snapshot(operation_id)

    def managed_transfer_status_snapshot(self, operation_id: str) -> dict[str, Any]:
        operation = self._managed_transfer_runs().get(operation_id)
        if operation is None:
            raise ManagedTransferError(
                "operation_not_found",
                f"未找到文件传输操作: {operation_id}",
            )
        now = time.monotonic()
        public_keys = (
            "operation_id",
            "kind",
            "device_id",
            "source_path",
            "source_name",
            "source_size",
            "destination_path",
            "overwrite",
            "status",
            "stage",
            "message",
            "session_id",
            "execution_id",
            "error_code",
        )
        snapshot = {
            key: operation.get(key)
            for key in public_keys
            if operation.get(key) not in {"", None}
        }
        snapshot["duration_ms"] = round(
            max(0.0, now - float(operation["created_monotonic"])) * 1000,
            2,
        )
        return snapshot

    def cancel_managed_file_transfer(self, operation_id: str) -> dict[str, Any]:
        operation = self._managed_transfer_runs().get(operation_id)
        if operation is None:
            raise ManagedTransferError(
                "operation_not_found",
                f"未找到文件传输操作: {operation_id}",
            )
        if operation.get("status") != "running":
            return self.managed_transfer_status_snapshot(operation_id)
        operation.update(
            {
                "status": "cancelled",
                "stage": "cancelled",
                "message": "文件传输已取消。",
                "error_code": "transfer_cancelled",
                "updated_monotonic": time.monotonic(),
            }
        )
        execution_id = str(operation.get("execution_id") or "")
        if execution_id:
            try:
                self.terminal_execution_coordinator.cancel(execution_id)
            except TerminalPlanError:
                pass
        self._release_managed_transfer_lease(operation)
        return self.managed_transfer_status_snapshot(operation_id)

    def managed_transfer_active_count(self) -> int:
        return sum(
            operation.get("status") == "running"
            for operation in self._managed_transfer_runs().values()
        )

    def _managed_transfer_runs(self) -> dict[str, dict[str, Any]]:
        runs = getattr(self, "managed_file_transfer_runs", None)
        if not isinstance(runs, dict):
            runs = {}
            self.managed_file_transfer_runs = runs
        return runs

    def _managed_transfer_config(self) -> TransferServiceConfig:
        service = getattr(self, "transfer_service", None)
        running_config = getattr(service, "config", None)
        if service is not None and service.is_running and running_config is not None:
            return running_config
        protocol = (
            self.transfer_protocol_combo.currentText().strip().casefold()
            if hasattr(self, "transfer_protocol_combo")
            else str(getattr(self, "transfer_protocol", "ftp")).casefold()
        )
        host = (
            self.transfer_host_input.text().strip()
            if hasattr(self, "transfer_host_input")
            else str(getattr(self, "transfer_host", ""))
        ) or "0.0.0.0"
        port_text = (
            self.transfer_port_input.text().strip()
            if hasattr(self, "transfer_port_input")
            else str(getattr(self, "transfer_port", 2121))
        )
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ManagedTransferError(
                "invalid_request",
                "文件传输服务端口必须是数字。",
            ) from exc
        if not 1 <= port <= 65535:
            raise ManagedTransferError(
                "invalid_request",
                "文件传输服务端口必须在 1-65535 之间。",
            )
        root_text = (
            self.transfer_root_input.text().strip()
            if hasattr(self, "transfer_root_input")
            else str(getattr(self, "transfer_root_directory", ""))
        )
        username = (
            self.transfer_username_input.text().strip()
            if hasattr(self, "transfer_username_input")
            else str(getattr(self, "transfer_username", "")).strip()
        )
        password = (
            self.transfer_password_input.text()
            if hasattr(self, "transfer_password_input")
            else str(getattr(self, "transfer_password", ""))
        )
        if protocol not in {"ftp", "sftp"}:
            raise ManagedTransferError(
                "invalid_request",
                f"不支持的文件传输协议: {protocol}",
            )
        if not username or not password:
            raise ManagedTransferError(
                "transfer_credentials_unavailable",
                "请先在 App 文件传输服务中配置账号和密码。",
            )
        return TransferServiceConfig(
            protocol=protocol,
            host=host,
            port=port,
            root=Path(root_text).expanduser(),
            username=username,
            password=password,
            writable=bool(
                self.transfer_writable_checkbox.isChecked()
                if hasattr(self, "transfer_writable_checkbox")
                else getattr(self, "transfer_writable", False)
            ),
        )

    def _wait_for_managed_transfer_session(
        self,
        operation_id: str,
        elapsed_ms: int,
    ) -> None:
        operation = self._managed_transfer_runs().get(operation_id)
        if not self._managed_transfer_is_active(operation):
            return
        assert operation is not None
        state = self.session_tabs_by_id.get(str(operation.get("session_id") or ""))
        if state is not None and bool(getattr(state.session, "is_connected", False)):
            self._start_managed_transfer_precheck(operation_id, state)
            return
        if elapsed_ms >= self.MANAGED_TRANSFER_SESSION_TIMEOUT_MS:
            self._managed_transfer_fail(
                operation_id,
                "session_not_connected",
                "等待设备终端连接超时。",
            )
            return
        self._schedule_managed_transfer(
            100,
            lambda: self._wait_for_managed_transfer_session(
                operation_id,
                elapsed_ms + 100,
            ),
        )

    def _start_managed_transfer_precheck(
        self,
        operation_id: str,
        state: Any,
    ) -> None:
        operation = self._managed_transfer_runs().get(operation_id)
        if not self._managed_transfer_is_active(operation):
            return
        assert operation is not None
        owner_id = str(operation["lease_owner_id"])
        try:
            self.terminal_execution_coordinator.acquire_external_lease(
                state.tab_id,
                owner_id,
                on_cancel=lambda: self.cancel_managed_file_transfer(operation_id),
            )
        except TerminalPlanError as exc:
            self._managed_transfer_fail(operation_id, exc.code, str(exc))
            return
        operation["lease_acquired"] = True
        self._managed_transfer_update(
            operation,
            stage="prechecking",
            message="正在检查设备源文件和 PC 共享目录空间。"
            if operation.get("direction") == "download"
            else "正在检查设备目标文件和可用空间。",
        )
        steps = [
            {
                "type": "send",
                "text": f"dir {self._managed_transfer_device_path(operation)}",
                "label": "读取设备源文件状态"
                if operation.get("direction") == "download"
                else "读取目标文件状态",
            },
            {
                "type": "expect",
                "success": ["device_prompt"],
                "failures": ["Unrecognized command", "Unknown command"],
                "timeout_seconds": 30,
                "label": "等待目标目录输出",
                "max_output_chars": 32_768,
            },
        ]
        self._start_managed_transfer_plan(
            operation_id,
            steps,
            total_timeout_seconds=45,
            on_done=self._finish_managed_transfer_precheck,
        )

    def _finish_managed_transfer_precheck(
        self,
        operation_id: str,
        result: dict[str, Any],
    ) -> None:
        operation = self._managed_transfer_runs().get(operation_id)
        if not self._managed_transfer_is_active(operation):
            return
        assert operation is not None
        if result.get("status") != "completed":
            self._managed_transfer_plan_failed(operation_id, result, "prechecking")
            return
        output = self._managed_transfer_plan_output(result)
        if operation.get("direction") == "download":
            self._finish_managed_transfer_precheck_download(
                operation_id,
                operation,
                output,
            )
            return
        existing = destination_entry(output, str(operation["destination_path"]))
        if existing is not None and not operation["overwrite"]:
            self._managed_transfer_fail(
                operation_id,
                "destination_exists",
                f"目标文件已存在，大小为 {existing.size_bytes} 字节；如需覆盖请显式设置 overwrite=true。",
            )
            return
        required_bytes = max(
            0,
            int(operation["source_size"]) - (existing.size_bytes if existing else 0),
        )
        free_bytes = parse_free_space_bytes(output)
        if free_bytes > 0 and required_bytes > free_bytes:
            self._managed_transfer_fail(
                operation_id,
                "insufficient_space",
                f"设备可用空间不足，需要 {required_bytes} 字节，可用 {free_bytes} 字节。",
            )
            return
        if not self._managed_transfer_source_unchanged(operation):
            self._managed_transfer_fail(
                operation_id,
                "transfer_source_changed",
                "预检期间源文件发生变化，请重新发起传输。",
            )
            return
        self._start_managed_transfer_download(operation_id)

    def _finish_managed_transfer_precheck_download(
        self,
        operation_id: str,
        operation: dict[str, Any],
        output: str,
    ) -> None:
        # For the device->PC direction the `dir` output describes the device-side
        # SOURCE file; capture its size to drive the transfer timeout and use it as
        # the verification oracle. The PC-side destination must stay inside the
        # transfer share (already validated) and be free/overwritable.
        entry = destination_entry(output, str(operation["source_path"]))
        if entry is None:
            self._managed_transfer_fail(
                operation_id,
                "transfer_source_not_found",
                f"设备端源文件不存在: {operation['source_path']}",
            )
            return
        operation["source_size"] = entry.size_bytes
        root = Path(str(operation.get("root") or ""))
        existing = self._managed_transfer_shared_entry(
            root,
            str(operation["destination_path"]),
        )
        if existing is not None and not operation["overwrite"]:
            self._managed_transfer_fail(
                operation_id,
                "destination_exists",
                f"PC 共享目录目标文件已存在，大小为 {existing.size_bytes} 字节；"
                "如需覆盖请显式设置 overwrite=true。",
            )
            return
        required_bytes = max(
            0,
            int(operation["source_size"]) - (existing.size_bytes if existing else 0),
        )
        try:
            free_bytes = shutil.disk_usage(root).free
        except OSError as exc:
            self._managed_transfer_fail(
                operation_id,
                "transfer_root_unavailable",
                f"无法读取 PC 共享目录磁盘空间: {exc}",
            )
            return
        if required_bytes > free_bytes:
            self._managed_transfer_fail(
                operation_id,
                "insufficient_space",
                f"PC 共享目录可用空间不足，需要 {required_bytes} 字节，"
                f"可用 {free_bytes} 字节。",
            )
            return
        self._start_managed_transfer_download(operation_id)

    def _start_managed_transfer_download(self, operation_id: str) -> None:
        operation = self._managed_transfer_runs().get(operation_id)
        if not self._managed_transfer_is_active(operation):
            return
        assert operation is not None
        try:
            config = self._ensure_managed_transfer_service()
            host = self._managed_transfer_device_host(operation, config)
            state = self.session_tabs_by_id[str(operation["session_id"])]
            if hasattr(state.session, "configure_managed_transfer"):
                state.session.configure_managed_transfer(
                    username=config.username,
                    password=config.password,
                    source_path=str(operation["source_path"]),
                    source_size=int(operation["source_size"]),
                    destination_path=str(operation["destination_path"]),
                )
            if operation.get("direction") == "download":
                steps, total_timeout = build_managed_transfer_download_steps(
                    protocol=config.protocol,
                    host=host,
                    port=getattr(self.transfer_service, "bound_port", 0)
                    or config.port,
                    source_path=str(operation["source_path"]),
                    destination_path=str(operation["destination_path"]),
                    source_size=int(operation["source_size"]),
                )
            else:
                steps, total_timeout = build_managed_transfer_steps(
                    protocol=config.protocol,
                    host=host,
                    port=getattr(self.transfer_service, "bound_port", 0)
                    or config.port,
                    source_path=str(operation["source_path"]),
                    destination_path=str(operation["destination_path"]),
                    source_size=int(operation["source_size"]),
                )
        except (ManagedTransferError, RuntimeError) as exc:
            code = getattr(exc, "code", "service_start_failed")
            self._managed_transfer_fail(operation_id, code, str(exc))
            return
        direction_word = "上传" if operation.get("direction") == "download" else "下载"
        self._managed_transfer_update(
            operation,
            stage="transferring",
            message=(
                f"正在通过 {config.protocol.upper()} {direction_word} "
                f"{operation['source_path']}。"
            ),
        )
        self._start_managed_transfer_plan(
            operation_id,
            steps,
            total_timeout_seconds=total_timeout,
            on_done=self._finish_managed_transfer_download,
        )

    def _finish_managed_transfer_download(
        self,
        operation_id: str,
        result: dict[str, Any],
    ) -> None:
        operation = self._managed_transfer_runs().get(operation_id)
        if not self._managed_transfer_is_active(operation):
            return
        assert operation is not None
        if result.get("status") != "completed":
            self._managed_transfer_plan_failed(operation_id, result, "transferring")
            return
        if operation.get("direction") == "download":
            self._finish_managed_transfer_download_verify(operation_id)
            return
        if not self._managed_transfer_source_unchanged(operation):
            self._managed_transfer_fail(
                operation_id,
                "transfer_source_changed",
                "传输期间源文件发生变化，结果不可信。",
            )
            return
        self._managed_transfer_update(
            operation,
            stage="verifying",
            message="正在核对设备端文件名和精确字节数。",
        )
        steps = [
            {
                "type": "send",
                "text": f"dir {operation['destination_path']}",
                "label": "读取传输结果",
            },
            {
                "type": "expect",
                "success": ["device_prompt"],
                "failures": ["Unrecognized command", "Unknown command"],
                "timeout_seconds": 30,
                "label": "等待传输结果目录输出",
                "max_output_chars": 32_768,
            },
        ]
        self._start_managed_transfer_plan(
            operation_id,
            steps,
            total_timeout_seconds=45,
            on_done=self._finish_managed_transfer_verification,
        )

    def _finish_managed_transfer_download_verify(self, operation_id: str) -> None:
        operation = self._managed_transfer_runs().get(operation_id)
        if not self._managed_transfer_is_active(operation):
            return
        assert operation is not None
        self._managed_transfer_update(
            operation,
            stage="verifying",
            message="正在核对 PC 共享目录文件名和精确字节数。",
        )
        root = Path(str(operation.get("root") or ""))
        info = self._managed_transfer_shared_entry(
            root,
            str(operation["destination_path"]),
        )
        if info is None or info.size_bytes != int(operation["source_size"]):
            self._managed_transfer_fail(
                operation_id,
                "transfer_verification_failed",
                "PC 共享目录中目标文件不存在，或字节数与设备端源文件不一致。",
            )
            return
        self._managed_transfer_update(
            operation,
            status="completed",
            stage="completed",
            message=(
                f"文件已从 {operation['source_path']} 下载到共享目录 "
                f"{operation['destination_path']}，"
                f"并确认 {info.size_bytes} 字节完全匹配。"
            ),
            error_code="",
        )
        self._release_managed_transfer_lease(operation)

    def _finish_managed_transfer_verification(
        self,
        operation_id: str,
        result: dict[str, Any],
    ) -> None:
        operation = self._managed_transfer_runs().get(operation_id)
        if not self._managed_transfer_is_active(operation):
            return
        assert operation is not None
        if result.get("status") != "completed":
            self._managed_transfer_plan_failed(operation_id, result, "verifying")
            return
        output = self._managed_transfer_plan_output(result)
        if not destination_matches(
            output,
            str(operation["destination_path"]),
            int(operation["source_size"]),
        ):
            self._managed_transfer_fail(
                operation_id,
                "transfer_verification_failed",
                "设备端文件不存在，或字节数与共享目录源文件不一致。",
            )
            return
        self._managed_transfer_update(
            operation,
            status="completed",
            stage="completed",
            message=(
                f"文件已传到 {operation['destination_path']}，"
                f"并确认 {operation['source_size']} 字节完全匹配。"
            ),
            error_code="",
        )
        self._release_managed_transfer_lease(operation)

    def _start_managed_transfer_plan(
        self,
        operation_id: str,
        steps: list[dict[str, Any]],
        *,
        total_timeout_seconds: int,
        on_done: Any,
    ) -> None:
        operation = self._managed_transfer_runs().get(operation_id)
        if not self._managed_transfer_is_active(operation):
            return
        assert operation is not None
        try:
            plan = parse_terminal_plan(
                steps,
                total_timeout_seconds=total_timeout_seconds,
            )
            runner = self.terminal_execution_coordinator.start(
                session_id=str(operation["session_id"]),
                device_id=str(operation["device_id"]),
                plan=plan,
                lease_owner_id=str(operation["lease_owner_id"]),
            )
        except TerminalPlanError as exc:
            self._managed_transfer_fail(operation_id, exc.code, str(exc))
            return
        operation["execution_id"] = runner.execution_id
        runner.add_done_callback(
            lambda completed: self.dispatch_ui(
                on_done,
                operation_id,
                completed.public_dict(),
            )
        )

    def _ensure_managed_transfer_service(self) -> TransferServiceConfig:
        config = self._managed_transfer_config()
        if self.transfer_service is None:
            self.transfer_service = TransferServiceController(
                lambda message: self.dispatch_ui(self.append_transfer_log, message)
            )
        if not self.transfer_service.is_running:
            try:
                self.transfer_service.start(config)
            except RuntimeError as exc:
                raise ManagedTransferError("service_start_failed", str(exc)) from exc
            self.remember_transfer_panel_config(config)
            if hasattr(self, "refresh_transfer_panel_state"):
                self.refresh_transfer_panel_state()
        running_config = getattr(self.transfer_service, "config", None)
        return running_config or config

    def _managed_transfer_device_host(
        self,
        operation: dict[str, Any],
        config: TransferServiceConfig,
    ) -> str:
        host = config.host.strip()
        state = self.session_tabs_by_id.get(str(operation["session_id"]))
        if state is not None and str(getattr(state, "kind", "")) == "simulated":
            return "192.0.2.10" if host in {"", "0.0.0.0", "::"} else host
        if host in {"", "0.0.0.0", "::"}:
            raise ManagedTransferError(
                "service_endpoint_unavailable",
                "请把文件传输服务的监听地址设置为设备可访问的本机 IP。",
            )
        return host

    def _managed_transfer_plan_failed(
        self,
        operation_id: str,
        result: dict[str, Any],
        stage: str,
    ) -> None:
        status = str(result.get("status") or "")
        if status in {"cancelled", "cancelled_by_user"}:
            code = "transfer_cancelled"
        elif status == "timed_out":
            code = "transfer_timeout"
        elif stage == "transferring" and int(result.get("current_step", 0)) <= 1:
            code = "transfer_login_failed"
        else:
            code = "transfer_command_failed"
        message = str(result.get("message") or f"{stage} 阶段执行失败。")
        self._managed_transfer_fail(operation_id, code, message)

    def _managed_transfer_fail(
        self,
        operation_id: str,
        code: str,
        message: str,
    ) -> None:
        operation = self._managed_transfer_runs().get(operation_id)
        if operation is None or operation.get("status") != "running":
            return
        self._managed_transfer_update(
            operation,
            status="failed",
            stage=str(operation.get("stage") or "failed"),
            message=message,
            error_code=code,
        )
        self._release_managed_transfer_lease(operation)

    def _release_managed_transfer_lease(self, operation: dict[str, Any]) -> None:
        if not operation.get("lease_acquired"):
            return
        self.terminal_execution_coordinator.release_external_lease(
            str(operation.get("session_id") or ""),
            str(operation.get("lease_owner_id") or ""),
        )
        operation["lease_acquired"] = False

    @staticmethod
    def _managed_transfer_is_active(
        operation: dict[str, Any] | None,
    ) -> bool:
        return bool(operation and operation.get("status") == "running")

    @staticmethod
    def _managed_transfer_update(
        operation: dict[str, Any],
        **changes: Any,
    ) -> None:
        operation.update(changes)
        operation["updated_monotonic"] = time.monotonic()

    @staticmethod
    def _managed_transfer_plan_output(result: dict[str, Any]) -> str:
        return "".join(
            str(step.get("output") or "")
            for step in result.get("steps", [])
            if isinstance(step, dict)
        )

    @staticmethod
    def _managed_transfer_device_path(operation: dict[str, Any]) -> str:
        # For downloads the device-side path queried via `dir` is the SOURCE;
        # for uploads it is the destination.
        if operation.get("direction") == "download":
            return str(operation["source_path"])
        return str(operation["destination_path"])

    @staticmethod
    def _managed_transfer_shared_entry(
        root: Path,
        relative_path: str,
    ) -> Any | None:
        try:
            _resolved, info = resolve_shared_file(root, relative_path)
            return info
        except ManagedTransferError:
            return None

    @staticmethod
    def _managed_transfer_source_unchanged(operation: dict[str, Any]) -> bool:
        if operation.get("direction") == "download":
            # The source is the device-side file: its size is captured during
            # precheck and re-verified against the transferred PC file, so skip
            # the PC-source drift check used by the upload path.
            return True
        try:
            return source_fingerprint(Path(operation["source_absolute"])) == tuple(
                operation["source_fingerprint"]
            )
        except (ManagedTransferError, KeyError, TypeError):
            return False

    @staticmethod
    def _schedule_managed_transfer(delay_ms: int, callback: Any) -> None:
        if QTimer is None:
            callback()
            return
        QTimer.singleShot(max(0, delay_ms), callback)
