from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import os
import queue
import re
import shutil
import threading
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import CancelledError as FutureCancelledError, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import pyte
except ModuleNotFoundError:
    pyte = None

try:
    from PySide6.QtCore import (
        QEasingCurve,
        QEvent,
        QMimeData,
        QParallelAnimationGroup,
        QPropertyAnimation,
        QSize,
        QTimer,
        Qt,
        QUrl,
        QVariantAnimation,
    )
    from PySide6.QtGui import (
        QBrush,
        QColor,
        QDesktopServices,
        QDrag,
        QIcon,
        QKeySequence,
        QPainter,
        QPen,
        QPixmap,
        QTextBlockFormat,
        QSyntaxHighlighter,
        QTextCharFormat,
        QTextCursor,
        QTextOption,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QInputDialog,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSplitter,
        QSizePolicy,
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
    QDesktopServices = None
    QDrag = None
    QEasingCurve = None
    QEvent = None
    QFileDialog = None
    QIcon = None
    QInputDialog = None
    QMimeData = None
    QKeySequence = None
    QParallelAnimationGroup = None
    QPainter = None
    QPen = None
    QPixmap = None
    QPropertyAnimation = None
    QTextBlockFormat = None
    QSyntaxHighlighter = None
    QTextCharFormat = None
    QUrl = None
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
    QSizePolicy = None
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
    QVariantAnimation = None
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
    from .styles import APP_STYLE
    from .helpers import build_search_text, mask_password, status_color
    from .app_state import RepositorySnapshot, DeviceTabState, SessionTabState
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
    from styles import APP_STYLE
    from helpers import build_search_text, mask_password, status_color
    from app_state import RepositorySnapshot, DeviceTabState, SessionTabState
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
DESKTOP_STATE_VERSION = 3
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SESSION_TAB_MIME = "application/x-device-tui-session-tab"


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

    async def _cancel_pending_tasks(self) -> None:
        current = asyncio.current_task(self._loop)
        tasks = [task for task in asyncio.all_tasks(self._loop) if task is not current and not task.done()]
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def cancel_pending(self, timeout: float = 2.0) -> None:
        if not self._loop.is_running():
            return
        try:
            self.submit(self._cancel_pending_tasks()).result(timeout=timeout)
        except Exception:
            pass

    def stop(self) -> None:
        self.cancel_pending(timeout=1.0)
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

    class TerminalSyntaxHighlighter(QSyntaxHighlighter):
        ANSI_COLORS = {
            "black": "#64748b",
            "red": "#f87171",
            "green": "#5eead4",
            "yellow": "#fbbf24",
            "blue": "#7dd3fc",
            "magenta": "#c4b5fd",
            "cyan": "#67e8f9",
            "white": "#d6deeb",
            "brightblack": "#94a3b8",
            "brightred": "#fca5a5",
            "brightgreen": "#99f6e4",
            "brightyellow": "#fde68a",
            "brightblue": "#bae6fd",
            "brightmagenta": "#ddd6fe",
            "brightcyan": "#a5f3fc",
            "brightwhite": "#f8fafc",
        }
        BRACKET_OUTPUT_LABELS = {
            "debug",
            "device",
            "error",
            "fail",
            "failed",
            "fatal",
            "info",
            "linux",
            "notice",
            "ok",
            "success",
            "system",
            "trace",
            "warn",
            "warning",
        }
        IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b")
        PATH_RE = re.compile(r"(?<!\w)(?:/[\w.\-]+(?:/[\w.\-]+)+|[A-Za-z]:\\[^\s]+)")
        TOKEN_RE = re.compile(r"\b(?:V\d+(?:R\d+)?(?:C\d+)?|ARM-\d+|\d+ms|\d+%)\b")
        HUAWEI_PRODUCT_RE = re.compile(r"^(Huawei)\s+(.+?\sSoftware)$")
        LS_LONG_RE = re.compile(
            r"^(\s*)([bcdlps-][rwxXsStT-]{9}[+.]?)\s+(\d+)\s+(\S+)\s+(\S+)\s+"
            r"(\d+(?:[.,]\d+)?[KMGTPE]?|[0-9]+)\s+"
            r"(\S+\s+\d+\s+(?:\d{1,2}:\d{2}|\d{4}))\s+(.+)$"
        )
        WORD_TOKEN_RE = re.compile(r"(?<!\S)(\S+)(?!\S)")
        DIRECTORY_NAMES = {
            "bin",
            "boot",
            "build",
            "conf",
            "config",
            "data",
            "dev",
            "doc",
            "docs",
            "etc",
            "home",
            "lib",
            "lib64",
            "log",
            "logs",
            "mnt",
            "opt",
            "proc",
            "root",
            "run",
            "sbin",
            "src",
            "sys",
            "tmp",
            "usr",
            "var",
        }
        ARCHIVE_EXTENSIONS = {
            ".7z",
            ".bz2",
            ".gz",
            ".rar",
            ".tar",
            ".tgz",
            ".xz",
            ".zip",
        }
        CODE_EXTENSIONS = {
            ".c",
            ".cc",
            ".cfg",
            ".conf",
            ".cpp",
            ".go",
            ".h",
            ".ini",
            ".json",
            ".log",
            ".md",
            ".py",
            ".sh",
            ".sql",
            ".toml",
            ".txt",
            ".xml",
            ".yaml",
            ".yml",
        }

        def __init__(self, document: Any) -> None:
            super().__init__(document)
            self._prompt_format = self._format("#8aa2b5")
            self._command_format = self._format("#f8fafc")
            self._info_format = self._format("#94a3b8")
            self._success_format = self._format("#5eead4")
            self._warning_format = self._format("#fbbf24")
            self._error_format = self._format("#f87171")
            self._field_label_format = self._format("#8aa2b5")
            self._field_separator_format = self._format("#64748b")
            self._field_value_format = self._format("#cbd5e1")
            self._ip_format = self._format("#7dd3fc")
            self._path_format = self._format("#a7f3d0")
            self._muted_number_format = self._format("#c4b5fd")
            self._directory_format = self._format("#7dd3fc")
            self._file_format = self._format("#d6deeb")
            self._executable_format = self._format("#5eead4")
            self._symlink_format = self._format("#c4b5fd")
            self._archive_format = self._format("#fbbf24")
            self._permission_format = self._format("#94a3b8")
            self._date_format = self._format("#8aa2b5")
            self._ansi_line_formats: list[list[tuple[int, int, str, str, bool, bool]]] = []
            self._ansi_format_cache: dict[tuple[str, str, bool, bool], QTextCharFormat] = {}

        def set_ansi_line_formats(
            self,
            line_formats: list[list[tuple[int, int, str, str, bool, bool]]],
        ) -> None:
            self._ansi_line_formats = line_formats

        def clear_ansi_line_formats(self) -> None:
            self._ansi_line_formats = []

        def highlightBlock(self, text: str) -> None:  # noqa: N802
            stripped = text.lstrip()
            leading_spaces = len(text) - len(stripped)
            if not stripped:
                self._highlight_ansi_line()
                return

            prompt_end = self._prompt_end_index(text)
            if prompt_end > 0:
                self.setFormat(0, prompt_end, self._prompt_format)
                if len(text) > prompt_end:
                    self.setFormat(prompt_end, len(text) - prompt_end, self._command_format)
                self._highlight_ansi_line()
                return

            if self._highlight_device_field(text, stripped, leading_spaces):
                self._highlight_ansi_line()
                return

            self._highlight_status_prefix(stripped, leading_spaces)
            self._highlight_ls_output(text, stripped, leading_spaces)
            self._highlight_inline_tokens(text)
            self._highlight_ansi_line()

        def _prompt_end_index(self, text: str) -> int:
            if text.startswith("<"):
                end = text.find(">")
                return end + 1 if end > 0 else 0
            if text.startswith("["):
                end = text.find("]")
                if end <= 0:
                    return 0
                content = text[1:end].strip()
                rest = text[end + 1 :]
                if self._looks_like_device_prompt(content) and (not rest or not rest[0].isspace()):
                    return end + 1
            return 0

        def _looks_like_device_prompt(self, content: str) -> bool:
            normalized = content.strip()
            if not normalized:
                return False
            plain = normalized.strip("*~").lower()
            if plain in self.BRACKET_OUTPUT_LABELS:
                return False
            if len(normalized) > 48 or not any(char.isalnum() for char in normalized):
                return False
            return all(char.isalnum() or char in {"-", "_", ".", "/", ":", "~", "*"} for char in normalized)

        def _highlight_status_prefix(self, stripped: str, leading_spaces: int) -> None:
            prefix_rules = (
                (("Error:", "ERROR:", "Fatal:", "FATAL:", "错误:", "失败:"), self._error_format),
                (("Warning:", "WARNING:", "Warn:", "WARN:", "告警:", "警告:"), self._warning_format),
                (("OK:", "Success:", "SUCCESS:", "Done:", "DONE:", "成功:"), self._success_format),
                (("Info:", "INFO:", "Notice:", "NOTICE:", "提示:", "信息:"), self._info_format),
            )
            for prefixes, fmt in prefix_rules:
                for prefix in prefixes:
                    if stripped.startswith(prefix):
                        self.setFormat(leading_spaces, len(prefix), fmt)
                        return

            if not stripped.startswith("["):
                return
            end = stripped.find("]")
            if end <= 0 or end > 12:
                return
            label = stripped[1:end].strip().lower()
            bracket_formats = {
                "error": self._error_format,
                "fail": self._error_format,
                "failed": self._error_format,
                "fatal": self._error_format,
                "warn": self._warning_format,
                "warning": self._warning_format,
                "ok": self._success_format,
                "success": self._success_format,
                "info": self._info_format,
                "notice": self._info_format,
            }
            fmt = bracket_formats.get(label)
            if fmt is not None:
                self.setFormat(leading_spaces, end + 1, fmt)

        def _highlight_device_field(self, text: str, stripped: str, leading_spaces: int) -> bool:
            field_prefixes = (
                ("Patch Version", ":"),
                ("Device name", ":"),
                ("Uptime", " is"),
                ("VRP (R) software, Version", " "),
            )
            for label, separator in field_prefixes:
                if not stripped.startswith(label + separator):
                    continue
                label_start = leading_spaces
                label_len = len(label)
                separator_start = label_start + label_len
                value_start = separator_start + len(separator)
                self.setFormat(label_start, label_len, self._field_label_format)
                self.setFormat(separator_start, len(separator), self._field_separator_format)
                if len(stripped) > value_start - leading_spaces:
                    self.setFormat(value_start, len(stripped) - (value_start - leading_spaces), self._field_value_format)
                return True

            product_match = self.HUAWEI_PRODUCT_RE.match(stripped)
            if product_match:
                vendor_start = leading_spaces + product_match.start(1)
                product_start = leading_spaces + product_match.start(2)
                self.setFormat(vendor_start, len(product_match.group(1)), self._field_label_format)
                self.setFormat(product_start, len(product_match.group(2)), self._field_value_format)
                return True
            self._highlight_inline_tokens(text)
            return False

        def _highlight_inline_tokens(self, text: str) -> None:
            if len(text) > 512:
                return
            for match in self.IP_RE.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), self._ip_format)
            for match in self.PATH_RE.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), self._path_format)
            for match in self.TOKEN_RE.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), self._muted_number_format)

        def _highlight_ls_output(self, text: str, stripped: str, leading_spaces: int) -> None:
            long_match = self.LS_LONG_RE.match(text)
            if long_match:
                self._highlight_ls_long_match(long_match)
                return
            if len(text) > 240 or "/" in stripped:
                return
            tokens = list(self.WORD_TOKEN_RE.finditer(text))
            if len(tokens) < 2:
                return
            gap_count = sum(1 for left, right in zip(tokens, tokens[1:]) if right.start() - left.end() >= 2)
            if gap_count == 0 and len(tokens) > 5:
                return
            for match in tokens:
                token = match.group(1)
                fmt = self._format_for_ls_name(token)
                if fmt is not None:
                    self.setFormat(match.start(1), len(token), fmt)

        def _highlight_ls_long_match(self, match: re.Match[str]) -> None:
            permission = match.group(2)
            self.setFormat(match.start(2), len(permission), self._permission_format)
            self.setFormat(match.start(3), len(match.group(3)), self._muted_number_format)
            self.setFormat(match.start(6), len(match.group(6)), self._muted_number_format)
            self.setFormat(match.start(7), len(match.group(7)), self._date_format)

            name = match.group(8)
            name_start = match.start(8)
            if permission.startswith("d"):
                fmt = self._directory_format
            elif permission.startswith("l"):
                fmt = self._symlink_format
            elif "x" in permission.lower() or "s" in permission.lower():
                fmt = self._executable_format
            else:
                fmt = self._format_for_ls_name(name) or self._file_format

            arrow_index = name.find(" -> ")
            if arrow_index >= 0:
                self.setFormat(name_start, arrow_index, self._symlink_format)
                self.setFormat(name_start + arrow_index, len(name) - arrow_index, self._path_format)
            else:
                self.setFormat(name_start, len(name), fmt)

        def _format_for_ls_name(self, name: str) -> QTextCharFormat | None:
            clean_name = name.strip().strip("\"'")
            if not clean_name or clean_name in {".", ".."}:
                return None
            marker = clean_name[-1]
            base_name = clean_name[:-1] if marker in {"/", "*", "@", "|", "="} else clean_name
            lower_name = base_name.lower()
            suffix = Path(lower_name).suffix
            if marker == "/" or lower_name in self.DIRECTORY_NAMES:
                return self._directory_format
            if marker == "@":
                return self._symlink_format
            if marker == "*" or lower_name.endswith((".run", ".bin", ".exe")):
                return self._executable_format
            if suffix in self.ARCHIVE_EXTENSIONS:
                return self._archive_format
            if suffix in self.CODE_EXTENSIONS:
                return self._file_format
            return None

        def _highlight_ansi_line(self) -> None:
            block_number = self.currentBlock().blockNumber()
            if block_number < 0 or block_number >= len(self._ansi_line_formats):
                return
            for start, length, fg, bg, reverse, underscore in self._ansi_line_formats[block_number]:
                fmt = self._ansi_format(fg, bg, reverse, underscore)
                if fmt is not None:
                    self.setFormat(start, length, fmt)

        def _ansi_format(
            self,
            fg: str,
            bg: str,
            reverse: bool,
            underscore: bool,
        ) -> QTextCharFormat | None:
            fg = fg or "default"
            bg = bg or "default"
            key = (fg, bg, reverse, underscore)
            cached = self._ansi_format_cache.get(key)
            if cached is not None:
                return cached
            foreground = self.ANSI_COLORS.get(bg if reverse else fg)
            background = self.ANSI_COLORS.get(fg if reverse else bg)
            if foreground is None and background is None and not underscore:
                return None
            fmt = QTextCharFormat()
            if foreground is not None:
                fmt.setForeground(QColor(foreground))
            if background is not None:
                fmt.setBackground(QColor(background))
            if underscore:
                fmt.setFontUnderline(True)
            self._ansi_format_cache[key] = fmt
            return fmt

        def _format(
            self,
            color: str,
            bold: bool = False,
            background: str | None = None,
        ) -> QTextCharFormat:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if background is not None:
                fmt.setBackground(QColor(background))
            if bold:
                fmt.setFontWeight(700)
            return fmt

    class InteractiveTerminal(QPlainTextEdit):
        DEFAULT_COLUMNS = 160
        DEFAULT_LINES = 40
        DEFAULT_HISTORY = 2000
        MIN_COLUMNS = 80
        MIN_LINES = 8
        RENDER_INTERVAL_MS = 16
        LARGE_OUTPUT_RENDER_INTERVAL_MS = 16
        LARGE_OUTPUT_THRESHOLD = 32768
        MAX_FEED_CHARS_PER_FRAME = 65536
        MAX_RENDER_LINES = 600
        LINE_SPACING_MAX_BLOCKS = 600
        FAST_PLAIN_OUTPUT_THRESHOLD = 4096
        FAST_PLAIN_TAIL_CHARS = 65536
        FAST_PLAIN_INSERT_CHARS_PER_FRAME = 262144
        TERMINAL_HORIZONTAL_INSET = 42

        def __init__(self) -> None:
            super().__init__()
            self._raw_sender: Callable[[str], None] | None = None
            self._command_recorder: Callable[[str], None] | None = None
            self._enter_reconnect_handler: Callable[[], bool] | None = None
            self._pending_command_chars: list[str] = []
            self._pyte_screen: Any | None = None
            self._pyte_stream: Any | None = None
            self._buffer_lines: list[list[str]] = [[]]
            self._cursor_row = 0
            self._cursor_col = 0
            self._last_output_char = ""
            self._pending_output_chunks: list[str] = []
            self._pending_render_kind = ""
            self._last_render_text = ""
            self._terminal_cursor_position = 0
            self._terminal_cursor_width = 2
            self._plain_fast_mode = False
            self._plain_fast_tail = ""
            self._skip_pyte_render_once = False
            self._defer_terminal_decoration = False
            self._terminal_highlighter_enabled = True
            self._terminal_resize_handler: Callable[[int, int], None] | None = None
            self._last_reported_terminal_dimensions = (0, 0)
            self.setObjectName("terminalLog")
            self.setReadOnly(False)
            self.setUndoRedoEnabled(False)
            self.setCursorWidth(2)
            self.setTabChangesFocus(False)
            self.setCenterOnScroll(False)
            self.setWordWrapMode(QTextOption.NoWrap)
            self.document().setMaximumBlockCount(self.MAX_RENDER_LINES)
            self._syntax_highlighter = TerminalSyntaxHighlighter(self.document())
            self._sync_terminal_tab_stop()
            self._render_timer = QTimer(self)
            self._render_timer.setSingleShot(True)
            self._render_timer.timeout.connect(self._flush_pending_render)
            self._init_terminal_backend()

        def _init_terminal_backend(self) -> None:
            if pyte is None:
                return
            columns, lines = self._terminal_dimensions()
            self._pyte_screen = pyte.HistoryScreen(
                columns,
                lines,
                history=self.DEFAULT_HISTORY,
                ratio=1.0,
            )
            self._pyte_stream = pyte.Stream(self._pyte_screen)

        def _terminal_dimensions(self) -> tuple[int, int]:
            metrics = self.fontMetrics()
            char_width = max(1, metrics.horizontalAdvance("M"))
            line_height = max(1, metrics.lineSpacing())
            viewport = self.viewport()
            content_width = max(1, self.width() - self.TERMINAL_HORIZONTAL_INSET)
            columns = max(self.MIN_COLUMNS, content_width // char_width)
            lines = max(self.MIN_LINES, viewport.height() // line_height)
            return columns, lines

        def terminal_dimensions(self) -> tuple[int, int]:
            return self._terminal_dimensions()

        def _sync_terminal_tab_stop(self) -> None:
            self.setTabStopDistance(max(1, self.fontMetrics().horizontalAdvance(" ")) * 8)

        def _sync_terminal_dimensions(self) -> bool:
            if self._pyte_screen is None:
                return False
            columns, lines = self._terminal_dimensions()
            current_columns = int(getattr(self._pyte_screen, "columns", columns))
            current_lines = int(getattr(self._pyte_screen, "lines", lines))
            if columns == current_columns and lines == current_lines:
                return False
            self._pyte_screen.resize(lines=lines, columns=columns)
            return True

        def set_terminal_resize_handler(self, handler: Callable[[int, int], None]) -> None:
            self._terminal_resize_handler = handler

        def _notify_terminal_resize(self) -> None:
            if self._terminal_resize_handler is None:
                return
            dimensions = self._terminal_dimensions()
            if dimensions == self._last_reported_terminal_dimensions:
                return
            self._last_reported_terminal_dimensions = dimensions
            self._terminal_resize_handler(*dimensions)

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
            if self._pyte_stream is not None:
                self._pending_output_chunks.append(self._normalize_output_newlines(message))
                self._schedule_terminal_render("pyte", len(message))
                return

            message = self._normalize_output_newlines(message)
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

            self._schedule_terminal_render("buffer", len(message))

        def _schedule_terminal_render(self, kind: str, message_size: int = 0) -> None:
            self._pending_render_kind = "pyte" if kind == "pyte" else "buffer"
            if self._render_timer.isActive():
                return
            interval = (
                self.LARGE_OUTPUT_RENDER_INTERVAL_MS
                if message_size >= self.LARGE_OUTPUT_THRESHOLD
                else self.RENDER_INTERVAL_MS
            )
            self._render_timer.start(interval)

        def _flush_pending_render(self) -> None:
            kind = self._pending_render_kind
            self._pending_render_kind = ""
            if kind == "pyte":
                has_more_output = self._flush_pending_pyte_output()
                if self._skip_pyte_render_once:
                    self._skip_pyte_render_once = False
                else:
                    self._defer_terminal_decoration = has_more_output
                    self._render_pyte_buffer_now()
                    self._defer_terminal_decoration = False
                if has_more_output:
                    self._schedule_terminal_render("pyte", self.LARGE_OUTPUT_THRESHOLD)
            elif kind == "buffer":
                self._render_buffer_now()

        def _flush_pending_pyte_output(self) -> bool:
            if self._pyte_stream is None or not self._pending_output_chunks:
                return False
            message = "".join(self._pending_output_chunks)
            if self._should_fast_render_plain_output(message):
                if len(message) > self.FAST_PLAIN_INSERT_CHARS_PER_FRAME:
                    feed_message = message[: self.FAST_PLAIN_INSERT_CHARS_PER_FRAME]
                    self._pending_output_chunks = [message[self.FAST_PLAIN_INSERT_CHARS_PER_FRAME :]]
                    has_more_output = True
                else:
                    feed_message = message
                    self._pending_output_chunks.clear()
                    has_more_output = False
                self._append_plain_output_fast(feed_message)
                self._skip_pyte_render_once = True
                return has_more_output
            if self._plain_fast_mode:
                self._resync_pyte_from_plain_tail()
            if len(message) > self.MAX_FEED_CHARS_PER_FRAME:
                feed_message = message[: self.MAX_FEED_CHARS_PER_FRAME]
                self._pending_output_chunks = [message[self.MAX_FEED_CHARS_PER_FRAME :]]
                has_more_output = True
            else:
                feed_message = message
                self._pending_output_chunks.clear()
                has_more_output = False
            self._sync_terminal_dimensions()
            self._pyte_stream.feed(feed_message)
            return has_more_output

        def _should_fast_render_plain_output(self, message: str) -> bool:
            if len(message) < self.FAST_PLAIN_OUTPUT_THRESHOLD and not self._plain_fast_mode:
                return False
            return self._is_plain_stream_output(message)

        def _is_plain_stream_output(self, message: str) -> bool:
            for index, char in enumerate(message):
                if char == "\x1b" or char in ("\b", "\x7f"):
                    return False
                if char == "\r":
                    if index + 1 >= len(message) or message[index + 1] != "\n":
                        return False
                    continue
                if char == "\n" or char == "\t" or char >= " ":
                    continue
                return False
            return True

        def _append_plain_output_fast(self, message: str) -> None:
            text = self._expand_tabs(message.replace("\r\n", "\n").replace("\r", "\n"))
            if not text:
                return

            self._plain_fast_mode = True
            self._plain_fast_tail = (self._plain_fast_tail + message)[-self.FAST_PLAIN_TAIL_CHARS :]
            self._syntax_highlighter.clear_ansi_line_formats()
            self._set_terminal_highlighter_enabled(False)

            cursor = QTextCursor(self.document())
            cursor.movePosition(QTextCursor.End)
            cursor.insertText(text)
            self._last_render_text = ""
            self._terminal_cursor_position = max(0, self.document().characterCount() - 1)
            cursor.setPosition(self._terminal_cursor_position)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()

        def _resync_pyte_from_plain_tail(self) -> None:
            if not self._plain_fast_mode:
                return
            tail = self._plain_fast_tail
            self._plain_fast_mode = False
            self._plain_fast_tail = ""
            self._init_terminal_backend()
            if self._pyte_stream is None or not tail:
                return
            self._sync_terminal_dimensions()
            self._pyte_stream.feed(tail)

        def _flush_render_before_user_input(self) -> None:
            if not self._render_timer.isActive():
                return
            self._render_timer.stop()
            self._flush_pending_render()

        def _normalize_output_newlines(self, message: str) -> str:
            if not message:
                return message
            previous = self._last_output_char
            self._last_output_char = message[-1]
            if previous == "\r" and message.startswith("\n"):
                return "\n" + message[1:].replace("\r\n", "\n").replace("\n", "\r\n")
            return message.replace("\r\n", "\n").replace("\n", "\r\n")

        def _expand_tabs(self, text: str, tab_size: int = 8) -> str:
            if "\t" not in text:
                return text
            expanded: list[str] = []
            column = 0
            for char in text:
                if char == "\t":
                    spaces = tab_size - (column % tab_size)
                    expanded.append(" " * spaces)
                    column += spaces
                    continue
                expanded.append(char)
                if char == "\n":
                    column = 0
                else:
                    column += 1
            return "".join(expanded)

        def _render_pyte_buffer_now(self) -> None:
            if self._pyte_screen is None:
                return
            self._sync_terminal_dimensions()

            history = getattr(self._pyte_screen, "history", None)
            history_top = list(getattr(history, "top", []))
            cursor_row = len(history_top) + int(self._pyte_screen.cursor.y)
            cursor_col = int(self._pyte_screen.cursor.x)
            screen_buffer = getattr(self._pyte_screen, "buffer", {})
            display_entries = [
                self._line_to_text_and_styles(
                    screen_buffer[index] if hasattr(screen_buffer, "__getitem__") else line,
                    cursor_col if index == self._pyte_screen.cursor.y else None,
                )
                for index, line in enumerate(self._pyte_screen.display)
            ]
            all_entries = [self._line_to_text_and_styles(line) for line in history_top] + display_entries
            lines, ansi_line_formats, cursor_row = self._trim_terminal_line_entries(all_entries, cursor_row)
            self._syntax_highlighter.set_ansi_line_formats(ansi_line_formats)

            text = "\n".join(lines)
            self._set_terminal_text(text)

            if not lines:
                lines = [""]

            cursor = self.textCursor()
            self._terminal_cursor_position = self._cursor_position_for_lines(lines, cursor_row, cursor_col)
            cursor.setPosition(self._terminal_cursor_position)
            self.setTextCursor(cursor)
            self._set_terminal_cursor_width(0 if getattr(self._pyte_screen.cursor, "hidden", False) else 2)
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
            cursor_index = cursor_row - start
            if len(trimmed) > self.MAX_RENDER_LINES:
                window_start = min(
                    max(0, cursor_index - self.MAX_RENDER_LINES + 1),
                    len(trimmed) - self.MAX_RENDER_LINES,
                )
                trimmed = trimmed[window_start : window_start + self.MAX_RENDER_LINES]
                cursor_index -= window_start
            return trimmed, cursor_index

        def _trim_terminal_line_entries(
            self,
            entries: list[tuple[str, list[tuple[int, int, str, str, bool, bool]]]],
            cursor_row: int,
        ) -> tuple[list[str], list[list[tuple[int, int, str, str, bool, bool]]], int]:
            lines = [text for text, _formats in entries]
            if not lines:
                return [""], [[]], 0

            non_empty_rows = [index for index, line in enumerate(lines) if line.strip()]
            if not non_empty_rows:
                safe_row = min(cursor_row, len(entries) - 1)
                text, formats = entries[safe_row]
                return [text], [formats], 0

            start = min(non_empty_rows[0], cursor_row)
            end = max(non_empty_rows[-1], cursor_row) + 1
            trimmed_entries = entries[start:end]
            cursor_index = cursor_row - start
            if len(trimmed_entries) > self.MAX_RENDER_LINES:
                window_start = min(
                    max(0, cursor_index - self.MAX_RENDER_LINES + 1),
                    len(trimmed_entries) - self.MAX_RENDER_LINES,
                )
                trimmed_entries = trimmed_entries[window_start : window_start + self.MAX_RENDER_LINES]
                cursor_index -= window_start
            return [text for text, _formats in trimmed_entries], [formats for _text, formats in trimmed_entries], cursor_index

        def _line_to_text(self, line: Any, preserve_to_column: int | None = None) -> str:
            if isinstance(line, str):
                text = line
            elif hasattr(line, "items"):
                cells = []
                for column, cell in line.items():
                    try:
                        column_index = int(column)
                    except (TypeError, ValueError):
                        continue
                    if column_index < 0:
                        continue
                    cells.append((column_index, cell))
                if not cells:
                    text = ""
                else:
                    width = max(column for column, _cell in cells) + 1
                    chars = [" "] * width
                    for column, cell in cells:
                        data = getattr(cell, "data", " ")
                        chars[column] = str(data)[:1] if data else " "
                    text = "".join(chars)
            else:
                text = "".join(getattr(cell, "data", str(cell)) for cell in line)
            if preserve_to_column is not None:
                visible_text = text.rstrip()
                return visible_text.ljust(preserve_to_column) if len(visible_text) < preserve_to_column else visible_text
            return text.rstrip()

        def _line_to_text_and_styles(
            self,
            line: Any,
            preserve_to_column: int | None = None,
        ) -> tuple[str, list[tuple[int, int, str, str, bool, bool]]]:
            if isinstance(line, str) or not hasattr(line, "items"):
                return self._line_to_text(line, preserve_to_column), []

            cells = []
            for column, cell in line.items():
                try:
                    column_index = int(column)
                except (TypeError, ValueError):
                    continue
                if column_index < 0:
                    continue
                cells.append((column_index, cell))
            if not cells:
                text = ""
                return (text.ljust(preserve_to_column) if preserve_to_column else text), []

            width = max(column for column, _cell in cells) + 1
            chars = [" "] * width
            style_by_column: dict[int, tuple[str, str, bool, bool]] = {}
            for column, cell in cells:
                data = getattr(cell, "data", " ")
                chars[column] = str(data)[:1] if data else " "
                style = self._cell_style_key(cell)
                if style is not None:
                    style_by_column[column] = style

            raw_text = "".join(chars)
            if preserve_to_column is not None:
                visible_text = raw_text.rstrip()
                text = visible_text.ljust(preserve_to_column) if len(visible_text) < preserve_to_column else visible_text
            else:
                text = raw_text.rstrip()

            visible_width = len(text)
            ranges: list[tuple[int, int, str, str, bool, bool]] = []
            range_start: int | None = None
            range_style: tuple[str, str, bool, bool] | None = None
            previous_column = -1
            for column in sorted(style_by_column):
                if column >= visible_width:
                    continue
                style = style_by_column[column]
                if range_start is None:
                    range_start = column
                    range_style = style
                elif column != previous_column + 1 or style != range_style:
                    if range_style is not None:
                        ranges.append((range_start, previous_column - range_start + 1, *range_style))
                    range_start = column
                    range_style = style
                previous_column = column
            if range_start is not None and range_style is not None:
                ranges.append((range_start, previous_column - range_start + 1, *range_style))
            return text, ranges

        @staticmethod
        def _cell_style_key(cell: Any) -> tuple[str, str, bool, bool] | None:
            fg = str(getattr(cell, "fg", "default") or "default")
            bg = str(getattr(cell, "bg", "default") or "default")
            reverse = bool(getattr(cell, "reverse", False))
            underscore = bool(getattr(cell, "underscore", False))
            if fg == "default" and bg == "default" and not reverse and not underscore:
                return None
            return fg, bg, reverse, underscore

        def _cursor_position_for_lines(self, lines: list[str], row: int, column: int) -> int:
            safe_row = max(0, min(row, len(lines) - 1))
            position = 0
            for line in lines[:safe_row]:
                position += len(line) + 1
            return position + min(column, len(lines[safe_row]))

        def _set_terminal_text(self, text: str) -> None:
            if text == self._last_render_text:
                if (
                    not self._defer_terminal_decoration
                    and not self._terminal_highlighter_enabled
                    and self.document().blockCount() <= self.LINE_SPACING_MAX_BLOCKS
                ):
                    self._set_terminal_highlighter_enabled(True)
                    self._apply_terminal_block_spacing()
                    self._syntax_highlighter.rehighlight()
                return
            self._last_render_text = text
            self.setPlainText(text)
            block_count = self.document().blockCount()
            if self._defer_terminal_decoration:
                self._set_terminal_highlighter_enabled(False)
                return
            if block_count <= self.LINE_SPACING_MAX_BLOCKS:
                self._set_terminal_highlighter_enabled(True)
                self._apply_terminal_block_spacing()
                self._syntax_highlighter.rehighlight()
            else:
                self._set_terminal_highlighter_enabled(False)

        def _set_terminal_highlighter_enabled(self, enabled: bool) -> None:
            if self._terminal_highlighter_enabled == enabled:
                return
            self._terminal_highlighter_enabled = enabled
            self._syntax_highlighter.setDocument(self.document() if enabled else None)

        def _apply_terminal_block_spacing(self) -> None:
            if QTextBlockFormat is None:
                return
            cursor = QTextCursor(self.document())
            cursor.select(QTextCursor.Document)
            block_format = QTextBlockFormat()
            line_height_type = getattr(QTextBlockFormat.ProportionalHeight, "value", QTextBlockFormat.ProportionalHeight)
            block_format.setLineHeight(118.0, int(line_height_type))
            cursor.mergeBlockFormat(block_format)

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

        def _render_buffer_now(self) -> None:
            text = "\n".join("".join(line) for line in self._buffer_lines)
            self._set_terminal_text(text)

            document = self.document()
            block = document.findBlockByNumber(self._cursor_row)
            if not block.isValid():
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.setTextCursor(cursor)
                self.ensureCursorVisible()
                return

            cursor = self.textCursor()
            self._terminal_cursor_position = block.position() + min(self._cursor_col, len(block.text()))
            cursor.setPosition(self._terminal_cursor_position)
            self.setTextCursor(cursor)
            self._set_terminal_cursor_width(2)
            self.ensureCursorVisible()

        def set_raw_sender(self, sender: Callable[[str], None]) -> None:
            self._raw_sender = sender

        def set_enter_reconnect_handler(self, handler: Callable[[], bool]) -> None:
            self._enter_reconnect_handler = handler

        def set_command_recorder(self, recorder: Callable[[str], None]) -> None:
            self._command_recorder = recorder

        def resizeEvent(self, event: Any) -> None:  # noqa: N802
            super().resizeEvent(event)
            self._sync_terminal_tab_stop()
            if self._plain_fast_mode:
                return
            if event.oldSize().isValid() and event.oldSize().width() == event.size().width():
                return
            if self._sync_terminal_dimensions():
                self._flush_pending_pyte_output()
                self._render_pyte_buffer_now()
                self._notify_terminal_resize()

        def mousePressEvent(self, event: Any) -> None:  # noqa: N802
            if event.button() == Qt.LeftButton:
                self.setCursorWidth(0)
            super().mousePressEvent(event)

        def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
            super().mouseReleaseEvent(event)
            if event.button() == Qt.LeftButton and not self.textCursor().hasSelection():
                self._restore_terminal_cursor()
            elif event.button() == Qt.LeftButton:
                self.setCursorWidth(0)

        def _restore_terminal_cursor(self) -> None:
            cursor = self.textCursor()
            position = max(0, min(self._terminal_cursor_position, self.document().characterCount() - 1))
            cursor.setPosition(position)
            self.setTextCursor(cursor)
            self._restore_terminal_cursor_width()

        def _set_terminal_cursor_width(self, width: int) -> None:
            self._terminal_cursor_width = width
            if not self.textCursor().hasSelection():
                self.setCursorWidth(width)

        def _restore_terminal_cursor_width(self) -> None:
            if not self.textCursor().hasSelection():
                self.setCursorWidth(self._terminal_cursor_width)

        def _move_terminal_cursor_preview(self, delta: int) -> None:
            self._restore_terminal_cursor_width()
            cursor = self.textCursor()
            if cursor.hasSelection():
                cursor.clearSelection()
            position = max(0, min(self._terminal_cursor_position, self.document().characterCount() - 1))
            block = self.document().findBlock(position)
            if not block.isValid():
                return
            line_start = block.position()
            line_end = line_start + len(block.text())
            next_position = max(line_start, min(line_end, position + delta))
            self._terminal_cursor_position = next_position
            cursor.setPosition(next_position)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()

        def _move_terminal_cursor_to_line_edge(self, edge: str) -> None:
            self._restore_terminal_cursor_width()
            cursor = self.textCursor()
            if cursor.hasSelection():
                cursor.clearSelection()
            position = max(0, min(self._terminal_cursor_position, self.document().characterCount() - 1))
            block = self.document().findBlock(position)
            if not block.isValid():
                return
            next_position = block.position() if edge == "start" else block.position() + len(block.text())
            self._terminal_cursor_position = next_position
            cursor.setPosition(next_position)
            self.setTextCursor(cursor)
            self.ensureCursorVisible()

        def keyPressEvent(self, event: Any) -> None:  # noqa: N802
            if self._raw_sender is None:
                return super().keyPressEvent(event)

            self._restore_terminal_cursor_width()
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
                    if self.textCursor().hasSelection():
                        self.copy()
                        return
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
                if self._enter_reconnect_handler is not None and self._enter_reconnect_handler():
                    return
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
                self._move_terminal_cursor_preview(-1)
                self._forward_text("\x1b[D")
                return
            if key == Qt.Key_Right:
                self._move_terminal_cursor_preview(1)
                self._forward_text("\x1b[C")
                return
            if key == Qt.Key_Up:
                self._forward_text("\x1b[A")
                return
            if key == Qt.Key_Down:
                self._forward_text("\x1b[B")
                return
            if key == Qt.Key_Home:
                self._move_terminal_cursor_to_line_edge("start")
                self._forward_text("\x1b[H")
                return
            if key == Qt.Key_End:
                self._move_terminal_cursor_to_line_edge("end")
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
            self.setMinimumHeight(72)
            self.setMaximumHeight(16777215)
            self.setTabChangesFocus(True)
            self.setUndoRedoEnabled(False)
            self.setLineWrapMode(QPlainTextEdit.NoWrap)
            self.setPlaceholderText("在此输入命令...")

        def set_submit_handler(self, handler: Callable[[str], None]) -> None:
            self._submit_handler = handler

        def set_enter_sends(self, enter_sends: bool) -> None:
            self._enter_sends = enter_sends

        def current_command_line(self) -> str:
            return self.textCursor().block().text().strip()

        def keyPressEvent(self, event: Any) -> None:  # noqa: N802
            key = event.key()
            modifiers = event.modifiers()
            if modifiers == Qt.NoModifier:
                if key == Qt.Key_Left:
                    cursor = self.textCursor()
                    cursor.movePosition(QTextCursor.Left)
                    self.setTextCursor(cursor)
                    self.ensureCursorVisible()
                    return
                if key == Qt.Key_Right:
                    cursor = self.textCursor()
                    cursor.movePosition(QTextCursor.Right)
                    self.setTextCursor(cursor)
                    self.ensureCursorVisible()
                    return
                if key == Qt.Key_Home:
                    cursor = self.textCursor()
                    cursor.movePosition(QTextCursor.StartOfLine)
                    self.setTextCursor(cursor)
                    self.ensureCursorVisible()
                    return
                if key == Qt.Key_End:
                    cursor = self.textCursor()
                    cursor.movePosition(QTextCursor.EndOfLine)
                    self.setTextCursor(cursor)
                    self.ensureCursorVisible()
                    return
            if key in (Qt.Key_Return, Qt.Key_Enter):
                ctrl_pressed = bool(modifiers & Qt.ControlModifier)
                should_submit = not ctrl_pressed if self._enter_sends else ctrl_pressed
                if should_submit:
                    command = self.current_command_line()
                    if command and self._submit_handler is not None:
                        self._submit_handler(command)
                    return
                self.insertPlainText("\n")
                return
            super().keyPressEvent(event)

    class CommandRecordResizeHandle(QFrame):
        def __init__(self, resize_handler: Callable[[int], None], parent: QWidget) -> None:
            super().__init__(parent)
            self._resize_handler = resize_handler
            self._drag_start_y = 0
            self._drag_start_height = 0
            self.setObjectName("commandRecordResizeHandle")
            self.setFixedHeight(5)
            self.setCursor(Qt.SizeVerCursor)

        def mousePressEvent(self, event: Any) -> None:  # noqa: N802
            if event.button() == Qt.LeftButton:
                self._drag_start_y = self._event_global_y(event)
                parent = self.parentWidget()
                self._drag_start_height = parent.height() if parent is not None else 0
                event.accept()
                return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
            if not (event.buttons() & Qt.LeftButton):
                return super().mouseMoveEvent(event)
            delta = self._event_global_y(event) - self._drag_start_y
            self._resize_handler(self._drag_start_height - delta)
            event.accept()

        def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
            if event.button() == Qt.LeftButton:
                event.accept()
                return
            super().mouseReleaseEvent(event)

        @staticmethod
        def _event_global_y(event: Any) -> int:
            if hasattr(event, "globalPosition"):
                return int(event.globalPosition().toPoint().y())
            return int(event.globalY())

    class DeviceDesktopApp(QMainWindow):
        LOG_FLUSH_INTERVAL_MS = 250
        LOG_FLUSH_IMMEDIATE_CHARS = 65536
        COMMAND_RECORD_COLLAPSED_HEIGHT = 25
        COMMAND_RECORD_DEFAULT_HEIGHT = 148
        COMMAND_RECORD_MIN_HEIGHT = 116
        COMMAND_RECORD_MAX_HEIGHT = 600

        def __init__(self, repository: DeviceRepository | None = None) -> None:
            super().__init__()
            self.repository = repository or create_repository_from_env()
            self.async_loop = AsyncLoopThread()
            self.ui_queue: queue.SimpleQueue[tuple[Callable[..., None], tuple[object, ...]]] = queue.SimpleQueue()
            self.repository_lock = threading.Lock()
            self.search_index: dict[str, str] = {}
            self.device_by_id: dict[str, Device] = {}
            self.device_table_rows: dict[str, int] = {}
            self.owned_table_rows: dict[str, int] = {}
            self.devices: list[Device] = []
            self.visible_devices: list[Device] = []
            self.owned_visible_devices: list[Device] = []
            self.visible_status_counts: dict[str, int] = {}
            self.selected_device_id = ""
            self.current_user = ""
            self.owned_device_ids: set[str] | None = None
            self.refresh_generation = 0
            self.closed = False
            self.loading_snapshot = False
            self.my_occupancy_filter_enabled = False
            self.recent_device_ids: list[str] = []
            self.command_record_groups: list[dict[str, object]] = [
                {"name": "终端", "content": ""},
            ]
            self.current_command_group = 0
            self.command_record_collapsed = True
            self.command_enter_sends = False
            self.command_record_height = self.COMMAND_RECORD_DEFAULT_HEIGHT
            self.connection_params_collapsed = True
            self.left_sidebar_collapsed = False
            self.left_sidebar_animation = None
            self.command_tab_buttons: list[QToolButton] = []
            self.command_tab_close_buttons: list[QToolButton] = []
            self.state_path = self.desktop_state_path()
            self.log_directory = self.default_log_directory()
            self.device_tabs_by_id: dict[str, DeviceTabState] = {}
            self.session_tabs_by_id: dict[str, SessionTabState] = {}
            self.pending_futures: set[Future] = set()
            self._drag_session_tab_id = ""
            self._last_desktop_state_payload = ""
            self._last_device_table_signature: tuple[object, ...] = ()
            self._last_owned_table_signature: tuple[object, ...] = ()
            self._table_render_jobs: list[dict[str, object]] = []
            self._table_render_generation = 0
            self.next_session_sequence = 1

            self.refresh_timer = QTimer(self)
            self.refresh_timer.setSingleShot(True)
            self.refresh_timer.timeout.connect(self.refresh_snapshot)
            self.filter_timer = QTimer(self)
            self.filter_timer.setSingleShot(True)
            self.filter_timer.setInterval(120)
            self.filter_timer.timeout.connect(self.apply_filters)
            self.state_save_timer = QTimer(self)
            self.state_save_timer.setSingleShot(True)
            self.state_save_timer.timeout.connect(self.save_desktop_state)
            self.ui_timer = QTimer(self)
            self.ui_timer.setInterval(10)
            self.ui_timer.timeout.connect(self._drain_ui_queue)
            self.log_flush_timer = QTimer(self)
            self.log_flush_timer.setSingleShot(True)
            self.log_flush_timer.timeout.connect(self.flush_pending_session_logs)
            self.table_render_timer = QTimer(self)
            self.table_render_timer.setSingleShot(True)
            self.table_render_timer.timeout.connect(self.process_table_render_jobs)

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
            self.setMinimumSize(1280, 800)
            base_font = self.font()
            if base_font.pointSize() <= 0:
                base_font.setPointSize(9)
                self.setFont(base_font)
            self.setStyleSheet(APP_STYLE)

            status_bar = QStatusBar(self)
            self.setStatusBar(status_bar)
            status_bar.showMessage("准备就绪")

        def _build_layout(self) -> None:
            root = QWidget(self)
            root_layout = QVBoxLayout(root)
            root_layout.setContentsMargins(12, 12, 12, 8)
            root_layout.setSpacing(8)

            splitter = QSplitter(Qt.Horizontal, root)
            self.main_splitter = splitter
            root_layout.addWidget(splitter, 1)

            splitter.addWidget(self._build_left_panel())
            splitter.addWidget(self._build_center_panel())
            splitter.setSizes([520, 1080])
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            self.apply_left_sidebar_state()

            self.setCentralWidget(root)

        def _build_toolbar(self) -> QWidget:
            frame = QFrame()
            frame.setObjectName("toolbarFrame")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(16, 12, 16, 12)
            layout.setSpacing(10)

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
            shell = QWidget()
            shell.setObjectName("leftSidebarShell")
            self.left_sidebar_shell = shell
            shell.setMinimumWidth(480)
            shell.setMaximumWidth(580)
            shell_layout = QHBoxLayout(shell)
            self.left_sidebar_layout = shell_layout
            shell_layout.setContentsMargins(0, 0, 8, 0)
            shell_layout.setSpacing(8)
            shell_layout.addWidget(self._build_activity_rail(), 0)

            scroll = QScrollArea()
            scroll.setObjectName("inspectorScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.left_sidebar_content = scroll
            scroll.setMinimumWidth(420)
            scroll.setMaximumWidth(520)

            panel = QWidget()
            panel.setObjectName("leftRail")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 8, 0)
            layout.setSpacing(8)

            navigation_group = QGroupBox("设备导航")
            navigation_group.setObjectName("navShell")
            nav_layout = QVBoxLayout(navigation_group)
            nav_layout.setSpacing(8)

            nav_header = QHBoxLayout()
            nav_header.setSpacing(8)
            nav_title_col = QVBoxLayout()
            nav_title_col.setSpacing(2)
            nav_title = QLabel("设备池")
            nav_title.setObjectName("railTitle")
            nav_copy = QLabel("按关键词、领域、状态和 CPU 快速定位目标设备")
            nav_copy.setObjectName("railCopy")
            nav_copy.setWordWrap(True)
            nav_copy.setMinimumWidth(0)
            if QSizePolicy is not None:
                nav_copy.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            nav_title_col.addWidget(nav_title)
            nav_title_col.addWidget(nav_copy)
            nav_header.addLayout(nav_title_col, 1)
            self.toolbar_refresh_button = QPushButton("刷新")
            self.toolbar_refresh_button.setObjectName("compactGhostButton")
            self.toolbar_refresh_button.setFixedWidth(58)
            nav_header.addWidget(self.toolbar_refresh_button, 0, Qt.AlignTop)
            nav_layout.addLayout(nav_header)

            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("搜索名称、ID、IP、型号")
            nav_layout.addWidget(self.search_input)

            filter_frame = QFrame()
            filter_frame.setObjectName("navFilterBar")
            filter_row = QHBoxLayout(filter_frame)
            filter_row.setContentsMargins(8, 8, 8, 8)
            filter_row.setSpacing(6)
            self.domain_combo = QComboBox()
            self.domain_combo.addItem(ALL_DOMAINS)
            self.status_combo = QComboBox()
            self.status_combo.addItems(FILTERABLE_STATUSES)
            self.cpu_input = QLineEdit()
            self.cpu_input.setPlaceholderText("CPU")
            self.my_occupancy_filter_button = QPushButton("我的")
            self.my_occupancy_filter_button.setObjectName("filterToggleButton")
            self.my_occupancy_filter_button.setCheckable(True)
            self.my_occupancy_filter_button.setToolTip("只显示当前 API 用户占用的设备")
            self.domain_combo.setMinimumWidth(0)
            self.status_combo.setMinimumWidth(0)
            self.cpu_input.setMinimumWidth(84)
            self.cpu_input.setMaximumWidth(110)
            self.my_occupancy_filter_button.setMinimumWidth(78)
            self.my_occupancy_filter_button.setMaximumWidth(96)
            filter_row.addWidget(self.domain_combo, 1)
            filter_row.addWidget(self.status_combo, 1)
            filter_row.addWidget(self.cpu_input, 0)
            filter_row.addWidget(self.my_occupancy_filter_button, 0)
            nav_layout.addWidget(filter_frame)

            stats_frame = QFrame()
            stats_frame.setObjectName("navStatsBar")
            stats_layout = QVBoxLayout(stats_frame)
            stats_layout.setContentsMargins(10, 6, 10, 6)
            stats_layout.setSpacing(4)
            stats_top_row = QHBoxLayout()
            stats_top_row.setContentsMargins(0, 0, 0, 0)
            stats_top_row.setSpacing(4)
            stats_bottom_row = QHBoxLayout()
            stats_bottom_row.setContentsMargins(0, 0, 0, 0)
            stats_bottom_row.setSpacing(4)
            self.stats_caption_label = QLabel("筛选结果")
            self.stats_caption_label.setObjectName("sectionCopy")
            self.stats_label = QLabel("设备 0  空闲 0  占用 0  流水线 0  其他 0")
            self.stats_label.setObjectName("navStatsText")
            self.stats_label.setTextFormat(Qt.RichText)
            self.filter_summary_label = QLabel("当前显示全部设备")
            self.filter_summary_label.setObjectName("activeFilterText")
            self.filter_summary_label.setTextFormat(Qt.RichText)
            self.filter_summary_label.setWordWrap(True)
            self.filter_summary_label.setMinimumWidth(0)
            if QSizePolicy is not None:
                self.filter_summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            stats_top_row.addWidget(self.stats_caption_label)
            stats_top_row.addWidget(self.stats_label, 1)
            stats_bottom_row.addWidget(self.filter_summary_label, 1)
            self.clear_filters_button = QPushButton("清空")
            self.clear_filters_button.setObjectName("compactGhostButton")
            self.clear_filters_button.setEnabled(False)
            self.clear_filters_button.setFixedWidth(58)
            stats_bottom_row.addWidget(self.clear_filters_button)
            stats_layout.addLayout(stats_top_row)
            stats_layout.addLayout(stats_bottom_row)
            nav_layout.addWidget(stats_frame)

            self.device_table = self._new_table(["序号", "设备", "领域", "CPU", "状态"])
            self.device_table.setMinimumHeight(320)
            self.device_table.setMaximumHeight(420)
            nav_layout.addWidget(self.device_table)
            layout.addWidget(navigation_group)
            layout.addWidget(self._build_device_context_panel())
            layout.addStretch(1)
            scroll.setWidget(panel)
            shell_layout.addWidget(scroll, 1)
            self.apply_left_sidebar_state(animated=True)
            return shell

        def _build_activity_rail(self) -> QWidget:
            rail = QFrame()
            rail.setObjectName("activityRail")
            rail.setFixedWidth(46)
            layout = QVBoxLayout(rail)
            layout.setContentsMargins(5, 8, 5, 8)
            layout.setSpacing(8)

            self.activity_device_button = self._new_activity_button(
                "devices",
                "设备导航",
                checked=not self.left_sidebar_collapsed,
            )

            layout.addWidget(self.activity_device_button)
            layout.addStretch(1)

            self.activity_device_button.clicked.connect(lambda: self.toggle_left_sidebar())
            return rail

        def _new_activity_button(self, icon_name: str, tooltip: str, *, checked: bool = False) -> QToolButton:
            button = QToolButton()
            button.setObjectName("activityRailButton")
            button.setToolTip(tooltip)
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setIcon(self._activity_icon(icon_name, "#ededed" if checked else "#a0a0a0"))
            button.setIconSize(QSize(22, 22))
            button.setFixedSize(34, 34)
            button.setCheckable(True)
            button.setChecked(checked)
            button.setAutoRaise(False)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            return button

        def _activity_icon(self, kind: str, color: str = "#a0a0a0") -> Any:
            if QIcon is None or QPainter is None or QPen is None or QPixmap is None:
                return QIcon() if QIcon is not None else None
            pixmap = QPixmap(24, 24)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(QColor(color), 1.7)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)

            if kind == "devices":
                painter.drawRoundedRect(6, 4, 11, 15, 2, 2)
                painter.drawLine(9, 8, 14, 8)
                painter.drawLine(9, 12, 14, 12)
                painter.drawLine(9, 16, 12, 16)
            elif kind == "search":
                painter.drawEllipse(5, 5, 10, 10)
                painter.drawLine(13, 13, 19, 19)
            elif kind == "owner":
                painter.drawEllipse(9, 5, 6, 6)
                painter.drawArc(6, 11, 12, 8, 20 * 16, 140 * 16)
                painter.drawLine(7, 20, 17, 20)
            elif kind == "terminal":
                painter.drawRoundedRect(4, 6, 16, 12, 2, 2)
                painter.drawLine(7, 10, 9, 12)
                painter.drawLine(7, 14, 13, 14)
            elif kind == "log":
                painter.drawRoundedRect(7, 4, 11, 16, 2, 2)
                painter.drawLine(10, 8, 15, 8)
                painter.drawLine(10, 12, 15, 12)
                painter.drawLine(10, 16, 13, 16)
            elif kind == "connector":
                painter.drawRoundedRect(4, 6, 9, 8, 2, 2)
                painter.drawRoundedRect(11, 10, 9, 8, 2, 2)
                painter.drawLine(12, 11, 15, 11)
                painter.drawLine(9, 14, 12, 14)
            else:
                painter.drawEllipse(7, 7, 10, 10)
            painter.end()
            return QIcon(pixmap)

        def _build_occupancy_panel(self) -> QWidget:
            frame = QFrame()
            frame.setObjectName("myOccupancyCard")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(6)

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
            layout.setSpacing(8)

            detail_group = QGroupBox("当前设备")
            detail_group.setObjectName("deviceDetailCard")
            detail_layout = QVBoxLayout(detail_group)
            detail_layout.setContentsMargins(10, 12, 10, 10)
            detail_layout.setSpacing(6)
            self.device_summary_card = QLabel("请选择一台设备。")
            self.device_summary_card.setObjectName("inspectorText")
            self.device_summary_card.setWordWrap(True)
            self.device_summary_card.setTextFormat(Qt.RichText)
            self.device_summary_card.setTextInteractionFlags(Qt.TextSelectableByMouse)
            detail_layout.addWidget(self.device_summary_card)

            layout.addWidget(detail_group)

            auth_group = QGroupBox("连接参数")
            auth_group.setObjectName("authCard")
            self.connection_params_group = auth_group
            auth_layout = QVBoxLayout(auth_group)
            auth_layout.setContentsMargins(10, 10, 10, 8)
            auth_layout.setSpacing(6)

            auth_header_frame = QFrame()
            auth_header_frame.setObjectName("connectionParamsHeader")
            auth_header = QHBoxLayout(auth_header_frame)
            auth_header.setContentsMargins(0, 0, 0, 0)
            auth_header.setSpacing(8)
            auth_hint = QLabel("账号和密码来自设备信息")
            auth_hint.setObjectName("sectionCopy")
            auth_hint.setWordWrap(True)
            auth_hint.setMinimumWidth(0)
            if QSizePolicy is not None:
                auth_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self.connection_params_toggle_button = QToolButton()
            self.connection_params_toggle_button.setObjectName("inspectorToggleButton")
            self.connection_params_toggle_button.setText("展开")
            self.connection_params_toggle_button.setToolTip("展开或收起连接参数")
            self.connection_params_toggle_button.setFixedWidth(58)
            auth_header.addWidget(auth_hint)
            auth_header.addStretch(1)
            auth_header.addWidget(self.connection_params_toggle_button)
            auth_layout.addWidget(auth_header_frame)

            self.connection_params_body = QWidget()
            body_layout = QVBoxLayout(self.connection_params_body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(6)

            device_form_group = QGroupBox("设备 Telnet")
            device_form = QFormLayout(device_form_group)
            device_form.setContentsMargins(8, 10, 8, 8)
            device_form.setVerticalSpacing(6)
            device_form.setHorizontalSpacing(6)
            device_form.setLabelAlignment(Qt.AlignRight)
            self.device_telnet_ip_value = SelectAllLineEdit()
            self.device_username_input = QLineEdit()
            self.device_password_input = QLineEdit()
            device_form.addRow("Telnet IP", self.device_telnet_ip_value)
            device_form.addRow("用户名", self.device_username_input)
            device_form.addRow("密码", self.device_password_input)

            serial_form_group = QGroupBox("串口 Telnet")
            serial_form = QFormLayout(serial_form_group)
            serial_form.setContentsMargins(8, 10, 8, 8)
            serial_form.setVerticalSpacing(6)
            serial_form.setHorizontalSpacing(6)
            serial_form.setLabelAlignment(Qt.AlignRight)
            self.device_serial_ip_value = SelectAllLineEdit()
            self.device_serial_ip_value.setPlaceholderText("占用后可见")
            serial_form.addRow("串口地址", self.device_serial_ip_value)

            linux_form_group = QGroupBox("Linux SSH")
            linux_form = QFormLayout(linux_form_group)
            linux_form.setContentsMargins(8, 10, 8, 8)
            linux_form.setVerticalSpacing(6)
            linux_form.setHorizontalSpacing(6)
            linux_form.setLabelAlignment(Qt.AlignRight)
            self.device_ssh_ip_value = SelectAllLineEdit()
            self.linux_username_input = QLineEdit()
            self.linux_password_input = QLineEdit()
            linux_form.addRow("SSH IP", self.device_ssh_ip_value)
            linux_form.addRow("用户名", self.linux_username_input)
            linux_form.addRow("密码", self.linux_password_input)

            body_layout.addWidget(device_form_group)
            body_layout.addWidget(serial_form_group)
            body_layout.addWidget(linux_form_group)
            auth_layout.addWidget(self.connection_params_body)
            layout.addWidget(auth_group)
            self.apply_connection_params_state()
            return panel

        def _quick_action_icon(self, kind: str, color: str = "#a0a0a0") -> Any:
            if QIcon is None or QPainter is None or QPen is None or QPixmap is None:
                return QIcon() if QIcon is not None else None
            pixmap = QPixmap(18, 18)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(QColor(color), 1.5)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)

            if kind == "terminal":
                painter.drawRoundedRect(3, 5, 14, 10, 2, 2)
                painter.drawLine(6, 8, 8, 10)
                painter.drawLine(6, 12, 11, 12)
            elif kind == "ssh":
                painter.drawRoundedRect(5, 9, 10, 7, 2, 2)
                painter.drawArc(6, 4, 8, 9, 0, 180 * 16)
                painter.drawLine(10, 12, 10, 14)
            elif kind == "serial":
                painter.drawRoundedRect(4, 4, 12, 8, 2, 2)
                painter.drawLine(7, 14, 13, 14)
                painter.drawLine(8, 17, 12, 17)
                painter.drawLine(10, 12, 10, 17)
                painter.drawPoint(7, 8)
                painter.drawPoint(10, 8)
                painter.drawPoint(13, 8)
            elif kind == "owner":
                painter.drawEllipse(7, 4, 6, 6)
                painter.drawArc(4, 9, 12, 8, 20 * 16, 140 * 16)
                painter.drawLine(5, 17, 15, 17)
            elif kind == "power":
                painter.drawArc(5, 6, 10, 10, 35 * 16, 290 * 16)
                painter.drawLine(10, 3, 10, 10)
            elif kind == "refresh":
                painter.drawArc(4, 4, 12, 12, 35 * 16, 260 * 16)
                painter.drawLine(15, 5, 15, 9)
                painter.drawLine(15, 5, 11, 5)
            elif kind == "log":
                painter.drawRoundedRect(5, 3, 10, 14, 1, 1)
                painter.drawLine(8, 7, 13, 7)
                painter.drawLine(8, 10, 13, 10)
                painter.drawLine(8, 13, 11, 13)
            elif kind == "disconnect":
                painter.drawLine(5, 5, 15, 15)
                painter.drawLine(7, 13, 13, 7)
                painter.drawLine(6, 15, 14, 15)
            painter.end()
            return QIcon(pixmap)

        def _configure_quick_action_button(
            self,
            button: QToolButton,
            icon_name: str,
            tooltip: str,
            *,
            danger: bool = False,
        ) -> None:
            button.setObjectName("quickDangerIconButton" if danger else "quickActionIconButton")
            button.setText("")
            button.setToolTip(tooltip)
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setIcon(self._quick_action_icon(icon_name, "#a0a0a0" if not danger else "#f88b91"))
            button.setIconSize(QSize(15, 15))
            button.setFixedSize(26, 26)
            button.setAutoRaise(False)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)

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
            quick_action_bar = QFrame()
            quick_action_bar.setObjectName("sessionQuickBar")
            quick_action_row = QHBoxLayout(quick_action_bar)
            quick_action_row.setContentsMargins(8, 4, 8, 4)
            quick_action_row.setSpacing(4)
            self.session_jump_combo = QComboBox()
            self.session_jump_combo.setObjectName("sessionJumpCombo")
            self.session_jump_combo.setMinimumWidth(240)
            self.session_jump_combo.setMaximumWidth(360)
            self.session_jump_combo.setToolTip("快速跳转到已打开的终端会话")
            quick_action_row.addWidget(self.session_jump_combo)
            quick_action_row.addStretch(1)
            self.quick_telnet_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_telnet_button,
                "terminal",
                "连接设备 Telnet",
            )
            self.quick_ssh_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_ssh_button,
                "ssh",
                "连接 Linux SSH",
            )
            self.quick_serial_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_serial_button,
                "serial",
                "连接串口 Telnet（占用后可用）",
            )
            self.quick_occupancy_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_occupancy_button,
                "owner",
                "占用 / 释放",
            )
            self.quick_power_off_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_power_off_button,
                "power",
                "掉电当前占用设备",
                danger=True,
            )
            self.quick_reconnect_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_reconnect_button,
                "refresh",
                "重连当前会话",
            )
            self.quick_log_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_log_button,
                "log",
                "打开当前会话日志",
            )
            self.quick_disconnect_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_disconnect_button,
                "disconnect",
                "断开当前会话",
                danger=True,
            )
            quick_action_row.addWidget(self.quick_telnet_button)
            quick_action_row.addWidget(self.quick_ssh_button)
            quick_action_row.addWidget(self.quick_serial_button)
            quick_action_row.addSpacing(6)
            quick_action_row.addWidget(self.quick_occupancy_button)
            quick_action_row.addWidget(self.quick_power_off_button)
            quick_action_row.addWidget(self.quick_reconnect_button)
            quick_action_row.addWidget(self.quick_log_button)
            quick_action_row.addSpacing(6)
            quick_action_row.addWidget(self.quick_disconnect_button)
            layout.addWidget(quick_action_bar)
            layout.addWidget(self._build_command_record_panel())
            self.refresh_workspace_context()
            self.update_center_stage_state()
            return panel

        def _build_right_panel(self) -> QWidget:
            scroll = QScrollArea()
            scroll.setObjectName("inspectorScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setMaximumWidth(400)

            panel = QWidget()
            panel.setObjectName("inspectorRail")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 8, 0)
            layout.setSpacing(8)

            detail_group = QGroupBox("当前设备")
            detail_group.setObjectName("deviceDetailCard")
            detail_layout = QVBoxLayout(detail_group)
            detail_layout.setContentsMargins(10, 12, 10, 10)
            detail_layout.setSpacing(6)
            self.device_summary_card = QLabel("请选择一台设备。")
            self.device_summary_card.setObjectName("detailCard")
            self.device_summary_card.setWordWrap(True)
            self.device_summary_card.setTextFormat(Qt.RichText)
            detail_layout.addWidget(self.device_summary_card)
            layout.addWidget(detail_group)

            action_group = QGroupBox("快捷动作")
            action_group.setObjectName("quickActionCard")
            action_layout = QVBoxLayout(action_group)
            action_layout.setContentsMargins(10, 12, 10, 10)
            action_layout.setSpacing(6)
            self.open_device_button = QPushButton("连接设备 Telnet")
            self.open_device_button.setObjectName("primaryButton")
            self.open_linux_button = QPushButton("连接 Linux SSH")
            self.open_linux_button.setObjectName("primaryButton")
            self.toggle_occupancy_button = QPushButton("占用 / 释放")
            self.toggle_occupancy_button.setObjectName("ghostButton")
            self.open_device_button.setMinimumHeight(34)
            self.open_linux_button.setMinimumHeight(34)
            self.toggle_occupancy_button.setMinimumHeight(32)
            action_layout.addWidget(self.open_device_button)
            action_layout.addWidget(self.open_linux_button)
            action_layout.addWidget(self.toggle_occupancy_button)
            layout.addWidget(action_group)

            auth_group = QGroupBox("连接参数")
            auth_group.setObjectName("authCard")
            auth_layout = QVBoxLayout(auth_group)
            auth_layout.setSpacing(6)

            device_form_group = QGroupBox("设备 Telnet")
            device_form = QFormLayout(device_form_group)
            device_form.setContentsMargins(8, 10, 8, 8)
            device_form.setVerticalSpacing(6)
            device_form.setHorizontalSpacing(6)
            device_form.setLabelAlignment(Qt.AlignRight)
            self.device_username_input = QLineEdit()
            self.device_password_input = QLineEdit()
            device_form.addRow("用户名", self.device_username_input)
            device_form.addRow("密码", self.device_password_input)


            linux_form_group = QGroupBox("Linux SSH")
            linux_form = QFormLayout(linux_form_group)
            linux_form.setContentsMargins(8, 10, 8, 8)
            linux_form.setVerticalSpacing(6)
            linux_form.setHorizontalSpacing(6)
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
            frame.setMinimumHeight(self.COMMAND_RECORD_MIN_HEIGHT)
            frame.setMaximumHeight(self.COMMAND_RECORD_MAX_HEIGHT)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self.command_record_resize_handle = CommandRecordResizeHandle(
                self.resize_command_record_panel,
                frame,
            )
            layout.addWidget(self.command_record_resize_handle)

            hint_bar = QFrame()
            hint_bar.setObjectName("commandRecordHintBar")
            hint_bar.setFixedHeight(22)
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
            footer.setFixedHeight(24)
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
            table.setAlternatingRowColors(False)
            table.setShowGrid(False)
            table.setWordWrap(False)
            table.setMouseTracking(True)
            table.setItemDelegate(NoFocusItemDelegate(table))
            table.verticalHeader().setVisible(False)
            table.verticalHeader().setDefaultSectionSize(32)
            header = table.horizontalHeader()
            header.setFixedHeight(28)
            header.setStretchLastSection(False)
            header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.setHighlightSections(False)
            header.setSectionsClickable(False)
            if len(headers) == 5:
                header.setSectionResizeMode(0, QHeaderView.Interactive)
                header.setSectionResizeMode(1, QHeaderView.Stretch)
                for column in range(2, len(headers)):
                    header.setSectionResizeMode(column, QHeaderView.Interactive)
            else:
                header.setSectionResizeMode(0, QHeaderView.Stretch)
                for column in range(1, len(headers)):
                    header.setSectionResizeMode(column, QHeaderView.Interactive)
            if len(headers) == 5:
                table.setColumnWidth(0, 56)
                table.setColumnWidth(2, 96)
                table.setColumnWidth(3, 78)
                table.setColumnWidth(4, 74)
            elif len(headers) == 4:
                table.setColumnWidth(1, 96)
                table.setColumnWidth(2, 78)
                table.setColumnWidth(3, 74)
            elif len(headers) == 3:
                table.setColumnWidth(1, 96)
                table.setColumnWidth(2, 74)
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
            self.cpu_input.textChanged.connect(self.schedule_apply_filters)
            self.my_occupancy_filter_button.toggled.connect(self.set_my_occupancy_filter)

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
            self.quick_serial_button.clicked.connect(self.open_serial_session)
            self.quick_occupancy_button.clicked.connect(self.toggle_occupancy)
            self.quick_power_off_button.clicked.connect(self.power_off_selected_device)
            self.quick_reconnect_button.clicked.connect(self.reconnect_current_session)
            self.quick_log_button.clicked.connect(self.open_current_session_log)
            self.quick_disconnect_button.clicked.connect(self.disconnect_current_session)
            self.session_jump_combo.activated.connect(self.handle_session_jump_activated)
            self.command_send_button.clicked.connect(self.submit_current_command_record)
            self.command_broadcast_button.clicked.connect(self.broadcast_command_record_input)
            self.command_clear_button.clicked.connect(self.clear_current_command_record)
            self.command_enter_mode_button.clicked.connect(self.toggle_command_enter_mode)
            self.command_record_toggle_button.clicked.connect(self.toggle_command_record_panel)
            self.connection_params_toggle_button.clicked.connect(self.toggle_connection_params)

            self.session_tab_widget.currentChanged.connect(self.handle_session_tab_changed)
            self.session_tab_widget.tabCloseRequested.connect(self.close_device_tab_at_index)

        def sync_left_search(self, value: str) -> None:
            del value
            self.schedule_apply_filters()

        def schedule_apply_filters(self) -> None:
            self.filter_timer.start()

        def clear_filters(self) -> None:
            self.search_input.clear()
            self.domain_combo.setCurrentText(ALL_DOMAINS)
            self.status_combo.setCurrentText(ALL_STATUS)
            self.cpu_input.clear()
            self.my_occupancy_filter_enabled = False
            self.my_occupancy_filter_button.blockSignals(True)
            self.my_occupancy_filter_button.setChecked(False)
            self.my_occupancy_filter_button.blockSignals(False)
            self.apply_filters()

        def set_my_occupancy_filter(self, enabled: bool) -> None:
            self.my_occupancy_filter_enabled = enabled
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

        def default_log_directory(self) -> Path:
            return self.state_path.parent / "logs"

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
            try:
                state_version = int(payload.get("version", 0))
            except (TypeError, ValueError):
                state_version = 0

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
            self.command_record_collapsed = bool(payload.get("command_record_collapsed", True))
            if state_version < 3:
                self.command_record_collapsed = True
            self.command_enter_sends = bool(payload.get("command_enter_sends", False))
            try:
                loaded_command_height = int(
                    payload.get("command_record_height", self.COMMAND_RECORD_DEFAULT_HEIGHT)
                )
            except (TypeError, ValueError):
                loaded_command_height = self.COMMAND_RECORD_DEFAULT_HEIGHT
            self.command_record_height = self.clamp_command_record_height(loaded_command_height)
            self.connection_params_collapsed = bool(payload.get("connection_params_collapsed", True))
            self.left_sidebar_collapsed = bool(payload.get("left_sidebar_collapsed", False))
            loaded_log_directory = str(payload.get("log_directory") or "").strip()
            if loaded_log_directory:
                self.log_directory = Path(loaded_log_directory).expanduser()

        def schedule_desktop_state_save(self) -> None:
            if hasattr(self, "state_save_timer"):
                self.state_save_timer.start(1200)

        def save_desktop_state(self) -> None:
            try:
                self._save_current_command_content()
                payload = {
                    "version": DESKTOP_STATE_VERSION,
                    "command_record_groups": self.command_record_groups,
                    "current_command_group": self.current_command_group_index(),
                    "command_record_collapsed": self.command_record_collapsed,
                    "command_enter_sends": self.command_enter_sends,
                    "command_record_height": self.command_record_height,
                    "connection_params_collapsed": self.connection_params_collapsed,
                    "left_sidebar_collapsed": self.left_sidebar_collapsed,
                    "log_directory": str(self.log_directory),
                }
                serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                if serialized == self._last_desktop_state_payload:
                    return
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
                temp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                temp_path.replace(self.state_path)
                self._last_desktop_state_payload = serialized
            except OSError as exc:
                if self.statusBar() is not None:
                    self.statusBar().showMessage(f"桌面状态保存失败: {exc}")

        def session_log_path(self, device: Device, title: str, kind: str) -> Path:
            timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            device_name = self.safe_log_component(device.name or device.id, "device")
            session_name = self.safe_log_component(title, "session")
            kind_name = "serial" if kind == "serial" else ("telnet" if kind == "device" else "ssh")
            filename = f"{timestamp}_{device_name}_{kind_name}_{session_name}.log"
            return self.unique_log_path(self.log_directory.expanduser() / filename)

        def unique_log_path(self, path: Path) -> Path:
            if not path.exists():
                return path
            counter = 2
            while True:
                candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
                if not candidate.exists():
                    return candidate
                counter += 1

        def safe_log_component(self, value: str, fallback: str) -> str:
            safe_chars: list[str] = []
            for char in value.strip():
                if char.isalnum() or char in {"-", "_", "."}:
                    safe_chars.append(char)
                elif safe_chars and safe_chars[-1] != "-":
                    safe_chars.append("-")
            safe = "".join(safe_chars).strip("-._")
            return (safe or fallback)[:80]

        def write_session_log_line(self, state: SessionTabState, channel: str, text: str) -> None:
            self.write_session_log(state, channel, f"{text}\n", separate_record=True)

        def write_session_log(
            self,
            state: SessionTabState,
            channel: str,
            text: str,
            *,
            separate_record: bool = False,
        ) -> None:
            if channel == "IN":
                return
            sanitized = self.sanitize_log_text(text)
            if not sanitized:
                return
            if channel == "SYS":
                sanitized = f"# {sanitized}"
            state.log_pending_records.append((channel, sanitized, separate_record))
            if separate_record or len(sanitized) >= self.LOG_FLUSH_IMMEDIATE_CHARS:
                self.flush_session_log_state(state)
            else:
                self.schedule_session_log_flush()

        def schedule_session_log_flush(self) -> None:
            if not self.log_flush_timer.isActive():
                self.log_flush_timer.start(self.LOG_FLUSH_INTERVAL_MS)

        def flush_pending_session_logs(self) -> None:
            for state in list(self.session_tabs_by_id.values()):
                self.flush_session_log_state(state)

        def flush_session_log_state(self, state: SessionTabState) -> None:
            if not state.log_pending_records:
                return
            try:
                state.log_path.parent.mkdir(parents=True, exist_ok=True)
                with state.log_path.open("a", encoding="utf-8", newline="") as log_file:
                    for channel, sanitized, separate_record in state.log_pending_records:
                        if separate_record and not state.log_at_line_start:
                            log_file.write("\n")
                            state.log_at_line_start = True
                        for segment in sanitized.splitlines(keepends=True):
                            if channel != "SYS" and state.log_at_line_start and not segment.strip():
                                continue
                            if state.log_at_line_start:
                                log_file.write(f"[{self.log_timestamp()}] ")
                            log_file.write(segment)
                            state.log_at_line_start = segment.endswith("\n")
                state.log_pending_records.clear()
            except OSError as exc:
                self.set_status_message(f"Log write failed: {exc}")

        def finish_session_log_record(self, state: SessionTabState) -> None:
            self.flush_session_log_state(state)
            if state.log_at_line_start:
                return
            try:
                state.log_path.parent.mkdir(parents=True, exist_ok=True)
                with state.log_path.open("a", encoding="utf-8", newline="") as log_file:
                    log_file.write("\n")
                state.log_at_line_start = True
            except OSError as exc:
                self.set_status_message(f"日志写入失败: {exc}")

        @staticmethod
        def sanitize_log_text(text: str) -> str:
            sanitized = ANSI_ESCAPE_RE.sub("", text)
            sanitized = sanitized.replace("\r\n", "\n").replace("\r", "\n")
            return "".join(char if char == "\n" or char == "\t" or char >= " " else "" for char in sanitized)

        @staticmethod
        def log_timestamp() -> str:
            return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        def log_session_input(self, state: SessionTabState, text: str) -> None:
            del state, text

        @staticmethod
        def skip_escape_sequence(text: str, index: int) -> int:
            if index + 1 >= len(text) or text[index + 1] != "[":
                return index + 1
            end = index + 2
            while end < len(text) and not ("@" <= text[end] <= "~"):
                end += 1
            return min(end + 1, len(text))

        def flush_session_input_log(self, state: SessionTabState) -> None:
            command = state.log_input_buffer.rstrip()
            state.log_input_buffer = ""
            if command:
                self.write_session_log_line(state, "IN", command)

        def open_session_log(self, state: SessionTabState) -> None:
            self.finish_session_log_record(state)
            self.open_local_path(state.log_path, "日志文件", is_directory=False)

        def open_session_log_directory(self, state: SessionTabState) -> None:
            self.finish_session_log_record(state)
            self.open_local_path(state.log_path.parent, "日志目录", is_directory=True)

        def open_local_path(self, path: Path, label: str, *, is_directory: bool) -> None:
            try:
                if is_directory:
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                if not is_directory and not path.exists():
                    path.touch()
            except OSError as exc:
                self.show_error(f"{label}准备失败: {exc}")
                return
            if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                self.set_status_message(f"已打开{label}: {path}")
                return
            self.show_warning(f"无法打开{label}: {path}")

        def change_log_directory(self) -> None:
            selected = QFileDialog.getExistingDirectory(
                self,
                "选择日志保存位置",
                str(self.log_directory.expanduser()),
            )
            if not selected:
                return
            new_directory = Path(selected).expanduser()
            try:
                new_directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.show_error(f"日志目录不可用: {exc}")
                return
            moved_count = self.move_active_session_logs(new_directory)
            self.log_directory = new_directory
            self.schedule_desktop_state_save()
            suffix = f"，已迁移 {moved_count} 个当前会话日志" if moved_count else ""
            self.set_status_message(f"日志位置已更改: {new_directory}{suffix}")

        def move_active_session_logs(self, new_directory: Path) -> int:
            moved_count = 0
            for state in self.session_tabs_by_id.values():
                old_path = state.log_path
                target_path = new_directory / old_path.name
                try:
                    same_path = old_path.resolve() == target_path.resolve()
                except OSError:
                    same_path = old_path == target_path
                if same_path:
                    continue
                new_path = self.unique_log_path(target_path)
                self.finish_session_log_record(state)
                try:
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    if old_path.exists():
                        shutil.move(str(old_path), str(new_path))
                        moved_count += 1
                    state.log_path = new_path
                    state.log_at_line_start = True
                    self.write_session_log_line(state, "SYS", f"Log location changed from {old_path}")
                except (OSError, shutil.Error) as exc:
                    self.set_status_message(f"日志迁移失败: {exc}")
            return moved_count

        def submit_command_record_input(self, command: str) -> None:
            self._save_current_command_content()
            self.schedule_desktop_state_save()
            self.send_command_text_to_current_session(command)

        def submit_current_command_record(self) -> None:
            command = self.command_record_input.current_command_line()
            if not command:
                self.set_status_message("请先将光标放到要发送的命令行。")
                return
            self.submit_command_record_input(command)

        def send_command_text_to_current_session(self, command: str) -> None:
            state = self.current_session_state()
            if state is None:
                self.set_status_message("命令已记录，当前没有打开的终端会话。")
                return
            self.send_session_text(state.tab_id, self.command_record_payload(command))
            self.command_record_input.setFocus()

        def broadcast_command_record_input(self) -> None:
            command = self.command_record_input.current_command_line()
            if not command:
                self.set_status_message("请先将光标放到要广播发送的命令行。")
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
                button.setToolTip("右键重命名")
                button.setProperty("commandGroupIndex", index)
                button.setContextMenuPolicy(Qt.CustomContextMenu)
                button.clicked.connect(lambda _checked=False, tab_index=index: self.switch_command_group(tab_index))
                button.customContextMenuRequested.connect(
                    lambda pos, tab_index=index, tab_button=button: self.show_command_group_context_menu(
                        tab_index,
                        tab_button,
                        pos,
                    )
                )
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

        def rename_command_group(self, index: int) -> None:
            if QInputDialog is None:
                return
            if index < 0 or index >= len(self.command_record_groups):
                return
            old_name = str(self.command_record_groups[index].get("name") or "").strip()
            new_name, ok = QInputDialog.getText(
                self,
                "重命名页签",
                "页签名称",
                QLineEdit.Normal,
                old_name,
            )
            if not ok:
                return
            name = new_name.strip()
            if not name or name == old_name:
                return
            existing_names = {
                str(group.get("name") or "").strip()
                for group_index, group in enumerate(self.command_record_groups)
                if group_index != index
            }
            if name in existing_names:
                self.show_warning("已存在同名页签。")
                return
            self._save_current_command_content()
            self.command_record_groups[index]["name"] = name
            current_index = self.current_command_group_index()
            self.rebuild_command_record_tabs()
            self.current_command_group = current_index
            self.refresh_command_tab_styles()
            self.set_status_message(f"已重命名常用命令页签: {name}")
            self.schedule_desktop_state_save()

        def show_command_group_context_menu(self, index: int, button: QToolButton, pos: Any) -> None:
            if index < 0 or index >= len(self.command_record_groups):
                return
            menu = QMenu(button)
            rename_action = menu.addAction("重命名")
            chosen = menu.exec(button.mapToGlobal(pos))
            if chosen == rename_action:
                self.rename_command_group(index)

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
                "常用命令"
                if self.command_record_collapsed
                else (
                    "常用命令  ·  Enter 发送"
                    if self.command_enter_sends
                    else "常用命令  ·  Ctrl+Enter 发送"
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
            will_expand = self.command_record_collapsed
            self.command_record_collapsed = not self.command_record_collapsed
            self.apply_command_record_panel_state(focus_editor=will_expand)
            self.schedule_desktop_state_save()

        def clamp_command_record_height(self, height: int) -> int:
            return max(self.COMMAND_RECORD_MIN_HEIGHT, min(self.COMMAND_RECORD_MAX_HEIGHT, height))

        def resize_command_record_panel(self, height: int) -> None:
            if self.command_record_collapsed:
                return
            self.command_record_height = self.clamp_command_record_height(height)
            self.apply_command_record_panel_state()
            self.schedule_desktop_state_save()

        def toggle_connection_params(self) -> None:
            self.connection_params_collapsed = not self.connection_params_collapsed
            self.apply_connection_params_state()
            self.schedule_desktop_state_save()

        def expand_connection_params(self) -> None:
            if not self.connection_params_collapsed:
                return
            self.connection_params_collapsed = False
            self.apply_connection_params_state()
            self.schedule_desktop_state_save()

        def toggle_left_sidebar(self) -> None:
            self.left_sidebar_collapsed = not self.left_sidebar_collapsed
            self.apply_left_sidebar_state()
            self.schedule_desktop_state_save()

        def apply_left_sidebar_state(self, *, animated: bool = False) -> None:
            if not hasattr(self, "left_sidebar_content"):
                return
            collapsed = self.left_sidebar_collapsed
            if (
                animated
                and QVariantAnimation is not None
            ):
                self.animate_left_sidebar_state(collapsed)
            else:
                self.left_sidebar_content.setVisible(not collapsed)
                self.left_sidebar_content.setMinimumWidth(0 if collapsed else 420)
                self.left_sidebar_content.setMaximumWidth(0 if collapsed else 520)
                if hasattr(self, "left_sidebar_layout"):
                    self.left_sidebar_layout.setContentsMargins(0, 0, 0 if collapsed else 8, 0)
                    self.left_sidebar_layout.setSpacing(0 if collapsed else 8)
                if hasattr(self, "left_sidebar_shell"):
                    self.left_sidebar_shell.setMinimumWidth(46 if collapsed else 480)
                    self.left_sidebar_shell.setMaximumWidth(46 if collapsed else 580)
                    self.left_sidebar_shell.updateGeometry()
                splitter = getattr(self, "main_splitter", None)
                if splitter is not None:
                    sizes = splitter.sizes()
                    total = sum(sizes) if len(sizes) >= 2 else 0
                    left_width = 46 if collapsed else 520
                    if total > 0:
                        splitter.setSizes([left_width, max(1, total - left_width)])
            if hasattr(self, "activity_device_button"):
                self.activity_device_button.setChecked(not collapsed)
                self.activity_device_button.setToolTip("显示设备导航" if collapsed else "隐藏设备导航")
                self.activity_device_button.setIcon(
                    self._activity_icon("devices", "#808080" if collapsed else "#ededed")
                )

        def animate_left_sidebar_state(self, collapsed: bool) -> None:
            if not hasattr(self, "left_sidebar_shell"):
                return
            if self.left_sidebar_animation is not None:
                self.left_sidebar_animation.stop()

            shell = self.left_sidebar_shell
            content = self.left_sidebar_content
            if hasattr(self, "left_sidebar_layout"):
                self.left_sidebar_layout.setContentsMargins(0, 0, 0 if collapsed else 8, 0)
                self.left_sidebar_layout.setSpacing(0 if collapsed else 8)

            splitter = getattr(self, "main_splitter", None)
            splitter_sizes = splitter.sizes() if splitter is not None else []
            splitter_total = sum(splitter_sizes) if len(splitter_sizes) >= 2 else 0
            start_width = splitter_sizes[0] if len(splitter_sizes) >= 2 else max(46, shell.width())
            end_width = 46 if collapsed else 520

            content.setVisible(True)
            content.setMinimumWidth(0)
            shell.setMinimumWidth(46)
            shell.setMaximumWidth(580)
            animation = QVariantAnimation(self)
            easing = QEasingCurve.OutCubic if QEasingCurve is not None else None
            animation.setDuration(180)
            animation.setStartValue(start_width)
            animation.setEndValue(end_width)
            if easing is not None:
                animation.setEasingCurve(easing)

            def apply_width(value: Any) -> None:
                width = max(46, int(value))
                content_width = max(0, width - 54)
                content.setMaximumWidth(content_width)
                shell.setMinimumWidth(width)
                shell.setMaximumWidth(width)
                shell.updateGeometry()
                if splitter is not None and splitter_total > 0:
                    splitter.setSizes([width, max(1, splitter_total - width)])

            animation.valueChanged.connect(apply_width)

            def finish() -> None:
                content.setMinimumWidth(0 if collapsed else 420)
                content.setMaximumWidth(0 if collapsed else 520)
                content.setVisible(not collapsed)
                shell.setMinimumWidth(46 if collapsed else 480)
                shell.setMaximumWidth(46 if collapsed else 580)
                shell.updateGeometry()
                if splitter is not None and splitter_total > 0:
                    splitter.setSizes([end_width, max(1, splitter_total - end_width)])
                if self.left_sidebar_animation is animation:
                    self.left_sidebar_animation = None

            animation.finished.connect(finish)
            self.left_sidebar_animation = animation
            animation.start()

        def apply_connection_params_state(self) -> None:
            if not hasattr(self, "connection_params_body"):
                return
            collapsed = self.connection_params_collapsed
            self.connection_params_body.setVisible(not collapsed)
            self.connection_params_toggle_button.setText("展开" if collapsed else "收起")
            if hasattr(self, "connection_params_group"):
                self.connection_params_group.setMinimumHeight(54 if collapsed else 0)
                self.connection_params_group.setMaximumHeight(64 if collapsed else 16777215)
                self.connection_params_group.updateGeometry()

        def apply_command_record_panel_state(self, focus_editor: bool = False) -> None:
            collapsed = self.command_record_collapsed
            self.command_record_resize_handle.setVisible(not collapsed)
            self.command_record_input.setVisible(not collapsed)
            self.command_record_footer.setVisible(not collapsed)
            self.command_enter_mode_button.setVisible(not collapsed)
            target_height = (
                self.COMMAND_RECORD_COLLAPSED_HEIGHT
                if collapsed
                else self.clamp_command_record_height(self.command_record_height)
            )
            self.command_record_frame.setMinimumHeight(target_height)
            self.command_record_frame.setMaximumHeight(target_height)
            self.command_record_frame.updateGeometry()
            self.command_record_toggle_button.setText("展开" if collapsed else "收起")
            self.update_command_enter_mode()
            if collapsed:
                self.set_status_message("常用命令区域已隐藏。")
            else:
                self._load_current_command_content(move_cursor_to_end=False)
                if focus_editor:
                    self.command_record_input.setFocus()

        def dispatch_ui(self, callback: Callable[..., None], *args: object) -> None:
            self.ui_queue.put((callback, args))

        def _drain_ui_queue(self) -> None:
            processed = 0
            deadline = time.monotonic() + 0.012
            while processed < 48 and time.monotonic() < deadline:
                try:
                    callback, args = self.ui_queue.get_nowait()
                except queue.Empty:
                    break
                callback(*args)
                processed += 1

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
            self.pending_futures.add(future)

            def done(completed: Future) -> None:
                self.pending_futures.discard(completed)
                try:
                    result = completed.result()
                except FutureCancelledError:
                    return
                except Exception as exc:
                    if self.closed:
                        return
                    self.dispatch_ui(on_error or self.handle_background_error, exc)
                    return
                if on_success is not None and not self.closed:
                    self.dispatch_ui(on_success, result)

            future.add_done_callback(done)

        def cancel_pending_futures(self) -> None:
            for future in list(self.pending_futures):
                future.cancel()
            self.pending_futures.clear()

        def refresh_snapshot(self) -> None:
            if self.loading_snapshot:
                return

            self.loading_snapshot = True
            self.set_status_message("正在刷新设备数据...")
            self.refresh_generation += 1
            generation = self.refresh_generation

            def load_snapshot() -> RepositorySnapshot:
                with self.repository_lock:
                    devices = self.repository.fetch_devices()
                    owned_device_ids = self.repository.fetch_owned_device_ids()
                    current_user = self.repository.current_user()
                return RepositorySnapshot(
                    current_user=current_user,
                    devices=devices,
                    owned_device_ids=owned_device_ids,
                )

            def apply_snapshot(result: object) -> None:
                snapshot = result
                if not isinstance(snapshot, RepositorySnapshot) or generation != self.refresh_generation:
                    return
                self.loading_snapshot = False
                self.current_user = snapshot.current_user
                self.devices = snapshot.devices
                self.owned_device_ids = snapshot.owned_device_ids
                self.device_by_id = {device.id: device for device in self.devices}
                self.search_index = {device.id: build_search_text(device) for device in self.devices}
                self._last_device_table_signature = ()
                self._last_owned_table_signature = ()
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
            if hasattr(self, "filter_timer"):
                self.filter_timer.stop()
            search_text = self.search_input.text().strip().lower()
            domain_filter = self.domain_combo.currentText().strip()
            status_filter = self.status_combo.currentText().strip()
            cpu_filter = self.cpu_input.text().strip().lower()
            my_occupancy_filter = self.my_occupancy_filter_enabled

            visible_devices: list[Device] = []
            status_counts = {
                STATUS_IDLE: 0,
                STATUS_OCCUPIED: 0,
                STATUS_PIPELINE: 0,
                STATUS_OTHER: 0,
            }
            for device in self.devices:
                if search_text and search_text not in self.device_search_text(device):
                    continue
                if domain_filter != ALL_DOMAINS and device.domain != domain_filter:
                    continue
                if status_filter != ALL_STATUS and device.status != status_filter:
                    continue
                if cpu_filter and cpu_filter not in device.cpu.lower():
                    continue
                if my_occupancy_filter and not self.is_my_occupied_device(device):
                    continue
                visible_devices.append(device)
                if device.status in status_counts:
                    status_counts[device.status] += 1

            self.visible_devices = visible_devices
            self.visible_status_counts = status_counts
            self.owned_visible_devices = [
                device for device in visible_devices if self.is_my_occupied_device(device)
            ]

            self.refresh_my_occupancy_filter_button()
            self.refresh_filter_summary()
            self.refresh_stats()
            self.refresh_device_table()
            self.refresh_owned_table()
            self.ensure_valid_selection()
            self.refresh_device_context()
            self.refresh_workspace_context()
            self.update_controls()

        def refresh_stats(self) -> None:
            total = len(self.visible_devices)
            idle = self.visible_status_counts.get(STATUS_IDLE, 0)
            occupied = self.visible_status_counts.get(STATUS_OCCUPIED, 0)
            pipeline = self.visible_status_counts.get(STATUS_PIPELINE, 0)
            other = self.visible_status_counts.get(STATUS_OTHER, 0)
            self.stats_label.setText(
                " ".join(
                    [
                        self.stat_chip_html("设备", total, "#ededed"),
                        self.stat_chip_html("空闲", idle, "#3cc98e"),
                        self.stat_chip_html("占用", occupied, "#f5a623"),
                        self.stat_chip_html("流水线", pipeline, "#5b6ef5"),
                        self.stat_chip_html("其他", other, "#808080"),
                    ]
                )
            )

        def stat_chip_html(self, label: str, value: int, color: str) -> str:
            return (
                f"<span style='color:{color};font-weight:800'>{html.escape(label)} {value}</span>"
            )

        def refresh_my_occupancy_filter_button(self) -> None:
            if not hasattr(self, "my_occupancy_filter_button"):
                return
            owned_count = self.my_occupancy_count()
            self.my_occupancy_filter_button.setText(f"我的 {owned_count}")
            self.my_occupancy_filter_button.setEnabled(self.owned_device_ids is not None or bool(self.current_user))
            self.my_occupancy_filter_button.setToolTip(
                "只显示我的占用 API 返回的设备"
                if self.owned_device_ids is not None
                else (
                    f"只显示 {self.current_user} 占用的设备"
                    if self.current_user
                    else "当前用户尚未从 API 加载"
                )
            )

        def my_occupancy_count(self) -> int:
            if self.owned_device_ids is not None:
                return len(self.owned_device_ids)
            if not self.current_user:
                return 0
            return sum(1 for device in self.devices if device.owner == self.current_user)

        def is_my_occupied_device(self, device: Device) -> bool:
            if self.owned_device_ids is not None:
                return device.id in self.owned_device_ids
            return bool(self.current_user and device.owner == self.current_user)

        def can_power_off_device(self, device: Device) -> bool:
            return bool(device.supports_power_off and self.is_my_occupied_device(device))

        def cancel_table_render_jobs(self) -> None:
            self._table_render_generation += 1
            self._table_render_jobs.clear()
            if hasattr(self, "table_render_timer"):
                self.table_render_timer.stop()

        def enqueue_table_render_job(
            self,
            table: QTableWidget,
            devices: list[Device],
            keyword: str,
            kind: str,
            generation: int,
            start_row: int,
        ) -> None:
            if start_row >= len(devices):
                return
            self._table_render_jobs.append(
                {
                    "table": table,
                    "devices": devices,
                    "keyword": keyword,
                    "kind": kind,
                    "generation": generation,
                    "row": start_row,
                }
            )
            if not self.table_render_timer.isActive():
                self.table_render_timer.start(0)

        def process_table_render_jobs(self) -> None:
            frame_started = time.perf_counter()
            while self._table_render_jobs:
                job = self._table_render_jobs[0]
                if job.get("generation") != self._table_render_generation:
                    self._table_render_jobs.pop(0)
                    continue
                table = job["table"]
                if not isinstance(table, QTableWidget):
                    self._table_render_jobs.pop(0)
                    continue
                table.setUpdatesEnabled(False)
                try:
                    self.render_table_job_rows(job, max_rows=180)
                finally:
                    table.setUpdatesEnabled(True)
                if int(job["row"]) >= len(job["devices"]):
                    self._table_render_jobs.pop(0)
                if (time.perf_counter() - frame_started) >= 0.008:
                    break
            if self._table_render_jobs:
                self.table_render_timer.start(0)

        def render_table_job_rows(self, job: dict[str, object], max_rows: int) -> None:
            devices = job["devices"]
            if not isinstance(devices, list):
                return
            keyword = str(job["keyword"])
            kind = str(job["kind"])
            row = int(job["row"])
            end_row = min(len(devices), row + max_rows)
            for current_row in range(row, end_row):
                device = devices[current_row]
                if kind == "owned":
                    self.render_owned_table_row(current_row, device, keyword)
                else:
                    self.render_device_table_row(current_row, device, keyword)
            job["row"] = end_row

        def render_device_table_row(self, row: int, device: Device, keyword: str) -> None:
            hidden_keyword_match = self.device_matches_hidden_keyword(
                device,
                keyword,
                visible_values=(device.board_id, device.name, device.domain, device.cpu, device.status),
            )
            self._set_table_item(
                self.device_table,
                row,
                0,
                device.board_id,
                device.id,
                highlight=self.text_matches_keyword(device.board_id, keyword),
            )
            self._set_table_item(
                self.device_table,
                row,
                1,
                device.name,
                device.id,
                highlight=hidden_keyword_match or self.text_matches_keyword(device.name, keyword),
            )
            self._set_table_item(
                self.device_table,
                row,
                2,
                device.domain,
                device.id,
                highlight=self.text_matches_keyword(device.domain, keyword),
            )
            self._set_table_item(
                self.device_table,
                row,
                3,
                device.cpu,
                device.id,
                highlight=self.text_matches_keyword(device.cpu, keyword),
            )
            self._set_table_item(
                self.device_table,
                row,
                4,
                device.status,
                device.id,
                color=status_color(device.status),
                highlight=self.text_matches_keyword(device.status, keyword),
            )

        def render_owned_table_row(self, row: int, device: Device, keyword: str) -> None:
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

        def refresh_device_table(self) -> None:
            keyword = self.search_input.text().strip().lower()
            signature = (
                keyword,
                tuple(
                    (device.id, device.board_id, device.name, device.domain, device.cpu, device.status)
                    for device in self.visible_devices
                ),
            )
            if signature == self._last_device_table_signature:
                return
            self._last_device_table_signature = signature
            self.cancel_table_render_jobs()
            generation = self._table_render_generation
            table = self.device_table
            table.setUpdatesEnabled(False)
            table.blockSignals(True)
            try:
                table.setRowCount(len(self.visible_devices))
                self.device_table_rows = {}
                for row, device in enumerate(self.visible_devices):
                    self.device_table_rows[device.id] = row
                sync_rows = min(80, len(self.visible_devices))
                for row in range(sync_rows):
                    self.render_device_table_row(row, self.visible_devices[row], keyword)
            finally:
                table.blockSignals(False)
                table.setUpdatesEnabled(True)
            self.enqueue_table_render_job(
                table,
                self.visible_devices,
                keyword,
                "device",
                generation,
                sync_rows,
            )

        def refresh_owned_table(self) -> None:
            if not hasattr(self, "owned_table"):
                self.owned_visible_devices = []
                return
            keyword = self.search_input.text().strip().lower()
            self.owned_count_label.setText(str(len(self.owned_visible_devices)))
            signature = (
                keyword,
                tuple(
                    (device.id, device.name, device.domain, device.status)
                    for device in self.owned_visible_devices
                ),
            )
            if signature == self._last_owned_table_signature:
                return
            self._last_owned_table_signature = signature
            table = self.owned_table
            table.setUpdatesEnabled(False)
            table.blockSignals(True)
            try:
                table.setRowCount(len(self.owned_visible_devices))
                self.owned_table_rows = {}
                for row, device in enumerate(self.owned_visible_devices):
                    self.owned_table_rows[device.id] = row
                sync_rows = min(60, len(self.owned_visible_devices))
                for row in range(sync_rows):
                    self.render_owned_table_row(row, self.owned_visible_devices[row], keyword)
            finally:
                table.blockSignals(False)
                table.setUpdatesEnabled(True)
            self.enqueue_table_render_job(
                table,
                self.owned_visible_devices,
                keyword,
                "owned",
                self._table_render_generation,
                sync_rows,
            )

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
            item = table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                table.setItem(row, column, item)
            if item.text() != text:
                item.setText(text)
            if item.data(Qt.UserRole) != device_id:
                item.setData(Qt.UserRole, device_id)
            if item.toolTip() != text:
                item.setToolTip(text)
            item.setBackground(QBrush())
            item.setForeground(QBrush())
            font = item.font()
            if font.bold():
                font.setBold(False)
                item.setFont(font)
            if color:
                item.setForeground(QBrush(QColor(color)))
            if highlight:
                item.setBackground(QBrush(QColor("#1c1c1c")))
                item.setForeground(QBrush(QColor("#ededed")))
                font = item.font()
                font.setBold(True)
                item.setFont(font)

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
            return self.device_by_id.get(device_id)

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
            row_map = self.owned_table_rows if hasattr(self, "owned_table") and table is self.owned_table else self.device_table_rows
            mapped_row = row_map.get(device_id)
            if mapped_row is not None and 0 <= mapped_row < table.rowCount():
                item = table.item(mapped_row, 0)
                if item is None:
                    table.selectRow(mapped_row)
                    table.blockSignals(False)
                    return
                if item.data(Qt.UserRole) == device_id:
                    table.selectRow(mapped_row)
                    table.scrollToItem(item)
                    table.blockSignals(False)
                    return
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and item.data(Qt.UserRole) == device_id:
                    table.selectRow(row)
                    table.scrollToItem(item)
                    break
            table.blockSignals(False)

        def get_selected_device(self) -> Device | None:
            if not self.selected_device_id:
                return None
            return self.get_device_by_id(self.selected_device_id)

        def get_quick_action_device(self) -> Device | None:
            state = self.current_session_state()
            if state is not None:
                device = self.get_device_by_id(state.device_id)
                if device is not None:
                    return device
            device_tab = self.current_device_tab_state()
            if device_tab is not None:
                device = self.get_device_by_id(device_tab.device_id)
                if device is not None:
                    return device
            return self.get_selected_device()

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
            return "\t".join([device.board_id, device.name, device.domain, device.cpu, device.status])

        def device_connection_copy_text(self, device: Device) -> str:
            serial_text = (
                f"{device.serial_ip}:{device.serial_port}"
                if self.can_view_serial_connection(device)
                else "占用后可见"
            )
            return (
                f"设备: {device.name}\n"
                f"Telnet: {device.telnet_ip}:{device.telnet_port}\n"
                f"Telnet 账号: {device.username}\n"
                f"Telnet 密码: {device.password}\n"
                f"串口: {serial_text}\n"
                f"SSH: {device.ssh_ip}:{device.ssh_port}\n"
                f"SSH 账号: {self.device_ssh_username(device)}\n"
                f"SSH 密码: {self.device_ssh_password(device)}"
            )

        def clone_telnet_session(self, device: Device) -> None:
            username = device.username.strip()
            password = device.password
            if not device.telnet_ip.strip() or not username or not password:
                self.show_warning("设备 Telnet 地址、用户名和密码不完整。")
                return
            self.ensure_session_tab(
                kind="device",
                device=device,
                host=device.telnet_ip.strip(),
                port=device.telnet_port,
                username=username,
                password=password,
            )

        def clone_ssh_session(self, device: Device) -> None:
            username = self.device_ssh_username(device).strip()
            password = self.device_ssh_password(device)
            if not device.ssh_ip.strip() or not username or not password:
                self.show_warning("设备 SSH 地址、用户名和密码不完整。")
                return
            self.ensure_session_tab(
                kind="linux",
                device=device,
                host=device.ssh_ip.strip(),
                port=device.ssh_port,
                username=username,
                password=password,
            )

        def clone_serial_session(self, device: Device) -> None:
            if not self.is_my_occupied_device(device):
                self.show_warning("请先占用设备后再连接串口。")
                self.set_status_message("串口连接需要先占用当前设备。")
                return
            if not device.serial_ip.strip():
                self.show_warning("当前设备未返回串口 IP 和端口，请刷新或检查接口数据。")
                self.set_status_message("串口地址不可用。")
                return
            username = self.device_serial_username(device).strip()
            password = self.device_serial_password(device)
            if not device.serial_ip.strip() or not username or not password:
                self.show_warning("设备串口地址、用户名和密码不完整。")
                return
            self.ensure_session_tab(
                kind="serial",
                device=device,
                host=device.serial_ip.strip(),
                port=device.serial_port,
                username=username,
                password=password,
            )

        def copy_device_field(self, device: Device, field: str) -> None:
            serial_endpoint = (
                f"{device.serial_ip}:{device.serial_port}"
                if self.can_view_serial_connection(device)
                else "占用后可见"
            )
            field_map = {
                "name": ("设备名", device.name),
                "ssh_ip": ("SSH IP", device.ssh_ip),
                "ssh_endpoint": ("SSH 地址", f"{device.ssh_ip}:{device.ssh_port}"),
                "telnet_ip": ("Telnet IP", device.telnet_ip),
                "telnet_endpoint": ("Telnet 地址", f"{device.telnet_ip}:{device.telnet_port}"),
                "serial_ip": ("串口 IP", device.serial_ip if self.can_view_serial_connection(device) else ""),
                "serial_endpoint": ("串口地址", serial_endpoint),
                "username": ("Telnet 账号", device.username),
                "password": ("Telnet 密码", device.password),
                "ssh_username": ("SSH 账号", self.device_ssh_username(device)),
                "ssh_password": ("SSH 密码", self.device_ssh_password(device)),
            }
            label, value = field_map[field]
            if field == "serial_ip" and not value:
                self.show_warning("请先占用设备后再查看串口 IP。")
                return
            self.copy_text_to_clipboard(value, f"已复制{label}: {value}")

        def device_ssh_username(self, device: Device) -> str:
            return device.ssh_username or device.username

        def device_ssh_password(self, device: Device) -> str:
            return device.ssh_password or device.password

        def device_serial_username(self, device: Device) -> str:
            return device.serial_username or device.username

        def device_serial_password(self, device: Device) -> str:
            return device.serial_password or device.password

        def can_view_serial_connection(self, device: Device) -> bool:
            return bool(device.serial_ip.strip() and self.is_my_occupied_device(device))

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

        def locate_device_in_list(self, device_id: str) -> None:
            device = self.get_device_by_id(device_id)
            if device is None:
                self.set_status_message("未找到当前会话对应的设备。")
                return
            visible_ids = {item.id for item in self.visible_devices}
            if device_id not in visible_ids:
                self.clear_filters()
            self.activate_device(device_id)
            self.device_table.setFocus()
            self.set_status_message(f"已定位到设备: {device.name}")

        def refresh_filter_summary(self) -> None:
            active_filters: list[str] = []
            search_text = self.search_input.text().strip()
            domain_filter = self.domain_combo.currentText().strip()
            status_filter = self.status_combo.currentText().strip()
            cpu_filter = self.cpu_input.text().strip()

            if search_text:
                active_filters.append(self.filter_chip_html("关键词", search_text))
            if self.my_occupancy_filter_enabled:
                label = self.current_user or "我的占用"
                active_filters.append(self.filter_chip_html("占用", label))
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
                f"<span style='color:#c0c0c0;font-weight:600;background:#181818;"
                f"padding:2px 6px;border-radius:4px'>{html.escape(label)}: {html.escape(value)}</span>"
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
            device = self.get_device_by_id(device_id)
            if device is None:
                return

            menu = QMenu(table)
            copy_ssh_ip_action = menu.addAction("复制 SSH IP")
            copy_telnet_ip_action = menu.addAction("复制 Telnet IP")
            copy_serial_ip_action = menu.addAction("复制串口 IP")
            copy_connection_action = menu.addAction("复制连接信息")
            menu.addSeparator()
            toggle_action = menu.addAction("占用 / 释放")
            power_off_action = menu.addAction("掉电")
            menu.addSeparator()
            open_device_action = menu.addAction("打开设备管理口")
            open_linux_action = menu.addAction("打开 Linux 后台")
            open_serial_action = menu.addAction("打开串口")
            serial_available = self.can_view_serial_connection(device)
            copy_serial_ip_action.setEnabled(serial_available)
            open_serial_action.setEnabled(serial_available)
            power_off_action.setEnabled(self.can_power_off_device(device))

            chosen = menu.exec(table.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            if chosen == copy_ssh_ip_action:
                self.copy_device_field(device, "ssh_ip")
                return
            if chosen == copy_telnet_ip_action:
                self.copy_device_field(device, "telnet_ip")
                return
            if chosen == copy_serial_ip_action:
                self.copy_device_field(device, "serial_ip")
                return
            if chosen == copy_connection_action:
                self.copy_text_to_clipboard(
                    self.device_connection_copy_text(device),
                    f"已复制连接信息: {device.name}",
                )
                return
            if chosen == toggle_action:
                self.toggle_occupancy(device)
                return
            if chosen == power_off_action:
                self.power_off_device(device)
                return
            if chosen == open_device_action:
                self.open_device_session(device)
                return
            if chosen == open_linux_action:
                self.open_linux_session(device)
                return
            if chosen == open_serial_action:
                self.open_serial_session(device)

        def show_terminal_context_menu(self, tab_id: str, terminal: InteractiveTerminal, pos: Any) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return
            device = self.get_device_by_id(state.device_id)
            if device is None:
                return

            menu = QMenu(terminal)
            copy_selection_action = None
            if terminal.textCursor().hasSelection():
                copy_selection_action = menu.addAction("复制选中文本")
                menu.addSeparator()
            actions = self._add_device_quick_actions(menu)
            log_actions = self._add_session_log_actions(menu)
            menu.addSeparator()
            split_actions = self._add_session_split_actions(menu)

            chosen = menu.exec(terminal.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            if copy_selection_action is not None and chosen == copy_selection_action:
                terminal.copy()
                return
            if self._handle_session_split_action(chosen, split_actions, tab_id):
                return
            if self._handle_session_log_action(chosen, log_actions, state):
                return
            self._handle_device_quick_action(chosen, actions, device)

        def show_device_quick_context_menu(self, device_id: str, widget: QWidget, pos: Any) -> None:
            device = self.get_device_by_id(device_id)
            if device is None:
                return
            menu = QMenu(widget)
            actions = self._add_device_quick_actions(menu)
            chosen = menu.exec(widget.mapToGlobal(pos))
            if chosen is None:
                return
            self._handle_device_quick_action(chosen, actions, device)

        def show_session_quick_context_menu(self, tab_id: str, widget: QWidget, pos: Any) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return
            device = self.get_device_by_id(state.device_id)
            if device is None:
                return
            menu = QMenu(widget)
            actions = self._add_device_quick_actions(menu)
            log_actions = self._add_session_log_actions(menu)
            menu.addSeparator()
            split_actions = self._add_session_split_actions(menu)
            chosen = menu.exec(widget.mapToGlobal(pos))
            if chosen is None:
                return
            if self._handle_session_split_action(chosen, split_actions, tab_id):
                return
            if self._handle_session_log_action(chosen, log_actions, state):
                return
            self._handle_device_quick_action(chosen, actions, device)

        def _add_session_split_actions(self, menu: QMenu) -> dict[str, Any]:
            return {
                "left": menu.addAction("向左分屏"),
                "right": menu.addAction("向右分屏"),
                "top": menu.addAction("向上分屏"),
                "bottom": menu.addAction("向下分屏"),
            }

        def _handle_session_split_action(
            self,
            chosen: Any,
            actions: dict[str, Any],
            tab_id: str,
        ) -> bool:
            for direction, action in actions.items():
                if chosen == action:
                    self.split_session(tab_id, direction)
                    return True
            return False

        def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802
            if QEvent is not None:
                event_type = event.type()
                if event_type == QEvent.MouseButtonPress and hasattr(watched, "property"):
                    if watched.property("sessionDragTabId"):
                        watched.setProperty("sessionDragStart", event.pos())
                elif event_type == QEvent.MouseMove and hasattr(watched, "property"):
                    tab_id = str(watched.property("sessionDragTabId") or "")
                    start_pos = watched.property("sessionDragStart")
                    if tab_id and start_pos is not None and event.buttons() & Qt.LeftButton:
                        distance = (event.pos() - start_pos).manhattanLength()
                        if distance >= QApplication.startDragDistance():
                            self.start_session_tab_drag(watched, tab_id)
                            return True
                elif event_type in {QEvent.DragEnter, QEvent.DragMove}:
                    if self.event_has_session_tab(event):
                        event.acceptProposedAction()
                        return True
                elif event_type == QEvent.Drop:
                    if self.handle_session_tab_drop(watched, event):
                        return True
            return super().eventFilter(watched, event)

        @staticmethod
        def event_has_session_tab(event: Any) -> bool:
            mime = event.mimeData()
            return bool(mime is not None and mime.hasFormat(SESSION_TAB_MIME))

        def start_session_tab_drag(self, source: QWidget, tab_id: str) -> None:
            if QDrag is None or QMimeData is None:
                return
            self._drag_session_tab_id = tab_id
            mime = QMimeData()
            mime.setData(SESSION_TAB_MIME, tab_id.encode("utf-8"))
            drag = QDrag(source)
            drag.setMimeData(mime)
            drag.exec(Qt.MoveAction)
            self._drag_session_tab_id = ""

        def handle_session_tab_drop(self, target: Any, event: Any) -> bool:
            if not self.event_has_session_tab(event):
                return False
            tab_id = bytes(event.mimeData().data(SESSION_TAB_MIME)).decode("utf-8")
            if tab_id not in self.session_tabs_by_id:
                return False
            direction = self.split_direction_for_drop(target, event)
            self.split_session(tab_id, direction)
            event.acceptProposedAction()
            return True

        @staticmethod
        def split_direction_for_drop(target: QWidget, event: Any) -> str:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            rect = target.rect()
            distances = {
                "left": max(0, pos.x() - rect.left()),
                "right": max(0, rect.right() - pos.x()),
                "top": max(0, pos.y() - rect.top()),
                "bottom": max(0, rect.bottom() - pos.y()),
            }
            return min(distances, key=distances.get)

        def split_session_to_right(self, tab_id: str) -> None:
            self.split_session(tab_id, "right")

        def split_session(self, tab_id: str, direction: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return
            device_tab = self.device_tabs_by_id.get(state.device_id)
            if device_tab is None or device_tab.session_splitter is None:
                return
            source_tabs = self.find_session_tab_widget(device_tab, state.page)
            if source_tabs is None:
                return
            horizontal = direction in {"left", "right"}
            device_tab.session_splitter.setOrientation(Qt.Horizontal if horizontal else Qt.Vertical)
            if len(self.session_tab_widgets_for_device(device_tab)) < 2:
                target_tabs = self.create_session_tab_widget(device_tab.device_id, device_tab.session_splitter)
                if direction in {"left", "top"}:
                    device_tab.session_splitter.insertWidget(0, target_tabs)
                    device_tab.session_tab_widgets.insert(0, target_tabs)
                else:
                    device_tab.session_splitter.addWidget(target_tabs)
                    device_tab.session_tab_widgets.append(target_tabs)
                device_tab.session_splitter.setSizes([1, 1])
            else:
                target_tabs = self.session_tab_widgets_for_device(device_tab)[0 if direction in {"left", "top"} else -1]
            if source_tabs is target_tabs:
                self.set_status_message("当前会话已经在目标分屏。")
                return
            source_index = source_tabs.indexOf(state.page)
            if source_index < 0:
                return
            source_tabs.removeTab(source_index)
            target_index = target_tabs.addTab(state.page, state.title)
            self._install_session_tab_header(target_tabs, target_index, state)
            target_tabs.setCurrentIndex(target_index)
            device_tab.active_session_tab_widget = target_tabs
            self.session_tab_widget.setCurrentWidget(device_tab.page)
            self._refresh_tab_header_styles()
            self.refresh_workspace_context()
            self.update_controls()
            state.terminal.setFocus()
            direction_label = {"left": "左侧", "right": "右侧", "top": "上方", "bottom": "下方"}.get(direction, "目标")
            self.set_status_message(f"已将会话移动到{direction_label}分屏: {state.title}")

        def _add_device_quick_actions(self, menu: QMenu) -> dict[str, Any]:
            actions = {
                "locate": menu.addAction("定位到设备列表"),
            }
            menu.addSeparator()
            actions["clone_telnet"] = menu.addAction("复制 Telnet")
            actions["clone_ssh"] = menu.addAction("复制 SSH")
            actions["clone_serial"] = menu.addAction("复制串口")
            actions["copy_telnet_ip"] = menu.addAction("复制 Telnet IP")
            actions["copy_ssh_ip"] = menu.addAction("复制 SSH IP")
            actions["copy_serial_ip"] = menu.addAction("复制串口 IP")
            actions["copy_connection"] = menu.addAction("复制连接信息")
            menu.addSeparator()
            actions["power_off"] = menu.addAction("掉电")
            return actions

        def _add_session_log_actions(self, menu: QMenu) -> dict[str, Any]:
            menu.addSeparator()
            return {
                "open_log": menu.addAction("打开本会话日志"),
                "open_log_directory": menu.addAction("打开日志目录"),
                "change_log_directory": menu.addAction("更改日志位置..."),
            }

        def _handle_session_log_action(
            self,
            chosen: Any,
            actions: dict[str, Any],
            state: SessionTabState,
        ) -> bool:
            if chosen == actions["open_log"]:
                self.open_session_log(state)
                return True
            if chosen == actions["open_log_directory"]:
                self.open_session_log_directory(state)
                return True
            if chosen == actions["change_log_directory"]:
                self.change_log_directory()
                return True
            return False

        def _handle_device_quick_action(
            self,
            chosen: Any,
            actions: dict[str, Any],
            device: Device,
        ) -> None:
            if chosen == actions["locate"]:
                self.locate_device_in_list(device.id)
                return
            if chosen == actions["clone_telnet"]:
                self.clone_telnet_session(device)
                return
            if chosen == actions["clone_ssh"]:
                self.clone_ssh_session(device)
                return
            if chosen == actions["clone_serial"]:
                self.clone_serial_session(device)
                return
            if chosen == actions["copy_telnet_ip"]:
                self.copy_device_field(device, "telnet_ip")
                return
            if chosen == actions["copy_ssh_ip"]:
                self.copy_device_field(device, "ssh_ip")
                return
            if chosen == actions["copy_serial_ip"]:
                self.copy_device_field(device, "serial_ip")
                return
            if chosen == actions["copy_connection"]:
                self.copy_text_to_clipboard(
                    self.device_connection_copy_text(device),
                    f"已复制连接信息: {device.name}",
                )

            if chosen == actions["power_off"]:
                self.power_off_device(device)

        def sync_auth_fields_from_selected(self) -> None:
            device = self.get_quick_action_device()
            if device is None:
                return
            self.device_telnet_ip_value.setText(device.telnet_ip)
            self.device_username_input.setText(device.username)
            self.device_password_input.setText(device.password)
            self.device_ssh_ip_value.setText(device.ssh_ip)
            self.device_serial_ip_value.setText(
                f"{device.serial_ip}:{device.serial_port}" if self.can_view_serial_connection(device) else ""
            )
            self.linux_username_input.setText(self.device_ssh_username(device))
            self.linux_password_input.setText(self.device_ssh_password(device))

        def refresh_device_context(self) -> None:
            device = self.get_selected_device()
            if device is None:
                self.device_summary_card.setText("请选择一台设备。")
                self.device_ssh_ip_value.clear()
                self.device_telnet_ip_value.clear()
                self.device_serial_ip_value.clear()
                return

            self.device_ssh_ip_value.setText(device.ssh_ip)
            self.device_telnet_ip_value.setText(device.telnet_ip)
            serial_visible = self.can_view_serial_connection(device)
            self.device_serial_ip_value.setText(
                f"{device.serial_ip}:{device.serial_port}" if serial_visible else ""
            )
            owner_text = device.owner or "未占用"
            owner_color = "#c0c0c0" if device.owner else "#808080"
            telnet_text = f"{device.telnet_ip}:{device.telnet_port}"
            ssh_text = f"{device.ssh_ip}:{device.ssh_port}"
            serial_text = f"{device.serial_ip}:{device.serial_port}" if serial_visible else "占用后可见"
            serial_color = "#c0c0c0" if serial_visible else "#707070"
            self.device_summary_card.setText(
                (
                    f"<div style='font-size:15px;font-weight:600;color:#ededed'>{html.escape(device.name)}</div>"
                    f"<div style='margin-top:4px;color:#808080;font-size:11px'>"
                    f"<span style='color:#c0c0c0;font-weight:600'>{html.escape(device.id)}</span>"
                    f" &nbsp;·&nbsp; {html.escape(device.domain)}"
                    f"</div>"
                    f"<div style='margin-top:10px;color:#c0c0c0;line-height:1.8'>"
                    f"<span style='color:#808080'>状态</span>&nbsp;&nbsp;"
                    f"<span style='color:{status_color(device.status)};font-weight:700'>{html.escape(device.status)}</span><br>"
                    f"<span style='color:#808080'>占用</span>&nbsp;&nbsp;"
                    f"<span style='color:{owner_color};font-weight:600'>{html.escape(owner_text)}</span><br>"
                    f"<span style='color:#808080'>Telnet</span>&nbsp;&nbsp;"
                    f"<span style='font-weight:600'>{html.escape(telnet_text)}</span><br>"
                    f"<span style='color:#808080'>串口</span>&nbsp;&nbsp;"
                    f"<span style='color:{serial_color};font-weight:600'>{html.escape(serial_text)}</span><br>"
                    f"<span style='color:#808080'>SSH</span>&nbsp;&nbsp;"
                    f"<span style='font-weight:600'>{html.escape(ssh_text)}</span>"
                    f"</div>"
                )
            )

        def refresh_workspace_context(self) -> None:
            self.refresh_session_jump_combo()

        def refresh_session_jump_combo(self) -> None:
            if not hasattr(self, "session_jump_combo"):
                return
            current_tab_id = self.current_session_key()
            combo = self.session_jump_combo
            combo.blockSignals(True)
            combo.clear()
            states = self.ordered_session_states()
            if not states:
                combo.addItem("无打开会话", "")
                combo.setCurrentIndex(0)
                combo.setEnabled(False)
                combo.blockSignals(False)
                return
            combo.setEnabled(True)
            current_index = 0
            for index, state in enumerate(states):
                combo.addItem(self.session_jump_text(state), state.tab_id)
                if state.tab_id == current_tab_id:
                    current_index = index
            combo.setCurrentIndex(current_index)
            combo.blockSignals(False)

        def ordered_session_states(self) -> list[SessionTabState]:
            states: list[SessionTabState] = []
            for device_index in range(self.session_tab_widget.count()):
                device_tab = self._device_tab_for_page(self.session_tab_widget.widget(device_index))
                if device_tab is None:
                    continue
                for tabs in self.session_tab_widgets_for_device(device_tab):
                    for session_index in range(tabs.count()):
                        state = self._session_state_for_page(tabs.widget(session_index))
                        if state is not None:
                            states.append(state)
            return states

        def session_jump_text(self, state: SessionTabState) -> str:
            device = self.get_device_by_id(state.device_id)
            device_name = device.name if device is not None else state.device_id
            kind = self.session_kind_label(state.kind)
            return f"{device_name} · {self.session_display_title(state, kind)} · {self.session_status_label(state.status_text)}"

        @staticmethod
        def session_kind_label(kind: str) -> str:
            if kind == "device":
                return "Telnet"
            if kind == "serial":
                return "串口"
            return "SSH"

        @staticmethod
        def session_display_title(state: SessionTabState, kind: str) -> str:
            title = state.title.strip()
            if title.lower().startswith(kind.lower()):
                return title
            return f"{kind} {title}" if title else kind

        @staticmethod
        def session_status_label(status: str) -> str:
            normalized = status.strip().lower()
            if normalized == "connected":
                return "已连接"
            if normalized == "connecting":
                return "连接中"
            if normalized == "disconnected":
                return "未连接"
            return status or "未知"

        def handle_session_jump_activated(self, index: int) -> None:
            tab_id = str(self.session_jump_combo.itemData(index) or "")
            if tab_id:
                self.jump_to_session(tab_id)

        def jump_to_session(self, tab_id: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                self.refresh_session_jump_combo()
                return
            device_tab = self.device_tabs_by_id.get(state.device_id)
            if device_tab is None:
                self.refresh_session_jump_combo()
                return
            device_index = self.session_tab_widget.indexOf(device_tab.page)
            session_tabs = self.find_session_tab_widget(device_tab, state.page)
            session_index = session_tabs.indexOf(state.page) if session_tabs is not None else -1
            if device_index >= 0:
                self.session_tab_widget.setCurrentIndex(device_index)
            if session_tabs is not None and session_index >= 0:
                device_tab.active_session_tab_widget = session_tabs
                session_tabs.setCurrentIndex(session_index)
            device = self.get_device_by_id(state.device_id)
            if device is not None:
                self.activate_device(device.id)
            state.terminal.setFocus()
            self.refresh_session_jump_combo()
            self.set_status_message(f"已跳转到会话: {self.session_jump_text(state)}")

        def handle_session_tab_changed(self, _index: int) -> None:
            self.refresh_workspace_context()
            self._refresh_tab_header_styles()
            self.update_controls()
            state = self.current_session_state()
            if state is not None:
                state.terminal.setFocus()

        def handle_split_session_tab_changed(self, device_id: str, tabs: QTabWidget) -> None:
            self.mark_active_session_tab_widget(device_id, tabs)
            self.handle_session_tab_changed(tabs.currentIndex())

        def handle_split_session_tab_clicked(self, device_id: str, tabs: QTabWidget, index: int) -> None:
            if index < 0:
                return
            self.mark_active_session_tab_widget(device_id, tabs)
            if tabs.currentIndex() != index:
                tabs.setCurrentIndex(index)
            self.refresh_workspace_context()
            self._refresh_tab_header_styles()
            self.update_controls()
            state = self._session_state_for_page(tabs.widget(index))
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

        def session_tab_widgets_for_device(self, device_tab: DeviceTabState) -> list[QTabWidget]:
            return device_tab.session_tab_widgets or [device_tab.session_tab_widget]

        def active_session_tabs_for_device(self, device_tab: DeviceTabState) -> QTabWidget:
            tabs = device_tab.active_session_tab_widget or device_tab.session_tab_widget
            if tabs in self.session_tab_widgets_for_device(device_tab):
                return tabs
            return device_tab.session_tab_widget

        def find_session_tab_widget(self, device_tab: DeviceTabState, page: QWidget) -> QTabWidget | None:
            for tabs in self.session_tab_widgets_for_device(device_tab):
                if tabs.indexOf(page) >= 0:
                    return tabs
            return None

        def mark_active_session_tab_widget(self, device_id: str, tabs: QTabWidget) -> None:
            device_tab = self.device_tabs_by_id.get(device_id)
            if device_tab is not None:
                device_tab.active_session_tab_widget = tabs

        def open_device_session(self, device: Device | None = None) -> None:
            device = device if isinstance(device, Device) else None
            device = device or self.get_selected_device()
            if device is None:
                self.show_warning("请先选择设备。")
                return

            selected_device = self.get_selected_device()
            if selected_device is not None and selected_device.id == device.id:
                username = self.device_username_input.text().strip()
                password = self.device_password_input.text()
            else:
                username = device.username.strip()
                password = device.password
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

        def open_linux_session(self, device: Device | None = None) -> None:
            device = device if isinstance(device, Device) else None
            device = device or self.get_quick_action_device()
            if device is None:
                self.show_warning("请先选择设备。")
                return

            host = device.ssh_ip.strip()
            selected_device = self.get_selected_device()
            if selected_device is not None and selected_device.id == device.id:
                username = self.linux_username_input.text().strip()
                password = self.linux_password_input.text()
            else:
                username = self.device_ssh_username(device).strip()
                password = self.device_ssh_password(device)
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

        def open_serial_session(self, device: Device | None = None) -> None:
            device = device if isinstance(device, Device) else None
            device = device or self.get_quick_action_device()
            if device is None:
                self.show_warning("请先选择设备。")
                return
            self.clone_serial_session(device)

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
            target_tabs = self.active_session_tabs_for_device(device_tab)
            index = target_tabs.addTab(state.page, title)
            self._install_session_tab_header(target_tabs, index, state)
            self.session_tab_widget.setCurrentWidget(device_tab.page)
            target_tabs.setCurrentIndex(index)
            device_tab.active_session_tab_widget = target_tabs
            self.set_status_message(f"正在打开会话: {title}")
            self.refresh_workspace_context()
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

            session_splitter = QSplitter(Qt.Horizontal, page)
            session_splitter.setObjectName("sessionSplitPane")
            session_splitter.setAcceptDrops(True)
            session_splitter.setProperty("sessionDropDeviceId", device.id)
            session_splitter.installEventFilter(self)
            page.setAcceptDrops(True)
            page.setProperty("sessionDropDeviceId", device.id)
            page.installEventFilter(self)
            layout.addWidget(session_splitter, 1)
            child_tabs = self.create_session_tab_widget(device.id, session_splitter)
            session_splitter.addWidget(child_tabs)

            state = DeviceTabState(
                device_id=device.id,
                title=device.name,
                page=page,
                session_tab_widget=child_tabs,
                session_splitter=session_splitter,
                session_tab_widgets=[child_tabs],
                active_session_tab_widget=child_tabs,
            )
            self.device_tabs_by_id[device.id] = state
            index = self.session_tab_widget.addTab(page, device.name)
            self._install_device_tab_header(index, state)
            self.session_tab_widget.setCurrentIndex(index)
            self.update_center_stage_state()
            return state

        def create_session_tab_widget(self, device_id: str, parent: QWidget) -> QTabWidget:
            child_tabs = QTabWidget(parent)
            child_tabs.setObjectName("deviceSessionTabs")
            child_tabs.setAcceptDrops(True)
            child_tabs.setProperty("sessionDropDeviceId", device_id)
            child_tabs.installEventFilter(self)
            child_tabs.setDocumentMode(True)
            child_tabs.setTabsClosable(False)
            child_tabs.setMovable(True)
            child_tabs.tabBar().setExpanding(False)
            child_tabs.tabBar().setUsesScrollButtons(True)
            child_tabs.currentChanged.connect(
                lambda _index, device_id=device_id, tabs=child_tabs: self.handle_split_session_tab_changed(
                    device_id,
                    tabs,
                )
            )
            child_tabs.tabBarClicked.connect(
                lambda index, device_id=device_id, tabs=child_tabs: self.handle_split_session_tab_clicked(
                    device_id,
                    tabs,
                    index,
                )
            )
            child_tabs.tabCloseRequested.connect(
                lambda index, device_id=device_id, tabs=child_tabs: self.close_child_session_tab_at_index(
                    device_id,
                    index,
                    tabs,
                )
            )
            return child_tabs

        def next_session_title(self, device_tab: DeviceTabState, kind: str) -> str:
            if kind == "device":
                number = device_tab.next_telnet_index
                device_tab.next_telnet_index += 1
                return f"Telnet #{number}"
            if kind == "serial":
                number = device_tab.next_serial_index
                device_tab.next_serial_index += 1
                return f"串口 #{number}"
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
            terminal.setContextMenuPolicy(Qt.CustomContextMenu)
            terminal.customContextMenuRequested.connect(
                lambda pos, tab_id=tab_id, terminal=terminal: self.show_terminal_context_menu(tab_id, terminal, pos)
            )
            layout.addWidget(terminal, 1)

            if kind in {"device", "serial"}:
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
                log_path=self.session_log_path(device, title, kind),
                connecting=True,
                status_text="Connecting",
            )

            terminal.set_raw_sender(lambda text, tab_id=tab_id: self.send_session_text(tab_id, text))
            terminal.set_enter_reconnect_handler(lambda tab_id=tab_id: self.reconnect_session_from_enter(tab_id))
            terminal.set_terminal_resize_handler(
                lambda columns, lines, tab_id=tab_id: self.resize_session_pty(tab_id, columns, lines)
            )
            kind_label = self.session_kind_label(kind)
            self.write_session_log_line(
                state,
                "SYS",
                f"Session created: {kind_label} {host}:{port} user={username} device={device.name} ({device.id})",
            )
            return state

        def _install_device_tab_header(self, index: int, state: DeviceTabState) -> None:
            self._install_tab_header(
                self.session_tab_widget,
                index,
                state,
                close_callback=lambda page=state.page: self.close_device_tab_for_page(page),
                close_tooltip="关闭设备会话",
                min_label_width=112,
                header_height=23,
                dot_size=8,
                close_slot_size=(21, 19),
                close_button_size=15,
            )
            self._install_device_context_menu_on_tab_header(state.device_id, state)

        def _install_session_tab_header(self, tab_widget: QTabWidget, index: int, state: SessionTabState) -> None:
            self._install_tab_header(
                tab_widget,
                index,
                state,
                close_callback=lambda page=state.page: self.close_session_tab_for_page(page),
                close_tooltip="关闭会话",
                min_label_width=44,
                header_height=20,
                dot_size=6,
                close_slot_size=(17, 16),
                close_button_size=13,
            )
            self._install_device_context_menu_on_tab_header(state.device_id, state)

        def _install_device_context_menu_on_tab_header(
            self,
            device_id: str,
            state: DeviceTabState | SessionTabState,
        ) -> None:
            for widget in (state.tab_header, state.tab_title_label, state.tab_status_dot):
                if widget is None:
                    continue
                widget.setContextMenuPolicy(Qt.CustomContextMenu)
                if isinstance(state, SessionTabState):
                    widget.setProperty("sessionDragTabId", state.tab_id)
                    widget.setToolTip("拖动到终端区边缘分屏，右键可选择分屏方向")
                    widget.installEventFilter(self)
                    widget.customContextMenuRequested.connect(
                        lambda pos, widget=widget, tab_id=state.tab_id: self.show_session_quick_context_menu(
                            tab_id,
                            widget,
                            pos,
                        )
                    )
                else:
                    widget.customContextMenuRequested.connect(
                        lambda pos, widget=widget, device_id=device_id: self.show_device_quick_context_menu(
                            device_id,
                            widget,
                            pos,
                        )
                    )

        def _install_tab_header(
            self,
            tab_widget: QTabWidget,
            index: int,
            state: DeviceTabState | SessionTabState,
            close_callback: Callable[[], None],
            close_tooltip: str,
            min_label_width: int,
            header_height: int,
            dot_size: int,
            close_slot_size: tuple[int, int],
            close_button_size: int,
        ) -> None:
            if QToolButton is None:
                return
            header = QWidget(tab_widget)
            header.setObjectName("tabHeader")
            header.setFixedHeight(header_height)
            layout = QHBoxLayout(header)
            layout.setContentsMargins(7, 2, 0, 2)
            layout.setSpacing(5)

            dot = QLabel(header)
            dot.setObjectName("tabStatusDot")
            dot.setFixedSize(dot_size, dot_size)
            layout.addWidget(dot, 0, Qt.AlignVCenter)

            label = QLabel(state.title, header)
            label.setObjectName("tabHeaderLabel")
            label.setMinimumWidth(min_label_width)
            layout.addWidget(label, 1)

            close_slot = QWidget(tab_widget.tabBar())
            close_slot.setObjectName("tabHeader")
            close_slot.setFixedSize(*close_slot_size)
            close_layout = QHBoxLayout(close_slot)
            close_layout.setContentsMargins(0, 1, 4, 1)
            close_layout.setSpacing(0)

            button = QToolButton(close_slot)
            button.setObjectName("tabCloseButton")
            button.setText("×")
            button.setAutoRaise(True)
            button.setFixedSize(close_button_size, close_button_size)
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
                tabs = self.find_session_tab_widget(device_tab, state.page)
                index = tabs.indexOf(state.page) if tabs is not None else -1
                selected = (
                    device_tab is current_device
                    and tabs is not None
                    and tabs is device_tab.active_session_tab_widget
                    and index == tabs.currentIndex()
                )
                self._apply_tab_header_style(state, selected, self._tab_connection_state(state))

        def close_session_tab_for_page(self, page: QWidget) -> None:
            state = self._session_state_for_page(page)
            if state is None:
                return
            device_tab = self.device_tabs_by_id.get(state.device_id)
            if device_tab is None:
                return
            tabs = self.find_session_tab_widget(device_tab, page)
            if tabs is not None:
                index = tabs.indexOf(page)
                if index >= 0:
                    self.close_child_session_tab_at_index(device_tab.device_id, index, tabs)

        def connect_session_tab(self, tab_id: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return

            state.connecting = True
            self.set_session_status(tab_id, "Connecting")
            self.write_session_log_line(state, "SYS", f"Connecting to {state.host}:{state.port}")
            self.update_controls()

            async def connect() -> None:
                if isinstance(state.session, LinuxSshSession):
                    await state.session.connect(
                        state.host,
                        state.port,
                        state.username,
                        state.password,
                        term_size=state.terminal.terminal_dimensions(),
                    )
                    return
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
                self.write_session_log_line(current_state, "SYS", "Connected")
                self.set_status_message(f"会话已连接: {current_state.title}")
                current_state.terminal.setFocus()

            def failure(exc: Exception) -> None:
                current_state = self.session_tabs_by_id.get(tab_id)
                if current_state is None:
                    return
                current_state.connecting = False
                self.set_session_status(tab_id, "Disconnected")
                self.write_session_log_line(current_state, "SYS", f"Connection failed: {exc}")
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

        def resize_session_pty(self, tab_id: str, columns: int, lines: int) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None or not isinstance(state.session, LinuxSshSession):
                return

            async def resize() -> None:
                await state.session.resize_terminal(columns, lines)

            self.run_coro(resize(), on_error=lambda _exc: None)

        def set_session_status(self, tab_id: str, status: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return
            state.status_text = status
            if status != "Connecting":
                state.connecting = False
            device_tab = self.device_tabs_by_id.get(state.device_id)
            if device_tab is not None:
                tabs = self.find_session_tab_widget(device_tab, state.page)
                if tabs is not None:
                    index = tabs.indexOf(state.page)
                    if index >= 0:
                        tabs.setTabText(index, "")
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
            self.write_session_log(state, "OUT", message)

        def send_session_text(self, tab_id: str, text: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return

            if text == "\x7f":
                text = "\x08" if state.kind in {"device", "serial"} else "\x7f"
            self.log_session_input(state, text)

            async def send() -> None:
                await state.session.send_text(text)

            def failure(exc: Exception) -> None:
                self.write_session_log_line(state, "SYS", f"Send failed: {exc}")
                if isinstance(exc, (TelnetSessionError, SessionUnavailableError)):
                    self.show_error(str(exc))
                    return
                self.handle_background_error(exc)

            self.run_coro(send(), on_error=failure)

        def reconnect_session_from_enter(self, tab_id: str) -> bool:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return False
            if state.connecting:
                self.set_status_message(f"Session is connecting: {state.title}")
                return True
            if state.session.is_connected:
                return False
            self.reconnect_session_tab(tab_id)
            return True

        def disconnect_session_tab(self, tab_id: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None:
                return

            async def disconnect() -> None:
                await state.session.disconnect("Disconnected.")

            def success(_result: object) -> None:
                self.set_session_status(tab_id, "Disconnected")
                self.write_session_log_line(state, "SYS", "Disconnected")
                self.set_status_message(f"会话已断开: {state.title}")

            self.run_coro(disconnect(), on_success=success)

        def reconnect_session_tab(self, tab_id: str) -> None:
            state = self.session_tabs_by_id.get(tab_id)
            if state is None or state.connecting:
                return

            state.connecting = True
            self.set_session_status(tab_id, "Connecting")
            self.write_session_log_line(state, "SYS", f"Reconnecting to {state.host}:{state.port}")
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
                self.write_session_log_line(current_state, "SYS", "Reconnected")
                current_state.terminal.setFocus()
                self.set_status_message(f"会话已重连: {current_state.title}")

            def failure(exc: Exception) -> None:
                current_state = self.session_tabs_by_id.get(tab_id)
                if current_state is not None:
                    current_state.connecting = False
                    self.set_session_status(tab_id, "Disconnected")
                    self.write_session_log_line(current_state, "SYS", f"Reconnect failed: {exc}")
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

        def close_child_session_tab_at_index(
            self,
            device_id: str,
            index: int,
            tab_widget: QTabWidget | None = None,
        ) -> None:
            device_tab = self.device_tabs_by_id.get(device_id)
            if device_tab is None:
                return
            tabs = tab_widget or self.active_session_tabs_for_device(device_tab)
            page = tabs.widget(index)
            state = self._session_state_for_page(page)
            if state is None:
                if index >= 0:
                    tabs.removeTab(index)
                self.normalize_session_splitters(device_tab)
                self._remove_device_tab_if_empty(device_tab)
                return

            async def disconnect() -> None:
                await state.session.disconnect("")

            def finalize_close(_result: object | None = None) -> None:
                current_device_tab = self.device_tabs_by_id.get(device_id)
                if current_device_tab is not None:
                    close_tabs = self.find_session_tab_widget(current_device_tab, state.page)
                    if close_tabs is not None:
                        close_index = close_tabs.indexOf(state.page)
                        if close_index >= 0:
                            close_tabs.removeTab(close_index)
                self.write_session_log_line(state, "SYS", "Session closed")
                self.session_tabs_by_id.pop(state.tab_id, None)
                state.page.deleteLater()
                if current_device_tab is not None:
                    self.normalize_session_splitters(current_device_tab)
                    self._remove_device_tab_if_empty(current_device_tab)
                self.refresh_workspace_context()
                self._refresh_tab_header_styles()
                self.update_controls()

            self.run_coro(disconnect(), on_success=finalize_close, on_error=lambda _exc: finalize_close())

        def close_session_tab_at_index(self, index: int) -> None:
            device_tab = self.current_device_tab_state()
            if device_tab is None:
                return
            self.close_child_session_tab_at_index(
                device_tab.device_id,
                index,
                self.active_session_tabs_for_device(device_tab),
            )

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
                    self.write_session_log_line(state, "SYS", "Session closed")
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
            if any(tabs.count() > 0 for tabs in self.session_tab_widgets_for_device(device_tab)):
                return
            self._remove_device_tab(device_tab)

        def normalize_session_splitters(self, device_tab: DeviceTabState) -> None:
            splitter = device_tab.session_splitter
            if splitter is None:
                return
            primary_tabs = device_tab.session_tab_widget
            all_tabs = self.session_tab_widgets_for_device(device_tab)
            nonempty_tabs = [tabs for tabs in all_tabs if tabs.count() > 0]

            if not nonempty_tabs:
                for tabs in list(all_tabs):
                    if tabs is not primary_tabs:
                        device_tab.session_tab_widgets.remove(tabs)
                        tabs.setParent(None)
                        tabs.deleteLater()
                device_tab.active_session_tab_widget = primary_tabs
                return

            if len(nonempty_tabs) == 1:
                survivor = nonempty_tabs[0]
                if survivor is not primary_tabs:
                    while survivor.count() > 0:
                        page = survivor.widget(0)
                        state = self._session_state_for_page(page)
                        survivor.removeTab(0)
                        title = state.title if state is not None else ""
                        index = primary_tabs.addTab(page, title)
                        if state is not None:
                            self._install_session_tab_header(primary_tabs, index, state)
                    survivor.setParent(None)
                    survivor.deleteLater()
                for tabs in list(device_tab.session_tab_widgets):
                    if tabs is not primary_tabs and tabs.count() == 0:
                        device_tab.session_tab_widgets.remove(tabs)
                        tabs.setParent(None)
                        tabs.deleteLater()
                device_tab.session_tab_widgets = [primary_tabs]
                device_tab.active_session_tab_widget = primary_tabs
                splitter.setSizes([1])
                return

            for tabs in list(device_tab.session_tab_widgets):
                if tabs is not primary_tabs and tabs.count() == 0:
                    device_tab.session_tab_widgets.remove(tabs)
                    tabs.setParent(None)
                    tabs.deleteLater()
            if device_tab.active_session_tab_widget not in device_tab.session_tab_widgets:
                device_tab.active_session_tab_widget = device_tab.session_tab_widgets[0]

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
            tabs = self.active_session_tabs_for_device(device_tab)
            return self._session_state_for_page(tabs.currentWidget())

        def reconnect_current_session(self) -> None:
            state = self.current_session_state()
            if state is None:
                self.set_status_message("当前没有可重连的终端会话。")
                return
            self.reconnect_session_tab(state.tab_id)

        def open_current_session_log(self) -> None:
            state = self.current_session_state()
            if state is None:
                self.set_status_message("当前没有可打开日志的终端会话。")
                return
            self.open_session_log(state)

        def disconnect_current_session(self) -> None:
            state = self.current_session_state()
            if state is None:
                self.set_status_message("当前没有可断开的终端会话。")
                return
            self.disconnect_session_tab(state.tab_id)

        def update_controls(self) -> None:
            device = self.get_quick_action_device()
            selected = device is not None
            state = self.current_session_state()
            self.quick_telnet_button.setEnabled(selected)
            self.quick_ssh_button.setEnabled(selected)
            self.quick_serial_button.setEnabled(selected)
            self.quick_occupancy_button.setEnabled(selected)
            self.quick_power_off_button.setEnabled(bool(device and self.can_power_off_device(device)))
            self.quick_reconnect_button.setEnabled(state is not None and not state.connecting)
            self.quick_log_button.setEnabled(state is not None)
            self.quick_disconnect_button.setEnabled(
                state is not None and (state.session.is_connected or state.connecting)
            )
            self.update_center_stage_state()

        def refresh_current_operation_label(
            self,
            device: Device | None,
            state: SessionTabState | None,
        ) -> None:
            if not hasattr(self, "current_operation_label"):
                return
            if device is None:
                self.current_operation_label.setText("当前操作：未选择")
                self.current_operation_label.setToolTip("")
                return
            if state is not None:
                text = f"当前操作：{device.name} / {state.title}"
                tip = f"右下角快捷动作将作用于当前终端页签：{device.name} - {state.title}"
            else:
                text = f"当前操作：{device.name}"
                tip = f"右下角快捷动作将作用于左侧选中设备：{device.name}"
            self.current_operation_label.setText(text)
            self.current_operation_label.setToolTip(tip)

        def toggle_occupancy(self, device: Device | None = None) -> None:
            device = device if isinstance(device, Device) else None
            device = device or self.get_quick_action_device()
            if device is None:
                self.show_warning("请先选择设备。")
                return

            self.set_status_message(f"正在更新设备占用状态: {device.name}")

            def toggle() -> str:
                with self.repository_lock:
                    return self.repository.toggle_device(device.id, self.current_user)

            def done(result: object) -> None:
                self.set_status_message(str(result))
                self.refresh_snapshot()

            self.run_blocking(toggle, on_success=done, on_error=self.handle_toggle_error)

        def power_off_selected_device(self) -> None:
            device = self.get_quick_action_device()
            if device is None:
                self.show_warning("请先选择设备。")
                return
            self.power_off_device(device)

        def power_off_device(self, device: Device) -> None:
            if not device.supports_power_off:
                self.show_warning("当前设备不支持掉电。")
                return
            if not self.is_my_occupied_device(device):
                self.show_warning("请先占用设备后再执行掉电。")
                return

            confirmed = QMessageBox.question(
                self,
                "设备掉电",
                f"确认对 {device.name} 执行掉电？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirmed != QMessageBox.Yes:
                return

            self.set_status_message(f"正在执行设备掉电: {device.name}")

            def power_off() -> str:
                with self.repository_lock:
                    return self.repository.power_off_device(device.id, self.current_user)

            def done(result: object) -> None:
                self.set_status_message(str(result))
                self.refresh_snapshot()

            self.run_blocking(power_off, on_success=done, on_error=self.handle_toggle_error)

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
            self.log_flush_timer.stop()
            for state in self.session_tabs_by_id.values():
                self.write_session_log_line(state, "SYS", "Application closing")
                self.flush_session_log_state(state)

            self.cancel_pending_futures()
            self.async_loop.cancel_pending(timeout=2.0)

            async def shutdown_sessions() -> None:
                await asyncio.gather(
                    *[state.session.disconnect("") for state in self.session_tabs_by_id.values()],
                    return_exceptions=True,
                )

            try:
                self.async_loop.submit(shutdown_sessions()).result(timeout=3.0)
            except Exception:
                pass
            self.async_loop.cancel_pending(timeout=1.0)
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
