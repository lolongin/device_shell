"""Managed file-transfer service backed by terminal plans and local FTP/SFTP."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, replace
from functools import partial
import json
from pathlib import Path
import secrets as random_secrets
import shutil
from threading import Lock
from typing import Callable, Protocol

from ..file_transfer_service import TransferServiceConfig, TransferServiceController
from ..managed_file_transfer import (
    ManagedTransferError,
    SharedFileCatalog,
    _validate_relative_path,
    build_managed_transfer_download_steps,
    build_managed_transfer_steps,
    destination_entry,
    destination_matches,
    list_shared_files,
    resolve_shared_file,
    resolve_shared_root,
    source_fingerprint,
    validate_destination_path,
)
from ..package_upgrade import parse_free_space_bytes
from ..terminal_orchestration import TerminalExecutionPlan, TerminalPlanError, parse_terminal_plan
from .errors import (
    ApplicationConflictError,
    ResourceNotFoundError,
    TransferOperationError,
    UnsupportedOperationError,
)
from .events import EventBus
from .operations import OperationManager, OperationRecord, TERMINAL_OPERATION_STATUSES
from .secrets import SecretStore
from .sessions import SessionRecord, SessionService


@dataclass(frozen=True, slots=True)
class TransferSettings:
    protocol: str
    host: str
    port: int
    root: str
    username: str
    writable: bool
    has_password: bool
    service_running: bool
    bound_port: int


@dataclass(frozen=True, slots=True)
class PreparedTransferSource:
    path: Path
    relative_path: str
    name: str
    size_bytes: int
    fingerprint: tuple[int, int]
    protocol: str = ""
    host: str = ""
    port: int = 0


class TransferStore(Protocol):
    def get_meta(self, key: str) -> str | None: ...

    def set_meta(self, key: str, value: str) -> None: ...


class MemoryTransferStore:
    def __init__(self) -> None:
        self._meta: dict[str, str] = {}

    def get_meta(self, key: str) -> str | None:
        return self._meta.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self._meta[key] = value


class TerminalPlanExecutor(Protocol):
    def acquire(
        self,
        session_id: str,
        owner_id: str,
        *,
        on_cancel: Callable[[], None],
    ) -> None: ...

    def release(self, session_id: str, owner_id: str) -> None: ...

    async def run(
        self,
        *,
        session_id: str,
        device_id: str,
        plan: TerminalExecutionPlan,
        owner_id: str,
    ) -> dict[str, object]: ...

    def cancel_active(self, session_id: str) -> str: ...

    def configure_managed_transfer(
        self,
        session_id: str,
        *,
        username: str,
        password: str,
        source_path: str,
        source_size: int,
        destination_path: str,
    ) -> None: ...


class UnavailableTerminalPlanExecutor:
    def acquire(self, *_args: object, **_kwargs: object) -> None:
        raise UnsupportedOperationError("Terminal operations are unavailable.")

    def release(self, *_args: object, **_kwargs: object) -> None:
        return

    async def run(self, **_kwargs: object) -> dict[str, object]:
        raise UnsupportedOperationError("Terminal operations are unavailable.")

    def cancel_active(self, _session_id: str) -> str:
        return ""

    def configure_managed_transfer(self, *_args: object, **_kwargs: object) -> None:
        return


class ManagedTransferService:
    CONFIG_KEY = "file_transfer_config_v1"
    LEGACY_IMPORT_KEY = "legacy_file_transfer_v1"
    PASSWORD_SECRET_ID = "file-transfer:service-password"

    def __init__(
        self,
        store: TransferStore,
        secrets: SecretStore,
        sessions: SessionService,
        operations: OperationManager,
        events: EventBus,
        *,
        terminal_executor: TerminalPlanExecutor | None = None,
        default_root: Path | None = None,
    ) -> None:
        self._store = store
        self._secrets = secrets
        self._sessions = sessions
        self._operations = operations
        self._events = events
        self._executor = terminal_executor or UnavailableTerminalPlanExecutor()
        self._default_root = (default_root or Path.cwd()).resolve()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._service_log: deque[str] = deque(maxlen=300)
        self._service_log_lock = Lock()
        self._controller = TransferServiceController(self._on_service_log)

    def settings(self) -> TransferSettings:
        config = self._saved_config()
        return TransferSettings(
            protocol=config["protocol"],
            host=config["host"],
            port=int(config["port"]),
            root=config["root"],
            username=config["username"],
            writable=bool(config["writable"]),
            has_password=self._secrets.get(self.PASSWORD_SECRET_ID) is not None,
            service_running=self._controller.is_running,
            bound_port=self._controller.bound_port,
        )

    def update_settings(
        self,
        *,
        protocol: str,
        host: str,
        port: int,
        root: str,
        username: str,
        writable: bool,
    ) -> TransferSettings:
        if self._controller.is_running:
            raise ApplicationConflictError(
                "Stop the file-transfer service before changing its settings."
            )
        normalized_protocol = protocol.strip().casefold()
        if normalized_protocol not in {"ftp", "sftp"}:
            raise UnsupportedOperationError(f"Unsupported transfer protocol: {protocol}")
        if not 0 <= int(port) <= 65535:
            raise UnsupportedOperationError("The transfer port must be between 0 and 65535.")
        normalized_username = username.strip()
        if not normalized_username:
            raise UnsupportedOperationError("A transfer-service username is required.")
        resolved_root = resolve_shared_root(Path(root))
        payload = {
            "protocol": normalized_protocol,
            "host": host.strip() or "0.0.0.0",
            "port": int(port),
            "root": str(resolved_root),
            "username": normalized_username,
            "writable": bool(writable),
        }
        self._store.set_meta(self.CONFIG_KEY, json.dumps(payload, ensure_ascii=False))
        return self.settings()

    def set_password(self, value: str) -> TransferSettings:
        if not value:
            self._secrets.delete(self.PASSWORD_SECRET_ID)
        else:
            self._secrets.set(self.PASSWORD_SECRET_ID, value)
        return self.settings()

    def resolve_secret(self, secret_ref: str) -> str:
        if secret_ref == "file_transfer.username":
            return str(self._saved_config()["username"])
        if secret_ref == "file_transfer.password":
            return self._secrets.get(self.PASSWORD_SECRET_ID) or ""
        return self._secrets.get(secret_ref) or ""

    async def start_service(self) -> TransferSettings:
        if self._controller.is_running:
            return self.settings()
        self._event_loop = asyncio.get_running_loop()
        config = self._runtime_config(ensure_password=True)
        try:
            await asyncio.to_thread(self._controller.start, config)
        except RuntimeError as exc:
            raise TransferOperationError(str(exc)) from exc
        self._events.publish(
            "transfer.service.started",
            data={
                "protocol": self._controller.protocol,
                "bound_port": self._controller.bound_port,
            },
        )
        return self.settings()

    async def stop_service(self) -> TransferSettings:
        if self._controller.is_running:
            await asyncio.to_thread(self._controller.stop)
            self._events.publish("transfer.service.stopped")
        return self.settings()

    def service_log(self, limit: int = 300) -> list[str]:
        safe_limit = max(0, min(300, int(limit)))
        with self._service_log_lock:
            return list(self._service_log)[-safe_limit:] if safe_limit else []

    def clear_service_log(self) -> None:
        with self._service_log_lock:
            self._service_log.clear()

    def client_command_hint(self) -> str:
        settings = self.settings()
        host = settings.host.strip()
        target = host if host not in {"", "0.0.0.0", "::"} else "<本机IP>"
        port = settings.bound_port or settings.port
        if settings.protocol == "sftp":
            return f"sftp -P {port} {settings.username}@{target}"
        return f"ftp {target} {port}"

    def list_files(
        self,
        *,
        relative_path: str = "",
        recursive: bool = True,
        limit: int = 200,
    ) -> SharedFileCatalog:
        try:
            return list_shared_files(
                Path(str(self._saved_config()["root"])),
                relative_path=relative_path,
                recursive=recursive,
                limit=limit,
            )
        except ManagedTransferError as exc:
            raise self._application_error(exc) from exc

    def resolve_source(self, relative_path: str) -> PreparedTransferSource:
        try:
            path, info = resolve_shared_file(
                Path(str(self._saved_config()["root"])),
                relative_path,
            )
            fingerprint = source_fingerprint(path)
        except ManagedTransferError as exc:
            raise self._application_error(exc) from exc
        return PreparedTransferSource(
            path=path,
            relative_path=info.relative_path,
            name=info.name,
            size_bytes=info.size_bytes,
            fingerprint=fingerprint,
        )

    async def prepare_upload_source(
        self,
        session: SessionRecord,
        *,
        source_path: str,
        destination_path: str,
    ) -> PreparedTransferSource:
        source = self.resolve_source(source_path)
        config = await self._ensure_service()
        host = self._device_host(session, config)
        self._executor.configure_managed_transfer(
            session.id,
            username=config.username,
            password=config.password,
            source_path=source.relative_path,
            source_size=source.size_bytes,
            destination_path=destination_path,
        )
        return replace(
            source,
            protocol=config.protocol,
            host=host,
            port=self._controller.bound_port or config.port,
        )

    def start_upload(
        self,
        *,
        session_id: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> OperationRecord:
        session = self._connected_session(session_id)
        try:
            source, info = resolve_shared_file(
                Path(str(self._saved_config()["root"])),
                source_path,
            )
            destination = validate_destination_path(destination_path)
            fingerprint = source_fingerprint(source)
        except ManagedTransferError as exc:
            raise self._application_error(exc) from exc
        record = self._operations.create(
            kind="managed_file_transfer",
            direction="upload",
            device_id=session.device_id,
            session_id=session.id,
            stage="queued",
            message="文件传输已排队。",
            data={
                "source_path": info.relative_path,
                "source_name": info.name,
                "source_size": info.size_bytes,
                "destination_path": destination,
                "overwrite": bool(overwrite),
            },
        )
        task = asyncio.create_task(
            self._run_upload(
                record.id,
                session,
                source,
                fingerprint,
            ),
            name=f"managed-transfer-{record.id}",
        )
        self._attach_task(record.id, session.id, task)
        return self._operations.get(record.id)

    def start_download(
        self,
        *,
        session_id: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> OperationRecord:
        session = self._connected_session(session_id)
        try:
            source = validate_destination_path(source_path)
            destination = _validate_relative_path(
                destination_path,
                label="destination_path",
            ).as_posix()
        except ManagedTransferError as exc:
            raise self._application_error(exc) from exc
        record = self._operations.create(
            kind="managed_file_transfer",
            direction="download",
            device_id=session.device_id,
            session_id=session.id,
            stage="queued",
            message="文件传输已排队。",
            data={
                "source_path": source,
                "source_name": Path(source).name,
                "source_size": 0,
                "destination_path": destination,
                "overwrite": bool(overwrite),
            },
        )
        task = asyncio.create_task(
            self._run_download(record.id, session),
            name=f"managed-transfer-{record.id}",
        )
        self._attach_task(record.id, session.id, task)
        return self._operations.get(record.id)

    def cancel(self, operation_id: str) -> OperationRecord:
        return self._operations.cancel(operation_id)

    def cancel_session(self, session_id: str) -> int:
        cancelled = 0
        for operation_id in tuple(self._tasks):
            record = self._operations.get(operation_id)
            if record.session_id != session_id or record.status in TERMINAL_OPERATION_STATUSES:
                continue
            self.cancel(operation_id)
            cancelled += 1
        return cancelled

    def import_legacy_state(self, state_path: Path) -> dict[str, int]:
        if self._store.get_meta(self.LEGACY_IMPORT_KEY) is not None or not state_path.exists():
            return {"settings": 0, "secrets": 0}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"settings": 0, "secrets": 0}
        raw = payload.get("file_transfer_service", {}) if isinstance(payload, dict) else {}
        imported = 0
        protected = 0
        if isinstance(raw, dict) and raw:
            config = self._saved_config()
            protocol = str(raw.get("protocol") or config["protocol"]).casefold()
            if protocol not in {"ftp", "sftp"}:
                protocol = "ftp"
            try:
                port = max(0, min(65535, int(raw.get("port", config["port"]))))
            except (TypeError, ValueError):
                port = int(config["port"])
            imported_payload = {
                "protocol": protocol,
                "host": str(raw.get("host") or config["host"]),
                "port": port,
                "root": str(raw.get("root") or config["root"]),
                "username": str(raw.get("username") or config["username"]),
                "writable": bool(raw.get("writable", config["writable"])),
            }
            self._store.set_meta(
                self.CONFIG_KEY,
                json.dumps(imported_payload, ensure_ascii=False),
            )
            imported = 1
            password = str(raw.get("password") or "")
            if password:
                self._secrets.set(self.PASSWORD_SECRET_ID, password)
                protected = 1
        result = {"settings": imported, "secrets": protected}
        self._store.set_meta(self.LEGACY_IMPORT_KEY, json.dumps(result))
        return result

    async def close(self) -> None:
        for operation_id in list(self._tasks):
            try:
                self.cancel(operation_id)
            except (ResourceNotFoundError, UnsupportedOperationError):
                continue
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        await self.stop_service()

    async def _run_upload(
        self,
        operation_id: str,
        session: SessionRecord,
        source: Path,
        initial_fingerprint: tuple[int, int],
    ) -> None:
        owner_id = f"managed-transfer:{operation_id}"
        acquired = False
        try:
            self._executor.acquire(
                session.id,
                owner_id,
                on_cancel=lambda: self._cancel_task(operation_id, session.id),
            )
            acquired = True
            operation = self._operations.update(
                operation_id,
                stage="prechecking",
                message="正在检查设备目标路径和可用空间。",
                progress_percent=10,
            )
            destination = str(operation.data["destination_path"])
            precheck = await self._run_plan(
                session,
                owner_id,
                self._directory_plan(destination),
            )
            output = self._require_completed(precheck, "prechecking")
            existing = destination_entry(output, destination)
            if existing is not None and not bool(operation.data["overwrite"]):
                raise _TransferRunError(
                    "destination_exists",
                    f"设备目标文件已存在，大小为 {existing.size_bytes} 字节。",
                )
            source_size = int(operation.data["source_size"])
            required = max(0, source_size - (existing.size_bytes if existing else 0))
            free_bytes = parse_free_space_bytes(output)
            if free_bytes < required:
                raise _TransferRunError(
                    "insufficient_space",
                    f"设备可用空间不足，需要 {required} 字节，可用 {free_bytes} 字节。",
                )
            if source_fingerprint(source) != initial_fingerprint:
                raise _TransferRunError("transfer_source_changed", "传输前源文件发生变化。")
            config = await self._ensure_service()
            host = self._device_host(session, config)
            self._executor.configure_managed_transfer(
                session.id,
                username=config.username,
                password=config.password,
                source_path=str(operation.data["source_path"]),
                source_size=source_size,
                destination_path=destination,
            )
            steps, timeout = build_managed_transfer_steps(
                protocol=config.protocol,
                host=host,
                port=self._controller.bound_port or config.port,
                source_path=str(operation.data["source_path"]),
                destination_path=destination,
                source_size=source_size,
            )
            self._operations.update(
                operation_id,
                stage="transferring",
                message=f"正在通过 {config.protocol.upper()} 传输文件。",
                progress_percent=45,
            )
            transferred = await self._run_plan(
                session,
                owner_id,
                parse_terminal_plan(steps, total_timeout_seconds=timeout),
            )
            self._require_completed(transferred, "transferring")
            if source_fingerprint(source) != initial_fingerprint:
                raise _TransferRunError("transfer_source_changed", "传输期间源文件发生变化。")
            self._operations.update(
                operation_id,
                stage="verifying",
                message="正在核对设备端文件名和精确字节数。",
                progress_percent=90,
            )
            verified = await self._run_plan(
                session,
                owner_id,
                self._directory_plan(destination),
            )
            verify_output = self._require_completed(verified, "verifying")
            if not destination_matches(verify_output, destination, source_size):
                raise _TransferRunError(
                    "transfer_verification_failed",
                    "设备端文件不存在，或字节数与源文件不一致。",
                )
            self._operations.update(
                operation_id,
                status="completed",
                stage="completed",
                message=f"文件已传到 {destination}，并确认 {source_size} 字节完全匹配。",
                progress_percent=100,
                error_code="",
            )
        except asyncio.CancelledError:
            self._mark_cancelled(operation_id)
        except (ManagedTransferError, TerminalPlanError, TransferOperationError, _TransferRunError) as exc:
            self._mark_failed(operation_id, getattr(exc, "code", "transfer_failed"), str(exc))
        finally:
            if acquired:
                self._executor.release(session.id, owner_id)
            self._tasks.pop(operation_id, None)

    async def _run_download(self, operation_id: str, session: SessionRecord) -> None:
        owner_id = f"managed-transfer:{operation_id}"
        acquired = False
        try:
            self._executor.acquire(
                session.id,
                owner_id,
                on_cancel=lambda: self._cancel_task(operation_id, session.id),
            )
            acquired = True
            operation = self._operations.update(
                operation_id,
                stage="prechecking",
                message="正在检查设备源文件和 PC 目标空间。",
                progress_percent=10,
            )
            source_path = str(operation.data["source_path"])
            precheck = await self._run_plan(
                session,
                owner_id,
                self._directory_plan(source_path),
            )
            output = self._require_completed(precheck, "prechecking")
            entry = destination_entry(output, source_path)
            if entry is None:
                raise _TransferRunError("transfer_source_not_found", "设备端源文件不存在。")
            root = Path(str(self._saved_config()["root"]))
            relative = str(operation.data["destination_path"])
            destination = root.joinpath(*_validate_relative_path(relative, label="destination_path").parts)
            existing_size = destination.stat().st_size if destination.is_file() else 0
            if destination.exists() and not bool(operation.data["overwrite"]):
                raise _TransferRunError("destination_exists", "PC 目标文件已存在。")
            required = max(0, entry.size_bytes - existing_size)
            if shutil.disk_usage(root).free < required:
                raise _TransferRunError("insufficient_space", "PC 共享目录可用空间不足。")
            operation = self._operations.update(
                operation_id,
                data={"source_size": entry.size_bytes},
            )
            config = await self._ensure_service()
            if not config.writable:
                raise _TransferRunError(
                    "transfer_service_read_only",
                    "设备下载到 PC 时文件服务必须允许写入。",
                )
            host = self._device_host(session, config)
            self._executor.configure_managed_transfer(
                session.id,
                username=config.username,
                password=config.password,
                source_path=source_path,
                source_size=entry.size_bytes,
                destination_path=relative,
            )
            steps, timeout = build_managed_transfer_download_steps(
                protocol=config.protocol,
                host=host,
                port=self._controller.bound_port or config.port,
                source_path=source_path,
                destination_path=relative,
                source_size=entry.size_bytes,
            )
            self._operations.update(
                operation_id,
                stage="transferring",
                message=f"正在通过 {config.protocol.upper()} 下载文件。",
                progress_percent=45,
            )
            result = await self._run_plan(
                session,
                owner_id,
                parse_terminal_plan(steps, total_timeout_seconds=timeout),
            )
            self._require_completed(result, "transferring")
            if not destination.is_file() or destination.stat().st_size != entry.size_bytes:
                raise _TransferRunError(
                    "transfer_verification_failed",
                    "PC 目标文件不存在，或字节数与设备源文件不一致。",
                )
            self._operations.update(
                operation_id,
                status="completed",
                stage="completed",
                message=f"文件已下载到 {relative}，并确认 {entry.size_bytes} 字节完全匹配。",
                progress_percent=100,
                error_code="",
            )
        except asyncio.CancelledError:
            self._mark_cancelled(operation_id)
        except (ManagedTransferError, TerminalPlanError, TransferOperationError, _TransferRunError, OSError) as exc:
            self._mark_failed(operation_id, getattr(exc, "code", "transfer_failed"), str(exc))
        finally:
            if acquired:
                self._executor.release(session.id, owner_id)
            self._tasks.pop(operation_id, None)

    async def _ensure_service(self) -> TransferServiceConfig:
        await self.start_service()
        config = self._controller.config
        if config is None:
            raise TransferOperationError("The file-transfer service did not start.")
        return config

    async def _run_plan(
        self,
        session: SessionRecord,
        owner_id: str,
        plan: TerminalExecutionPlan,
    ) -> dict[str, object]:
        return await self._executor.run(
            session_id=session.id,
            device_id=session.device_id,
            plan=plan,
            owner_id=owner_id,
        )

    @staticmethod
    def _directory_plan(path: str) -> TerminalExecutionPlan:
        return parse_terminal_plan(
            [
                {"type": "send", "text": f"dir {path}", "label": "读取目录"},
                {
                    "type": "expect",
                    "success": ["device_prompt"],
                    "failures": ["Unrecognized command", "Unknown command"],
                    "timeout_seconds": 30,
                    "label": "等待目录输出",
                    "max_output_chars": 32_768,
                },
            ],
            total_timeout_seconds=45,
        )

    @staticmethod
    def _require_completed(result: dict[str, object], stage: str) -> str:
        status = str(result.get("status") or "")
        if status != "completed":
            if status in {"cancelled", "cancelled_by_user"}:
                raise _TransferRunError("transfer_cancelled", "文件传输已取消。")
            if status == "timed_out":
                raise _TransferRunError("transfer_timeout", f"{stage} 阶段超时。")
            raise _TransferRunError(
                "transfer_command_failed",
                str(result.get("message") or f"{stage} 阶段失败。"),
            )
        return "".join(
            str(step.get("output") or "")
            for step in result.get("steps", [])
            if isinstance(step, dict)
        )

    def _attach_task(
        self,
        operation_id: str,
        session_id: str,
        task: asyncio.Task[None],
    ) -> None:
        self._tasks[operation_id] = task
        self._operations.register_canceller(
            operation_id,
            lambda: self._cancel_task(operation_id, session_id),
        )

    def _cancel_task(self, operation_id: str, session_id: str) -> None:
        self._executor.cancel_active(session_id)
        self._executor.release(session_id, f"managed-transfer:{operation_id}")
        task = self._tasks.get(operation_id)
        if task is not None and not task.done():
            task.cancel()
        self._mark_cancelled(operation_id)

    def _mark_cancelled(self, operation_id: str) -> None:
        record = self._operations.get(operation_id)
        if record.status in TERMINAL_OPERATION_STATUSES:
            return
        self._operations.update(
            operation_id,
            status="cancelled",
            stage="cancelled",
            message="文件传输已取消。",
            error_code="transfer_cancelled",
        )

    def _mark_failed(self, operation_id: str, code: str, message: str) -> None:
        record = self._operations.get(operation_id)
        if record.status in TERMINAL_OPERATION_STATUSES:
            return
        if code == "transfer_cancelled":
            self._mark_cancelled(operation_id)
            return
        self._operations.update(
            operation_id,
            status="failed",
            stage=record.stage,
            message=message,
            error_code=code,
        )

    def _connected_session(self, session_id: str) -> SessionRecord:
        session = next(
            (item for item in self._sessions.list_sessions() if item.id == session_id),
            None,
        )
        if session is None:
            raise ResourceNotFoundError(
                f"Unknown session: {session_id}",
                details={"resource": "session", "session_id": session_id},
            )
        if session.status != "connected":
            raise ApplicationConflictError("The terminal session is not connected.")
        return session

    def _runtime_config(self, *, ensure_password: bool) -> TransferServiceConfig:
        config = self._saved_config()
        password = self._secrets.get(self.PASSWORD_SECRET_ID) or ""
        if ensure_password and not password:
            password = random_secrets.token_urlsafe(24)
            self._secrets.set(self.PASSWORD_SECRET_ID, password)
        return TransferServiceConfig(
            protocol=str(config["protocol"]),
            host=str(config["host"]),
            port=int(config["port"]),
            root=Path(str(config["root"])),
            username=str(config["username"]),
            password=password,
            writable=bool(config["writable"]),
        )

    def _saved_config(self) -> dict[str, object]:
        defaults: dict[str, object] = {
            "protocol": "ftp",
            "host": "0.0.0.0",
            "port": 0,
            "root": str(self._default_root),
            "username": "device",
            "writable": True,
        }
        raw = self._store.get_meta(self.CONFIG_KEY)
        if not raw:
            return defaults
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return defaults
        if not isinstance(payload, dict):
            return defaults
        return {**defaults, **payload}

    @staticmethod
    def _device_host(session: SessionRecord, config: TransferServiceConfig) -> str:
        host = config.host.strip()
        if session.kind == "simulated" and host in {"", "0.0.0.0", "::"}:
            return "192.0.2.10"
        if host in {"", "0.0.0.0", "::"}:
            raise _TransferRunError(
                "service_endpoint_unavailable",
                "请把文件传输监听地址设置为设备可访问的本机 IP。",
            )
        return host

    @staticmethod
    def _application_error(exc: ManagedTransferError) -> TransferOperationError:
        return TransferOperationError(str(exc), details={"transfer_code": exc.code})

    def _on_service_log(self, message: str) -> None:
        safe_message = str(message).replace("\x00", "").strip()
        if not safe_message:
            return
        with self._service_log_lock:
            self._service_log.append(safe_message)
        publish = partial(
            self._events.publish,
            "transfer.service.log",
            data={"message": safe_message},
        )
        loop = self._event_loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(publish)
            return
        publish()


class _TransferRunError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
