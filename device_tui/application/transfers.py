"""Managed file-transfer service backed by terminal plans and local FTP/SFTP."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta, timezone
from functools import partial
import ipaddress
import json
from pathlib import Path
import secrets as random_secrets
import shutil
import socket
from threading import Lock
import time
from typing import Callable, Protocol

from device_tui.application.terminal.orchestration import (
    TerminalExecutionPlan,
    TerminalPlanError,
    parse_terminal_plan,
)
from device_tui.application.upgrades.package import find_free_space_bytes
from device_tui.infrastructure.transfers.file_transfer_service import (
    TransferServiceConfig,
    TransferServiceController,
)
from device_tui.infrastructure.transfers.managed_file_transfer import (
    ManagedTransferError,
    TransferInteractionProfile,
    SharedFileCatalog,
    _validate_relative_path,
    build_ftpget_command,
    build_ftpget_transfer_steps,
    build_linux_inspection_command,
    build_managed_transfer_download_steps,
    build_managed_transfer_steps,
    destination_entry,
    destination_matches,
    destination_storage,
    infer_terminal_environment,
    list_shared_files,
    linux_client_available,
    linux_directory_available,
    linux_file_size,
    linux_free_space_bytes,
    normalize_terminal_environment,
    resolve_shared_file,
    resolve_shared_root,
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


@dataclass(frozen=True, slots=True)
class TransferSettings:
    protocol: str
    host: str
    advertised_host: str
    port: int
    root: str
    username: str
    writable: bool
    has_password: bool
    service_running: bool
    bound_port: int
    idle_stop_at: str = ""


def normalize_advertised_host(value: str) -> str:
    raw = value.strip()
    if not raw or raw.casefold() == "auto":
        return ""
    try:
        address = ipaddress.ip_address(raw)
    except ValueError as exc:
        raise UnsupportedOperationError("设备访问地址必须是 IPv4 地址或留空自动选择。") from exc
    if not isinstance(address, ipaddress.IPv4Address):
        raise UnsupportedOperationError("设备访问地址目前仅支持 IPv4。")
    if address.is_unspecified or address.is_loopback or address.is_multicast:
        raise UnsupportedOperationError("设备访问地址必须是设备可达的本机 IPv4 地址。")
    return str(address)


def select_route_local_ipv4(remote_host: str, remote_port: int = 0) -> str:
    target = remote_host.strip()
    if not target:
        raise OSError("终端没有可用的远端地址。")
    port = int(remote_port) if 0 < int(remote_port) <= 65535 else 9
    errors: list[OSError] = []
    for family, socktype, protocol, _canonical, sockaddr in socket.getaddrinfo(
        target,
        port,
        family=socket.AF_INET,
        type=socket.SOCK_DGRAM,
    ):
        probe = socket.socket(family, socktype, protocol)
        try:
            probe.connect(sockaddr)
            local_host = str(probe.getsockname()[0]).strip()
            address = ipaddress.ip_address(local_host)
            if (
                isinstance(address, ipaddress.IPv4Address)
                and not address.is_unspecified
                and not address.is_loopback
                and not address.is_multicast
            ):
                return str(address)
        except OSError as exc:
            errors.append(exc)
        finally:
            probe.close()
    if errors:
        raise OSError(str(errors[-1]))
    raise OSError(f"无法确定到 {target} 的本机 IPv4 路由。")


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
        execution_id: str | None = None,
    ) -> dict[str, object]: ...

    def get_execution(self, execution_id: str) -> dict[str, object]: ...

    def cancel_execution(self, execution_id: str) -> dict[str, object]: ...

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

    def get_execution(self, _execution_id: str) -> dict[str, object]:
        raise UnsupportedOperationError("Terminal operations are unavailable.")

    def cancel_execution(self, _execution_id: str) -> dict[str, object]:
        raise UnsupportedOperationError("Terminal operations are unavailable.")

    def cancel_active(self, _session_id: str) -> str:
        return ""

    def configure_managed_transfer(self, *_args: object, **_kwargs: object) -> None:
        return


class ManagedTransferService:
    CONFIG_KEY = "file_transfer_config_v1"
    LEGACY_IMPORT_KEY = "legacy_file_transfer_v1"
    PASSWORD_SECRET_ID = "file-transfer:service-password"
    IDLE_STOP_SECONDS = 300

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

    def settings(self) -> TransferSettings:
        config = self._saved_config()
        return TransferSettings(
            protocol=config["protocol"],
            host=config["host"],
            advertised_host=str(config.get("advertised_host") or ""),
            port=int(config["port"]),
            root=config["root"],
            username=config["username"],
            writable=bool(config["writable"]),
            has_password=self._secrets.get(self.PASSWORD_SECRET_ID) is not None,
            service_running=self._controller.is_running,
            bound_port=self._controller.bound_port,
            idle_stop_at=self._idle_stop_at,
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
        advertised_host: str = "",
    ) -> TransferSettings:
        if self._controller.is_running:
            raise ApplicationConflictError(
                "Stop the file-transfer service before changing its settings."
            )
        normalized_protocol = protocol.strip().casefold()
        if normalized_protocol != "ftp":
            raise UnsupportedOperationError("当前文件传输仅支持 FTP。")
        if not 0 <= int(port) <= 65535:
            raise UnsupportedOperationError("The transfer port must be between 0 and 65535.")
        normalized_username = username.strip()
        if not normalized_username:
            raise UnsupportedOperationError("A transfer-service username is required.")
        resolved_root = resolve_shared_root(Path(root))
        payload = {
            "protocol": normalized_protocol,
            "host": host.strip() or "0.0.0.0",
            "advertised_host": normalize_advertised_host(advertised_host),
            "port": int(port),
            "root": str(resolved_root),
            "username": normalized_username,
            "writable": bool(writable),
        }
        self._store.set_meta(self.CONFIG_KEY, json.dumps(payload, ensure_ascii=False))
        return self.settings()

    async def reconfigure(
        self,
        *,
        protocol: str,
        host: str,
        port: int,
        root: str,
        username: str,
        writable: bool,
        password: str | None = None,
        advertised_host: str = "",
    ) -> TransferSettings:
        if self._tasks:
            raise ApplicationConflictError("活动传输期间不能修改文件服务配置。")
        if self._controller.is_running:
            await self.stop_service()
        self.update_settings(
            protocol=protocol,
            host=host,
            port=port,
            root=root,
            username=username,
            writable=writable,
            advertised_host=advertised_host,
        )
        if password is not None:
            self.set_password(password)
        return self.settings()

    def set_password(self, value: str) -> TransferSettings:
        if not value:
            self._secrets.delete(self.PASSWORD_SECRET_ID)
        else:
            self._secrets.set(self.PASSWORD_SECRET_ID, value)
        return self.settings()

    def resolve_secret(self, secret_ref: str) -> str:
        if secret_ref in self._runtime_secrets:
            return self._runtime_secrets[secret_ref]
        if secret_ref == "file_transfer.username":
            return str(self._saved_config()["username"])
        if secret_ref == "file_transfer.password":
            return self._secrets.get(self.PASSWORD_SECRET_ID) or ""
        return self._secrets.get(secret_ref) or ""

    def _register_runtime_credentials(
        self,
        operation_id: str,
        username: str,
        password: str,
    ) -> tuple[str, str]:
        username_ref = f"managed_transfer.{operation_id}.username"
        password_ref = f"managed_transfer.{operation_id}.password"
        self._runtime_secrets[username_ref] = username
        self._runtime_secrets[password_ref] = password
        return username_ref, password_ref

    def _register_runtime_command(self, operation_id: str, command: str) -> str:
        command_ref = f"managed_transfer.{operation_id}.command"
        self._runtime_secrets[command_ref] = command
        return command_ref

    def _clear_runtime_credentials(self, operation_id: str) -> None:
        self._runtime_secrets.pop(f"managed_transfer.{operation_id}.username", None)
        self._runtime_secrets.pop(f"managed_transfer.{operation_id}.password", None)
        self._runtime_secrets.pop(f"managed_transfer.{operation_id}.command", None)

    async def start_service(self, *, auto_stop_when_idle: bool = True) -> TransferSettings:
        self._cancel_idle_stop()
        async with self._service_lifecycle_lock:
            if not self._controller.is_running:
                self._event_loop = asyncio.get_running_loop()
                config = self._runtime_config(ensure_password=True)
                try:
                    await asyncio.to_thread(self._controller.start, config)
                except RuntimeError as exc:
                    raise TransferOperationError(str(exc)) from exc
                self._publish_service_state("transfer.service.started")
        if auto_stop_when_idle:
            self._schedule_idle_stop()
        return self.settings()

    async def service_endpoint_for_session(self, session_id: str) -> tuple[str, int]:
        """Return the service address reachable from a device session.

        The bind address is a local-server concern. Device-facing workflows
        must use the advertised address or the address selected from the route
        to the target device.
        """
        session = self._connected_session(session_id)
        config = await self._ensure_service()
        # Keep the built-in simulator's device-side FTP client aligned with
        # the credentials exposed by the managed service. Real transports do
        # not use this hook; they authenticate against the actual service.
        if session.kind == "simulated":
            self._executor.configure_managed_transfer(
                session.id,
                username=config.username,
                password=config.password,
                source_path="",
                source_size=0,
                destination_path="",
            )
        host = self._device_host(session, config).strip()
        settings = self.settings()
        port = int(settings.bound_port or config.port)
        if not host or not 0 < port <= 65535:
            raise TransferOperationError("The file-transfer service has no usable device endpoint.")
        return host, port

    async def stop_service(self) -> TransferSettings:
        if self._tasks:
            raise ApplicationConflictError("活动传输期间不能停止文件服务。")
        self._cancel_idle_stop()
        async with self._service_lifecycle_lock:
            if self._controller.is_running:
                await asyncio.to_thread(self._controller.stop)
                self._publish_service_state("transfer.service.stopped")
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
        advertised_host = settings.advertised_host.strip()
        target = advertised_host or (
            host if host not in {"", "0.0.0.0", "::"} else "<按设备路由自动选择>"
        )
        port = settings.bound_port or settings.port
        if settings.protocol == "sftp":
            return f"sftp -P {port} {settings.username}@{target}"
        return f"ftp {target} {port}"

    def network_addresses(self, session_id: str = "") -> tuple[list[str], str]:
        """Return usable local IPv4 addresses with the session route first."""
        addresses: list[str] = []
        recommended = ""
        if session_id:
            try:
                target = self._sessions.connection_target(session_id)
            except ResourceNotFoundError:
                target = None
            if target is not None and target.host.strip():
                try:
                    recommended = select_route_local_ipv4(target.host, target.port)
                except OSError:
                    recommended = ""
        if recommended:
            addresses.append(recommended)

        try:
            candidates = socket.getaddrinfo(
                socket.gethostname(),
                None,
                family=socket.AF_INET,
                type=socket.SOCK_DGRAM,
            )
        except OSError:
            candidates = []
        for _family, _socktype, _protocol, _canonical, sockaddr in candidates:
            raw = str(sockaddr[0]).strip()
            try:
                address = ipaddress.ip_address(raw)
            except ValueError:
                continue
            if (
                not isinstance(address, ipaddress.IPv4Address)
                or address.is_unspecified
                or address.is_loopback
                or address.is_multicast
            ):
                continue
            normalized = str(address)
            if normalized not in addresses:
                addresses.append(normalized)
        return addresses, recommended

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

    async def _run_upload(
        self,
        operation_id: str,
        session: SessionRecord,
    ) -> None:
        owner_id = f"managed-transfer:{operation_id}"
        acquired = False
        managed_username = ""
        try:
            current = self._operations.get(operation_id)
            source, info = resolve_shared_file(
                Path(str(self._saved_config()["root"])),
                str(current.data["source_path"]),
            )
            initial_fingerprint = source_fingerprint(source)
            self._executor.acquire(
                session.id,
                owner_id,
                on_cancel=lambda: self._cancel_active(operation_id, session.id, pause_queue=True),
            )
            acquired = True
            operation = self._operations.update(
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
            terminal_environment = str(
                operation.data.get("terminal_environment") or "vrp"
            )
            precheck = await self._run_plan(
                session,
                owner_id,
                self._inspection_plan(
                    destination,
                    terminal_environment,
                    str(self._saved_config()["protocol"]),
                ),
            )
            output = self._require_completed(precheck, "prechecking")
            if terminal_environment == "linux":
                self._require_linux_inspection(output, str(self._saved_config()["protocol"]))
                existing_size = linux_file_size(output)
                free_bytes = linux_free_space_bytes(output)
            else:
                existing = destination_entry(output, destination)
                existing_size = existing.size_bytes if existing is not None else None
                free_bytes = find_free_space_bytes(output)
            if existing_size is not None and not bool(operation.data["overwrite"]):
                raise _TransferRunError(
                    "destination_exists",
                    f"设备目标文件已存在，大小为 {existing_size} 字节。",
                )
            source_size = int(operation.data["source_size"])
            required = max(0, source_size - (existing_size or 0))
            if free_bytes is None:
                raise _TransferRunError(
                    "storage_space_indeterminate",
                    "设备目录输出未包含可识别的可用空间，未开始传输。",
                )
            if free_bytes < required:
                raise _TransferRunError(
                    "insufficient_space",
                    f"设备可用空间不足，需要 {required} 字节，可用 {free_bytes} 字节。",
                )
            if source_fingerprint(source) != initial_fingerprint:
                raise _TransferRunError("transfer_source_changed", "传输前源文件发生变化。")
            config = await self._ensure_service()
            host = self._device_host(session, config)
            self._operations.update(operation_id, data={"service_host": host})
            managed_username, managed_password = self._controller.register_managed_transfer(
                operation_id,
                total_bytes=source_size,
                on_progress=self._queue_progress_from_thread,
            )
            username_ref, password_ref = self._register_runtime_credentials(
                operation_id,
                managed_username,
                managed_password,
            )
            connect_secret_ref = ""
            if terminal_environment == "linux" and config.protocol == "sftp":
                connect_secret_ref = username_ref
            self._executor.configure_managed_transfer(
                session.id,
                username=managed_username,
                password=managed_password,
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
                username_secret_ref=username_ref,
                password_secret_ref=password_ref,
                terminal_environment=terminal_environment,
                connect_secret_ref=connect_secret_ref,
                profile=self._interaction_profile(current.data.get("interaction_profile")),
            )
            self._operations.update(
                operation_id,
                stage="transferring",
                message=f"正在通过 {config.protocol.upper()}（{self._environment_label(terminal_environment)}）传输文件。",
                progress_percent=0,
            )
            transferred = await self._run_plan(
                session,
                owner_id,
                parse_terminal_plan(steps, total_timeout_seconds=timeout),
            )
            self._require_completed(transferred, "transferring")
            self._record_progress(operation_id, source_size, force=True)
            if source_fingerprint(source) != initial_fingerprint:
                raise _TransferRunError("transfer_source_changed", "传输期间源文件发生变化。")
            self._operations.update(
                operation_id,
                stage="verifying",
                message="正在核对设备端文件名和精确字节数。",
                progress_percent=100,
                bytes_per_second=0,
                clear_eta=True,
            )
            verified = await self._run_plan(
                session,
                owner_id,
                self._inspection_plan(destination, terminal_environment, config.protocol),
            )
            verify_output = self._require_completed(verified, "verifying")
            verified_size = (
                linux_file_size(verify_output)
                if terminal_environment == "linux"
                else None
            )
            verified_matches = (
                verified_size == source_size
                if terminal_environment == "linux"
                else destination_matches(verify_output, destination, source_size)
            )
            if not verified_matches:
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
                bytes_transferred=source_size,
                total_bytes=source_size,
                bytes_per_second=0,
                clear_eta=True,
                error_code="",
            )
        except asyncio.CancelledError:
            self._mark_cancelled(operation_id)
        except (ManagedTransferError, TerminalPlanError, TransferOperationError, _TransferRunError, RuntimeError, OSError) as exc:
            self._mark_failed(operation_id, getattr(exc, "code", "transfer_failed"), str(exc))
        finally:
            if managed_username:
                self._controller.unregister_managed_transfer(managed_username)
                self._clear_runtime_credentials(operation_id)
            if acquired:
                self._executor.release(session.id, owner_id)

    async def _run_ftpget_upload(
        self,
        operation_id: str,
        session: SessionRecord,
    ) -> None:
        owner_id = f"managed-transfer:{operation_id}"
        acquired = False
        managed_username = ""
        try:
            operation = self._operations.get(operation_id)
            source, info = resolve_shared_file(
                Path(str(self._saved_config()["root"])),
                str(operation.data["source_path"]),
            )
            initial_fingerprint = source_fingerprint(source)
            saved_config = self._saved_config()
            if str(saved_config["protocol"]).casefold() != "ftp":
                raise _TransferRunError(
                    "ftpget_requires_ftp",
                    "ftpget 单命令需要将本机文件服务协议设置为 FTP。",
                )
            if int(saved_config["port"]) != 21:
                raise _TransferRunError(
                    "ftpget_requires_port_21",
                    "当前 ftpget 语法不包含端口参数，请将 FTP 服务端口设置为 21。",
                )
            self._executor.acquire(
                session.id,
                owner_id,
                on_cancel=lambda: self._cancel_active(operation_id, session.id, pause_queue=True),
            )
            acquired = True
            self._operations.update(
                operation_id,
                stage="prechecking",
                message="正在检查 ftpget 命令和本机 FTP 服务配置。",
                progress_percent=0,
                total_bytes=info.size_bytes,
                bytes_transferred=0,
                bytes_per_second=0,
                clear_eta=True,
            )
            config = await self._ensure_service()
            bound_port = self._controller.bound_port or config.port
            if bound_port != 21:
                raise _TransferRunError(
                    "ftpget_requires_port_21",
                    f"当前 FTP 服务实际端口为 {bound_port}，ftpget 单命令需要端口 21。",
                )
            host = self._device_host(session, config)
            managed_username, managed_password = self._controller.register_managed_transfer(
                operation_id,
                total_bytes=info.size_bytes,
                on_progress=self._queue_progress_from_thread,
            )
            command = build_ftpget_command(
                username=managed_username,
                password=managed_password,
                host=host,
                source_path=info.relative_path,
            )
            command_ref = self._register_runtime_command(operation_id, command)
            self._executor.configure_managed_transfer(
                session.id,
                username=managed_username,
                password=managed_password,
                source_path=info.relative_path,
                source_size=info.size_bytes,
                destination_path=info.relative_path,
            )
            steps, timeout = build_ftpget_transfer_steps(
                command_secret_ref=command_ref,
                source_size=info.size_bytes,
            )
            self._operations.update(
                operation_id,
                stage="transferring",
                message="已向当前终端发送 ftpget，正在等待 FTP 数据传输完成。",
                progress_percent=0,
                data={
                    "service_host": host,
                    "service_port": bound_port,
                    "command_preview": (
                        f"ftpget -u <临时账号> -p ****** {host} {info.relative_path}"
                    ),
                    "verification": "ftp_server_and_terminal_completion",
                },
            )
            result = await self._run_plan(
                session,
                owner_id,
                parse_terminal_plan(steps, total_timeout_seconds=timeout),
            )
            self._require_completed(result, "transferring")
            self._record_progress(operation_id, info.size_bytes, force=True)
            if source_fingerprint(source) != initial_fingerprint:
                raise _TransferRunError("transfer_source_changed", "传输期间源文件发生变化。")
            self._operations.update(
                operation_id,
                status="completed",
                stage="completed",
                message=f"ftpget 已完成 {info.relative_path}，本机 FTP 服务共发送 {info.size_bytes} 字节。",
                progress_percent=100,
                bytes_transferred=info.size_bytes,
                total_bytes=info.size_bytes,
                bytes_per_second=0,
                clear_eta=True,
                error_code="",
            )
        except asyncio.CancelledError:
            self._mark_cancelled(operation_id)
        except (ManagedTransferError, TerminalPlanError, TransferOperationError, _TransferRunError, RuntimeError, OSError) as exc:
            self._mark_failed(operation_id, getattr(exc, "code", "transfer_failed"), str(exc))
        finally:
            if managed_username:
                self._controller.unregister_managed_transfer(managed_username)
            self._clear_runtime_credentials(operation_id)
            if acquired:
                self._executor.release(session.id, owner_id)

    async def _run_download(self, operation_id: str, session: SessionRecord) -> None:
        owner_id = f"managed-transfer:{operation_id}"
        acquired = False
        managed_username = ""
        try:
            self._executor.acquire(
                session.id,
                owner_id,
                on_cancel=lambda: self._cancel_active(operation_id, session.id, pause_queue=True),
            )
            acquired = True
            operation = self._operations.update(
                operation_id,
                stage="prechecking",
                message="正在检查设备源文件和 PC 目标空间。",
                progress_percent=0,
                bytes_transferred=0,
                bytes_per_second=0,
                clear_eta=True,
            )
            source_path = str(operation.data["source_path"])
            terminal_environment = str(
                operation.data.get("terminal_environment") or "vrp"
            )
            precheck = await self._run_plan(
                session,
                owner_id,
                self._inspection_plan(
                    source_path,
                    terminal_environment,
                    str(self._saved_config()["protocol"]),
                ),
            )
            output = self._require_completed(precheck, "prechecking")
            if terminal_environment == "linux":
                self._require_linux_inspection(output, str(self._saved_config()["protocol"]))
                source_size = linux_file_size(output)
            else:
                entry = destination_entry(output, source_path)
                source_size = entry.size_bytes if entry is not None else None
            if source_size is None:
                raise _TransferRunError("transfer_source_not_found", "设备端源文件不存在。")
            root = Path(str(self._saved_config()["root"]))
            relative = str(operation.data["destination_path"])
            destination = root.joinpath(*_validate_relative_path(relative, label="destination_path").parts)
            existing_size = destination.stat().st_size if destination.is_file() else 0
            if destination.exists() and not bool(operation.data["overwrite"]):
                raise _TransferRunError("destination_exists", "PC 目标文件已存在。")
            required = max(0, source_size - existing_size)
            if shutil.disk_usage(root).free < required:
                raise _TransferRunError("insufficient_space", "PC 共享目录可用空间不足。")
            operation = self._operations.update(
                operation_id,
                total_bytes=source_size,
                data={"source_size": source_size},
            )
            config = await self._ensure_service()
            if not config.writable:
                raise _TransferRunError(
                    "transfer_service_read_only",
                    "设备下载到 PC 时文件服务必须允许写入。",
                )
            host = self._device_host(session, config)
            self._operations.update(operation_id, data={"service_host": host})
            managed_username, managed_password = self._controller.register_managed_transfer(
                operation_id,
                total_bytes=source_size,
                on_progress=self._queue_progress_from_thread,
            )
            username_ref, password_ref = self._register_runtime_credentials(
                operation_id,
                managed_username,
                managed_password,
            )
            connect_secret_ref = ""
            if terminal_environment == "linux" and config.protocol == "sftp":
                connect_secret_ref = username_ref
            self._executor.configure_managed_transfer(
                session.id,
                username=managed_username,
                password=managed_password,
                source_path=source_path,
                source_size=source_size,
                destination_path=relative,
            )
            steps, timeout = build_managed_transfer_download_steps(
                protocol=config.protocol,
                host=host,
                port=self._controller.bound_port or config.port,
                source_path=source_path,
                destination_path=relative,
                source_size=source_size,
                username_secret_ref=username_ref,
                password_secret_ref=password_ref,
                terminal_environment=terminal_environment,
                connect_secret_ref=connect_secret_ref,
                profile=self._interaction_profile(current.data.get("interaction_profile")),
            )
            self._operations.update(
                operation_id,
                stage="transferring",
                message=f"正在通过 {config.protocol.upper()}（{self._environment_label(terminal_environment)}）下载文件。",
                progress_percent=0,
            )
            result = await self._run_plan(
                session,
                owner_id,
                parse_terminal_plan(steps, total_timeout_seconds=timeout),
            )
            self._require_completed(result, "transferring")
            self._record_progress(operation_id, source_size, force=True)
            self._operations.update(
                operation_id,
                stage="verifying",
                message="正在核对 PC 端文件名和精确字节数。",
                progress_percent=100,
                bytes_per_second=0,
                clear_eta=True,
            )
            if not destination.is_file() or destination.stat().st_size != source_size:
                raise _TransferRunError(
                    "transfer_verification_failed",
                    "PC 目标文件不存在，或字节数与设备源文件不一致。",
                )
            self._operations.update(
                operation_id,
                status="completed",
                stage="completed",
                message=f"文件已下载到 {relative}，并确认 {source_size} 字节完全匹配。",
                progress_percent=100,
                bytes_transferred=source_size,
                total_bytes=source_size,
                bytes_per_second=0,
                clear_eta=True,
                error_code="",
            )
        except asyncio.CancelledError:
            self._mark_cancelled(operation_id)
        except (ManagedTransferError, TerminalPlanError, TransferOperationError, _TransferRunError, RuntimeError, OSError) as exc:
            self._mark_failed(operation_id, getattr(exc, "code", "transfer_failed"), str(exc))
        finally:
            if managed_username:
                self._controller.unregister_managed_transfer(managed_username)
                self._clear_runtime_credentials(operation_id)
            if acquired:
                self._executor.release(session.id, owner_id)

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

    @staticmethod
    def _inspection_plan(
        path: str,
        terminal_environment: str,
        protocol: str,
    ) -> TerminalExecutionPlan:
        if terminal_environment == "linux":
            return parse_terminal_plan(
                [
                    {
                        "type": "send",
                        "text": build_linux_inspection_command(path, protocol),
                        "label": "检查 Linux 文件、空间和传输客户端",
                    },
                    {
                        "type": "expect",
                        "success": ["device_prompt"],
                        "timeout_seconds": 30,
                        "label": "等待 Linux 检查结果",
                        "max_output_chars": 32_768,
                    },
                ],
                total_timeout_seconds=45,
            )
        return parse_terminal_plan(
            [
                {"type": "send", "text": f"dir {destination_storage(path)}", "label": "读取目录"},
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
    def _require_linux_inspection(output: str, protocol: str) -> None:
        if not linux_client_available(output):
            raise _TransferRunError(
                "transfer_client_unavailable",
                f"Linux Shell 中未找到 {protocol.upper()} 客户端，请安装后重试或切换传输协议。",
            )
        if not linux_directory_available(output):
            raise _TransferRunError(
                "transfer_directory_not_found",
                "Linux 文件路径的父目录不存在。",
            )

    @staticmethod
    def _environment_label(terminal_environment: str) -> str:
        return "Linux Shell" if terminal_environment == "linux" else "Huawei VRP"

    @staticmethod
    def _normalize_command_mode(command_mode: str) -> str:
        normalized = str(command_mode or "vrp").strip().casefold()
        if normalized not in {"vrp", "ftpget"}:
            raise ManagedTransferError(
                "invalid_request",
                f"不支持的设备 FTP 命令方式: {command_mode}",
            )
        return normalized

    @staticmethod
    def _interaction_profile(value: object) -> TransferInteractionProfile | None:
        if not isinstance(value, dict) or not value:
            return None
        valid_fields = {item.name for item in fields(TransferInteractionProfile)}
        values = {
            str(key): str(raw)
            for key, raw in value.items()
            if str(key) in valid_fields and isinstance(raw, str)
        }
        return TransferInteractionProfile(**values) if values else None

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

    def _enqueue(self, record: OperationRecord) -> None:
        self._event_loop = asyncio.get_running_loop()
        self._cancel_idle_stop()
        queue = self._queues.setdefault(record.session_id, deque())
        queue.append(record.id)
        self._operations.register_canceller(
            record.id,
            lambda: self._cancel_queued(record.id, record.session_id),
        )
        self._refresh_queue_positions(record.session_id)
        self._ensure_worker(record.session_id)

    def _ensure_worker(self, session_id: str) -> None:
        if session_id in self._paused_sessions:
            return
        current = self._workers.get(session_id)
        if current is not None and not current.done():
            return
        worker = asyncio.create_task(
            self._run_session_queue(session_id),
            name=f"managed-transfer-queue-{session_id}",
        )
        self._workers[session_id] = worker

    async def _run_session_queue(self, session_id: str) -> None:
        try:
            while session_id not in self._paused_sessions:
                queue = self._queues.get(session_id)
                if not queue:
                    break
                operation_id = queue.popleft()
                self._refresh_queue_positions(session_id)
                record = self._operations.get(operation_id)
                if record.status != "queued":
                    continue
                try:
                    session = self._connected_session(session_id)
                except (ResourceNotFoundError, ApplicationConflictError) as exc:
                    self._mark_failed(operation_id, "session_unavailable", str(exc))
                    continue
                self._operations.update(
                    operation_id,
                    status="running",
                    stage="prechecking",
                    message="正在准备传输。",
                    clear_queue_position=True,
                )
                if record.direction == "download":
                    runner = self._run_download
                elif str(record.data.get("command_mode") or "vrp") == "ftpget":
                    runner = self._run_ftpget_upload
                else:
                    runner = self._run_upload
                task = asyncio.create_task(
                    runner(operation_id, session),
                    name=f"managed-transfer-{operation_id}",
                )
                self._tasks[operation_id] = task
                self._operations.register_canceller(
                    operation_id,
                    lambda oid=operation_id, sid=session_id: self._cancel_active(
                        oid,
                        sid,
                        pause_queue=False,
                    ),
                )
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                finally:
                    self._tasks.pop(operation_id, None)
                    self._progress_samples.pop(operation_id, None)
                    self._last_progress_emit.pop(operation_id, None)
        finally:
            self._workers.pop(session_id, None)
            if not self._queues.get(session_id):
                self._queues.pop(session_id, None)
            elif session_id not in self._paused_sessions:
                self._ensure_worker(session_id)
            self._schedule_idle_stop()

    def _cancel_queued(self, operation_id: str, session_id: str) -> None:
        queue = self._queues.get(session_id)
        if queue is not None:
            try:
                queue.remove(operation_id)
            except ValueError:
                pass
        self._mark_cancelled(operation_id)
        self._refresh_queue_positions(session_id)
        self._schedule_idle_stop()

    def _cancel_active(
        self,
        operation_id: str,
        session_id: str,
        *,
        pause_queue: bool,
    ) -> None:
        if operation_id in self._cancelling:
            return
        self._cancelling.add(operation_id)
        try:
            if pause_queue:
                self._pause_queue_for_takeover(session_id)
            self._executor.cancel_active(session_id)
            self._executor.release(session_id, f"managed-transfer:{operation_id}")
            task = self._tasks.get(operation_id)
            if task is not None and not task.done():
                task.cancel()
            self._mark_cancelled(operation_id)
        finally:
            self._cancelling.discard(operation_id)

    def _pause_queue_for_takeover(self, session_id: str) -> None:
        self._paused_sessions.add(session_id)
        for operation_id in self._queues.get(session_id, ()):
            record = self._operations.get(operation_id)
            if record.status == "queued":
                self._operations.update(
                    operation_id,
                    stage="paused",
                    message="手工输入已接管终端，队列暂停。",
                )

    def _refresh_queue_positions(self, session_id: str) -> None:
        queue = self._queues.get(session_id, deque())
        paused = session_id in self._paused_sessions
        for position, operation_id in enumerate(queue, start=1):
            record = self._operations.get(operation_id)
            if record.status != "queued":
                continue
            self._operations.update(
                operation_id,
                queue_position=position,
                stage="paused" if paused else "queued",
            )

    def _queue_progress_from_thread(self, operation_id: str, transferred: int) -> None:
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._record_progress, operation_id, transferred)

    def _record_progress(
        self,
        operation_id: str,
        transferred: int,
        *,
        force: bool = False,
    ) -> None:
        record = self._operations.get(operation_id)
        if record.status != "running" or record.stage not in {"transferring", "verifying"}:
            return
        now = time.monotonic()
        safe_bytes = max(record.bytes_transferred, int(transferred))
        samples = self._progress_samples.setdefault(operation_id, deque())
        samples.append((now, safe_bytes))
        while len(samples) > 1 and now - samples[0][0] > 5:
            samples.popleft()
        last_emit = self._last_progress_emit.get(operation_id, 0.0)
        if not force and now - last_emit < 0.25:
            return
        speed = 0
        if len(samples) > 1 and samples[-1][0] > samples[0][0]:
            speed = max(0, int((samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0])))
        total = record.total_bytes
        percent = min(100, int(safe_bytes * 100 / total)) if total else 0
        eta = max(0, int((total - safe_bytes) / speed)) if total and speed else None
        self._last_progress_emit[operation_id] = now
        self._operations.update(
            operation_id,
            bytes_transferred=safe_bytes,
            bytes_per_second=speed,
            eta_seconds=eta,
            clear_eta=eta is None,
            progress_percent=percent,
        )

    def _cancel_idle_stop(self) -> None:
        task = self._idle_stop_task
        self._idle_stop_task = None
        self._idle_stop_at = ""
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    def _schedule_idle_stop(self) -> None:
        if self._tasks or not self._controller.is_running:
            return
        if self._idle_stop_task is not None and not self._idle_stop_task.done():
            return
        self._idle_stop_at = (
            datetime.now(timezone.utc) + timedelta(seconds=self.IDLE_STOP_SECONDS)
        ).isoformat()
        self._publish_service_state("transfer.service.updated")
        self._idle_stop_task = asyncio.create_task(
            self._stop_service_when_idle(),
            name="managed-transfer-idle-stop",
        )

    async def _stop_service_when_idle(self) -> None:
        try:
            await asyncio.sleep(self.IDLE_STOP_SECONDS)
            async with self._service_lifecycle_lock:
                if self._tasks or not self._controller.is_running:
                    return
                await asyncio.to_thread(self._controller.stop)
                self._idle_stop_task = None
                self._idle_stop_at = ""
                self._publish_service_state("transfer.service.stopped")
        except asyncio.CancelledError:
            return

    def _publish_service_state(self, event_type: str) -> None:
        self._events.publish(event_type, data=asdict(self.settings()))

    def _mark_cancelled(self, operation_id: str) -> None:
        record = self._operations.get(operation_id)
        if record.status in TERMINAL_OPERATION_STATUSES:
            return
        self._operations.update(
            operation_id,
            status="cancelled",
            stage="cancelled",
            message="文件传输已取消。",
            bytes_per_second=0,
            clear_eta=True,
            clear_queue_position=True,
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
            bytes_per_second=0,
            clear_eta=True,
            clear_queue_position=True,
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
            advertised_host=str(config.get("advertised_host") or ""),
        )

    def _saved_config(self) -> dict[str, object]:
        defaults: dict[str, object] = {
            "protocol": "ftp",
            "host": "0.0.0.0",
            "advertised_host": "",
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
        merged = {**defaults, **payload}
        # The current desktop contract is FTP-only. Treat persisted SFTP
        # settings from older releases as a one-time migration to FTP.
        if str(merged.get("protocol") or "").casefold() != "ftp":
            merged["protocol"] = "ftp"
            self._store.set_meta(self.CONFIG_KEY, json.dumps(merged, ensure_ascii=False))
        return merged

    def _device_host(self, session: SessionRecord, config: TransferServiceConfig) -> str:
        advertised_host = config.advertised_host.strip()
        if advertised_host:
            return advertised_host
        host = config.host.strip()
        if session.kind == "simulated" and host in {"", "0.0.0.0", "::"}:
            return "192.0.2.10"
        if host not in {"", "0.0.0.0", "::"}:
            return host
        target = self._sessions.connection_target(session.id)
        if target is None or not target.host.strip():
            raise _TransferRunError(
                "service_endpoint_unavailable",
                "当前终端没有可用的远端 IP，请在高级设置中填写设备访问地址。",
            )
        try:
            return select_route_local_ipv4(target.host, target.port)
        except OSError as exc:
            raise _TransferRunError(
                "service_endpoint_unavailable",
                f"无法根据到 {target.host} 的系统路由选择本机 IP，请在高级设置中手动指定设备访问地址。",
            ) from exc

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
