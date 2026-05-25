"""Shared state dataclasses for the desktop application."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QLabel, QSplitter, QTabWidget, QToolButton, QWidget

from .data import Device
from .telnet_session import HuaweiTelnetSession
from .linux_session import LinuxSshSession


@dataclass(slots=True)
class RepositorySnapshot:
    current_user: str
    devices: list[Device]
    owned_device_ids: set[str] | None


@dataclass(slots=True)
class DeviceTabState:
    device_id: str
    title: str
    page: QWidget
    session_tab_widget: QTabWidget
    session_splitter: QSplitter | None = None
    session_tab_widgets: list[QTabWidget] = field(default_factory=list)
    active_session_tab_widget: QTabWidget | None = None
    next_session_index: int = 1
    next_telnet_index: int = 1
    next_ssh_index: int = 1
    next_serial_index: int = 1
    tab_title_label: QLabel | None = None
    tab_header: QWidget | None = None
    tab_status_dot: QLabel | None = None
    tab_close_button: QToolButton | None = None


@dataclass(slots=True)
class SessionTabState:
    tab_id: str
    kind: str
    device_id: str
    title: str
    host: str
    port: int
    username: str
    password: str
    page: QWidget
    terminal: Any  # InteractiveTerminal (forward reference)
    session: HuaweiTelnetSession | LinuxSshSession
    log_path: Path
    credential_candidates: list[tuple[str, str]] = field(default_factory=list)
    log_at_line_start: bool = True
    log_input_buffer: str = ""
    log_pending_records: list[tuple[str, str, bool]] = field(default_factory=list)
    pending_input_text: str = ""
    input_flush_scheduled: bool = False
    tab_title_label: QLabel | None = None
    tab_header: QWidget | None = None
    tab_status_dot: QLabel | None = None
    tab_close_button: QToolButton | None = None
    connecting: bool = False
    status_text: str = "Disconnected"
