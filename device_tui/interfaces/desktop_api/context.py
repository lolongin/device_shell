"""Runtime dependencies owned by the desktop API composition root."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from device_tui.application import AiApplicationService, DesktopApplication
from device_tui.device_sources.import_parser import ParsedDeviceImport
from device_tui.device_sources.service import DeviceSourceService
from device_tui.interfaces.desktop_api.data_migration import PersistenceMigrationStatus
from device_tui.interfaces.desktop_api.mcp_service import DesktopMcpService
from device_tui.interfaces.desktop_api.session_hub import SessionHub
from device_tui.interfaces.desktop_api.terminal_executor import BackendTerminalExecutor
from device_tui.interfaces.desktop_api.ws_tickets import WebSocketTicketStore


@dataclass(slots=True)
class BackendContext:
    """All process-local dependencies used by API adapters.

    The context is deliberately an adapter concern. Business services remain
    owned by :class:`DesktopApplication`; routers only receive this container
    through FastAPI dependencies.
    """

    desktop: DesktopApplication
    repository: DeviceSourceService
    hub: SessionHub
    terminal_executor: BackendTerminalExecutor
    ai_service: AiApplicationService
    mcp_service: DesktopMcpService
    ticket_store: WebSocketTicketStore
    access_token: str
    persistence_status: PersistenceMigrationStatus | None = None
    import_previews: dict[str, tuple[float, ParsedDeviceImport]] = field(
        default_factory=dict
    )
    legacy_import: dict[str, Any] = field(default_factory=dict)
    legacy_command_import: dict[str, Any] = field(default_factory=dict)
    legacy_automation_import: dict[str, Any] = field(default_factory=dict)
    legacy_transfer_import: dict[str, Any] = field(default_factory=dict)
    log_policy: dict[str, int] = field(default_factory=dict)
    data_root: Path | None = None
