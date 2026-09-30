"""Managed file-transfer service backed by terminal plans and local FTP/SFTP."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, replace
from functools import partial
import json
from pathlib import Path
import shutil
import socket  # compatibility export: callers/tests historically patch transfers.socket
from threading import Lock

from device_tui.infrastructure.transfers.file_transfer_service import (
    TransferServiceConfig,
    TransferServiceController,
)
# Import the vendor package before managed_file_transfer. Its package exports
# currently load command profiles that refer back to the transfer model.
from device_tui.infrastructure.vendor_adapters.huawei_vrp import parsers as _huawei_vrp_parsers  # noqa: F401
from device_tui.infrastructure.transfers.managed_file_transfer import (
    ManagedTransferError,
    SharedFileCatalog,
    _validate_relative_path,
    infer_terminal_environment,
    list_shared_files,
    normalize_terminal_environment,
    resolve_shared_file,
    resolve_shared_root,
    stage_workflow_source,
    source_fingerprint,
    validate_transfer_device_path,
)
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
from .transfer_models import TransferSettings
from .transfer_ports import (
    MemoryTransferStore,
    PreparedTransferSource,
    TransferStore,
    UnavailableTerminalPlanExecutor,
)
from .transfer_lifecycle import TransferServiceLifecycleMixin
from .transfer_queue import TransferQueueMixin
from .transfer_helpers import normalize_command_mode as _normalize_command_mode
from .transfer_network import normalize_advertised_host, select_route_local_ipv4
from .transfer_execution import TransferExecutionRunner
from .transfer_ports import TerminalPlanExecutor


class ManagedTransferService(TransferQueueMixin, TransferServiceLifecycleMixin):
    CONFIG_KEY = "file_transfer_config_v1"
    LEGACY_IMPORT_KEY = "legacy_file_transfer_v1"
    PASSWORD_SECRET_ID = "file-transfer:service-password"
    IDLE_STOP_SECONDS = 300
    _normalize_command_mode = staticmethod(_normalize_command_mode)

    @staticmethod
    def _inspection_plan(path: str, terminal_environment: str, protocol: str):
        from .transfer_planning import inspection_plan

        return inspection_plan(path, terminal_environment, protocol)

    @staticmethod
    def _require_linux_inspection(output: str, protocol: str) -> None:
        from .transfer_planning import require_linux_inspection

        require_linux_inspection(output, protocol)

    @staticmethod
    def _route_local_ipv4(host: str, port: int) -> str:
        return select_route_local_ipv4(host, port)

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
        self._queues: dict[str, deque[str]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._paused_sessions: set[str] = set()
        self._cancelling: set[str] = set()
        self._progress_samples: dict[str, deque[tuple[float, int]]] = {}
        self._last_progress_emit: dict[str, float] = {}
        self._runtime_secrets: dict[str, str] = {}
        self._idle_stop_task: asyncio.Task[None] | None = None
        self._idle_stop_at = ""
        self._service_lifecycle_lock = asyncio.Lock()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._service_log: deque[str] = deque(maxlen=300)
        self._service_log_lock = Lock()
        self._controller = TransferServiceController(self._on_service_log)
        self._transfer_runner = TransferExecutionRunner(self, self._controller)

    def list_files(
        self,
        *,
        relative_path: str = "",
        recursive: bool = True,
        limit: int = 200,
        query: str = "",
        sort: str = "name",
        order: str = "asc",
        offset: int = 0,
    ) -> SharedFileCatalog:
        try:
            return list_shared_files(
                Path(str(self._saved_config()["root"])),
                relative_path=relative_path,
                recursive=recursive,
                limit=limit,
                query=query,
                sort=sort,
                order=order,
                offset=offset,
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

    def prepare_workflow_source(self, source_path: str, *, staging_id: str) -> str:
        """Prepare a Workflow upload source as a shared-root-relative path."""
        try:
            return stage_workflow_source(
                Path(str(self._saved_config()["root"])),
                source_path,
                staging_id=staging_id,
            )
        except ManagedTransferError as exc:
            raise self._application_error(exc) from exc

    def cleanup_workflow_source(self, staging_id: str) -> None:
        """Remove a workflow's private staging directory after its task ends."""
        safe_staging_id = str(staging_id or "").strip()
        if not safe_staging_id or "/" in safe_staging_id or "\\" in safe_staging_id or safe_staging_id in {".", ".."}:
            return
        root = resolve_shared_root(Path(str(self._saved_config()["root"])))
        staging_dir = (root / ".workflow-staging" / safe_staging_id).resolve()
        if not staging_dir.is_relative_to(root / ".workflow-staging"):
            return
        shutil.rmtree(staging_dir, ignore_errors=True)

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
        terminal_environment: str = "auto",
        command_mode: str = "vrp",
        interaction_profile: dict[str, str] | None = None,
        retry_of: str | None = None,
    ) -> OperationRecord:
        session = self._connected_session(session_id)
        try:
            source, info = resolve_shared_file(
                Path(str(self._saved_config()["root"])),
                source_path,
            )
            normalized_command_mode = self._normalize_command_mode(command_mode)
            requested_environment = normalize_terminal_environment(terminal_environment)
            if normalized_command_mode == "ftpget":
                destination = info.relative_path
                resolved_environment = "linux"
            else:
                destination = validate_transfer_device_path(
                    destination_path,
                    requested_environment,
                )
                resolved_environment = (
                    infer_terminal_environment(destination, session_kind=session.kind)
                    if requested_environment == "auto"
                    else requested_environment
                )
                destination = validate_transfer_device_path(destination, resolved_environment)
            fingerprint = source_fingerprint(source)
        except ManagedTransferError as exc:
            raise self._application_error(exc) from exc
        record = self._operations.create(
            kind="managed_file_transfer",
            direction="upload",
            device_id=session.device_id,
            session_id=session.id,
            status="queued",
            stage="queued",
            message="文件传输已加入队列。",
            total_bytes=info.size_bytes,
            retry_of=retry_of,
            data={
                "source_path": info.relative_path,
                "source_name": info.name,
                "source_size": info.size_bytes,
                "destination_path": destination,
                "overwrite": bool(overwrite),
                "terminal_environment_requested": requested_environment,
                "terminal_environment": resolved_environment,
                "command_mode": normalized_command_mode,
                "interaction_profile": dict(interaction_profile or {}),
            },
        )
        del source, fingerprint
        self._enqueue(record)
        return self._operations.get(record.id)

    def start_download(
        self,
        *,
        session_id: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
        terminal_environment: str = "auto",
        command_mode: str = "vrp",
        interaction_profile: dict[str, str] | None = None,
        retry_of: str | None = None,
    ) -> OperationRecord:
        session = self._connected_session(session_id)
        try:
            normalized_command_mode = self._normalize_command_mode(command_mode)
            if normalized_command_mode == "ftpget":
                raise ManagedTransferError(
                    "ftpget_direction_unsupported",
                    "ftpget 单命令当前只支持 PC 到设备；设备到 PC 请使用 VRP 交互模式。",
                )
            requested_environment = normalize_terminal_environment(terminal_environment)
            source = validate_transfer_device_path(source_path, requested_environment)
            resolved_environment = (
                infer_terminal_environment(source, session_kind=session.kind)
                if requested_environment == "auto"
                else requested_environment
            )
            source = validate_transfer_device_path(source, resolved_environment)
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
            status="queued",
            stage="queued",
            message="文件传输已加入队列。",
            retry_of=retry_of,
            data={
                "source_path": source,
                "source_name": Path(source).name,
                "source_size": 0,
                "destination_path": destination,
                "overwrite": bool(overwrite),
                "terminal_environment_requested": requested_environment,
                "terminal_environment": resolved_environment,
                "command_mode": normalized_command_mode,
                "interaction_profile": dict(interaction_profile or {}),
            },
        )
        self._enqueue(record)
        return self._operations.get(record.id)

    def cancel(self, operation_id: str) -> OperationRecord:
        return self._operations.cancel(operation_id)

    def retry(self, operation_id: str) -> OperationRecord:
        original = self._operations.get(operation_id)
        if original.kind != "managed_file_transfer" or original.status not in {
            "failed",
            "cancelled",
            "interrupted",
        }:
            raise ApplicationConflictError("当前传输状态不允许重试。")
        payload = original.data
        starter = self.start_download if original.direction == "download" else self.start_upload
        return starter(
            session_id=original.session_id,
            source_path=str(payload.get("source_path") or ""),
            destination_path=str(payload.get("destination_path") or ""),
            overwrite=bool(payload.get("overwrite")),
            terminal_environment=str(
                payload.get("terminal_environment_requested")
                or payload.get("terminal_environment")
                or "auto"
            ),
            command_mode=str(payload.get("command_mode") or "vrp"),
            interaction_profile=dict(payload.get("interaction_profile") or {}),
            retry_of=original.id,
        )

    def resume_queue(self, session_id: str) -> int:
        self._connected_session(session_id)
        self._paused_sessions.discard(session_id)
        queue = self._queues.get(session_id, deque())
        resumed = 0
        for operation_id in queue:
            record = self._operations.get(operation_id)
            if record.status != "queued":
                continue
            self._operations.update(
                operation_id,
                stage="queued",
                message="文件传输等待执行。",
            )
            resumed += 1
        self._refresh_queue_positions(session_id)
        self._ensure_worker(session_id)
        return resumed

    def clear_history(self) -> int:
        return self._operations.delete_terminal(kind="managed_file_transfer")

    def cancel_session(self, session_id: str) -> int:
        cancelled = 0
        operation_ids = set(self._tasks)
        operation_ids.update(self._queues.get(session_id, ()))
        for operation_id in tuple(operation_ids):
            record = self._operations.get(operation_id)
            if record.session_id != session_id or record.status in TERMINAL_OPERATION_STATUSES:
                continue
            self.cancel(operation_id)
            cancelled += 1
        self._paused_sessions.discard(session_id)
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
        self._cancel_idle_stop()
        session_ids = set(self._queues)
        session_ids.update(
            self._operations.get(operation_id).session_id for operation_id in self._tasks
        )
        for session_id in session_ids:
            self.cancel_session(session_id)
        for operation_id in list(self._tasks):
            try:
                self.cancel(operation_id)
            except (ResourceNotFoundError, UnsupportedOperationError):
                continue
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        if self._workers:
            await asyncio.gather(*self._workers.values(), return_exceptions=True)
        await self.stop_service()

    async def _run_upload(self, operation_id: str, session: SessionRecord) -> None:
        await self._transfer_runner.upload(operation_id, session)

    async def _run_ftpget_upload(
        self,
        operation_id: str,
        session: SessionRecord,
    ) -> None:
        await self._transfer_runner.ftpget_upload(operation_id, session)

    async def _run_download(self, operation_id: str, session: SessionRecord) -> None:
        await self._transfer_runner.download(operation_id, session)

    async def _ensure_service(self) -> TransferServiceConfig:
        self._cancel_idle_stop()
        await self.start_service(auto_stop_when_idle=False)
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
