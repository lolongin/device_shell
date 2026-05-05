from __future__ import annotations

import asyncio
import html
import json
import os
import queue
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import pyte
except ModuleNotFoundError:
    pyte = None

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QBrush, QColor, QKeySequence, QTextCursor, QTextOption
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSplitter,
        QStackedLayout,
        QStatusBar,
        QStyle,
        QStyledItemDelegate,
        QStyleOptionViewItem,
        QTabBar,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without PySide6 installed
    QApplication = None
    QBrush = None
    QColor = None
    QKeySequence = None
    QComboBox = None
    QFormLayout = None
    QFrame = None
    QGroupBox = None
    QHBoxLayout = None
    QHeaderView = None
    QLabel = None
    QLineEdit = None
    QMainWindow = object
    QMenu = None
    QMessageBox = None
    QPlainTextEdit = None
    QPushButton = None
    QScrollArea = None
    QSplitter = None
    QStackedLayout = None
    QStatusBar = None
    QStyle = None
    QStyledItemDelegate = None
    QStyleOptionViewItem = None
    QTabBar = None
    QTabWidget = None
    QTableWidget = None
    QTableWidgetItem = None
    QToolButton = None
    QSize = None
    QTimer = None
    QTextCursor = None
    Qt = None
    QVBoxLayout = None
    QWidget = None
    PYSIDE6_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    PYSIDE6_IMPORT_ERROR = None

try:
    from .data import (
        STATUS_IDLE,
        STATUS_OCCUPIED,
        STATUS_OTHER,
        STATUS_PIPELINE,
        Device,
    )
    from .linux_session import LinuxSshSession
    from .repository import (
        DeviceRepository,
        RepositoryConflictError,
        RepositoryError,
        create_repository_from_env,
    )
    from .session_protocol import SessionCallbacks, SessionUnavailableError
    from .telnet_session import HuaweiTelnetSession, TelnetSessionError
except ImportError:
    from data import (
        STATUS_IDLE,
        STATUS_OCCUPIED,
        STATUS_OTHER,
        STATUS_PIPELINE,
        Device,
    )
    from linux_session import LinuxSshSession
    from repository import (
        DeviceRepository,
        RepositoryConflictError,
        RepositoryError,
        create_repository_from_env,
    )
    from session_protocol import SessionCallbacks, SessionUnavailableError
    from telnet_session import HuaweiTelnetSession, TelnetSessionError


ALL_DOMAINS = "全部领域"
ALL_STATUS = "全部状态"
FILTERABLE_STATUSES = [ALL_STATUS, STATUS_OCCUPIED, STATUS_IDLE, STATUS_PIPELINE, STATUS_OTHER]
DESKTOP_STATE_VERSION = 1

STATUS_COLORS = {
    STATUS_IDLE: "#34d399",
    STATUS_OCCUPIED: "#fb923c",
    STATUS_PIPELINE: "#fbbf24",
    STATUS_OTHER: "#a8b5c4",
}

APP_STYLE = """
QWidget {
    background: #0b0f14;
    color: #e5edf6;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
    font-size: 13px;
}
QMainWindow {
    background: #0b0f14;
}
QFrame#toolbarFrame,
QFrame#workspaceHeader,
QFrame#sessionToolbar,
QFrame#sessionInfoCard,
QFrame#sessionInputBar,
QFrame#navFilterBar,
QFrame#navStatsBar,
QFrame#myOccupancyCard,
QFrame#activeFilterBar,
QFrame#commandRecordDock,
QGroupBox {
    background: #111820;
    border: 1px solid #202a36;
    border-radius: 10px;
}
QGroupBox {
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
    color: #e7f1ff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    background: transparent;
}
QWidget#centerStage,
QWidget#inspectorRail,
QWidget#leftRail {
    background: transparent;
}
QFrame#sessionEmptyState {
    background: #0f141a;
    border: 1px dashed #334155;
    border-radius: 14px;
}
QScrollArea#inspectorScroll {
    background: transparent;
    border: none;
}
QScrollArea#inspectorScroll > QWidget > QWidget {
    background: transparent;
}
QLabel#sessionEmptyTitle {
    background: transparent;
    color: #f8fbff;
    font-size: 24px;
    font-weight: 700;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
}
QLabel#sessionEmptyCopy {
    background: transparent;
    color: #8ea7c2;
    font-size: 13px;
    line-height: 1.7;
}
QGroupBox#navShell,
QGroupBox#deviceDetailCard,
QGroupBox#quickActionCard,
QGroupBox#authCard {
    border-radius: 12px;
}
QGroupBox#deviceDetailCard {
    border-color: #204061;
    background: #0d1621;
}
QGroupBox#quickActionCard {
    border-color: #315042;
    background: #101820;
}
QGroupBox#authCard {
    background: #101820;
}
QGroupBox#navShell {
    border-color: #2a3644;
}
QFrame#navFilterBar {
    background: #0c1218;
    border-color: #273242;
}
QFrame#navStatsBar {
    background: #0c1218;
    border-color: #233548;
}
QFrame#myOccupancyCard {
    background: #101820;
    border-color: #253444;
}
QFrame#activeFilterBar,
QFrame#commandRecordDock {
    background: #0c1218;
    border-color: #273242;
}
QGroupBox#authCard QGroupBox {
    background: #0c1218;
    border: 1px solid #273242;
    border-radius: 10px;
    margin-top: 18px;
    padding-top: 18px;
}
QGroupBox#authCard QGroupBox::title {
    color: #8ea7c2;
    font-size: 12px;
    font-weight: 600;
}
QPushButton {
    background: #17212c;
    border: 1px solid #2d3a49;
    border-radius: 8px;
    padding: 8px 14px;
    color: #e5edf6;
}
QPushButton:hover {
    background: #1d2b38;
    border-color: #3f5267;
}
QPushButton:pressed {
    background: #101820;
}
QPushButton:disabled {
    color: #64748b;
    background: #0b1118;
    border-color: #15212e;
}
QPushButton#primaryButton {
    background: #0f766e;
    border-color: #14b8a6;
    color: #f6fffd;
}
QPushButton#dangerButton {
    background: #4a1f23;
    border-color: #8f2f3a;
    color: #fecaca;
}
QPushButton#ghostButton {
    background: transparent;
    border-color: #303d4d;
}
QLineEdit,
QComboBox,
QPlainTextEdit {
    background: #0b1117;
    border: 1px solid #263544;
    border-radius: 8px;
    padding: 8px 10px;
    color: #e5edf6;
    selection-background-color: #0f766e;
}
QLineEdit:focus,
QComboBox:focus,
QPlainTextEdit:focus {
    border-color: #14b8a6;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QScrollBar:vertical {
    background: #0b141d;
    width: 12px;
    margin: 6px 2px 6px 2px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #26445f;
    min-height: 28px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background: #35658f;
}
QScrollBar::handle:vertical:pressed {
    background: #4a86b8;
}
QScrollBar::sub-line:vertical,
QScrollBar::add-line:vertical {
    height: 0px;
    background: transparent;
    border: none;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    background: #0b141d;
    height: 12px;
    margin: 2px 6px 2px 6px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal {
    background: #26445f;
    min-width: 28px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal:hover {
    background: #35658f;
}
QScrollBar::handle:horizontal:pressed {
    background: #4a86b8;
}
QScrollBar::sub-line:horizontal,
QScrollBar::add-line:horizontal {
    width: 0px;
    background: transparent;
    border: none;
}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
QTableWidget {
    background: #0c1218;
    alternate-background-color: #101820;
    border: 1px solid #253140;
    border-radius: 10px;
    gridline-color: #172231;
    selection-background-color: #164e63;
    selection-color: #ffffff;
}
QTableWidget::item {
    padding: 10px 8px;
    border-bottom: 1px solid #0f1b29;
}
QTableWidget::item:selected {
    background: #164e63;
}
QTableWidget::item:focus {
    border: none;
    outline: none;
}
QTableWidget#deviceTable {
    border-color: #2a3644;
}
QHeaderView::section {
    background: #101820;
    color: #96a6b8;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #162535;
    font-weight: 600;
}
QSplitter::handle {
    background: #0b0f14;
}
QSplitter::handle:horizontal {
    width: 10px;
    margin: 8px 0;
}
QSplitter::handle:horizontal:hover {
    background: #1a2531;
}
QTabWidget::pane {
    border: 1px solid #253140;
    border-radius: 10px;
    background: #0b1117;
    top: -2px;
}
QTabWidget::tab-bar {
    left: 8px;
}
QTabBar::tab {
    background: #101923;
    color: #96a6b8;
    border: 1px solid #263544;
    border-bottom: 1px solid #253140;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    padding: 5px 8px 5px 8px;
    min-width: 164px;
    min-height: 32px;
    margin-right: 5px;
    margin-top: 4px;
}
QTabBar::tab:selected {
    background: #13242d;
    color: #f8fbff;
    border-color: #0f766e;
    border-bottom-color: #13242d;
    margin-top: 0px;
    min-height: 36px;
}
QTabBar::tab:hover {
    color: #e5edf6;
    background: #172532;
    border-color: #385064;
}
QWidget#deviceSessionPage {
    background: transparent;
}
QTabWidget#deviceSessionTabs::pane {
    border-color: #1f3342;
    border-radius: 8px;
    background: #05080c;
    top: -1px;
}
QTabWidget#deviceSessionTabs::tab-bar {
    left: 6px;
}
QTabWidget#deviceSessionTabs QTabBar::tab {
    min-width: 112px;
    min-height: 28px;
    padding: 4px 6px;
    margin-right: 4px;
    margin-top: 3px;
}
QTabWidget#deviceSessionTabs QTabBar::tab:selected {
    background: #0d1d24;
    border-color: #5eead4;
    border-bottom-color: #0d1d24;
    min-height: 31px;
    margin-top: 0px;
}
QWidget#tabHeader {
    background: transparent;
}
QWidget#tabHeader[selected="true"] {
    background: transparent;
}
QLabel#tabStatusDot {
    background: #49627d;
    border-radius: 5px;
}
QLabel#tabStatusDot[connectionState="connecting"] {
    background: #f59e0b;
}
QLabel#tabStatusDot[connectionState="connected"] {
    background: #22c55e;
}
QLabel#tabStatusDot[connectionState="error"] {
    background: #ef4444;
}
QLabel#tabHeaderLabel {
    background: transparent;
    color: #b8c7d9;
    font-size: 13px;
    font-weight: 700;
}
QLabel#tabHeaderLabel[selected="true"] {
    color: #f8fbff;
    font-weight: 700;
}
QToolButton#tabCloseButton {
    background: rgba(148, 163, 184, 0.10);
    color: #9fb0c2;
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 10px;
    font-family: "Arial", "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 14px;
    font-weight: 700;
    padding: 0px;
    margin: 0px;
}
QToolButton#tabCloseButton[selected="true"] {
    background: rgba(143, 247, 210, 0.12);
    border-color: rgba(143, 247, 210, 0.28);
    color: #d7fff2;
}
QToolButton#tabCloseButton:hover {
    background: #7f1d1d;
    color: #ffffff;
    border-color: #ef4444;
}
QToolButton#tabCloseButton:pressed {
    background: #5f1717;
    color: #ffffff;
    border-color: #ef4444;
}
QPlainTextEdit#terminalLog {
    background: #05080c;
    color: #d6deeb;
    border: 1px solid #1f3342;
    border-radius: 10px;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI";
    font-size: 14px;
    padding: 12px;
    selection-background-color: #1e3a4a;
    selection-color: #f8fafc;
}
QPlainTextEdit#terminalLog:focus {
    border-color: #5eead4;
}
QFrame#commandRecordDock {
    background: #0b1117;
    border: 1px solid #1f3b49;
    border-radius: 8px;
}
QFrame#commandRecordHintBar {
    background: #0f1720;
    border: none;
    border-bottom: 1px solid #1d3341;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    min-height: 27px;
    max-height: 27px;
}
QLabel#commandRecordHint {
    background: transparent;
    color: #90a9c2;
    font-size: 12px;
    font-weight: 600;
}
QPlainTextEdit#commandRecordEditor {
    background: #071018;
    color: #f8fafc;
    border: none;
    border-radius: 0px;
    padding: 7px 8px;
    selection-background-color: #1e3a4a;
    selection-color: #f8fbff;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei UI", "Microsoft YaHei";
    font-size: 14px;
}
QPlainTextEdit#commandRecordEditor:focus {
    border: none;
}
QFrame#commandRecordFooter {
    background: #0f1720;
    border: none;
    border-top: 1px solid #1d3341;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
    min-height: 29px;
    max-height: 29px;
}
QToolButton#commandTabButton {
    background: transparent;
    border: none;
    border-radius: 0px;
    color: #96a6b8;
    padding: 5px 10px;
    min-height: 24px;
    font-weight: 600;
}
QToolButton#commandTabButton[selected="true"] {
    background: #12313a;
    color: #8ff7d2;
}
QToolButton#commandTabButton:hover {
    background: #172532;
    color: #e5edf6;
}
QWidget#commandTabItem {
    background: transparent;
}
QToolButton#commandTabCloseButton {
    background: transparent;
    border: none;
    border-radius: 7px;
    color: #7f92a6;
    padding: 0px;
    margin: 0px;
    min-width: 16px;
    max-width: 16px;
    min-height: 16px;
    max-height: 16px;
    font-size: 12px;
    font-weight: 700;
}
QToolButton#commandTabCloseButton[selected="true"] {
    color: #b9fff0;
}
QToolButton#commandTabCloseButton:hover {
    background: #7f1d1d;
    color: #ffffff;
}
QToolButton#commandActionButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    color: #c3d3e4;
    padding: 4px 7px;
    font-weight: 600;
}
QToolButton#commandActionButton:hover {
    background: #13242d;
    border-color: #5eead4;
    color: #5eead4;
}
QToolButton#commandEnterModeButton {
    background: #13242d;
    border: 1px solid #2b4252;
    border-radius: 5px;
    color: #7dd3fc;
    padding: 1px 7px;
    min-height: 19px;
    font-size: 13px;
    font-weight: 700;
}
QToolButton#commandEnterModeButton[enterSends="true"] {
    background: #0f766e;
    border-color: #5eead4;
    color: #f6fffd;
}
QToolButton#commandEnterModeButton:hover {
    background: #12313a;
    border-color: #5eead4;
    color: #d7fff2;
}
QToolButton#commandCollapseButton {
    background: #101c26;
    border: 1px solid #2b4252;
    border-radius: 5px;
    color: #c3d3e4;
    padding: 3px 8px;
    font-weight: 700;
}
QToolButton#commandCollapseButton:hover {
    background: #13242d;
    border-color: #14b8a6;
    color: #d7fff2;
}
QToolButton#quickActionIconButton {
    background: #101c26;
    border: 1px solid #2b4252;
    border-radius: 6px;
    color: #d7fff2;
    padding: 0px;
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    font-weight: 700;
}
QToolButton#quickActionIconButton:hover {
    background: #12313a;
    border-color: #14b8a6;
    color: #ffffff;
}
QToolButton#quickActionIconButton:disabled {
    color: #64748b;
    background: #0b1118;
    border-color: #15212e;
}
QStatusBar {
    background: #0b1117;
    color: #96a6b8;
    border-top: 1px solid #253140;
}
QLabel#brandLabel {
    background: transparent;
    color: #f8fbff;
    font-size: 24px;
    font-weight: 700;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
}
QLabel#sectionTitle {
    background: transparent;
    color: #f8fbff;
    font-size: 16px;
    font-weight: 700;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
}
QLabel#sectionCopy {
    background: transparent;
    color: #96a6b8;
    font-size: 12px;
}
QLabel#navStatsText {
    background: transparent;
    color: #edf5ff;
    font-size: 14px;
    font-weight: 700;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
}
QLabel#navStatsText span {
    white-space: nowrap;
}
QLabel#statChip {
    border: 1px solid #283747;
    border-radius: 8px;
    padding: 8px 12px;
    background: #0f161d;
    color: #e5edf6;
}
QLabel#detailCard {
    border: 1px solid #273747;
    border-radius: 10px;
    padding: 16px;
    background: #0f161d;
    color: #e5edf6;
    line-height: 1.55;
}
QFrame#detailCard {
    border: 1px solid #273747;
    border-radius: 10px;
    background: #0f161d;
}
QLineEdit#detailValueInput {
    background: #0b1117;
    border: 1px solid #274052;
    border-radius: 7px;
    color: #8ff7d2;
    padding: 4px 8px;
    font-weight: 700;
    selection-background-color: #0f766e;
    selection-color: #ffffff;
}
QLineEdit#detailValueInput:focus {
    border-color: #14b8a6;
}
QLabel#footerMetric {
    background: transparent;
    color: #96a6b8;
    font-size: 12px;
    font-weight: 600;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
    padding-left: 8px;
    padding-right: 8px;
}
QLabel#railTitle {
    background: transparent;
    color: #f8fbff;
    font-size: 15px;
    font-weight: 700;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans SC", "Segoe UI";
}
QLabel#railCopy {
    background: transparent;
    color: #96a6b8;
    font-size: 12px;
}
QLabel#activeFilterText {
    background: transparent;
    color: #a8b5c4;
    font-size: 12px;
}
QLabel#activeFilterText {
    color: #c5d5e6;
}
"""


def build_search_text(device: Device) -> str:
    fields = (
        device.id,
        device.name,
        device.domain,
        device.device_type,
        device.cpu,
        device.status,
        device.owner or "",
        device.ssh_ip,
        device.telnet_ip,
        device.vendor,
        device.model,
        device.site,
        device.rack,
        device.version,
        device.notes,
    )
    return " ".join(value.lower() for value in fields)


def mask_password(password: str) -> str:
    return password


def status_color(status: str) -> str:
    return STATUS_COLORS.get(status, "#94a3b8")

@dataclass(slots=True)
class RepositorySnapshot:
    current_user: str
    devices: list[Device]


@dataclass(slots=True)
class DeviceTabState:
    device_id: str
    title: str
    page: QWidget
    session_tab_widget: QTabWidget
    next_session_index: int = 1
    next_telnet_index: int = 1
    next_ssh_index: int = 1
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
    terminal: "InteractiveTerminal"
    session: HuaweiTelnetSession | LinuxSshSession
    tab_title_label: QLabel | None = None
    tab_header: QWidget | None = None
    tab_status_dot: QLabel | None = None
    tab_close_button: QToolButton | None = None
    connecting: bool = False
    status_text: str = "Disconnected"


class AsyncLoopThread:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="device-tui-async-loop")
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)


if PYSIDE6_IMPORT_ERROR is None:

    class NoFocusItemDelegate(QStyledItemDelegate):
        def paint(self, painter: Any, option: Any, index: Any) -> None:
            clean_option = QStyleOptionViewItem(option)
            clean_option.state &= ~QStyle.State_HasFocus
            super().paint(painter, clean_option, index)

    class CopyableDeviceTable(QTableWidget):
        def __init__(
            self,
            copy_handler: Callable[["CopyableDeviceTable"], None],
            field_copy_handler: Callable[["CopyableDeviceTable", str], None],
            parent: QWidget,
        ) -> None:
            super().__init__(0, 0, parent)
            self._copy_handler = copy_handler
            self._field_copy_handler = field_copy_handler

        def keyPressEvent(self, event: Any) -> None:  # noqa: N802
            if event.matches(QKeySequence.Copy):
                self._copy_handler(self)
                return
            if event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier):
                key_map = {
                    Qt.Key_S: "ssh_ip",
                    Qt.Key_T: "telnet_ip",
                    Qt.Key_U: "username",
                    Qt.Key_P: "password",
                }
                field = key_map.get(event.key())
                if field is not None:
                    self._field_copy_handler(self, field)
                    return
            super().keyPressEvent(event)

    class SelectAllLineEdit(QLineEdit):
        def __init__(self) -> None:
            super().__init__()
            self.setReadOnly(True)
            self.setObjectName("detailValueInput")

        def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802
            super().mouseDoubleClickEvent(event)
            self.selectAll()

    class InteractiveTerminal(QPlainTextEdit):
        DEFAULT_COLUMNS = 160
        DEFAULT_LINES = 40
        DEFAULT_HISTORY = 2000

        def __init__(self) -> None:
            super().__init__()
            self._raw_sender: Callable[[str], None] | None = None
            self._command_recorder: Callable[[str], None] | None = None
            self._pending_command_chars: list[str] = []
            self._pyte_screen: Any | None = None
            self._pyte_stream: Any | None = None
            self._buffer_lines: list[list[str]] = [[]]
            self._cursor_row = 0
            self._cursor_col = 0
            self._last_output_char = ""
            self.setObjectName("terminalLog")
            self.setReadOnly(False)
            self.setUndoRedoEnabled(False)
            self.setCursorWidth(2)
            self.setTabChangesFocus(False)
            self.setCenterOnScroll(True)
            self.setWordWrapMode(QTextOption.NoWrap)
            self._init_terminal_backend()

        def _init_terminal_backend(self) -> None:
            if pyte is None:
                return
            self._pyte_screen = pyte.HistoryScreen(
                self.DEFAULT_COLUMNS,
                self.DEFAULT_LINES,
                history=self.DEFAULT_HISTORY,
                ratio=1.0,
            )
            self._pyte_stream = pyte.Stream(self._pyte_screen)

        def _forward_text(self, text: str) -> None:
            if self._raw_sender is None:
                return
            self._raw_sender(text)

        def _record_local_text(self, text: str) -> None:
            for char in text:
                if char in ("\r", "\n"):
                    self._commit_pending_command()
                elif char in ("\b", "\x7f"):
                    if self._pending_command_chars:
                        self._pending_command_chars.pop()
                elif char >= " ":
                    self._pending_command_chars.append(char)

        def _commit_pending_command(self) -> None:
            command = "".join(self._pending_command_chars).strip()
            self._pending_command_chars.clear()
            if command and self._command_recorder is not None:
                self._command_recorder(command)

        def append_output(self, message: str) -> None:
            message = self._normalize_output_newlines(message)
            if self._pyte_stream is not None:
                self._pyte_stream.feed(message)
                self._render_pyte_buffer()
                return

            index = 0
            while index < len(message):
                char = message[index]

                if char == "\x1b":
                    consumed = self._apply_escape_sequence(message, index)
                    if consumed > index:
                        index = consumed
                        continue

                if char == "\r":
                    self._cursor_col = 0
                elif char == "\n":
                    self._cursor_row += 1
                    self._cursor_col = 0
                    self._ensure_line(self._cursor_row)
                elif char in ("\b", "\x7f"):
                    if self._cursor_col > 0:
                        self._cursor_col -= 1
                elif char == "\t":
                    for _ in range(4):
                        self._write_char(" ")
                elif char >= " ":
                    self._write_char(char)
                index += 1

            self._render_buffer()

        def _normalize_output_newlines(self, message: str) -> str:
            normalized: list[str] = []
            previous = self._last_output_char
            for char in message:
                if char == "\n" and previous != "\r":
                    normalized.append("\r")
                normalized.append(char)
                previous = char
            self._last_output_char = previous
            return "".join(normalized)

        def _render_pyte_buffer(self) -> None:
            if self._pyte_screen is None:
                return

            history = getattr(self._pyte_screen, "history", None)
            history_top = list(getattr(history, "top", []))
            cursor_row = len(history_top) + int(self._pyte_screen.cursor.y)
            cursor_col = int(self._pyte_screen.cursor.x)
            display_lines = [
                self._line_to_text(line, cursor_col if index == self._pyte_screen.cursor.y else None)
                for index, line in enumerate(self._pyte_screen.display)
            ]
            all_lines = [self._line_to_text(line) for line in history_top] + display_lines
            lines, cursor_row = self._trim_terminal_lines(all_lines, cursor_row)

            text = "\n".join(lines)
            self.setPlainText(text)

            if not lines:
                lines = [""]

            cursor = self.textCursor()
            cursor.setPosition(self._cursor_position_for_lines(lines, cursor_row, cursor_col))
            self.setTextCursor(cursor)
            self.setCursorWidth(0 if getattr(self._pyte_screen.cursor, "hidden", False) else 2)
            self.ensureCursorVisible()

        def _trim_terminal_lines(self, lines: list[str], cursor_row: int) -> tuple[list[str], int]:
            if not lines:
                return [""], 0

            non_empty_rows = [index for index, line in enumerate(lines) if line.strip()]
            if not non_empty_rows:
                kept = [lines[min(cursor_row, len(lines) - 1)]]
                return kept, 0

            start = min(non_empty_rows[0], cursor_row)
            end = max(non_empty_rows[-1], cursor_row) + 1
            trimmed = lines[start:end]
            return trimmed, cursor_row - start

        def _line_to_text(self, line: Any, preserve_to_column: int | None = None) -> str:
            if isinstance(line, str):
                text = line
            else:
                text = "".join(getattr(cell, "data", str(cell)) for cell in line)
            if preserve_to_column is not None:
                return text[:preserve_to_column].ljust(preserve_to_column)
            return text.rstrip()

        def _cursor_position_for_lines(self, lines: list[str], row: int, column: int) -> int:
            safe_row = max(0, min(row, len(lines) - 1))
            position = 0
            for line in lines[:safe_row]:
                position += len(line) + 1
            return position + min(column, len(lines[safe_row]))

        def _apply_escape_sequence(self, message: str, index: int) -> int:
            if index + 1 >= len(message) or message[index + 1] != "[":
                return index

            end = index + 2
            while end < len(message) and not ("@" <= message[end] <= "~"):
                end += 1
            if end >= len(message):
                return index

            command = message[end]
            raw_params = message[index + 2 : end]
            params = [part for part in raw_params.split(";") if part]
            count = 1
            if params and params[0].isdigit():
                count = max(1, int(params[0]))

            if command == "D":
                self._cursor_col = max(0, self._cursor_col - count)
            elif command == "C":
                self._cursor_col += count
                self._ensure_column(self._cursor_row, self._cursor_col)
            elif command == "K":
                mode = params[0] if params else "0"
                if mode == "2":
                    self._buffer_lines[self._cursor_row] = []
                    self._cursor_col = 0
                elif mode == "1":
                    self._buffer_lines[self._cursor_row] = self._buffer_lines[self._cursor_row][self._cursor_col :]
                    self._cursor_col = 0
                else:
                    self._buffer_lines[self._cursor_row] = self._buffer_lines[self._cursor_row][: self._cursor_col]
            elif command == "P":
                self._delete_chars(self._cursor_row, self._cursor_col, count)

            return end + 1

        def _ensure_line(self, row: int) -> None:
            while row >= len(self._buffer_lines):
                self._buffer_lines.append([])

        def _ensure_column(self, row: int, column: int) -> None:
            self._ensure_line(row)
            line = self._buffer_lines[row]
            while len(line) < column:
                line.append(" ")

        def _write_char(self, char: str) -> None:
            self._ensure_column(self._cursor_row, self._cursor_col)
            line = self._buffer_lines[self._cursor_row]
            if self._cursor_col < len(line):
                line[self._cursor_col] = char
            else:
                line.append(char)
            self._cursor_col += 1

        def _delete_chars(self, row: int, start: int, count: int) -> None:
            self._ensure_line(row)
            line = self._buffer_lines[row]
            if start >= len(line):
                return
            del line[start : start + count]

        def _render_buffer(self) -> None:
            text = "\n".join("".join(line) for line in self._buffer_lines)
            self.setPlainText(text)

            document = self.document()
            block = document.findBlockByNumber(self._cursor_row)
            if not block.isValid():
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.setTextCursor(cursor)
                self.ensureCursorVisible()
                return

            cursor = self.textCursor()
            cursor.setPosition(block.position() + min(self._cursor_col, len(block.text())))
            self.setTextCursor(cursor)
            self.ensureCursorVisible()

        def set_raw_sender(self, sender: Callable[[str], None]) -> None:
            self._raw_sender = sender

        def set_command_recorder(self, recorder: Callable[[str], None]) -> None:
            self._command_recorder = recorder

        def keyPressEvent(self, event: Any) -> None:  # noqa: N802
            if self._raw_sender is None:
                return super().keyPressEvent(event)

            key = event.key()
            modifiers = event.modifiers()

            if modifiers == (Qt.ControlModifier | Qt.ShiftModifier):
                if key == Qt.Key_C:
                    self.copy()
                    return
                if key == Qt.Key_V:
                    clipboard_text = QApplication.clipboard().text()
                    if clipboard_text:
                        self._record_local_text(clipboard_text)
                        self._forward_text(clipboard_text)
                    return

            if modifiers == Qt.ControlModifier:
                if key == Qt.Key_C:
                    self._forward_text("\x03")
                    return
                if key == Qt.Key_V:
                    clipboard_text = QApplication.clipboard().text()
                    if clipboard_text:
                        self._record_local_text(clipboard_text)
                        self._forward_text(clipboard_text)
                    return
                return super().keyPressEvent(event)

            if modifiers == Qt.ShiftModifier and key == Qt.Key_Insert:
                clipboard_text = QApplication.clipboard().text()
                if clipboard_text:
                    self._record_local_text(clipboard_text)
                    self._forward_text(clipboard_text)
                return

            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._commit_pending_command()
                self._forward_text("\r")
                return
            if key == Qt.Key_Backspace:
                self._record_local_text("\x7f")
                self._forward_text("\x7f")
                return
            if key == Qt.Key_Delete:
                self._forward_text("\x1b[3~")
                return
            if key == Qt.Key_Tab:
                self._forward_text("\t")
                return
            if key == Qt.Key_Left:
                self._forward_text("\x1b[D")
                return
            if key == Qt.Key_Right:
                self._forward_text("\x1b[C")
                return
            if key == Qt.Key_Up:
                self._forward_text("\x1b[A")
                return
            if key == Qt.Key_Down:
                self._forward_text("\x1b[B")
                return
            if key == Qt.Key_Home:
                self._forward_text("\x1b[H")
                return
            if key == Qt.Key_End:
                self._forward_text("\x1b[F")
                return
            if key == Qt.Key_PageUp:
                self._forward_text("\x1b[5~")
                return
            if key == Qt.Key_PageDown:
                self._forward_text("\x1b[6~")
                return

            text = event.text()
            if text:
                self._record_local_text(text)
                self._forward_text(text)
                return
            super().keyPressEvent(event)

    class CommandRecordInput(QPlainTextEdit):
        def __init__(self) -> None:
            super().__init__()
            self._submit_handler: Callable[[str], None] | None = None
            self._enter_sends = False
            self.setObjectName("commandRecordEditor")
            self.setMinimumHeight(132)
            self.setMaximumHeight(180)
            self.setTabChangesFocus(True)
            self.setPlaceholderText("在此输入命令...")

        def set_submit_handler(self, handler: Callable[[str], None]) -> None:
            self._submit_handler = handler

        def set_enter_sends(self, enter_sends: bool) -> None:
            self._enter_sends = enter_sends

        def keyPressEvent(self, event: Any) -> None:  # noqa: N802
            key = event.key()
            modifiers = event.modifiers()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                ctrl_pressed = bool(modifiers & Qt.ControlModifier)
                should_submit = not ctrl_pressed if self._enter_sends else ctrl_pressed
                if should_submit:
                    command = self.toPlainText().strip()
                    if command and self._submit_handler is not None:
                        self._submit_handler(command)
                    return
                self.insertPlainText("\n")
                return
            super().keyPressEvent(event)

    class DeviceDesktopApp(QMainWindow):
        def __init__(self, repository: DeviceRepository | None = None) -> None:
            super().__init__()
            self.repository = repository or create_repository_from_env()
            self.async_loop = AsyncLoopThread()
            self.ui_queue: queue.SimpleQueue[tuple[Callable[..., None], tuple[object, ...]]] = queue.SimpleQueue()
            self.repository_lock = threading.Lock()
            self.search_index: dict[str, str] = {}
            self.devices: list[Device] = []
            self.visible_devices: list[Device] = []
            self.owned_visible_devices: list[Device] = []
            self.selected_device_id = ""
            self.current_user = ""
            self.refresh_generation = 0
            self.closed = False
            self.loading_snapshot = False
            self.recent_device_ids: list[str] = []
            self.command_record_groups: list[dict[str, object]] = [
                {"name": "终端", "content": ""},
            ]
            self.current_command_group = 0
            self.command_record_collapsed = False
            self.command_enter_sends = False
            self.command_tab_buttons: list[QToolButton] = []
            self.command_tab_close_buttons: list[QToolButton] = []
            self.state_path = self.desktop_state_path()
            self.device_tabs_by_id: dict[str, DeviceTabState] = {}
            self.session_tabs_by_id: dict[str, SessionTabState] = {}
            self.next_session_sequence = 1

            self.refresh_timer = QTimer(self)
            self.refresh_timer.setSingleShot(True)
            self.refresh_timer.timeout.connect(self.refresh_snapshot)
            self.state_save_timer = QTimer(self)
            self.state_save_timer.setSingleShot(True)
            self.state_save_timer.timeout.connect(self.save_desktop_state)
            self.ui_timer = QTimer(self)
            self.ui_timer.setInterval(50)
            self.ui_timer.timeout.connect(self._drain_ui_queue)

            self.load_desktop_state()
            self._build_window()
            self._build_layout()
            self._wire_events()
            self.update_controls()
            self.ui_timer.start()
            self.refresh_snapshot()

        def _build_window(self) -> None:
            self.setWindowTitle("设备工作台")
            self.resize(1700, 1000)
            self.setMinimumSize(1360, 860)
            self.setStyleSheet(APP_STYLE)

            status_bar = QStatusBar(self)
            self.setStatusBar(status_bar)
            status_bar.showMessage("准备就绪")

        def _build_layout(self) -> None:
            root = QWidget(self)
            root_layout = QVBoxLayout(root)
            root_layout.setContentsMargins(14, 14, 14, 8)
            root_layout.setSpacing(12)

            splitter = QSplitter(Qt.Horizontal, root)
            root_layout.addWidget(splitter, 1)

            splitter.addWidget(self._build_left_panel())
            splitter.addWidget(self._build_center_panel())
            splitter.setSizes([470, 1180])
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)

            self.setCentralWidget(root)

        def _build_toolbar(self) -> QWidget:
            frame = QFrame()
            frame.setObjectName("toolbarFrame")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(18, 14, 18, 14)
            layout.setSpacing(12)

            title_col = QVBoxLayout()
            title_col.setSpacing(2)
            brand = QLabel("设备运维工作台")
            brand.setObjectName("brandLabel")
            copy = QLabel("资产筛选、占用管理、Telnet / SSH 会话集中在同一个桌面工作区")
            copy.setObjectName("sectionCopy")
            title_col.addWidget(brand)
            title_col.addWidget(copy)
            layout.addLayout(title_col)

            layout.addStretch(1)

            self.toolbar_refresh_button = QPushButton("刷新")
            self.toolbar_refresh_button.setObjectName("ghostButton")
            layout.addWidget(self.toolbar_refresh_button)
            return frame

        def _build_left_panel(self) -> QWidget:
            scroll = QScrollArea()
            scroll.setObjectName("inspectorScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setMinimumWidth(430)
            scroll.setMaximumWidth(520)

            panel = QWidget()
            panel.setObjectName("leftRail")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 8, 0)
            layout.setSpacing(10)

            navigation_group = QGroupBox("设备导航")
            navigation_group.setObjectName("navShell")
            nav_layout = QVBoxLayout(navigation_group)
            nav_layout.setSpacing(10)

            nav_header = QHBoxLayout()
            nav_header.setSpacing(10)
            nav_title_col = QVBoxLayout()
            nav_title_col.setSpacing(2)
            nav_title = QLabel("设备池")
            nav_title.setObjectName("railTitle")
            nav_copy = QLabel("按关键词、领域、状态和 CPU 快速定位目标设备")
            nav_copy.setObjectName("railCopy")
            nav_title_col.addWidget(nav_title)
            nav_title_col.addWidget(nav_copy)
            nav_header.addLayout(nav_title_col, 1)
            self.toolbar_refresh_button = QPushButton("刷新")
            self.toolbar_refresh_button.setObjectName("ghostButton")
            nav_header.addWidget(self.toolbar_refresh_button, 0, Qt.AlignTop)
            nav_layout.addLayout(nav_header)

            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("搜索名称、ID、IP、型号")
            nav_layout.addWidget(self.search_input)

            filter_frame = QFrame()
            filter_frame.setObjectName("navFilterBar")
            filter_row = QHBoxLayout(filter_frame)
            filter_row.setContentsMargins(10, 10, 10, 10)
            filter_row.setSpacing(8)
            self.domain_combo = QComboBox()
            self.domain_combo.addItem(ALL_DOMAINS)
            self.status_combo = QComboBox()
            self.status_combo.addItems(FILTERABLE_STATUSES)
            self.cpu_input = QLineEdit()
            self.cpu_input.setPlaceholderText("CPU")
            filter_row.addWidget(self.domain_combo, 1)
            filter_row.addWidget(self.status_combo, 1)
            filter_row.addWidget(self.cpu_input, 1)
            nav_layout.addWidget(filter_frame)

            stats_frame = QFrame()
            stats_frame.setObjectName("navStatsBar")
            stats_layout = QHBoxLayout(stats_frame)
            stats_layout.setContentsMargins(12, 8, 12, 8)
            stats_layout.setSpacing(6)
            self.stats_caption_label = QLabel("筛选结果")
            self.stats_caption_label.setObjectName("sectionCopy")
            self.stats_label = QLabel("设备 0  空闲 0  占用 0  流水线 0  其他 0")
            self.stats_label.setObjectName("navStatsText")
            self.stats_label.setTextFormat(Qt.RichText)
            stats_layout.addWidget(self.stats_caption_label)
            stats_layout.addStretch(1)
            stats_layout.addWidget(self.stats_label)
            nav_layout.addWidget(stats_frame)

            active_filter_frame = QFrame()
            active_filter_frame.setObjectName("activeFilterBar")
            active_filter_layout = QHBoxLayout(active_filter_frame)
            active_filter_layout.setContentsMargins(10, 8, 10, 8)
            active_filter_layout.setSpacing(8)
            self.filter_summary_label = QLabel("当前显示全部设备")
            self.filter_summary_label.setObjectName("activeFilterText")
            self.filter_summary_label.setTextFormat(Qt.RichText)
            self.filter_summary_label.setWordWrap(True)
            self.clear_filters_button = QPushButton("清空")
            self.clear_filters_button.setObjectName("ghostButton")
            self.clear_filters_button.setEnabled(False)
            active_filter_layout.addWidget(self.filter_summary_label, 1)
            active_filter_layout.addWidget(self.clear_filters_button)
            nav_layout.addWidget(active_filter_frame)

            self.device_table = self._new_table(["设备", "领域", "CPU", "状态"])
            self.device_table.setMinimumHeight(320)
            self.device_table.setMaximumHeight(420)
            nav_layout.addWidget(self.device_table)
            layout.addWidget(navigation_group)
            layout.addWidget(self._build_device_context_panel())
            layout.addStretch(1)
            scroll.setWidget(panel)
            return scroll

        def _build_occupancy_panel(self) -> QWidget:
            frame = QFrame()
            frame.setObjectName("myOccupancyCard")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(8)

            header_row = QHBoxLayout()
            title_col = QVBoxLayout()
            title_col.setSpacing(2)
            title = QLabel("我的占用")
            title.setObjectName("railTitle")
            title_col.addWidget(title)
            header_row.addLayout(title_col)
            header_row.addStretch(1)
            self.owned_count_label = QLabel("0")
            self.owned_count_label.setObjectName("navStatsText")
            header_row.addWidget(self.owned_count_label, 0, Qt.AlignTop)
            layout.addLayout(header_row)

            self.owned_table = self._new_table(["设备", "领域", "状态"])
            self.owned_table.setMinimumHeight(150)
            layout.addWidget(self.owned_table, 1)
            return frame

        def _build_device_context_panel(self) -> QWidget:
            panel = QWidget()
            panel.setObjectName("inspectorRail")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)

            detail_group = QGroupBox("当前设备")
            detail_group.setObjectName("deviceDetailCard")
            detail_layout = QVBoxLayout(detail_group)
            detail_layout.setContentsMargins(12, 16, 12, 12)
            detail_layout.setSpacing(10)
            self.device_summary_card = QLabel("请选择一台设备。")
            self.device_summary_card.setObjectName("detailCard")
            self.device_summary_card.setWordWrap(True)
            self.device_summary_card.setTextFormat(Qt.RichText)
            self.device_summary_card.setTextInteractionFlags(Qt.TextSelectableByMouse)
            detail_layout.addWidget(self.device_summary_card)

            layout.addWidget(detail_group)

            auth_group = QGroupBox("连接参数")
            auth_group.setObjectName("authCard")
            auth_layout = QVBoxLayout(auth_group)
            auth_layout.setSpacing(10)

            device_form_group = QGroupBox("设备 Telnet")
            device_form = QFormLayout(device_form_group)
            device_form.setContentsMargins(10, 14, 10, 10)
            device_form.setVerticalSpacing(8)
            device_form.setHorizontalSpacing(8)
            device_form.setLabelAlignment(Qt.AlignRight)
            self.device_telnet_ip_value = SelectAllLineEdit()
            self.device_username_input = QLineEdit()
            self.device_password_input = QLineEdit()
            device_form.addRow("Telnet IP", self.device_telnet_ip_value)
            device_form.addRow("用户名", self.device_username_input)
            device_form.addRow("密码", self.device_password_input)

            linux_form_group = QGroupBox("Linux SSH")
            linux_form = QFormLayout(linux_form_group)
            linux_form.setContentsMargins(10, 14, 10, 10)
            linux_form.setVerticalSpacing(8)
            linux_form.setHorizontalSpacing(8)
            linux_form.setLabelAlignment(Qt.AlignRight)
            self.device_ssh_ip_value = SelectAllLineEdit()
            self.linux_username_input = QLineEdit()
            self.linux_password_input = QLineEdit()
            linux_form.addRow("SSH IP", self.device_ssh_ip_value)
            linux_form.addRow("用户名", self.linux_username_input)
            linux_form.addRow("密码", self.linux_password_input)

            auth_layout.addWidget(device_form_group)
            auth_layout.addWidget(linux_form_group)
            layout.addWidget(auth_group)
            return panel

        def _build_center_panel(self) -> QWidget:
            panel = QWidget()
            panel.setObjectName("centerStage")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self.center_stage_stack = QStackedLayout()
            self.center_stage_stack.setContentsMargins(0, 0, 0, 0)
            self.center_stage_stack.setStackingMode(QStackedLayout.StackOne)
            layout.addLayout(self.center_stage_stack, 1)

            empty_state = QFrame()
            empty_state.setObjectName("sessionEmptyState")
            empty_layout = QVBoxLayout(empty_state)
            empty_layout.setContentsMargins(44, 36, 44, 36)
            empty_layout.addStretch(1)
            empty_title = QLabel("终端会话工作区")
            empty_title.setObjectName("sessionEmptyTitle")
            empty_copy = QLabel(
                "从左侧选择设备，使用右下角快捷动作发起连接。\n"
                "Telnet / SSH 会话会在这里打开，下方可记录和发送常用命令。"
            )
            empty_copy.setObjectName("sessionEmptyCopy")
            empty_copy.setWordWrap(True)
            empty_layout.addWidget(empty_title, 0, Qt.AlignHCenter)
            empty_layout.addWidget(empty_copy, 0, Qt.AlignHCenter)
            empty_layout.addStretch(1)

            self.session_tab_widget = QTabWidget()
            self.session_tab_widget.setObjectName("sessionTabs")
            self.session_tab_widget.setDocumentMode(True)
            self.session_tab_widget.setTabsClosable(False)
            self.session_tab_widget.setMovable(True)
            self.session_tab_widget.tabBar().setExpanding(False)
            self.session_tab_widget.tabBar().setUsesScrollButtons(True)
            self.center_stage_stack.addWidget(empty_state)
            self.center_stage_stack.addWidget(self.session_tab_widget)
            quick_action_row = QHBoxLayout()
            quick_action_row.setContentsMargins(0, 8, 0, 8)
            quick_action_row.addStretch(1)
            self.quick_telnet_button = QToolButton()
            self.quick_telnet_button.setObjectName("quickActionIconButton")
            self.quick_telnet_button.setText("T")
            self.quick_telnet_button.setToolTip("连接设备 Telnet")
            self.quick_ssh_button = QToolButton()
            self.quick_ssh_button.setObjectName("quickActionIconButton")
            self.quick_ssh_button.setText("S")
            self.quick_ssh_button.setToolTip("连接 Linux SSH")
            self.quick_occupancy_button = QToolButton()
            self.quick_occupancy_button.setObjectName("quickActionIconButton")
            self.quick_occupancy_button.setText("占")
            self.quick_occupancy_button.setToolTip("占用 / 释放")
            self.quick_reconnect_button = QToolButton()
            self.quick_reconnect_button.setObjectName("quickActionIconButton")
            self.quick_reconnect_button.setText("重")
            self.quick_reconnect_button.setToolTip("重连当前会话")
            self.quick_disconnect_button = QToolButton()
            self.quick_disconnect_button.setObjectName("quickActionIconButton")
            self.quick_disconnect_button.setText("断")
            self.quick_disconnect_button.setToolTip("断开当前会话")
            quick_action_row.addWidget(self.quick_telnet_button)
            quick_action_row.addWidget(self.quick_ssh_button)
            quick_action_row.addWidget(self.quick_occupancy_button)
            quick_action_row.addWidget(self.quick_reconnect_button)
            quick_action_row.addWidget(self.quick_disconnect_button)
            layout.addLayout(quick_action_row)
            layout.addWidget(self._build_command_record_panel())
            self.update_center_stage_state()
            return panel

        def _build_right_panel(self) -> QWidget:
            scroll = QScrollArea()
            scroll.setObjectName("inspectorScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setMaximumWidth(410)

            panel = QWidget()
            panel.setObjectName("inspectorRail")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 8, 0)
            layout.setSpacing(10)

            detail_group = QGroupBox("当前设备")
            detail_group.setObjectName("deviceDetailCard")
            detail_layout = QVBoxLayout(detail_group)
            detail_layout.setContentsMargins(12, 16, 12, 12)
            detail_layout.setSpacing(10)
            self.device_summary_card = QLabel("请选择一台设备。")
            self.device_summary_card.setObjectName("detailCard")
            self.device_summary_card.setWordWrap(True)
            self.device_summary_card.setTextFormat(Qt.RichText)
            detail_layout.addWidget(self.device_summary_card)
            layout.addWidget(detail_group)

            action_group = QGroupBox("快捷动作")
            action_group.setObjectName("quickActionCard")
            action_layout = QVBoxLayout(action_group)
            action_layout.setContentsMargins(12, 14, 12, 12)
            action_layout.setSpacing(10)
            self.open_device_button = QPushButton("连接设备 Telnet")
            self.open_device_button.setObjectName("primaryButton")
            self.open_linux_button = QPushButton("连接 Linux SSH")
            self.open_linux_button.setObjectName("primaryButton")
            self.toggle_occupancy_button = QPushButton("占用 / 释放")
            self.toggle_occupancy_button.setObjectName("ghostButton")
            self.open_device_button.setMinimumHeight(40)
            self.open_linux_button.setMinimumHeight(40)
            self.toggle_occupancy_button.setMinimumHeight(38)
            action_layout.addWidget(self.open_device_button)
            action_layout.addWidget(self.open_linux_button)
            action_layout.addWidget(self.toggle_occupancy_button)
            layout.addWidget(action_group)

            auth_group = QGroupBox("连接参数")
            auth_group.setObjectName("authCard")
            auth_layout = QVBoxLayout(auth_group)
            auth_layout.setSpacing(10)

            device_form_group = QGroupBox("设备 Telnet")
            device_form = QFormLayout(device_form_group)
            device_form.setContentsMargins(10, 14, 10, 10)
            device_form.setVerticalSpacing(8)
            device_form.setHorizontalSpacing(8)
            device_form.setLabelAlignment(Qt.AlignRight)
            self.device_username_input = QLineEdit()
            self.device_password_input = QLineEdit()
            device_form.addRow("用户名", self.device_username_input)
            device_form.addRow("密码", self.device_password_input)


            linux_form_group = QGroupBox("Linux SSH")
            linux_form = QFormLayout(linux_form_group)
            linux_form.setContentsMargins(10, 14, 10, 10)
            linux_form.setVerticalSpacing(8)
            linux_form.setHorizontalSpacing(8)
            linux_form.setLabelAlignment(Qt.AlignRight)
            self.linux_username_input = QLineEdit()
            self.linux_password_input = QLineEdit()
            linux_form.addRow("用户名", self.linux_username_input)
            linux_form.addRow("密码", self.linux_password_input)


            auth_layout.addWidget(device_form_group)
            auth_layout.addWidget(linux_form_group)
            layout.addWidget(auth_group)
            layout.addStretch(1)
            scroll.setWidget(panel)
            return scroll

        def _build_command_record_panel(self) -> QWidget:
            frame = QFrame()
            frame.setObjectName("commandRecordDock")
            self.command_record_frame = frame
            frame.setMinimumHeight(196)
            frame.setMaximumHeight(240)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            hint_bar = QFrame()
            hint_bar.setObjectName("commandRecordHintBar")
            hint_bar.setFixedHeight(27)
            hint_layout = QHBoxLayout(hint_bar)
            hint_layout.setContentsMargins(10, 0, 10, 0)
            hint_layout.setSpacing(8)
            self.command_record_hint_label = QLabel("")
            self.command_record_hint_label.setObjectName("commandRecordHint")
            hint_layout.addWidget(self.command_record_hint_label)
            self.command_enter_mode_button = QToolButton()
            self.command_enter_mode_button.setObjectName("commandEnterModeButton")
            self.command_enter_mode_button.setText("↵")
            self.command_enter_mode_button.setToolTip("切换 Enter 行为")
            hint_layout.addWidget(self.command_enter_mode_button)
            hint_layout.addStretch(1)
            self.command_record_toggle_button = QToolButton()
            self.command_record_toggle_button.setObjectName("commandCollapseButton")
            self.command_record_toggle_button.setText("收起")
            hint_layout.addWidget(self.command_record_toggle_button)
            layout.addWidget(hint_bar)

            self.command_record_input = CommandRecordInput()
            self.command_record_input.set_submit_handler(self.submit_command_record_input)
            self.command_record_input.textChanged.connect(self.schedule_desktop_state_save)
            self.update_command_enter_mode()
            layout.addWidget(self.command_record_input)

            footer = QFrame()
            footer.setObjectName("commandRecordFooter")
            self.command_record_footer = footer
            footer.setFixedHeight(29)
            footer_layout = QHBoxLayout(footer)
            footer_layout.setContentsMargins(8, 0, 8, 0)
            footer_layout.setSpacing(4)

            self.command_tab_row = QHBoxLayout()
            self.command_tab_row.setContentsMargins(0, 0, 0, 0)
            self.command_tab_row.setSpacing(2)
            footer_layout.addLayout(self.command_tab_row)
            footer_layout.addStretch(1)

            self.command_broadcast_button = QToolButton()
            self.command_broadcast_button.setObjectName("commandActionButton")
            self.command_broadcast_button.setText("⇄ 广播发送")
            self.command_send_button = QToolButton()
            self.command_send_button.setObjectName("commandActionButton")
            self.command_send_button.setText("▶ 发送到终端")
            self.command_clear_button = QToolButton()
            self.command_clear_button.setObjectName("commandActionButton")
            self.command_clear_button.setText("⌫ 清除")
            footer_layout.addWidget(self.command_broadcast_button)
            footer_layout.addWidget(self.command_send_button)
            footer_layout.addWidget(self.command_clear_button)
            layout.addWidget(footer)

            self.rebuild_command_record_tabs()
            self._load_current_command_content(move_cursor_to_end=False)
            self.apply_command_record_panel_state()
            return frame

        def _section_label(self, text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("sectionTitle")
            return label

        def _new_table(self, headers: list[str]) -> QTableWidget:
            table = CopyableDeviceTable(
                self.copy_selected_table_row,
                self.copy_selected_device_field,
                self,
            )
            table.setColumnCount(len(headers))
            table.setObjectName("deviceTable")
            table.setHorizontalHeaderLabels(headers)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setSelectionMode(QTableWidget.SingleSelection)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.setShowGrid(False)
            table.setItemDelegate(NoFocusItemDelegate(table))
            table.verticalHeader().setVisible(False)
            table.verticalHeader().setDefaultSectionSize(38)
            header = table.horizontalHeader()
            header.setStretchLastSection(False)
            header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.setSectionResizeMode(0, QHeaderView.Stretch)
            for column in range(1, len(headers)):
                header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
            return table

        def _new_stat_chip(self) -> QLabel:
            label = QLabel("-")
            label.setObjectName("statChip")
            label.setTextFormat(Qt.RichText)
            label.setWordWrap(True)
            return label

        def _new_terminal(self) -> QPlainTextEdit:
            terminal = QPlainTextEdit()
            terminal.setObjectName("terminalLog")
            terminal.setReadOnly(True)
            return terminal

        def _wire_events(self) -> None:
            self.search_input.textChanged.connect(self.sync_left_search)
            self.domain_combo.currentTextChanged.connect(self.apply_filters)
            self.status_combo.currentTextChanged.connect(self.apply_filters)
            self.cpu_input.textChanged.connect(self.apply_filters)

            self.toolbar_refresh_button.clicked.connect(self.refresh_snapshot)
            self.clear_filters_button.clicked.connect(self.clear_filters)

            self.device_table.itemSelectionChanged.connect(self.handle_device_table_selected)
            self.device_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.device_table.customContextMenuRequested.connect(self.show_device_table_context_menu)
            if hasattr(self, "owned_table"):
                self.owned_table.itemSelectionChanged.connect(self.handle_owned_table_selected)
                self.owned_table.setContextMenuPolicy(Qt.CustomContextMenu)
                self.owned_table.customContextMenuRequested.connect(self.show_device_table_context_menu)

            self.quick_telnet_button.clicked.connect(self.open_device_session)
            self.quick_ssh_button.clicked.connect(self.open_linux_session)
            self.quick_occupancy_button.clicked.connect(self.toggle_occupancy)
            self.quick_reconnect_button.clicked.connect(self.reconnect_current_session)
            self.quick_disconnect_button.clicked.connect(self.disconnect_current_session)
            self.command_send_button.clicked.connect(self.submit_current_command_record)
            self.command_broadcast_button.clicked.connect(self.broadcast_command_record_input)
            self.command_clear_button.clicked.connect(self.clear_current_command_record)
            self.command_enter_mode_button.clicked.connect(self.toggle_command_enter_mode)
            self.command_record_toggle_button.clicked.connect(self.toggle_command_record_panel)

            self.session_tab_widget.currentChanged.connect(self.handle_session_tab_changed)
            self.session_tab_widget.tabCloseRequested.connect(self.close_device_tab_at_index)

        def sync_left_search(self, value: str) -> None:
            del value
            self.apply_filters()

        def clear_filters(self) -> None:
            self.search_input.clear()
            self.domain_combo.setCurrentText(ALL_DOMAINS)
            self.status_combo.setCurrentText(ALL_STATUS)
            self.cpu_input.clear()
            self.apply_filters()

        @staticmethod
        def desktop_state_path() -> Path:
            configured = os.getenv("DEVICE_TUI_DESKTOP_STATE_PATH", "").strip()
            if configured:
                return Path(configured).expanduser()
            appdata = os.getenv("APPDATA", "").strip()
            if appdata:
                return Path(appdata) / "device_tui" / "desktop_state.json"
            return Path.home() / ".device_tui" / "desktop_state.json"

        @staticmethod
        def default_command_record_groups() -> list[dict[str, object]]:
            return [{"name": "终端", "content": ""}]

        def load_desktop_state(self) -> None:
            try:
                if not self.state_path.exists():
                    return
                payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return
            if not isinstance(payload, dict):
                return

            groups: list[dict[str, object]] = []
            raw_groups = payload.get("command_record_groups", [])
            if isinstance(raw_groups, list):
                for index, item in enumerate(raw_groups, start=1):
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or f"分组 {index}").strip()
                    content = str(item.get("content") or "")
                    groups.append({"name": name or f"分组 {index}", "content": content})
            self.command_record_groups = groups or self.default_command_record_groups()

            try:
                loaded_index = int(payload.get("current_command_group", 0))
            except (TypeError, ValueError):
                loaded_index = 0
            self.current_command_group = min(max(loaded_index, 0), len(self.command_record_groups) - 1)
            self.command_record_collapsed = bool(payload.get("command_record_collapsed", False))
            self.command_enter_sends = bool(payload.get("command_enter_sends", False))

        def schedule_desktop_state_save(self) -> None:
            if hasattr(self, "state_save_timer"):
                self.state_save_timer.start(450)

        def save_desktop_state(self) -> None:
            try:
                self._save_current_command_content()
                payload = {
                    "version": DESKTOP_STATE_VERSION,
                    "command_record_groups": self.command_record_groups,
                    "current_command_group": self.current_command_group_index(),
                    "command_record_collapsed": self.command_record_collapsed,
                    "command_enter_sends": self.command_enter_sends,
                }
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
                temp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temp_path.replace(self.state_path)
            except OSError as exc:
                if self.statusBar() is not None:
                    self.statusBar().showMessage(f"常用命令保存失败: {exc}")

        def submit_command_record_input(self, command: str) -> None:
            self._save_current_command_content()
            self.schedule_desktop_state_save()
            self.send_command_text_to_current_session(command)

        def submit_current_command_record(self) -> None:
            command = self.command_record_input.toPlainText().strip()
            if not command:
                self.set_status_message("请先输入要发送的命令。")
                return
            self.submit_command_record_input(command)

        def send_command_text_to_current_session(self, command: str) -> None:
            state = self.current_session_state()
            if state is None:
                self.set_status_message("命令已记录，当前没有打开的终端会话。")
                return
            self.send_session_text(state.tab_id, self.command_record_payload(command))
            state.terminal.setFocus()

        def broadcast_command_record_input(self) -> None:
            command = self.command_record_input.toPlainText().strip()
            if not command:
                self.set_status_message("请先输入要广播发送的命令。")
                return
            self._save_current_command_content()
            connected_states = [
                state for state in self.session_tabs_by_id.values() if state.session.is_connected
            ]
            if not connected_states:
                self.set_status_message("命令已记录，当前没有已连接的终端会话。")
                return
            payload = self.command_record_payload(command)
            for state in connected_states:
                self.send_session_text(state.tab_id, payload)
            self.set_status_message(f"已广播发送到 {len(connected_states)} 个终端会话。")

        def command_record_payload(self, command: str) -> str:
            normalized = command.replace("\r\n", "\n").replace("\r", "\n")
            payload = normalized.replace("\n", "\r")
            return f"{payload}\r"

        def add_command_record(self, command: str) -> None:
            normalized = command.strip()
            if not normalized:
                return
            self._save_current_command_content()
            records = self.current_command_records()
            if normalized in records:
                return
            group = self.command_record_groups[self.current_command_group_index()]
            content = str(group.get("content", "")).rstrip()
            group["content"] = f"{content}\n{normalized}" if content else normalized
            self._load_current_command_content(move_cursor_to_end=True)
            self.schedule_desktop_state_save()

        def current_command_group_index(self) -> int:
            index = self.current_command_group
            if index < 0 or index >= len(self.command_record_groups):
                return 0
            return index

        def current_command_records(self) -> list[str]:
            group = self.command_record_groups[self.current_command_group_index()]
            content = str(group.get("content", ""))
            return [line.strip() for line in content.splitlines() if line.strip()]

        def rebuild_command_record_tabs(self) -> None:
            while self.command_tab_row.count():
                item = self.command_tab_row.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.command_tab_buttons = []
            self.command_tab_close_buttons = []

            for index, group in enumerate(self.command_record_groups):
                tab_item = QWidget()
                tab_item.setObjectName("commandTabItem")
                tab_layout = QHBoxLayout(tab_item)
                tab_layout.setContentsMargins(0, 0, 2, 0)
                tab_layout.setSpacing(0)

                button = QToolButton()
                button.setObjectName("commandTabButton")
                button.setText(str(group["name"]))
                button.setCheckable(True)
                button.setAutoRaise(True)
                button.clicked.connect(lambda _checked=False, tab_index=index: self.switch_command_group(tab_index))
                self.command_tab_buttons.append(button)
                tab_layout.addWidget(button)

                close_button = QToolButton()
                close_button.setObjectName("commandTabCloseButton")
                close_button.setText("×")
                close_button.setAutoRaise(True)
                close_button.setToolTip("删除页签")
                close_button.clicked.connect(lambda _checked=False, tab_index=index: self.remove_command_group(tab_index))
                self.command_tab_close_buttons.append(close_button)
                tab_layout.addWidget(close_button)
                self.command_tab_row.addWidget(tab_item)

            plus_button = QToolButton()
            plus_button.setObjectName("commandTabButton")
            plus_button.setText("+")
            plus_button.setAutoRaise(True)
            plus_button.clicked.connect(self.add_command_group)
            self.command_tab_row.addWidget(plus_button)
            self.refresh_command_tab_styles()

        def switch_command_group(self, index: int) -> None:
            if index < 0 or index >= len(self.command_record_groups):
                return
            self._save_current_command_content()
            self.current_command_group = index
            self._load_current_command_content(move_cursor_to_end=False)
            self.refresh_command_tab_styles()
            self.schedule_desktop_state_save()

        def add_command_group(self) -> None:
            existing_names = {str(group["name"]) for group in self.command_record_groups}
            next_index = max(len(self.command_record_groups), 1)
            name = f"分组 {next_index}"
            while name in existing_names:
                next_index += 1
                name = f"分组 {next_index}"
            self._save_current_command_content()
            self.command_record_groups.append({"name": name, "content": ""})
            self.rebuild_command_record_tabs()
            self.switch_command_group(len(self.command_record_groups) - 1)
            self.schedule_desktop_state_save()

        def remove_command_group(self, index: int) -> None:
            if len(self.command_record_groups) <= 1:
                self.set_status_message("至少保留一个常用命令页签。")
                return
            if index < 0 or index >= len(self.command_record_groups):
                return
            self._save_current_command_content()
            removed_name = str(self.command_record_groups[index]["name"])
            del self.command_record_groups[index]
            if index < self.current_command_group:
                self.current_command_group -= 1
            elif index == self.current_command_group:
                self.current_command_group = min(index, len(self.command_record_groups) - 1)
            self.rebuild_command_record_tabs()
            self._load_current_command_content(move_cursor_to_end=False)
            self.set_status_message(f"已删除常用命令页签: {removed_name}")
            self.schedule_desktop_state_save()

        def refresh_command_tab_styles(self) -> None:
            for index, button in enumerate(self.command_tab_buttons):
                selected = index == self.current_command_group_index()
                button.setChecked(selected)
                button.setProperty("selected", selected)
                button.style().unpolish(button)
                button.style().polish(button)
                button.update()
                if index < len(self.command_tab_close_buttons):
                    close_button = self.command_tab_close_buttons[index]
                    close_button.setVisible(len(self.command_record_groups) > 1)
                    close_button.setProperty("selected", selected)
                    close_button.style().unpolish(close_button)
                    close_button.style().polish(close_button)
                    close_button.update()

        def _save_current_command_content(self) -> None:
            if not hasattr(self, "command_record_input"):
                return
            self.command_record_groups[self.current_command_group_index()]["content"] = (
                self.command_record_input.toPlainText()
            )

        def _load_current_command_content(self, move_cursor_to_end: bool) -> None:
            if not hasattr(self, "command_record_input"):
                return
            content = str(self.command_record_groups[self.current_command_group_index()].get("content", ""))
            self.command_record_input.setPlainText(content)
            if move_cursor_to_end:
                cursor = self.command_record_input.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.command_record_input.setTextCursor(cursor)

        def clear_current_command_record(self) -> None:
            self.command_record_input.clear()
            self.command_record_groups[self.current_command_group_index()]["content"] = ""
            self.command_record_input.setFocus()
            self.schedule_desktop_state_save()

        def toggle_command_enter_mode(self) -> None:
            self.command_enter_sends = not self.command_enter_sends
            self.update_command_enter_mode()
            message = "Enter 发送，Ctrl+Enter 换行" if self.command_enter_sends else "Enter 换行，Ctrl+Enter 发送"
            self.set_status_message(f"常用命令已切换为: {message}")
            self.schedule_desktop_state_save()

        def update_command_enter_mode(self) -> None:
            if not hasattr(self, "command_record_input"):
                return
            self.command_record_input.set_enter_sends(self.command_enter_sends)
            hint = (
                "</>  常用命令已隐藏"
                if self.command_record_collapsed
                else (
                    "</>  常用命令    Enter: 发送 | Ctrl+Enter: 换行"
                    if self.command_enter_sends
                    else "</>  常用命令    Enter: 换行 | Ctrl+Enter: 发送"
                )
            )
            self.command_record_hint_label.setText(hint)
            self.command_enter_mode_button.setProperty("enterSends", self.command_enter_sends)
            self.command_enter_mode_button.setToolTip(
                "切换为 Ctrl+Enter 发送" if self.command_enter_sends else "切换为 Enter 发送"
            )
            self.command_enter_mode_button.style().unpolish(self.command_enter_mode_button)
            self.command_enter_mode_button.style().polish(self.command_enter_mode_button)
            self.command_enter_mode_button.update()

        def toggle_command_record_panel(self) -> None:
            self._save_current_command_content()
            self.command_record_collapsed = not self.command_record_collapsed
            self.apply_command_record_panel_state()
            self.schedule_desktop_state_save()

        def apply_command_record_panel_state(self) -> None:
            collapsed = self.command_record_collapsed
            self.command_record_input.setVisible(not collapsed)
            self.command_record_footer.setVisible(not collapsed)
            self.command_record_frame.setMinimumHeight(29 if collapsed else 196)
            self.command_record_frame.setMaximumHeight(29 if collapsed else 240)
            self.command_record_toggle_button.setText("展开" if collapsed else "收起")
            self.command_record_hint_label.setText(
                "</>  常用命令已隐藏"
                if collapsed
                else (
                    "</>  常用命令    Enter: 发送 | Ctrl+Enter: 换行"
                    if self.command_enter_sends
                    else "</>  常用命令    Enter: 换行 | Ctrl+Enter: 发送"
                )
            )
            if collapsed:
                self.set_status_message("常用命令区域已隐藏。")
            else:
                self._load_current_command_content(move_cursor_to_end=False)
                self.command_record_input.setFocus()

        def dispatch_ui(self, callback: Callable[..., None], *args: object) -> None:
            self.ui_queue.put((callback, args))

        def _drain_ui_queue(self) -> None:
            while True:
                try:
                    callback, args = self.ui_queue.get_nowait()
                except queue.Empty:
                    break
                callback(*args)

        def run_blocking(
            self,
            work: Callable[[], object],
            on_success: Callable[[object], None] | None = None,
            on_error: Callable[[Exception], None] | None = None,
        ) -> None:
            def task() -> None:
                try:
                    result = work()
                except Exception as exc:
                    self.dispatch_ui(on_error or self.handle_background_error, exc)
                    return
                if on_success is not None:
                    self.dispatch_ui(on_success, result)

            threading.Thread(target=task, daemon=True, name="device-tui-blocking").start()

        def run_coro(
            self,
            coro: Coroutine[Any, Any, Any],
            on_success: Callable[[object], None] | None = None,
            on_error: Callable[[Exception], None] | None = None,
        ) -> None:
            future = self.async_loop.submit(coro)

            def done(completed: Future) -> None:
                try:
                    result = completed.result()
                except Exception as exc:
                    self.dispatch_ui(on_error or self.handle_background_error, exc)
                    return
                if on_success is not None:
                    self.dispatch_ui(on_success, result)

            future.add_done_callback(done)

        def refresh_snapshot(self) -> None:
            if self.loading_snapshot:
                return

            self.loading_snapshot = True
            self.set_status_message("正在刷新设备数据...")
            self.refresh_generation += 1
            generation = self.refresh_generation

            def load_snapshot() -> RepositorySnapshot:
                with self.repository_lock:
                    current_user = self.repository.current_user()
                    devices = self.repository.fetch_devices()
                return RepositorySnapshot(current_user=current_user, devices=devices)

            def apply_snapshot(result: object) -> None:
                snapshot = result
                if not isinstance(snapshot, RepositorySnapshot) or generation != self.refresh_generation:
                    return
                self.loading_snapshot = False
                self.current_user = snapshot.current_user
                self.devices = snapshot.devices
                self.search_index = {device.id: build_search_text(device) for device in self.devices}
                self.refresh_domain_options()
                self.apply_filters()
                self.set_status_message(f"已加载 {len(self.devices)} 台设备")
                self.schedule_next_refresh()

            def handle_error(exc: Exception) -> None:
                self.loading_snapshot = False
                self.handle_background_error(exc)
                self.schedule_next_refresh()

            self.run_blocking(load_snapshot, on_success=apply_snapshot, on_error=handle_error)

        def schedule_next_refresh(self) -> None:
            refresh_seconds = getattr(self.repository, "refresh_interval_seconds", 0.0)
            if refresh_seconds and not self.closed:
                self.refresh_timer.start(int(refresh_seconds * 1000))

        def refresh_domain_options(self) -> None:
            current = self.domain_combo.currentText() or ALL_DOMAINS
            domains = sorted({device.domain for device in self.devices})
            self.domain_combo.blockSignals(True)
            self.domain_combo.clear()
            self.domain_combo.addItems([ALL_DOMAINS, *domains])
            self.domain_combo.setCurrentText(current if current in {ALL_DOMAINS, *domains} else ALL_DOMAINS)
            self.domain_combo.blockSignals(False)

        def apply_filters(self) -> None:
            search_text = self.search_input.text().strip().lower()
            domain_filter = self.domain_combo.currentText().strip()
            status_filter = self.status_combo.currentText().strip()
            cpu_filter = self.cpu_input.text().strip().lower()

            self.visible_devices = []
            for device in self.devices:
                if search_text and search_text not in self.device_search_text(device):
                    continue
                if domain_filter != ALL_DOMAINS and device.domain != domain_filter:
                    continue
                if status_filter != ALL_STATUS and device.status != status_filter:
                    continue
                if cpu_filter and cpu_filter not in device.cpu.lower():
                    continue
                self.visible_devices.append(device)
            self.visible_devices.sort(key=self._device_sort_key)

            self.refresh_filter_summary()
            self.refresh_stats()
            self.refresh_device_table()
            self.refresh_owned_table()
            self.ensure_valid_selection()
            self.refresh_device_context()
            self.refresh_workspace_context()
            self.update_controls()

        def _device_sort_key(self, device: Device) -> tuple[int, int, str]:
            if device.id == self.selected_device_id:
                return (0, 0, device.name.lower())
            if device.id in self.recent_device_ids:
                return (1, self.recent_device_ids.index(device.id), device.name.lower())
            return (2, 0, device.name.lower())

        def refresh_stats(self) -> None:
            total = len(self.visible_devices)
            idle = sum(1 for device in self.visible_devices if device.status == STATUS_IDLE)
            occupied = sum(1 for device in self.visible_devices if device.status == STATUS_OCCUPIED)
            pipeline = sum(1 for device in self.visible_devices if device.status == STATUS_PIPELINE)
            other = sum(1 for device in self.visible_devices if device.status == STATUS_OTHER)
            self.stats_label.setText(
                " ".join(
                    [
                        self.stat_chip_html("设备", total, "#edf5ff"),
                        self.stat_chip_html("空闲", idle, "#8ff7d2"),
                        self.stat_chip_html("占用", occupied, "#fb923c"),
                        self.stat_chip_html("流水线", pipeline, "#fbbf24"),
                        self.stat_chip_html("其他", other, "#a8b5c4"),
                    ]
                )
            )

        def stat_chip_html(self, label: str, value: int, color: str) -> str:
            return (
                f"<span style='color:{color};font-weight:800'>{html.escape(label)} {value}</span>"
            )

        def refresh_device_table(self) -> None:
            keyword = self.search_input.text().strip().lower()
            self.device_table.setRowCount(len(self.visible_devices))
            for row, device in enumerate(self.visible_devices):
                hidden_keyword_match = self.device_matches_hidden_keyword(
                    device,
                    keyword,
                    visible_values=(device.name, device.domain, device.cpu, device.status),
                )
                self._set_table_item(
                    self.device_table,
                    row,
                    0,
                    device.name,
                    device.id,
                    highlight=hidden_keyword_match or self.text_matches_keyword(device.name, keyword),
                )
                self._set_table_item(
                    self.device_table,
                    row,
                    1,
                    device.domain,
                    device.id,
                    highlight=self.text_matches_keyword(device.domain, keyword),
                )
                self._set_table_item(
                    self.device_table,
                    row,
                    2,
                    device.cpu,
                    device.id,
                    highlight=self.text_matches_keyword(device.cpu, keyword),
                )
                self._set_table_item(
                    self.device_table,
                    row,
                    3,
                    device.status,
                    device.id,
                    color=status_color(device.status),
                    highlight=self.text_matches_keyword(device.status, keyword),
                )
                self.device_table.setRowHeight(row, 38)

        def refresh_owned_table(self) -> None:
            if not hasattr(self, "owned_table"):
                self.owned_visible_devices = []
                return
            keyword = self.search_input.text().strip().lower()
            self.owned_visible_devices = [
                device for device in self.visible_devices if device.owner == self.current_user
            ]
            self.owned_count_label.setText(str(len(self.owned_visible_devices)))
            self.owned_table.setRowCount(len(self.owned_visible_devices))
            for row, device in enumerate(self.owned_visible_devices):
                hidden_keyword_match = self.device_matches_hidden_keyword(
                    device,
                    keyword,
                    visible_values=(device.name, device.domain, device.status),
                )
                self._set_table_item(
                    self.owned_table,
                    row,
                    0,
                    device.name,
                    device.id,
                    highlight=hidden_keyword_match or self.text_matches_keyword(device.name, keyword),
                )
                self._set_table_item(
                    self.owned_table,
                    row,
                    1,
                    device.domain,
                    device.id,
                    highlight=self.text_matches_keyword(device.domain, keyword),
                )
                self._set_table_item(
                    self.owned_table,
                    row,
                    2,
                    device.status,
                    device.id,
                    color=status_color(device.status),
                    highlight=self.text_matches_keyword(device.status, keyword),
                )
                self.owned_table.setRowHeight(row, 36)

        def _set_table_item(
            self,
            table: QTableWidget,
            row: int,
            column: int,
            text: str,
            device_id: str,
            color: str | None = None,
            highlight: bool = False,
        ) -> None:
            item = QTableWidgetItem(text)
            item.setData(Qt.UserRole, device_id)
            item.setToolTip(text)
            if color:
                item.setForeground(QBrush(QColor(color)))
            if highlight:
                item.setBackground(QBrush(QColor("#123b36")))
                item.setForeground(QBrush(QColor("#eafff7")))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            table.setItem(row, column, item)

        def text_matches_keyword(self, value: str, keyword: str) -> bool:
            return bool(keyword and keyword in value.lower())

        def device_search_text(self, device: Device) -> str:
            return self.search_index.get(device.id) or build_search_text(device)

        def device_matches_hidden_keyword(
            self,
            device: Device,
            keyword: str,
            visible_values: tuple[str, ...],
        ) -> bool:
            if not keyword or keyword not in self.device_search_text(device):
                return False
            return not any(self.text_matches_keyword(value, keyword) for value in visible_values)

        def get_device_by_id(self, device_id: str) -> Device | None:
            return next((device for device in self.devices if device.id == device_id), None)

        def ensure_valid_selection(self) -> None:
            visible_ids = {device.id for device in self.visible_devices}
            if not self.visible_devices:
                self.selected_device_id = ""
                return
            if self.selected_device_id not in visible_ids:
                self.selected_device_id = self.visible_devices[0].id
            self.select_device_in_table(self.selected_device_id)
            self.sync_auth_fields_from_selected()

        def select_device_in_table(self, device_id: str) -> None:
            self._select_device_row(self.device_table, device_id)
            if hasattr(self, "owned_table"):
                self._select_device_row(self.owned_table, device_id)

        def _select_device_row(self, table: QTableWidget, device_id: str) -> None:
            table.blockSignals(True)
            table.clearSelection()
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and item.data(Qt.UserRole) == device_id:
                    table.selectRow(row)
                    break
            table.blockSignals(False)

        def get_selected_device(self) -> Device | None:
            if not self.selected_device_id:
                return None
            return self.get_device_by_id(self.selected_device_id)

        def _device_id_from_table(self, table: QTableWidget, id_column: int = 0) -> str:
            row = table.currentRow()
            if row < 0:
                return ""
            item = table.item(row, id_column)
            if item is None:
                return ""
            return str(item.data(Qt.UserRole) or "")

        def _device_from_table(self, table: QTableWidget) -> Device | None:
            return self.get_device_by_id(self._device_id_from_table(table, 0))

        def copy_text_to_clipboard(self, text: str, message: str) -> None:
            if not text:
                return
            QApplication.clipboard().setText(text)
            self.set_status_message(message)

        def device_row_copy_text(self, device: Device) -> str:
            return "\t".join([device.name, device.domain, device.cpu, device.status])

        def device_connection_copy_text(self, device: Device) -> str:
            return (
                f"设备: {device.name}\n"
                f"Telnet: {device.telnet_ip}:{device.telnet_port}\n"
                f"SSH: {device.ssh_ip}:{device.ssh_port}\n"
                f"账号: {device.username}\n"
                f"密码: {device.password}"
            )

        def copy_device_field(self, device: Device, field: str) -> None:
            field_map = {
                "name": ("设备名", device.name),
                "ssh_ip": ("SSH IP", device.ssh_ip),
                "ssh_endpoint": ("SSH 地址", f"{device.ssh_ip}:{device.ssh_port}"),
                "telnet_ip": ("Telnet IP", device.telnet_ip),
                "telnet_endpoint": ("Telnet 地址", f"{device.telnet_ip}:{device.telnet_port}"),
                "username": ("账号", device.username),
                "password": ("密码", device.password),
            }
            label, value = field_map[field]
            self.copy_text_to_clipboard(value, f"已复制{label}: {value}")

        def copy_selected_device_field(self, table: QTableWidget, field: str) -> None:
            device = self._device_from_table(table)
            if device is None:
                self.set_status_message("请先选择一台设备。")
                return
            self.copy_device_field(device, field)

        def copy_selected_table_row(self, table: QTableWidget) -> None:
            device = self._device_from_table(table)
            if device is None:
                self.set_status_message("请先选择一台设备。")
                return
            self.copy_text_to_clipboard(self.device_row_copy_text(device), f"已复制设备行: {device.name}")

        def _mark_recent_device(self, device_id: str) -> None:
            if not device_id:
                return
            if device_id in self.recent_device_ids:
                self.recent_device_ids.remove(device_id)
            self.recent_device_ids.insert(0, device_id)
            self.recent_device_ids = self.recent_device_ids[:8]

        def handle_device_table_selected(self) -> None:
            device_id = self._device_id_from_table(self.device_table, 0)
            if not device_id:
                return
            self.activate_device(device_id)

        def handle_owned_table_selected(self) -> None:
            device_id = self._device_id_from_table(self.owned_table, 0)
            if not device_id:
                return
            self.activate_device(device_id)

        def activate_device(self, device_id: str) -> None:
            self.selected_device_id = device_id
            self._mark_recent_device(device_id)
            self.select_device_in_table(device_id)
            self.sync_auth_fields_from_selected()
            self.refresh_device_context()
            self.refresh_workspace_context()
            self.update_controls()

        def refresh_filter_summary(self) -> None:
            active_filters: list[str] = []
            search_text = self.search_input.text().strip()
            domain_filter = self.domain_combo.currentText().strip()
            status_filter = self.status_combo.currentText().strip()
            cpu_filter = self.cpu_input.text().strip()

            if search_text:
                active_filters.append(self.filter_chip_html("关键词", search_text))
            if domain_filter and domain_filter != ALL_DOMAINS:
                active_filters.append(self.filter_chip_html("领域", domain_filter))
            if status_filter and status_filter != ALL_STATUS:
                active_filters.append(self.filter_chip_html("状态", status_filter))
            if cpu_filter:
                active_filters.append(self.filter_chip_html("CPU", cpu_filter))

            has_filters = bool(active_filters)
            summary = " / ".join(active_filters) if has_filters else "当前显示全部设备"
            self.filter_summary_label.setText(summary)
            self.clear_filters_button.setEnabled(has_filters)

        def filter_chip_html(self, label: str, value: str) -> str:
            return (
                f"<span style='color:#8ff7d2;font-weight:700;background:#0f302b;"
                f"padding:2px 6px;border-radius:6px'>{html.escape(label)}: {html.escape(value)}</span>"
            )

        def show_device_table_context_menu(self, pos: Any) -> None:
            table = self.sender()
            if not isinstance(table, QTableWidget):
                table = self.device_table

            item = table.itemAt(pos)
            if item is None:
                return

            device_id = str(item.data(Qt.UserRole) or "")
            if not device_id:
                return

            self.select_device_in_table(device_id)
            self.activate_device(device_id)

            menu = QMenu(table)
            copy_ssh_ip_action = menu.addAction("复制 SSH IP")
            copy_telnet_ip_action = menu.addAction("复制 Telnet IP")
            copy_connection_action = menu.addAction("复制连接信息")
            menu.addSeparator()
            toggle_action = menu.addAction("占用 / 释放")
            menu.addSeparator()
            open_device_action = menu.addAction("打开设备终端")
            open_linux_action = menu.addAction("打开 Linux 后台")

            chosen = menu.exec(table.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            device = self.get_device_by_id(device_id)
            if device is None:
                return
            if chosen == copy_ssh_ip_action:
                self.copy_device_field(device, "ssh_ip")
                return
            if chosen == copy_telnet_ip_action:
                self.copy_device_field(device, "telnet_ip")
                return
            if chosen == copy_connection_action:
                self.copy_text_to_clipboard(
                    self.device_connection_copy_text(device),
                    f"已复制连接信息: {device.name}",
                )
                return
            if chosen == toggle_action:
                self.toggle_occupancy()
                return
            if chosen == open_device_action:
                self.open_device_session()
                return
            if chosen == open_linux_action:
                self.open_linux_session()

        def sync_auth_fields_from_selected(self) -> None:
            device = self.get_selected_device()
            if device is None:
                return
            self.device_telnet_ip_value.setText(device.telnet_ip)
            self.device_username_input.setText(device.username)
            self.device_password_input.setText(device.password)
            self.device_ssh_ip_value.setText(device.ssh_ip)
            self.linux_username_input.setText(device.username)
            self.linux_password_input.setText(device.password)

        def refresh_device_context(self) -> None:
            device = self.get_selected_device()
            if device is None:
                self.device_summary_card.setText("请选择一台设备。")
                self.device_ssh_ip_value.clear()
                self.device_telnet_ip_value.clear()
                return

            self.device_ssh_ip_value.setText(device.ssh_ip)
            self.device_telnet_ip_value.setText(device.telnet_ip)
            self.device_summary_card.setText(
                (
                    f"<div style='font-size:20px;font-weight:800;color:#f8fbff'>{html.escape(device.name)}</div>"
                    f"<div style='margin-top:6px;color:#96a6b8;font-size:12px'>"
                    f"<span style='color:#8ff7d2;font-weight:700'>{html.escape(device.id)}</span>"
                    f" &nbsp;/&nbsp; {html.escape(device.domain)} &nbsp;/&nbsp; {html.escape(device.device_type)}"
                    f"</div>"
                    f"<div style='margin-top:12px;color:#e5edf6;line-height:1.9'>"
                    f"<span style='color:#96a6b8'>当前状态</span>&nbsp;&nbsp;"
                    f"<span style='color:{status_color(device.status)};font-weight:800'>{html.escape(device.status)}</span>"
                    f"</div>"
                    f"<div style='margin-top:14px;padding-top:12px;border-top:1px solid #223244'>"
                    f"<div style='color:#8ea7c2;font-size:12px;font-weight:700'>资产信息</div>"
                    f"<div style='margin-top:8px;color:#e5edf6;line-height:1.9'>"
                    f"<span style='color:#96a6b8'>厂商</span>&nbsp;&nbsp;"
                    f"<span style='font-weight:700'>{html.escape(device.vendor)}</span> / {html.escape(device.model)}<br>"
                    f"<span style='color:#96a6b8'>位置</span>&nbsp;&nbsp;"
                    f"<span style='font-weight:700'>{html.escape(device.site)}</span> / {html.escape(device.rack)}<br>"
                    f"<span style='color:#96a6b8'>版本</span>&nbsp;&nbsp;{html.escape(device.version)}"
                    f"</div>"
                    f"</div>"
                )
            )

        def refresh_workspace_context(self) -> None:
            return

        def handle_session_tab_changed(self, _index: int) -> None:
            self.refresh_workspace_context()
            self._refresh_tab_header_styles()
            state = self.current_session_state()
            if state is not None:
                state.terminal.setFocus()

        def update_center_stage_state(self) -> None:
            if not hasattr(self, "center_stage_stack"):
                return
            self.center_stage_stack.setCurrentIndex(1 if self.session_tab_widget.count() > 0 else 0)

        def current_session_key(self) -> str | None:
            state = self.current_session_state()
            return state.tab_id if state else None

        def current_device_tab_state(self) -> DeviceTabState | None:
            current_page = self.session_tab_widget.currentWidget()
            if current_page is None:
                return None
            return next((state for state in self.device_tabs_by_id.values() if state.page is current_page), None)

        def _device_tab_for_page(self, page: QWidget | None) -> DeviceTabState | None:
            if page is None:
                return None
            return next((state for state in self.device_tabs_by_id.values() if state.page is page), None)

        def _session_state_for_page(self, page: QWidget | None) -> SessionTabState | None:
            if page is None:
                return None
            return next((state for state in self.session_tabs_by_id.values() if state.page is page), None)

        def _session_states_for_device(self, device_id: str) -> list[SessionTabState]:
            return [state for state in self.session_tabs_by_id.values() if state.device_id == device_id]

        def open_device_session(self) -> None:
            device = self.get_selected_device()
            if device is None:
                self.show_warning("请先选择设备。")
                return

            username = self.device_username_input.text().strip()
            password = self.device_password_input.text()
            if not username or not password:
                self.show_warning("设备终端需要用户名和密码。")
                return

            self.ensure_session_tab(
                kind="device",
                device=device,
                host=device.telnet_ip.strip(),
                port=device.telnet_port,
                username=username,
                password=password,
            )

        def open_linux_session(self) -> None:
            device = self.get_selected_device()
            if device is None:
                self.show_warning("请先选择设备。")
                return

            host = device.ssh_ip.strip()
            username = self.linux_username_input.text().strip()
            password = self.linux_password_input.text()
            port = device.ssh_port
            if not host or not username or not password:
                self.show_warning("Linux 后台需要设备 SSH 地址、用户名和密码。")
                return

            self.ensure_session_tab(
                kind="linux",
                device=device,
                host=host,
                port=port,
                username=username,
                password=password,
            )

        def ensure_session_tab(
            self,
            kind: str,
            device: Device,
            host: str,
            port: int,
            username: str,
            password: str,
        ) -> None:
            if not host:
                self.show_warning("目标地址不能为空。")
                return

            device_tab = self.ensure_device_tab(device)
            title = self.next_session_title(device_tab, kind)
            tab_id = self.next_session_tab_id(device.id, kind)
            state = self._create_session_tab(
                tab_id=tab_id,
                kind=kind,
                device=device,
                title=title,
                host=host,
                port=port,
                username=username,
                password=password,
            )
            self.session_tabs_by_id[tab_id] = state
            index = device_tab.session_tab_widget.addTab(state.page, title)
            self._install_session_tab_header(device_tab.session_tab_widget, index, state)
            self.session_tab_widget.setCurrentWidget(device_tab.page)
            device_tab.session_tab_widget.setCurrentIndex(index)
            self.set_status_message(f"正在打开会话: {title}")
            self.update_center_stage_state()
            self.update_controls()
            self.connect_session_tab(tab_id)

        def ensure_device_tab(self, device: Device) -> DeviceTabState:
            existing = self.device_tabs_by_id.get(device.id)
            if existing is not None:
                existing.title = device.name
                if existing.tab_title_label is not None:
                    existing.tab_title_label.setText(device.name)
                index = self.session_tab_widget.indexOf(existing.page)
                if index >= 0:
                    self.session_tab_widget.setCurrentIndex(index)
                    return existing
                self.device_tabs_by_id.pop(device.id, None)

            page = QWidget()
            page.setObjectName("deviceSessionPage")
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            child_tabs = QTabWidget(page)
            child_tabs.setObjectName("deviceSessionTabs")
            child_tabs.setDocumentMode(True)
            child_tabs.setTabsClosable(False)
            child_tabs.setMovable(True)
            child_tabs.tabBar().setExpanding(False)
            child_tabs.tabBar().setUsesScrollButtons(True)
            child_tabs.currentChanged.connect(self.handle_session_tab_changed)
            child_tabs.tabCloseRequested.connect(
                lambda index, device_id=device.id: self.close_child_session_tab_at_index(device_id, index)
            )
            layout.addWidget(child_tabs, 1)

            state = DeviceTabState(
                device_id=device.id,
                title=device.name,
                page=page,
                session_tab_widget=child_tabs,
            )
            self.device_tabs_by_id[device.id] = state
            index = self.session_tab_widget.addTab(page, device.name)
            self._install_device_tab_header(index, state)
            self.session_tab_widget.setCurrentIndex(index)
            self.update_center_stage_state()
            return state

        def next_session_title(self, device_tab: DeviceTabState, kind: str) -> str:
            if kind == "device":
                number = device_tab.next_telnet_index
                device_tab.next_telnet_index += 1
                return f"Telnet #{number}"
            number = device_tab.next_ssh_index
            device_tab.next_ssh_index += 1
            return f"SSH #{number}"

        def next_session_tab_id(self, device_id: str, kind: str) -> str:
            tab_id = f"{device_id}:{kind}:{self.next_session_sequence}"
            self.next_session_sequence += 1
            return tab_id

        def _create_session_tab(
            self,
            tab_id: str,
            kind: str,
            device: Device,
            title: str,
            host: str,
            port: int,
            username: str,
            password: str,
        ) -> SessionTabState:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            terminal = InteractiveTerminal()
            layout.addWidget(terminal, 1)

            if kind == "device":
                session = HuaweiTelnetSession(
                    on_output=lambda message, tab_id=tab_id: self.dispatch_ui(self.append_session_output, tab_id, message),
                    on_status=lambda status, tab_id=tab_id: self.dispatch_ui(self.set_session_status, tab_id, status),
                )
            else:
                session = LinuxSshSession(
                    SessionCallbacks(
                        on_output=lambda message, tab_id=tab_id: self.dispatch_ui(self.append_session_output, tab_id, message),
                        on_status=lambda status, tab_id=tab_id: self.dispatch_ui(self.set_session_status, tab_id, status),
                    )
                )

            state = SessionTabState(
                tab_id=tab_id,
                kind=kind,
                device_id=device.id,
                title=title,
                host=host,
                port=port,
                username=username,
                password=password,
                page=page,
                terminal=terminal,
                session=session,
                connecting=True,
                status_text="Connecting",
            )

            terminal.set_raw_sender(lambda text, tab_id=tab_id: self.send_session_text(tab_id, text))
            terminal.set_command_recorder(self.add_command_record)
            return state

        def _install_device_tab_header(self, index: int, state: DeviceTabState) -> None:
            self._install_tab_header(
                self.session_tab_widget,
                index,
                state,
                close_callback=lambda page=state.page: self.close_device_tab_for_page(page),
                close_tooltip="关闭设备会话",
                min_label_width=118,
            )

        def _install_session_tab_header(self, tab_widget: QTabWidget, index: int, state: SessionTabState) -> None:
            self._install_tab_header(
                tab_widget,
                index,
                state,
                close_callback=lambda page=state.page: self.close_session_tab_for_page(page),
                close_tooltip="关闭会话",
                min_label_width=72,
            )

        def _install_tab_header(
            self,
            tab_widget: QTabWidget,
            index: int,
            state: DeviceTabState | SessionTabState,
            close_callback: Callable[[], None],
            close_tooltip: str,
            min_label_width: int,
        ) -> None:
            if QToolButton is None:
                return
            header = QWidget(tab_widget)
            header.setObjectName("tabHeader")
            header.setFixedHeight(28)
            layout = QHBoxLayout(header)
            layout.setContentsMargins(8, 3, 1, 3)
            layout.setSpacing(5)

            dot = QLabel(header)
            dot.setObjectName("tabStatusDot")
            dot.setFixedSize(10, 10)
            layout.addWidget(dot, 0, Qt.AlignVCenter)

            label = QLabel(state.title, header)
            label.setObjectName("tabHeaderLabel")
            label.setMinimumWidth(min_label_width)
            layout.addWidget(label, 1)

            close_slot = QWidget(tab_widget.tabBar())
            close_slot.setObjectName("tabHeader")
            close_slot.setFixedSize(26, 24)
            close_layout = QHBoxLayout(close_slot)
            close_layout.setContentsMargins(0, 2, 6, 2)
            close_layout.setSpacing(0)

            button = QToolButton(close_slot)
            button.setObjectName("tabCloseButton")
            button.setText("×")
            button.setAutoRaise(True)
            button.setFixedSize(20, 20)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(close_tooltip)
            button.clicked.connect(lambda _checked=False, callback=close_callback: callback())
            close_layout.addWidget(button)

            state.tab_title_label = label
            state.tab_header = header
            state.tab_status_dot = dot
            state.tab_close_button = button
            tab_widget.setTabText(index, "")
            tab_widget.tabBar().setTabButton(index, QTabBar.LeftSide, header)
            tab_widget.tabBar().setTabButton(index, QTabBar.RightSide, close_slot)
            self._refresh_tab_header_styles()

        def _tab_connection_state(self, state: SessionTabState) -> str:
            if state.connecting:
                return "connecting"
            if state.session.is_connected:
                return "connected"
            if state.status_text.lower() == "disconnected":
                return "idle"
            return "error"

        def refresh_session_header(self, state: SessionTabState) -> None:
            del state

        def _device_connection_state(self, state: DeviceTabState) -> str:
            child_states = self._session_states_for_device(state.device_id)
            if any(child.connecting for child in child_states):
                return "connecting"
            if any(child.session.is_connected for child in child_states):
                return "connected"
            if any(self._tab_connection_state(child) == "error" for child in child_states):
                return "error"
            return "idle"

        def _apply_tab_header_style(
            self,
            state: DeviceTabState | SessionTabState,
            selected: bool,
            connection_state: str,
        ) -> None:
            if state.tab_header is not None:
                state.tab_header.setProperty("selected", selected)
                state.tab_header.style().unpolish(state.tab_header)
                state.tab_header.style().polish(state.tab_header)
                state.tab_header.update()
            if state.tab_title_label is not None:
                state.tab_title_label.setProperty("selected", selected)
                state.tab_title_label.style().unpolish(state.tab_title_label)
                state.tab_title_label.style().polish(state.tab_title_label)
                state.tab_title_label.update()
            if state.tab_status_dot is not None:
                state.tab_status_dot.setProperty("connectionState", connection_state)
                state.tab_status_dot.style().unpolish(state.tab_status_dot)
                state.tab_status_dot.style().polish(state.tab_status_dot)
                state.tab_status_dot.update()
            if state.tab_close_button is not None:
                state.tab_close_button.setProperty("selected", selected)
                state.tab_close_button.style().unpolish(state.tab_close_button)
                state.tab_close_button.style().polish(state.tab_close_button)
                state.tab_close_button.update()

        def _refresh_tab_header_styles(self) -> None:
            current_device = self.current_device_tab_state()
            current_device_index = self.session_tab_widget.currentIndex()
            for state in self.device_tabs_by_id.values():
                index = self.session_tab_widget.indexOf(state.page)
                selected = index == current_device_index
                self._apply_tab_header_style(state, selected, self._device_connection_state(state))

            for state in self.session_tabs_by_id.values():
                self.refresh_session_header(state)
                device_tab = self.device_tabs_by_id.get(state.device_id)
                if device_tab is None:
                    continue
                index = device_tab.session_tab_widget.indexOf(state.page)
                selected = device_tab is current_device and index == device_tab.session_tab_widget.currentIndex()
                self._apply_tab_header_style(state, selected, self._tab_connection_state(state))

        def close_session_tab_for_page(self, page: QWidget) -> None:
            state = self._session_state_for_page(page)
            if state is None:
                return
            device_tab = self.device_tabs_by_id.get(state.device_id)
            if device_tab is None:
                return
            index = device_tab.session_tab_widget.indexOf(page)
            if index >= 0:
                self.close_child_session_tab_at_index(device_tab.device_id, index)

        def connect_session_tab(self, tab_id: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return

            state.connecting = True
            self.set_session_status(tab_id, "Connecting")
            self.update_controls()

            async def connect() -> None:
                await state.session.connect(
                    state.host,
                    state.port,
                    state.username,
                    state.password,
                )

            def success(_result: object) -> None:
                current_state = self.session_tabs_by_id.get(tab_id)
                if current_state is None:
                    return
                current_state.connecting = False
                self.set_session_status(tab_id, "Connected")
                self.set_status_message(f"会话已连接: {current_state.title}")
                current_state.terminal.setFocus()

            def failure(exc: Exception) -> None:
                current_state = self.session_tabs_by_id.get(tab_id)
                if current_state is None:
                    return
                current_state.connecting = False
                self.set_session_status(tab_id, "Disconnected")
                if isinstance(exc, (OSError, asyncio.TimeoutError, TelnetSessionError, SessionUnavailableError)):
                    self.append_session_output(tab_id, f"\n连接失败: {exc}\n")
                    if self.is_connection_timeout(exc):
                        self.set_status_message(f"连接超时: {current_state.title}")
                        self.update_controls()
                        return
                    self.show_error(str(exc))
                    self.set_status_message(f"连接失败: {exc}")
                    self.update_controls()
                    return
                self.handle_background_error(exc)

            self.run_coro(connect(), on_success=success, on_error=failure)

        def set_session_status(self, tab_id: str, status: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return
            state.status_text = status
            if status != "Connecting":
                state.connecting = False
            device_tab = self.device_tabs_by_id.get(state.device_id)
            if device_tab is not None:
                index = device_tab.session_tab_widget.indexOf(state.page)
                if index >= 0:
                    device_tab.session_tab_widget.setTabText(index, "")
            if state.tab_title_label is not None:
                state.tab_title_label.setText(state.title)
            self._refresh_tab_header_styles()
            self.refresh_workspace_context()
            self.update_center_stage_state()
            self.update_controls()

        def append_session_output(self, tab_id: str, message: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None or not message:
                return

            state.terminal.append_output(message)

        def send_session_text(self, tab_id: str, text: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return

            if text == "\x7f":
                text = "\x08" if state.kind == "device" else "\x7f"

            async def send() -> None:
                await state.session.send_text(text)

            def failure(exc: Exception) -> None:
                if isinstance(exc, (TelnetSessionError, SessionUnavailableError)):
                    self.show_error(str(exc))
                    return
                self.handle_background_error(exc)

            self.run_coro(send(), on_error=failure)

        def disconnect_session_tab(self, tab_id: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return

            async def disconnect() -> None:
                await state.session.disconnect("Disconnected.")

            def success(_result: object) -> None:
                self.set_session_status(tab_id, "Disconnected")
                self.set_status_message(f"会话已断开: {state.title}")

            self.run_coro(disconnect(), on_success=success)

        def reconnect_session_tab(self, tab_id: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None or state.connecting:
                return

            state.connecting = True
            self.set_session_status(tab_id, "Connecting")
            self.set_status_message(f"正在重连会话: {state.title}")

            async def reconnect() -> None:
                await state.session.disconnect("")
                await state.session.connect(
                    state.host,
                    state.port,
                    state.username,
                    state.password,
                )

            def success(_result: object) -> None:
                current_state = self.session_tabs_by_id.get(tab_id)
                if current_state is None:
                    return
                current_state.connecting = False
                self.set_session_status(tab_id, "Connected")
                current_state.terminal.setFocus()
                self.set_status_message(f"会话已重连: {current_state.title}")

            def failure(exc: Exception) -> None:
                current_state = self.session_tabs_by_id.get(tab_id)
                if current_state is not None:
                    current_state.connecting = False
                    self.set_session_status(tab_id, "Disconnected")
                if isinstance(exc, (OSError, asyncio.TimeoutError, TelnetSessionError, SessionUnavailableError)):
                    self.append_session_output(tab_id, f"\n重连失败: {exc}\n")
                    if self.is_connection_timeout(exc):
                        title = current_state.title if current_state is not None else tab_id
                        self.set_status_message(f"重连超时: {title}")
                        return
                    self.show_error(str(exc))
                    self.set_status_message(f"重连失败: {exc}")
                    return
                self.handle_background_error(exc)

            self.run_coro(reconnect(), on_success=success, on_error=failure)

        def is_connection_timeout(self, exc: Exception) -> bool:
            if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
                return True
            if getattr(exc, "winerror", None) in {121, 10060}:
                return True
            if getattr(exc, "errno", None) in {110, 121, 10060}:
                return True
            message = str(exc).lower()
            return "timed out" in message or "timeout" in message or "超时" in message

        def close_child_session_tab_at_index(self, device_id: str, index: int) -> None:
            device_tab = self.device_tabs_by_id.get(device_id)
            if device_tab is None:
                return
            page = device_tab.session_tab_widget.widget(index)
            state = self._session_state_for_page(page)
            if state is None:
                if index >= 0:
                    device_tab.session_tab_widget.removeTab(index)
                self._remove_device_tab_if_empty(device_tab)
                return

            async def disconnect() -> None:
                await state.session.disconnect("")

            def finalize_close(_result: object | None = None) -> None:
                current_device_tab = self.device_tabs_by_id.get(device_id)
                if current_device_tab is not None:
                    close_index = current_device_tab.session_tab_widget.indexOf(state.page)
                    if close_index >= 0:
                        current_device_tab.session_tab_widget.removeTab(close_index)
                self.session_tabs_by_id.pop(state.tab_id, None)
                state.page.deleteLater()
                if current_device_tab is not None:
                    self._remove_device_tab_if_empty(current_device_tab)
                self.refresh_workspace_context()
                self._refresh_tab_header_styles()
                self.update_controls()

            self.run_coro(disconnect(), on_success=finalize_close, on_error=lambda _exc: finalize_close())

        def close_session_tab_at_index(self, index: int) -> None:
            device_tab = self.current_device_tab_state()
            if device_tab is None:
                return
            self.close_child_session_tab_at_index(device_tab.device_id, index)

        def close_device_tab_for_page(self, page: QWidget) -> None:
            state = self._device_tab_for_page(page)
            if state is not None:
                self.close_device_tab_state(state)

        def close_device_tab_at_index(self, index: int) -> None:
            state = self._device_tab_for_page(self.session_tab_widget.widget(index))
            if state is None:
                if index >= 0:
                    self.session_tab_widget.removeTab(index)
                return
            self.close_device_tab_state(state)

        def close_device_tab_state(self, device_tab: DeviceTabState) -> None:
            child_states = list(self._session_states_for_device(device_tab.device_id))

            async def disconnect_all() -> None:
                await asyncio.gather(
                    *[state.session.disconnect("") for state in child_states],
                    return_exceptions=True,
                )

            def finalize_close(_result: object | None = None) -> None:
                current_device_tab = self.device_tabs_by_id.get(device_tab.device_id)
                if current_device_tab is None:
                    return
                for state in child_states:
                    self.session_tabs_by_id.pop(state.tab_id, None)
                    state.page.deleteLater()
                self._remove_device_tab(current_device_tab)
                self.refresh_workspace_context()
                self._refresh_tab_header_styles()
                self.update_controls()

            if not child_states:
                finalize_close()
                return
            self.run_coro(disconnect_all(), on_success=finalize_close, on_error=lambda _exc: finalize_close())

        def _remove_device_tab_if_empty(self, device_tab: DeviceTabState) -> None:
            if device_tab.session_tab_widget.count() > 0:
                return
            self._remove_device_tab(device_tab)

        def _remove_device_tab(self, device_tab: DeviceTabState) -> None:
            close_index = self.session_tab_widget.indexOf(device_tab.page)
            if close_index >= 0:
                self.session_tab_widget.removeTab(close_index)
            self.device_tabs_by_id.pop(device_tab.device_id, None)
            device_tab.page.deleteLater()
            self.update_center_stage_state()

        def current_session_state(self) -> SessionTabState | None:
            device_tab = self.current_device_tab_state()
            if device_tab is None:
                return None
            return self._session_state_for_page(device_tab.session_tab_widget.currentWidget())

        def reconnect_current_session(self) -> None:
            state = self.current_session_state()
            if state is None:
                self.set_status_message("当前没有可重连的终端会话。")
                return
            self.reconnect_session_tab(state.tab_id)

        def disconnect_current_session(self) -> None:
            state = self.current_session_state()
            if state is None:
                self.set_status_message("当前没有可断开的终端会话。")
                return
            self.disconnect_session_tab(state.tab_id)

        def update_controls(self) -> None:
            selected = self.get_selected_device() is not None
            state = self.current_session_state()
            self.quick_telnet_button.setEnabled(selected)
            self.quick_ssh_button.setEnabled(selected)
            self.quick_occupancy_button.setEnabled(selected)
            self.quick_reconnect_button.setEnabled(state is not None and not state.connecting)
            self.quick_disconnect_button.setEnabled(
                state is not None and (state.session.is_connected or state.connecting)
            )
            self.update_center_stage_state()

        def toggle_occupancy(self) -> None:
            device = self.get_selected_device()
            if device is None:
                self.show_warning("请先选择设备。")
                return
            if not self.current_user:
                self.show_warning("当前用户尚未加载完成。")
                return

            self.set_status_message(f"正在更新设备占用状态: {device.name}")

            def toggle() -> str:
                with self.repository_lock:
                    return self.repository.toggle_device(device.id, self.current_user)

            def done(result: object) -> None:
                self.set_status_message(str(result))
                self.refresh_snapshot()

            self.run_blocking(toggle, on_success=done, on_error=self.handle_toggle_error)

        def handle_toggle_error(self, exc: Exception) -> None:
            if isinstance(exc, RepositoryConflictError):
                self.show_warning(str(exc))
                self.set_status_message(str(exc))
                self.refresh_snapshot()
                return
            self.handle_background_error(exc)

        def set_status_message(self, message: str) -> None:
            if self.statusBar() is not None:
                self.statusBar().showMessage(message)

        def handle_background_error(self, exc: Exception) -> None:
            if isinstance(exc, RepositoryError):
                self.show_error(str(exc))
                self.set_status_message(f"数据加载失败: {exc}")
                self.update_controls()
                return
            self.show_error(f"未处理异常: {exc}")
            self.set_status_message(str(exc))
            self.update_controls()

        def show_warning(self, message: str) -> None:
            QMessageBox.warning(self, "设备工作台", message)

        def show_error(self, message: str) -> None:
            QMessageBox.critical(self, "设备工作台", message)

        def closeEvent(self, event: Any) -> None:  # noqa: N802
            if self.closed:
                event.accept()
                return

            self.closed = True
            self.save_desktop_state()
            self.state_save_timer.stop()
            self.ui_timer.stop()
            self.refresh_timer.stop()

            async def shutdown_sessions() -> None:
                await asyncio.gather(
                    *[state.session.disconnect("") for state in self.session_tabs_by_id.values()],
                    return_exceptions=True,
                )

            try:
                self.async_loop.submit(shutdown_sessions()).result(timeout=3.0)
            except Exception:
                pass
            self.async_loop.stop()
            event.accept()

else:

    class DeviceDesktopApp:  # pragma: no cover - simple placeholder when dependency is absent
        def __init__(self, repository: DeviceRepository | None = None) -> None:
            del repository
            raise RuntimeError("PySide6 is required to launch the desktop app.")


def main() -> None:
    if PYSIDE6_IMPORT_ERROR is not None:
        raise SystemExit(
            "PySide6 is not installed. Run `pip install -e .` or `pip install PySide6` and try again."
        )

    assert QApplication is not None
    app = QApplication.instance() or QApplication([])
    window = DeviceDesktopApp()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
