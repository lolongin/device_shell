"""QWebEngineView backed terminal widget using xterm.js."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QStackedLayout, QWidget

try:
    from ..theme_tokens import WORKSPACE_BG
    from ..command_suggestions import infer_completed_command_from_terminal_line
except ImportError:  # pragma: no cover - direct script execution fallback
    from theme_tokens import WORKSPACE_BG
    from command_suggestions import infer_completed_command_from_terminal_line


class _XtermTextCursor:
    def hasSelection(self) -> bool:  # noqa: N802 - Qt compatibility shim
        return False


class _XtermBridge(QObject):
    data_received = Signal(str)
    data_with_line_received = Signal(str, str)
    resized = Signal(int, int)
    terminal_ready = Signal()

    def __init__(self, terminal: "XtermWebWidget") -> None:
        super().__init__(terminal)
        self._terminal = terminal

    @Slot(str)
    def sendData(self, data: str) -> None:  # noqa: N802 - called from JavaScript
        self.data_received.emit(data)

    @Slot(str, str)
    def sendDataWithLine(self, data: str, line: str) -> None:  # noqa: N802 - called from JavaScript
        self.data_with_line_received.emit(data, line)

    @Slot(int, int)
    def resize(self, columns: int, lines: int) -> None:
        self.resized.emit(columns, lines)

    @Slot()
    def ready(self) -> None:
        self.terminal_ready.emit()

    @Slot(str)
    def copyText(self, text: str) -> None:  # noqa: N802 - called from JavaScript
        QApplication.clipboard().setText(text)

    @Slot()
    def pasteFromClipboard(self) -> None:  # noqa: N802 - called from JavaScript
        text = QApplication.clipboard().text()
        if text:
            self.data_received.emit(text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r"))


class XtermWebWidget(QWidget):
    """Compatibility wrapper matching the existing terminal widget surface."""

    DEFAULT_COLUMNS = 160
    DEFAULT_LINES = 40
    MAX_COMMAND_RECORD_CHARS = 4096
    MIN_VALID_COLUMNS = 20
    MIN_VALID_LINES = 5
    OUTPUT_FLUSH_INTERVAL_MS = 16

    def __init__(self) -> None:
        super().__init__()
        self._raw_sender: Callable[[str], None] | None = None
        self._command_recorder: Callable[[str], None] | None = None
        self._command_suggestion_provider: Callable[[str], str | None] | None = None
        self._enter_reconnect_handler: Callable[[], bool] | None = None
        self._terminal_resize_handler: Callable[[int, int], None] | None = None
        self._pending_command_chars: list[str] = []
        self._current_command_suggestion = ""
        self._pending_output: list[str] = []
        self._write_buffer: list[str] = []
        self._ready = False
        self._dimensions_ready = False
        self._engine_started = False
        self._columns = self.DEFAULT_COLUMNS
        self._lines = self.DEFAULT_LINES
        self._local_echo = os.getenv("DEVICE_TUI_XTERM_LOCAL_ECHO", "").lower() in {"1", "true", "yes", "on"}

        self.setObjectName("terminalLog")
        self.setStyleSheet(
            "QWidget#terminalLog, QWidget#terminalPlaceholder, "
            f"QWebEngineView#terminalWebView {{ background: {WORKSPACE_BG}; border: 0; }}"
        )

        self._placeholder = QWidget(self)
        self._placeholder.setObjectName("terminalPlaceholder")
        self._view: QWebEngineView | None = None

        self._stack = QStackedLayout(self)
        self._stack.setStackingMode(QStackedLayout.StackAll)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setSpacing(0)
        self._stack.addWidget(self._placeholder)
        self._stack.setCurrentWidget(self._placeholder)

        self._bridge: _XtermBridge | None = None
        self._channel: QWebChannel | None = None

        self._output_timer = QTimer(self)
        self._output_timer.setSingleShot(True)
        self._output_timer.timeout.connect(self._flush_output_buffer)

        QTimer.singleShot(0, self.start_terminal_engine)

    def start_terminal_engine(self) -> None:
        if self._engine_started:
            return
        self._engine_started = True
        self._view = QWebEngineView(self)
        self._view.setObjectName("terminalWebView")
        self._view.page().setBackgroundColor(QColor(WORKSPACE_BG))
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.customContextMenuRequested.connect(
            lambda pos: self.customContextMenuRequested.emit(self._view.mapTo(self, pos))
        )
        self._stack.insertWidget(0, self._view)

        self._bridge = _XtermBridge(self)
        self._bridge.data_received.connect(self._handle_input)
        self._bridge.data_with_line_received.connect(self._handle_input_with_terminal_line)
        self._bridge.resized.connect(self._handle_resize)
        self._bridge.terminal_ready.connect(self._handle_ready)

        self._channel = QWebChannel(self._view.page())
        self._channel.registerObject("terminalBridge", self._bridge)
        self._view.page().setWebChannel(self._channel)

        html_path = Path(__file__).resolve().parents[1] / "web" / "xterm_terminal.html"
        self._view.load(QUrl.fromLocalFile(str(html_path)))

    def page(self) -> object:
        """Return the inner QWebEnginePage for diagnostics and tests."""
        if self._view is None:
            self.start_terminal_engine()
        return self._view.page()

    def textCursor(self) -> _XtermTextCursor:  # noqa: N802 - Qt compatibility shim
        return _XtermTextCursor()

    def set_raw_sender(self, sender: Callable[[str], None]) -> None:
        self._raw_sender = sender

    def set_enter_reconnect_handler(self, handler: Callable[[], bool]) -> None:
        self._enter_reconnect_handler = handler

    def set_command_recorder(self, recorder: Callable[[str], None]) -> None:
        self._command_recorder = recorder

    def set_command_suggestion_provider(self, provider: Callable[[str], str | None]) -> None:
        self._command_suggestion_provider = provider
        self._refresh_command_suggestion()

    def set_terminal_resize_handler(self, handler: Callable[[int, int], None]) -> None:
        self._terminal_resize_handler = handler

    def set_bracketed_paste_enabled(self, enabled: bool) -> None:
        del enabled

    def set_confirm_multiline_paste(self, enabled: bool) -> None:
        del enabled

    def terminal_dimensions(self) -> tuple[int, int]:
        if not self._dimensions_ready:
            return self.DEFAULT_COLUMNS, self.DEFAULT_LINES
        return self._columns, self._lines

    def has_valid_terminal_dimensions(self) -> bool:
        return (
            self._ready
            and self._dimensions_ready
            and self._columns >= self.MIN_VALID_COLUMNS
            and self._lines >= self.MIN_VALID_LINES
        )

    def append_output(self, message: str | bytes) -> None:
        if isinstance(message, bytes):
            text = message.decode("utf-8", errors="replace")
        else:
            text = message
        if not text:
            return
        if not self._ready:
            self._pending_output.append(text)
            return
        self._queue_write(text)

    def clear_terminal(self) -> None:
        self._run_terminal_js("clear()")

    def copy(self) -> None:
        self._run_terminal_js("copySelection()")

    def copy_all(self) -> None:
        self._run_terminal_js("copyAll()")

    def has_selection(self) -> bool:
        return False

    def visible_text(self) -> str:
        return ""

    def all_text(self) -> str:
        return ""

    def setFocus(self, *args: object, **kwargs: object) -> None:  # noqa: N802
        super().setFocus(*args, **kwargs)
        if self._view is not None:
            self._view.setFocus()
        self._run_terminal_js("focus()")

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_fit()

    def showEvent(self, event: object) -> None:  # noqa: N802
        super().showEvent(event)
        self._schedule_fit()

    def _handle_ready(self) -> None:
        self._ready = True
        self._stack.setCurrentWidget(self._view)
        self._placeholder.hide()
        if self._pending_output:
            pending = "".join(self._pending_output)
            self._pending_output.clear()
            self._queue_write(pending)
        self._schedule_fit()

    def _schedule_fit(self) -> None:
        QTimer.singleShot(0, lambda: self._run_terminal_js("fit()"))
        QTimer.singleShot(50, lambda: self._run_terminal_js("fit()"))

    def _handle_resize(self, columns: int, lines: int) -> None:
        if columns <= 0 or lines <= 0:
            return
        dimensions = (columns, lines)
        if dimensions == (self._columns, self._lines):
            return
        self._columns, self._lines = dimensions
        self._dimensions_ready = columns >= self.MIN_VALID_COLUMNS and lines >= self.MIN_VALID_LINES
        if self._dimensions_ready and self._terminal_resize_handler is not None:
            self._terminal_resize_handler(columns, lines)

    def _handle_input(self, text: str) -> None:
        if text in {"\r", "\n"}:
            if self._enter_reconnect_handler is not None and self._enter_reconnect_handler():
                return
            self._clear_command_suggestion()
            self._commit_pending_command()
        else:
            self._record_local_text(text)
        if self._local_echo:
            self._echo_input(text)
        if self._raw_sender is not None:
            self._raw_sender(text)

    def _handle_input_with_terminal_line(self, text: str, terminal_line: str) -> None:
        if text in {"\r", "\n"}:
            self._sync_pending_command_from_terminal_line(terminal_line)
        self._handle_input(text)

    def _sync_pending_command_from_terminal_line(self, terminal_line: str) -> None:
        if not terminal_line or not self._pending_command_chars:
            return
        prefix = "".join(self._pending_command_chars).strip()
        if not prefix:
            return
        completed = infer_completed_command_from_terminal_line(prefix, terminal_line)
        if completed:
            self._pending_command_chars = list(completed)

    @staticmethod
    def _should_suggest_command(query: str) -> bool:
        stripped = query.strip()
        return len(stripped) >= 2 or " " in stripped

    def _record_local_text(self, text: str) -> None:
        if "\x1b" in text:
            self._clear_command_suggestion()
            return
        if text == "\t":
            self._clear_command_suggestion()
            return
        for char in text:
            if char in {"\r", "\n"}:
                self._clear_command_suggestion()
                self._commit_pending_command()
            elif char == "\x7f":
                if self._pending_command_chars:
                    self._pending_command_chars.pop()
            elif char == "\t":
                self._clear_command_suggestion()
            elif char >= " ":
                self._pending_command_chars.append(char)
                if len(self._pending_command_chars) > self.MAX_COMMAND_RECORD_CHARS:
                    self._pending_command_chars = self._pending_command_chars[-self.MAX_COMMAND_RECORD_CHARS :]
        self._refresh_command_suggestion()

    def _commit_pending_command(self) -> None:
        command = "".join(self._pending_command_chars).strip()
        self._pending_command_chars.clear()
        self._clear_command_suggestion()
        if command and self._command_recorder:
            self._command_recorder(command)

    def _current_command_prefix(self) -> str:
        return "".join(self._pending_command_chars).strip()

    def _refresh_command_suggestion(self) -> None:
        if self._command_suggestion_provider is None:
            self._clear_command_suggestion()
            return
        prefix = self._current_command_prefix()
        if not self._should_suggest_command(prefix):
            self._clear_command_suggestion()
            return
        suggestion = self._command_suggestion_provider(prefix) or ""
        if suggestion.casefold() == prefix.casefold():
            suggestion = ""
        self._current_command_suggestion = suggestion
        self._set_command_suggestion(prefix, suggestion)

    def _clear_command_suggestion(self) -> None:
        self._current_command_suggestion = ""
        self._run_terminal_js("clearSuggestion()")

    def _set_command_suggestion(self, prefix: str, suggestion: str) -> None:
        if not suggestion:
            self._clear_command_suggestion()
            return
        self._run_terminal_js(
            f"setSuggestion({json.dumps(suggestion)}, {json.dumps(prefix)})"
        )

    def _write_js(self, text: str) -> None:
        self._run_js(f"window.deviceTerminal && window.deviceTerminal.write({json.dumps(text)});")

    def _queue_write(self, text: str) -> None:
        self._write_buffer.append(text)
        if not self._output_timer.isActive():
            self._output_timer.start(self.OUTPUT_FLUSH_INTERVAL_MS)

    def _flush_output_buffer(self) -> None:
        if not self._ready or not self._write_buffer:
            return
        text = "".join(self._write_buffer)
        self._write_buffer.clear()
        self._write_js(text)

    def _echo_input(self, text: str) -> None:
        if text == "\r":
            self._write_js("\r\n")
        elif text == "\x7f":
            self._write_js("\b \b")
        elif text >= " " or text == "\t":
            self._write_js(text)

    def _run_terminal_js(self, expression: str) -> None:
        self._run_js(f"window.deviceTerminal && window.deviceTerminal.{expression};")

    def _run_js(self, script: str) -> None:
        if not self._ready and "write(" not in script:
            return
        if self._view is None:
            return
        self._view.page().runJavaScript(script)


def prewarm_xterm_webengine(parent: QObject | None = None) -> QWebEnginePage:
    """Warm up Qt WebEngine and xterm assets without creating a visible view."""
    page = QWebEnginePage(parent)
    page.setBackgroundColor(QColor(WORKSPACE_BG))
    html_path = Path(__file__).resolve().parents[1] / "web" / "xterm_prewarm.html"

    def finish(_ok: bool = True) -> None:
        QTimer.singleShot(500, page.deleteLater)

    page.loadFinished.connect(finish)
    QTimer.singleShot(8000, page.deleteLater)
    page.load(QUrl.fromLocalFile(str(html_path)))
    return page
