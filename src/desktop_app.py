from __future__ import annotations

import asyncio
import html
import queue
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

try:
    import pyte
except ModuleNotFoundError:
    pyte = None

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QBrush, QColor, QTextCursor, QTextOption
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFormLayout,
        QFrame,
        QGridLayout,
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
        QSplitter,
        QStackedLayout,
        QStatusBar,
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
    QComboBox = None
    QFormLayout = None
    QFrame = None
    QGridLayout = None
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
    QSplitter = None
    QStackedLayout = None
    QStatusBar = None
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
    font-family: "Noto Sans SC", "Segoe UI", "Microsoft YaHei UI";
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
QLabel#sessionEmptyTitle {
    color: #f8fbff;
    font-size: 24px;
    font-weight: 700;
    font-family: "Bahnschrift", "Noto Sans SC", "Segoe UI", "Microsoft YaHei UI";
}
QLabel#sessionEmptyCopy {
    color: #8ea7c2;
    font-size: 13px;
    line-height: 1.7;
}
QGroupBox#navShell,
QGroupBox#deviceDetailCard,
QGroupBox#quickActionCard,
QGroupBox#authCard,
QGroupBox#statusCard {
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
QGroupBox#authCard,
QGroupBox#statusCard {
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
QGroupBox#authCard QGroupBox {
    background: #0c1218;
    border: 1px solid #273242;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 8px;
}
QGroupBox#authCard QGroupBox::title {
    color: #8ea7c2;
    font-size: 12px;
    font-weight: 600;
}
QGroupBox#statusCard QLabel {
    color: #b8c7d9;
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
    top: -1px;
}
QTabWidget::tab-bar {
    left: 10px;
}
QTabBar::tab {
    background: #101820;
    color: #96a6b8;
    border: 1px solid #253140;
    border-bottom: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    padding: 6px 8px 4px 8px;
    min-width: 136px;
    min-height: 34px;
    margin-right: 6px;
}
QTabBar::tab:selected {
    background: #16212c;
    color: #f8fbff;
    border-color: #0f766e;
}
QTabBar::tab:hover {
    color: #e5edf6;
    background: #16212c;
}
QWidget#tabHeader {
    background: transparent;
}
QWidget#tabHeader[selected="true"] {
    background: transparent;
}
QLabel#tabStatusDot {
    background: #49627d;
    border-radius: 4px;
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
    color: #a8b5c4;
    font-size: 13px;
    font-weight: 600;
}
QLabel#tabHeaderLabel[selected="true"] {
    color: #f8fbff;
    font-weight: 700;
}
QToolButton#tabCloseButton {
    background: rgba(148, 163, 184, 0.14);
    color: #dbe7f5;
    border: 1px solid rgba(148, 163, 184, 0.22);
    border-radius: 8px;
    font-family: "Bahnschrift", "Segoe UI", "Microsoft YaHei UI";
    font-size: 12px;
    font-weight: 700;
    padding: 0px;
}
QToolButton#tabCloseButton[selected="true"] {
    background: rgba(59, 130, 246, 0.16);
    border-color: rgba(96, 165, 250, 0.28);
    color: #f8fbff;
}
QToolButton#tabCloseButton:hover {
    background: #8f2f3a;
    color: #ffffff;
    border-color: #b84351;
}
QToolButton#tabCloseButton:pressed {
    background: #6f232c;
    color: #ffffff;
    border-color: #b84351;
}
QPlainTextEdit#terminalLog {
    background: #05080c;
    color: #8ff7d2;
    border: 1px solid #17443b;
    border-radius: 10px;
    font-family: "Consolas";
    font-size: 14px;
    padding: 12px;
}
QStatusBar {
    background: #0b1117;
    color: #96a6b8;
    border-top: 1px solid #253140;
}
QLabel#brandLabel {
    color: #f8fbff;
    font-size: 24px;
    font-weight: 700;
    font-family: "Bahnschrift", "Noto Sans SC", "Segoe UI", "Microsoft YaHei UI";
}
QLabel#sectionTitle {
    color: #f8fbff;
    font-size: 16px;
    font-weight: 700;
    font-family: "Bahnschrift", "Noto Sans SC", "Segoe UI", "Microsoft YaHei UI";
}
QLabel#sectionCopy {
    color: #96a6b8;
    font-size: 12px;
}
QLabel#navStatsText {
    color: #edf5ff;
    font-size: 14px;
    font-weight: 700;
    font-family: "Bahnschrift", "Noto Sans SC", "Segoe UI", "Microsoft YaHei UI";
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
QLabel#footerMetric {
    color: #96a6b8;
    font-size: 12px;
    font-weight: 600;
    font-family: "Bahnschrift", "Noto Sans SC", "Segoe UI", "Microsoft YaHei UI";
    padding-left: 8px;
    padding-right: 8px;
}
QLabel#railTitle {
    color: #f8fbff;
    font-size: 15px;
    font-weight: 700;
    font-family: "Bahnschrift", "Noto Sans SC", "Segoe UI", "Microsoft YaHei UI";
}
QLabel#railCopy {
    color: #96a6b8;
    font-size: 12px;
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
    return "*" * max(8, len(password))


def status_color(status: str) -> str:
    return STATUS_COLORS.get(status, "#94a3b8")

@dataclass(slots=True)
class RepositorySnapshot:
    current_user: str
    devices: list[Device]


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

    class InteractiveTerminal(QPlainTextEdit):
        DEFAULT_COLUMNS = 160
        DEFAULT_LINES = 40
        DEFAULT_HISTORY = 2000

        def __init__(self) -> None:
            super().__init__()
            self._raw_sender: Callable[[str], None] | None = None
            self._pyte_screen: Any | None = None
            self._pyte_stream: Any | None = None
            self._buffer_lines: list[list[str]] = [[]]
            self._cursor_row = 0
            self._cursor_col = 0
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

        def append_output(self, message: str) -> None:
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

        def _render_pyte_buffer(self) -> None:
            if self._pyte_screen is None:
                return

            history = getattr(self._pyte_screen, "history", None)
            history_top = list(getattr(history, "top", []))
            display_lines = [self._line_to_text(line) for line in self._pyte_screen.display]
            all_lines = [self._line_to_text(line) for line in history_top] + display_lines

            cursor_row = len(history_top) + int(self._pyte_screen.cursor.y)
            cursor_col = int(self._pyte_screen.cursor.x)
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

        def _line_to_text(self, line: Any) -> str:
            if isinstance(line, str):
                return line.rstrip()
            return "".join(getattr(cell, "data", str(cell)) for cell in line).rstrip()

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
                        self._forward_text(clipboard_text)
                    return

            if modifiers == Qt.ControlModifier:
                if key == Qt.Key_C:
                    self._forward_text("\x03")
                    return
                if key == Qt.Key_V:
                    clipboard_text = QApplication.clipboard().text()
                    if clipboard_text:
                        self._forward_text(clipboard_text)
                    return
                return super().keyPressEvent(event)

            if modifiers == Qt.ShiftModifier and key == Qt.Key_Insert:
                clipboard_text = QApplication.clipboard().text()
                if clipboard_text:
                    self._forward_text(clipboard_text)
                return

            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._forward_text("\r")
                return
            if key == Qt.Key_Backspace:
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
                self._forward_text(text)
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
            self.session_tabs_by_id: dict[str, SessionTabState] = {}
            self.session_tabs_by_key: dict[str, str] = {}

            self.refresh_timer = QTimer(self)
            self.refresh_timer.setSingleShot(True)
            self.refresh_timer.timeout.connect(self.refresh_snapshot)
            self.ui_timer = QTimer(self)
            self.ui_timer.setInterval(50)
            self.ui_timer.timeout.connect(self._drain_ui_queue)

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
            self.footer_sessions_label = QLabel("会话 0")
            self.footer_sessions_label.setObjectName("footerMetric")
            self.footer_visible_label = QLabel("设备 0")
            self.footer_visible_label.setObjectName("footerMetric")
            self.footer_user_label = QLabel("用户 -")
            self.footer_user_label.setObjectName("footerMetric")
            self.footer_active_label = QLabel("当前无会话")
            self.footer_active_label.setObjectName("footerMetric")
            status_bar.addPermanentWidget(self.footer_sessions_label)
            status_bar.addPermanentWidget(self.footer_visible_label)
            status_bar.addPermanentWidget(self.footer_user_label)
            status_bar.addPermanentWidget(self.footer_active_label)
            status_bar.showMessage("准备就绪")

        def _build_layout(self) -> None:
            root = QWidget(self)
            root_layout = QVBoxLayout(root)
            root_layout.setContentsMargins(14, 14, 14, 8)
            root_layout.setSpacing(12)
            root_layout.addWidget(self._build_toolbar())

            splitter = QSplitter(Qt.Horizontal, root)
            root_layout.addWidget(splitter, 1)

            splitter.addWidget(self._build_left_panel())
            splitter.addWidget(self._build_center_panel())
            splitter.addWidget(self._build_right_panel())
            splitter.setSizes([390, 940, 380])
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setStretchFactor(2, 0)

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

            self.global_search_input = QLineEdit()
            self.global_search_input.setPlaceholderText("搜索设备、IP、型号、站点")
            self.global_search_input.setMinimumWidth(360)
            self.toolbar_refresh_button = QPushButton("刷新")
            self.toolbar_refresh_button.setObjectName("ghostButton")
            layout.addWidget(self.global_search_input)
            layout.addWidget(self.toolbar_refresh_button)
            return frame

        def _build_left_panel(self) -> QWidget:
            panel = QWidget()
            panel.setObjectName("leftRail")
            panel.setMaximumWidth(430)
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(10)

            navigation_group = QGroupBox("设备导航")
            navigation_group.setObjectName("navShell")
            nav_layout = QVBoxLayout(navigation_group)
            nav_layout.setSpacing(10)

            nav_title = QLabel("设备池")
            nav_title.setObjectName("railTitle")
            nav_copy = QLabel("按关键词、领域、状态和 CPU 快速定位目标设备")
            nav_copy.setObjectName("railCopy")
            nav_layout.addWidget(nav_title)
            nav_layout.addWidget(nav_copy)

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
            stats_layout.addWidget(self.stats_caption_label)
            stats_layout.addStretch(1)
            stats_layout.addWidget(self.stats_label)
            nav_layout.addWidget(stats_frame)

            self.device_table = self._new_table(["设备", "领域", "CPU", "状态"])
            self.device_table.setMinimumHeight(420)
            nav_layout.addWidget(self.device_table, 1)
            layout.addWidget(navigation_group, 3)
            layout.addWidget(self._build_occupancy_panel(), 1)
            return panel

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
            copy = QLabel("随当前筛选结果联动")
            copy.setObjectName("railCopy")
            title_col.addWidget(title)
            title_col.addWidget(copy)
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
                "从左侧选择设备后发起连接。\n"
                "这里会承载你的 Telnet / SSH 会话，设备导航和当前上下文保持在两侧辅助区。"
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
            self.update_center_stage_state()
            return panel

        def _build_right_panel(self) -> QWidget:
            panel = QWidget()
            panel.setObjectName("inspectorRail")
            panel.setMaximumWidth(390)
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
            device_form.setLabelAlignment(Qt.AlignRight)
            self.device_username_input = QLineEdit()
            self.device_password_input = QLineEdit()
            self.device_password_input.setEchoMode(QLineEdit.Password)
            device_form.addRow("用户名", self.device_username_input)
            device_form.addRow("密码", self.device_password_input)


            linux_form_group = QGroupBox("Linux SSH")
            linux_form = QFormLayout(linux_form_group)
            linux_form.setLabelAlignment(Qt.AlignRight)
            self.linux_host_input = QLineEdit()
            self.linux_port_input = QLineEdit("22")
            self.linux_username_input = QLineEdit()
            self.linux_password_input = QLineEdit()
            self.linux_password_input.setEchoMode(QLineEdit.Password)
            linux_form.addRow("主机", self.linux_host_input)
            linux_form.addRow("端口", self.linux_port_input)
            linux_form.addRow("用户名", self.linux_username_input)
            linux_form.addRow("密码", self.linux_password_input)


            auth_layout.addWidget(device_form_group)
            auth_layout.addWidget(linux_form_group)
            layout.addWidget(auth_group)

            footer = QGroupBox("当前状态")
            footer.setObjectName("statusCard")
            footer_layout = QVBoxLayout(footer)
            self.device_status_label = QLabel("设备终端: 无活动会话")
            self.device_status_label.setObjectName("sectionCopy")
            self.linux_status_label = QLabel("Linux 后台: 无活动会话")
            self.linux_status_label.setObjectName("sectionCopy")
            self.active_session_label = QLabel("当前活动: -")
            self.active_session_label.setObjectName("sectionCopy")
            footer_layout.addWidget(self.device_status_label)
            footer_layout.addWidget(self.linux_status_label)
            footer_layout.addWidget(self.active_session_label)
            layout.addWidget(footer)
            layout.addStretch(1)
            return panel

        def _section_label(self, text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("sectionTitle")
            return label

        def _new_table(self, headers: list[str]) -> QTableWidget:
            table = QTableWidget(0, len(headers), self)
            table.setObjectName("deviceTable")
            table.setHorizontalHeaderLabels(headers)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setSelectionMode(QTableWidget.SingleSelection)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.setShowGrid(False)
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
            self.global_search_input.textChanged.connect(self.sync_global_search)
            self.search_input.textChanged.connect(self.sync_left_search)
            self.domain_combo.currentTextChanged.connect(self.apply_filters)
            self.status_combo.currentTextChanged.connect(self.apply_filters)
            self.cpu_input.textChanged.connect(self.apply_filters)

            self.toolbar_refresh_button.clicked.connect(self.refresh_snapshot)

            self.device_table.itemSelectionChanged.connect(self.handle_device_table_selected)
            self.device_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.device_table.customContextMenuRequested.connect(self.show_device_table_context_menu)
            self.owned_table.itemSelectionChanged.connect(self.handle_owned_table_selected)
            self.owned_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.owned_table.customContextMenuRequested.connect(self.show_device_table_context_menu)

            self.open_device_button.clicked.connect(self.open_device_session)
            self.open_linux_button.clicked.connect(self.open_linux_session)
            self.toggle_occupancy_button.clicked.connect(self.toggle_occupancy)

            self.session_tab_widget.currentChanged.connect(self.handle_session_tab_changed)
            self.session_tab_widget.tabCloseRequested.connect(self.close_session_tab_at_index)

        def sync_global_search(self, value: str) -> None:
            if self.search_input.text() != value:
                self.search_input.setText(value)

        def sync_left_search(self, value: str) -> None:
            if self.global_search_input.text() != value:
                self.global_search_input.setText(value)
            self.apply_filters()

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
                self.footer_user_label.setText(f"用户 {self.current_user}")
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
                if search_text and search_text not in self.search_index.get(device.id, ""):
                    continue
                if domain_filter != ALL_DOMAINS and device.domain != domain_filter:
                    continue
                if status_filter != ALL_STATUS and device.status != status_filter:
                    continue
                if cpu_filter and cpu_filter not in device.cpu.lower():
                    continue
                self.visible_devices.append(device)
            self.visible_devices.sort(key=self._device_sort_key)

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
                f"设备 {total}  空闲 {idle}  占用 {occupied}  流水线 {pipeline}  其他 {other}"
            )

        def refresh_device_table(self) -> None:
            self.device_table.setRowCount(len(self.visible_devices))
            for row, device in enumerate(self.visible_devices):
                self._set_table_item(self.device_table, row, 0, device.name, device.id)
                self._set_table_item(self.device_table, row, 1, device.domain, device.id)
                self._set_table_item(self.device_table, row, 2, device.cpu, device.id)
                self._set_table_item(self.device_table, row, 3, device.status, device.id, color=status_color(device.status))
                self.device_table.setRowHeight(row, 38)

        def refresh_owned_table(self) -> None:
            self.owned_visible_devices = [
                device for device in self.visible_devices if device.owner == self.current_user
            ]
            self.owned_count_label.setText(str(len(self.owned_visible_devices)))
            self.owned_table.setRowCount(len(self.owned_visible_devices))
            for row, device in enumerate(self.owned_visible_devices):
                self._set_table_item(self.owned_table, row, 0, device.name, device.id)
                self._set_table_item(self.owned_table, row, 1, device.domain, device.id)
                self._set_table_item(self.owned_table, row, 2, device.status, device.id, color=status_color(device.status))
                self.owned_table.setRowHeight(row, 36)

        def _set_table_item(
            self,
            table: QTableWidget,
            row: int,
            column: int,
            text: str,
            device_id: str,
            color: str | None = None,
        ) -> None:
            item = QTableWidgetItem(text)
            item.setData(Qt.UserRole, device_id)
            item.setToolTip(text)
            if color:
                item.setForeground(QBrush(QColor(color)))
            table.setItem(row, column, item)

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
            toggle_action = menu.addAction("占用 / 释放")
            menu.addSeparator()
            open_device_action = menu.addAction("打开设备终端")
            open_linux_action = menu.addAction("打开 Linux 后台")

            chosen = menu.exec(table.viewport().mapToGlobal(pos))
            if chosen is None:
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
            self.device_username_input.setText(device.username)
            self.device_password_input.setText(device.password)
            self.linux_host_input.setText(device.ssh_ip)
            self.linux_username_input.setText(device.username)

        def refresh_device_context(self) -> None:
            device = self.get_selected_device()
            if device is None:
                self.device_summary_card.setText("请选择一台设备。")
                return

            owner = device.owner or "未占用"
            protocol_hint = "Telnet 优先" if device.telnet_ip else "SSH 优先"
            self.device_summary_card.setText(
                (
                    f"<div style='font-size:19px;font-weight:700;color:#f8fbff'>{html.escape(device.name)}</div>"
                    f"<div style='margin-top:6px;color:#96a6b8;font-size:12px'>"
                    f"{html.escape(device.id)} &nbsp;/&nbsp; {html.escape(device.domain)} &nbsp;/&nbsp; {html.escape(device.device_type)}"
                    f"</div>"
                    f"<div style='margin-top:10px'>"
                    f"<span style='display:inline-block;padding:4px 10px;border-radius:10px;background:#111827;"
                    f"color:{status_color(device.status)};font-weight:700'>{html.escape(device.status)}</span>"
                    f"<span style='display:inline-block;margin-left:8px;padding:4px 10px;border-radius:10px;"
                    f"background:#0f161d;color:#e5edf6'>占用 {html.escape(owner)}</span>"
                    f"<span style='display:inline-block;margin-left:8px;padding:4px 10px;border-radius:10px;"
                    f"background:#10251f;color:#8ff7d2'>{html.escape(protocol_hint)}</span>"
                    f"</div>"
                    f"<div style='margin-top:14px;color:#e5edf6;line-height:1.85'>"
                    f"<span style='color:#96a6b8'>SSH</span>&nbsp;&nbsp;{html.escape(device.ssh_ip)}:{device.ssh_port}<br>"
                    f"<span style='color:#96a6b8'>Telnet</span>&nbsp;&nbsp;{html.escape(device.telnet_ip)}:{device.telnet_port}<br>"
                    f"<span style='color:#96a6b8'>账号</span>&nbsp;&nbsp;{html.escape(device.username)} / {html.escape(mask_password(device.password))}<br>"
                    f"<span style='color:#96a6b8'>厂商</span>&nbsp;&nbsp;{html.escape(device.vendor)} / {html.escape(device.model)}<br>"
                    f"<span style='color:#96a6b8'>位置</span>&nbsp;&nbsp;{html.escape(device.site)} / {html.escape(device.rack)}<br>"
                    f"<span style='color:#96a6b8'>版本</span>&nbsp;&nbsp;{html.escape(device.version)}"
                    f"</div>"
                )
            )

        def refresh_workspace_context(self) -> None:
            state = self.current_session_state()

            if state is None:
                self.active_session_label.setText("当前活动: -")
                self.footer_active_label.setText("当前无会话")
                return

            device_obj = self.get_device_by_id(state.device_id)
            owner = device_obj.owner if device_obj and device_obj.owner else "未占用"
            protocol = "Telnet" if state.kind == "device" else "SSH"
            self.active_session_label.setText(
                f"当前活动: {state.title} / {protocol} / {owner} / {state.status_text}"
            )
            self.footer_active_label.setText(f"当前 {state.title}")

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

        def make_session_key(self, kind: str, device_id: str) -> str:
            return f"{kind}:{device_id}"

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

            host = self.linux_host_input.text().strip()
            username = self.linux_username_input.text().strip()
            password = self.linux_password_input.text()
            port_text = self.linux_port_input.text().strip() or "22"
            if not host or not username or not password:
                self.show_warning("Linux 后台需要主机、用户名和密码。")
                return
            try:
                port = int(port_text)
            except ValueError:
                self.show_warning("Linux 端口必须是数字。")
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

            key = self.make_session_key(kind, device.id)
            existing_tab_id = self.session_tabs_by_key.get(key)
            if existing_tab_id and existing_tab_id in self.session_tabs_by_id:
                state = self.session_tabs_by_id[existing_tab_id]
                self.session_tab_widget.setCurrentWidget(state.page)
                state.terminal.setFocus()
                return

            title = f"{device.name}-{'Telnet' if kind == 'device' else 'SSH'}"
            tab_id = key
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
            self.session_tabs_by_key[key] = tab_id
            index = self.session_tab_widget.addTab(state.page, title)
            self._install_tab_header(index, state)
            self.session_tab_widget.setCurrentIndex(index)
            self.set_status_message(f"正在打开会话: {title}")
            self.update_controls()
            self.connect_session_tab(tab_id)

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
            return state

        def _install_tab_header(self, index: int, state: SessionTabState) -> None:
            if QToolButton is None:
                return
            header = QWidget(self.session_tab_widget)
            header.setObjectName("tabHeader")
            header.setFixedHeight(24)
            layout = QHBoxLayout(header)
            layout.setContentsMargins(8, 2, 4, 2)
            layout.setSpacing(6)

            dot = QLabel(header)
            dot.setObjectName("tabStatusDot")
            dot.setFixedSize(8, 8)
            layout.addWidget(dot, 0, Qt.AlignVCenter)

            label = QLabel(state.title, header)
            label.setObjectName("tabHeaderLabel")
            layout.addWidget(label, 1)

            button = QToolButton(header)
            button.setObjectName("tabCloseButton")
            button.setText("x")
            button.setAutoRaise(True)
            button.setFixedSize(18, 18)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip("关闭会话")
            button.clicked.connect(lambda _checked=False, page=state.page: self.close_session_tab_for_page(page))
            layout.addWidget(button)

            state.tab_title_label = label
            state.tab_header = header
            state.tab_status_dot = dot
            state.tab_close_button = button
            self.session_tab_widget.setTabText(index, "")
            self.session_tab_widget.tabBar().setTabButton(index, QTabBar.LeftSide, header)
            self.session_tab_widget.tabBar().setTabButton(index, QTabBar.RightSide, None)
            self._refresh_tab_header_styles()

        def _tab_connection_state(self, state: SessionTabState) -> str:
            if state.connecting:
                return "connecting"
            if state.session.is_connected:
                return "connected"
            if state.status_text.lower() == "disconnected":
                return "idle"
            return "error"

        def _refresh_tab_header_styles(self) -> None:
            current_index = self.session_tab_widget.currentIndex()
            for state in self.session_tabs_by_id.values():
                if state.tab_title_label is None:
                    continue
                index = self.session_tab_widget.indexOf(state.page)
                selected = index == current_index
                connection_state = self._tab_connection_state(state)
                if state.tab_header is not None:
                    state.tab_header.setProperty("selected", selected)
                    state.tab_header.style().unpolish(state.tab_header)
                    state.tab_header.style().polish(state.tab_header)
                    state.tab_header.update()
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

        def close_session_tab_for_page(self, page: QWidget) -> None:
            index = self.session_tab_widget.indexOf(page)
            if index >= 0:
                self.close_session_tab_at_index(index)

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
                self.set_status_message(f"会话已连接: {current_state.title}")
                current_state.terminal.setFocus()
                self.update_controls()

            def failure(exc: Exception) -> None:
                current_state = self.session_tabs_by_id.get(tab_id)
                if current_state is None:
                    return
                current_state.connecting = False
                self.set_session_status(tab_id, "Disconnected")
                if isinstance(exc, (OSError, asyncio.TimeoutError, TelnetSessionError, SessionUnavailableError)):
                    self.append_session_output(tab_id, f"\n连接失败: {exc}\n")
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
            index = self.session_tab_widget.indexOf(state.page)
            if index >= 0:
                self.session_tab_widget.setTabText(index, "")
            if state.tab_title_label is not None:
                state.tab_title_label.setText(state.title)
            self._refresh_tab_header_styles()
            self.refresh_workspace_context()
            self.refresh_summary_statuses()
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

        def close_session_tab_at_index(self, index: int) -> None:
            page = self.session_tab_widget.widget(index)
            state = next((item for item in self.session_tabs_by_id.values() if item.page is page), None)
            if state is None:
                self.session_tab_widget.removeTab(index)
                return

            async def disconnect() -> None:
                await state.session.disconnect("")

            def finalize_close(_result: object | None = None) -> None:
                close_index = self.session_tab_widget.indexOf(state.page)
                if close_index >= 0:
                    self.session_tab_widget.removeTab(close_index)
                self.session_tabs_by_id.pop(state.tab_id, None)
                self.session_tabs_by_key.pop(self.make_session_key(state.kind, state.device_id), None)
                state.page.deleteLater()
                self.refresh_workspace_context()
                self.refresh_summary_statuses()
                self.update_controls()

            self.run_coro(disconnect(), on_success=finalize_close, on_error=lambda _exc: finalize_close())

        def refresh_summary_statuses(self) -> None:
            device_states = [
                state for state in self.session_tabs_by_id.values() if state.kind == "device"
            ]
            linux_states = [
                state for state in self.session_tabs_by_id.values() if state.kind == "linux"
            ]
            if device_states:
                active = next((state for state in device_states if state.session.is_connected), device_states[-1])
                self.device_status_label.setText(f"设备终端: {active.title} / {active.status_text}")
            else:
                self.device_status_label.setText("设备终端: 无活动会话")

            if linux_states:
                active = next((state for state in linux_states if state.session.is_connected), linux_states[-1])
                self.linux_status_label.setText(f"Linux 后台: {active.title} / {active.status_text}")
            else:
                self.linux_status_label.setText("Linux 后台: 无活动会话")

        def current_session_state(self) -> SessionTabState | None:
            current_page = self.session_tab_widget.currentWidget()
            if current_page is None:
                return None
            return next((state for state in self.session_tabs_by_id.values() if state.page is current_page), None)

        def update_controls(self) -> None:
            selected = self.get_selected_device() is not None
            self.open_device_button.setEnabled(selected)
            self.open_linux_button.setEnabled(selected)
            self.toggle_occupancy_button.setEnabled(selected)
            self.footer_sessions_label.setText(f"会话 {len(self.session_tabs_by_id)}")
            self.footer_visible_label.setText(f"设备 {len(self.visible_devices)}")
            self.refresh_summary_statuses()
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
