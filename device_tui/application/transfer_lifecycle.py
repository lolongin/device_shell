"""Managed transfer service lifecycle mixin."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import ipaddress
import json
from pathlib import Path
import secrets as random_secrets
import socket
from threading import Lock

from .errors import ApplicationConflictError, ResourceNotFoundError, TransferOperationError, UnsupportedOperationError
from .transfer_network import normalize_advertised_host, select_route_local_ipv4
from .transfer_models import TransferSettings
from device_tui.infrastructure.transfers.managed_file_transfer import resolve_shared_root
from device_tui.infrastructure.transfers.file_transfer_service import TransferServiceConfig
from .sessions import SessionRecord
from .transfer_helpers import TransferRunError

class TransferServiceLifecycleMixin:
    def _runtime_config(self, *, ensure_password: bool) -> TransferServiceConfig:
        config = self._saved_config()
        password = self._secrets.get(self.PASSWORD_SECRET_ID) or ""
        if ensure_password and not password:
            password = random_secrets.token_urlsafe(24)
            self._secrets.set(self.PASSWORD_SECRET_ID, password)
        return TransferServiceConfig(
            protocol=str(config["protocol"]), host=str(config["host"]), port=int(config["port"]),
            root=Path(str(config["root"])), username=str(config["username"]), password=password,
            writable=bool(config["writable"]), advertised_host=str(config.get("advertised_host") or ""),
        )

    def _saved_config(self) -> dict[str, object]:
        defaults: dict[str, object] = {
            "protocol": "ftp", "host": "0.0.0.0", "advertised_host": "", "port": 0,
            "root": str(self._default_root), "username": "device", "writable": True,
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
            raise TransferRunError("service_endpoint_unavailable", "当前终端没有可用的远端 IP，请在高级设置中填写设备访问地址。")
        try:
            resolver = getattr(self, "_route_local_ipv4", select_route_local_ipv4)
            return resolver(target.host, target.port)
        except OSError as exc:
            raise TransferRunError("service_endpoint_unavailable", f"无法根据到 {target.host} 的系统路由选择本机 IP，请在高级设置中手动指定设备访问地址。") from exc

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
