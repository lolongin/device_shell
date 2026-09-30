"""Shared runtime context for managed transfer execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from device_tui.infrastructure.transfers.file_transfer_service import TransferServiceConfig


class _TransferService(Protocol):
    _controller: object
    _executor: object

    async def _ensure_service(self) -> TransferServiceConfig: ...
    def _device_host(self, session: object, config: TransferServiceConfig) -> str: ...
    def _register_runtime_credentials(self, operation_id: str, username: str, password: str) -> tuple[str, str]: ...
    def _queue_progress_from_thread(self, operation_id: str, transferred: int, total: int) -> None: ...


@dataclass(frozen=True)
class TransferExecutionContext:
    config: TransferServiceConfig
    host: str
    managed_username: str
    managed_password: str
    username_ref: str
    password_ref: str
    connect_secret_ref: str


async def prepare_transfer_execution(
    service: _TransferService,
    *,
    operation_id: str,
    session: object,
    terminal_environment: str,
    source_path: str,
    source_size: int,
    destination_path: str,
) -> TransferExecutionContext:
    config = await service._ensure_service()
    host = service._device_host(session, config)
    username, password = service._controller.register_managed_transfer(
        operation_id,
        total_bytes=source_size,
        on_progress=service._queue_progress_from_thread,
    )
    username_ref, password_ref = service._register_runtime_credentials(operation_id, username, password)
    connect_secret_ref = username_ref if terminal_environment == "linux" and config.protocol == "sftp" else ""
    service._executor.configure_managed_transfer(
        session.id,
        username=username,
        password=password,
        source_path=source_path,
        source_size=source_size,
        destination_path=destination_path,
    )
    return TransferExecutionContext(
        config=config,
        host=host,
        managed_username=username,
        managed_password=password,
        username_ref=username_ref,
        password_ref=password_ref,
        connect_secret_ref=connect_secret_ref,
    )
