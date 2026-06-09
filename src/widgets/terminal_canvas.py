"""QPainter based terminal widget backed by pyte."""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollBar, QWidget

try:
    import pyte
except ModuleNotFoundError:  # pragma: no cover - dependency is declared for the app
    pyte = None

try:
    from ..command_suggestions import infer_completed_command_from_terminal_line
except ImportError:  # pragma: no cover - direct script execution fallback
    from command_suggestions import infer_completed_command_from_terminal_line


class _TerminalTextCursor:
    def __init__(self, owner: "TerminalCanvasWidget") -> None:
        self._owner = owner

    def hasSelection(self) -> bool:  # noqa: N802 - Qt compatibility shim
        return self._owner.has_selection()


class TerminalCanvasWidget(QWidget):
    """A terminal surface rendered as a fixed character grid."""

    DEFAULT_COLUMNS = 160
    DEFAULT_LINES = 40
    DEFAULT_HISTORY = 5000
    MIN_COLUMNS = 80
    MIN_LINES = 8
    RENDER_INTERVAL_MS = 16
    MAX_FEED_BYTES_PER_FRAME = 65536
    FAST_PLAIN_OUTPUT_THRESHOLD = 131072
    PASTE_CHUNK_SIZE = 4096
    MAX_COMMAND_RECORD_CHARS = 4096
    AUTO_SCROLL_INTERVAL_MS = 45
    AUTO_SCROLL_MARGIN_ROWS = 1
    TRIPLE_CLICK_INTERVAL_SECONDS = 0.45

    PADDING_LEFT = 16
    PADDING_TOP = 14
    PADDING_RIGHT = 16
    PADDING_BOTTOM = 14
    SCROLLBAR_WIDTH = 14

    DEFAULT_FG = QColor("#f8fafc")
    DEFAULT_BG = QColor("#020617")
    CURSOR_BG = QColor("#22c55e")
    CURSOR_FG = QColor("#020617")
    SELECTION_BG = QColor("#334155")
    SELECTION_FG = QColor("#f8fafc")
    WORD_RE = re.compile(r"[A-Za-z0-9_./:@%+=,\-]+")

    ANSI_COLORS = {
        "black": QColor("#64748b"),
        "red": QColor("#f87171"),
        "green": QColor("#5eead4"),
        "yellow": QColor("#fbbf24"),
        "brown": QColor("#fbbf24"),
        "blue": QColor("#7dd3fc"),
        "magenta": QColor("#c4b5fd"),
        "cyan": QColor("#67e8f9"),
        "white": QColor("#f8fafc"),
        "brightblack": QColor("#94a3b8"),
        "brightred": QColor("#fca5a5"),
        "brightgreen": QColor("#99f6e4"),
        "brightyellow": QColor("#fde68a"),
        "brightblue": QColor("#bae6fd"),
        "brightmagenta": QColor("#ddd6fe"),
        "brightcyan": QColor("#a5f3fc"),
        "brightwhite": QColor("#f8fafc"),
    }
    SPECIAL_KEY_SEQUENCES = {
        Qt.Key_Delete: "\x1b[3~",
        Qt.Key_Left: "\x1b[D",
        Qt.Key_Right: "\x1b[C",
        Qt.Key_Up: "\x1b[A",
        Qt.Key_Down: "\x1b[B",
        Qt.Key_Home: "\x1b[H",
        Qt.Key_End: "\x1b[F",
        Qt.Key_PageUp: "\x1b[5~",
        Qt.Key_PageDown: "\x1b[6~",
    }

    def __init__(self) -> None:
        super().__init__()
        self._raw_sender: Callable[[str], None] | None = None
        self._command_recorder: Callable[[str], None] | None = None
        self._enter_reconnect_handler: Callable[[], bool] | None = None
        self._terminal_resize_handler: Callable[[int, int], None] | None = None
        self._pending_command_chars: list[str] = []
        self._pending_output_chunks: list[bytes] = []
        self._last_output_char = ""
        self._screen: Any | None = None
        self._stream: Any | None = None
        self._fallback_lines: list[str] = [""]
        self._plain_fast_mode = False
        self._plain_fast_lines: list[str] = [""]
        self._last_reported_terminal_dimensions = (0, 0)
        self._last_painted_default_font = False
        self._last_painted_bold_font = False
        self._cell_width = 1
        self._cell_height = 1
        self._baseline_offset = 1
        self._bold_font: QFont | None = None
        self._selection_anchor: tuple[int, int] | None = None
        self._selection_cursor: tuple[int, int] | None = None
        self._selecting = False
        self._scroll_offset = 0
        self._updating_scrollbar = False
        self._bracketed_paste_enabled = False
        self._confirm_multiline_paste = True
        self._last_mouse_position: QPoint | None = None
        self._selection_auto_scroll_direction = 0
        self._last_double_click_time = 0.0
        self._last_double_click_row = -1

        self.setObjectName("terminalLog")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setMinimumSize(240, 160)
        self.setCursor(Qt.IBeamCursor)
        self.setFont(QFont("Cascadia Mono", 11))

        self._scrollbar = QScrollBar(Qt.Vertical, self)
        self._scrollbar.setObjectName("terminalScrollBar")
        self._scrollbar.valueChanged.connect(self._handle_scrollbar_value_changed)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._flush_pending_output)
        self._selection_scroll_timer = QTimer(self)
        self._selection_scroll_timer.timeout.connect(self._auto_scroll_selection)

        self._refresh_font_metrics()
        self._init_terminal_backend()

    def viewport(self) -> "TerminalCanvasWidget":
        """Return self for compatibility with QPlainTextEdit call sites."""
        return self

    def textCursor(self) -> _TerminalTextCursor:  # noqa: N802 - Qt compatibility shim
        return _TerminalTextCursor(self)

    def copy(self) -> None:
        text = self.selected_text() if self.has_selection() else self.visible_text()
        QApplication.clipboard().setText(text)

    def copy_all(self) -> None:
        QApplication.clipboard().setText(self.all_text())

    def clear_terminal(self) -> None:
        self._pending_output_chunks.clear()
        self._last_output_char = ""
        self._plain_fast_mode = False
        self._plain_fast_lines = [""]
        self.clear_selection()
        if self._screen is not None:
            self._screen.reset()
            self._screen.dirty.clear()
        else:
            self._fallback_lines = [""]
        self._scroll_offset = 0
        self._update_scrollbar()
        self.update()

    def has_selection(self) -> bool:
        return (
            self._selection_anchor is not None
            and self._selection_cursor is not None
            and self._selection_anchor != self._selection_cursor
        )

    def selected_text(self) -> str:
        selection = self._normalized_selection()
        if selection is None:
            return ""
        start_row, start_col, end_row, end_col = selection
        lines: list[str] = []
        for row in range(start_row, end_row + 1):
            text = self._visible_line_text(row)
            if row == start_row == end_row:
                lines.append(text[start_col : end_col + 1].rstrip())
            elif row == start_row:
                lines.append(text[start_col:].rstrip())
            elif row == end_row:
                lines.append(text[: end_col + 1].rstrip())
            else:
                lines.append(text.rstrip())
        return "\n".join(lines)

    def visible_text(self) -> str:
        if self._screen is None or self._plain_fast_mode:
            return "\n".join(self._active_plain_lines())
        return "\n".join(self._line_to_text(line).rstrip() for line in self._visible_terminal_lines()).rstrip()

    def all_text(self) -> str:
        if self._screen is None or self._plain_fast_mode:
            return "\n".join(line.rstrip() for line in self._active_plain_lines()).rstrip()
        return "\n".join(self._line_to_text(line).rstrip() for line in self._all_terminal_lines()).rstrip()

    def set_raw_sender(self, sender: Callable[[str], None]) -> None:
        self._raw_sender = sender

    def set_enter_reconnect_handler(self, handler: Callable[[], bool]) -> None:
        self._enter_reconnect_handler = handler

    def set_command_recorder(self, recorder: Callable[[str], None]) -> None:
        self._command_recorder = recorder

    def set_terminal_resize_handler(self, handler: Callable[[int, int], None]) -> None:
        self._terminal_resize_handler = handler

    def set_bracketed_paste_enabled(self, enabled: bool) -> None:
        self._bracketed_paste_enabled = enabled

    def set_confirm_multiline_paste(self, enabled: bool) -> None:
        self._confirm_multiline_paste = enabled

    def terminal_dimensions(self) -> tuple[int, int]:
        self._refresh_font_metrics()
        content_width = max(1, self.width() - self.PADDING_LEFT - self.PADDING_RIGHT - self.SCROLLBAR_WIDTH)
        content_height = max(1, self.height() - self.PADDING_TOP - self.PADDING_BOTTOM)
        columns = max(self.MIN_COLUMNS, content_width // self._cell_width)
        lines = max(self.MIN_LINES, content_height // self._cell_height)
        return columns, lines

    def append_output(self, message: str | bytes) -> None:
        if isinstance(message, bytes):
            payload = self._normalize_output_bytes(message)
        else:
            payload = self._normalize_output_newlines(self._sanitize_output_controls(message)).encode(
                "utf-8",
                errors="replace",
            )
        if not payload:
            return
        self._pending_output_chunks.append(payload)
        if not self._render_timer.isActive():
            self._render_timer.start(self.RENDER_INTERVAL_MS)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_scrollbar()
        if event.oldSize().isValid() and event.oldSize().width() == event.size().width():
            self._scroll_offset = min(self._scroll_offset, self._max_scroll_offset())
            self._update_scrollbar()
            self.update()
            return
        if self._sync_terminal_dimensions():
            self._notify_terminal_resize()
        self._scroll_offset = min(self._scroll_offset, self._max_scroll_offset())
        self._update_scrollbar()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        self._last_painted_default_font = False
        self._last_painted_bold_font = False
        painter.fillRect(event.rect(), self.DEFAULT_BG)
        self._set_painter_font(painter, False)
        self._paint_screen(painter, event.rect())

    def event(self, event: Any) -> bool:
        if (
            self._raw_sender is not None
            and event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Tab, Qt.Key_Backtab)
        ):
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def focusNextPrevChild(self, next: bool) -> bool:  # noqa: A002, N802 - Qt override
        if self._raw_sender is not None:
            return False
        return super().focusNextPrevChild(next)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.setFocus()
            cell = self._cell_at_position(event.position().toPoint())
            now = time.monotonic()
            if now - self._last_double_click_time <= self.TRIPLE_CLICK_INTERVAL_SECONDS and cell[0] == self._last_double_click_row:
                self._select_line_at(cell)
                self._last_double_click_time = 0.0
                event.accept()
                return
            cell = self._cell_at_position(event.position().toPoint())
            self._selection_anchor = cell
            self._selection_cursor = cell
            self._selecting = True
            self._last_mouse_position = event.position().toPoint()
            self._update_selection_auto_scroll(self._last_mouse_position)
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if self._selecting and event.buttons() & Qt.LeftButton:
            self._last_mouse_position = event.position().toPoint()
            self._selection_cursor = self._cell_at_position(self._last_mouse_position)
            self._update_selection_auto_scroll(self._last_mouse_position)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._selecting:
            self._selection_cursor = self._cell_at_position(event.position().toPoint())
            self._selecting = False
            self._stop_selection_auto_scroll()
            if self._selection_anchor == self._selection_cursor:
                self.clear_selection()
            else:
                self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            cell = self._cell_at_position(event.position().toPoint())
            self._select_word_at(cell)
            self._last_double_click_time = time.monotonic()
            self._last_double_click_row = cell[0]
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        lines = event.angleDelta().y() // 120
        if lines == 0:
            return super().wheelEvent(event)
        self._scroll_by(int(lines) * 3)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._raw_sender is None:
            return super().keyPressEvent(event)

        key = event.key()
        modifiers = event.modifiers()

        if modifiers & Qt.ControlModifier and modifiers & Qt.ShiftModifier:
            if key == Qt.Key_C:
                self.copy()
                return
            if key == Qt.Key_V:
                self._paste_clipboard()
                return

        if modifiers & Qt.ControlModifier:
            if key == Qt.Key_C and self.has_selection():
                self.copy()
                return
            control_text = self._control_sequence_for_key(key)
            if control_text is not None:
                self._record_local_text(control_text)
                self._forward_text(control_text)
                return
            text = event.text()
            if text:
                self._forward_text(text)
                return
            return

        if modifiers & Qt.ShiftModifier and key == Qt.Key_Insert:
            self._paste_clipboard()
            return

        if key in (Qt.Key_Return, Qt.Key_Enter):
            self._scroll_to_live_input()
            if self._enter_reconnect_handler is not None and self._enter_reconnect_handler():
                return
            self._sync_pending_command_from_current_line()
            self._commit_pending_command()
            self._forward_text("\r")
            return
        if key == Qt.Key_Backspace:
            self._record_local_text("\x7f")
            self._forward_text("\x7f")
            return
        if key == Qt.Key_Tab:
            self._record_local_text("\t")
            self._forward_text("\t")
            return
        if key == Qt.Key_Backtab:
            self._forward_text("\x1b[Z")
            return
        special_sequence = self.SPECIAL_KEY_SEQUENCES.get(key)
        if special_sequence is not None:
            self._forward_text(special_sequence)
            return

        text = event.text()
        if text:
            if modifiers & Qt.AltModifier:
                text = "\x1b" + text
            self._record_local_text(text)
            self._forward_text(text)
            return
        super().keyPressEvent(event)

    @staticmethod
    def _control_sequence_for_key(key: int) -> str | None:
        if Qt.Key_A <= key <= Qt.Key_Z:
            return chr(key - Qt.Key_A + 1)
        control_map = {
            Qt.Key_BracketLeft: "\x1b",
            Qt.Key_Backslash: "\x1c",
            Qt.Key_BracketRight: "\x1d",
            Qt.Key_AsciiCircum: "\x1e",
            Qt.Key_Underscore: "\x1f",
            Qt.Key_Space: "\x00",
            Qt.Key_Question: "\x7f",
        }
        return control_map.get(key)

    def _init_terminal_backend(self) -> None:
        if pyte is None:
            return
        columns, lines = self.terminal_dimensions()
        self._screen = pyte.HistoryScreen(columns, lines, history=self.DEFAULT_HISTORY, ratio=1.0)
        self._stream = pyte.ByteStream(self._screen)
        self._screen.dirty.clear()
        self._last_reported_terminal_dimensions = (columns, lines)
        self._update_scrollbar()

    def clear_selection(self) -> None:
        self._stop_selection_auto_scroll()
        if self._selection_anchor is None and self._selection_cursor is None:
            return
        self._selection_anchor = None
        self._selection_cursor = None
        self._selecting = False
        self.update()

    def _select_word_at(self, cell: tuple[int, int]) -> None:
        row, column = cell
        text = self._visible_line_text(row)
        if not text:
            self.clear_selection()
            return
        safe_column = max(0, min(column, len(text) - 1))
        for match in self.WORD_RE.finditer(text):
            if match.start() <= safe_column < match.end():
                self._selection_anchor = (row, match.start())
                self._selection_cursor = (row, match.end() - 1)
                self._selecting = False
                self.update()
                return
        self.clear_selection()

    def _select_line_at(self, cell: tuple[int, int]) -> None:
        row, _column = cell
        text = self._visible_line_text(row)
        end_column = max(0, len(text.rstrip()) - 1)
        self._selection_anchor = (row, 0)
        self._selection_cursor = (row, end_column)
        self._selecting = False
        self._stop_selection_auto_scroll()
        self.update()

    def _update_selection_auto_scroll(self, position: QPoint) -> None:
        top_threshold = self.PADDING_TOP + self.AUTO_SCROLL_MARGIN_ROWS * self._cell_height
        bottom_threshold = self.height() - self.PADDING_BOTTOM - self.AUTO_SCROLL_MARGIN_ROWS * self._cell_height
        if position.y() < top_threshold:
            self._selection_auto_scroll_direction = 1
        elif position.y() > bottom_threshold:
            self._selection_auto_scroll_direction = -1
        else:
            self._selection_auto_scroll_direction = 0

        if self._selection_auto_scroll_direction and not self._selection_scroll_timer.isActive():
            self._selection_scroll_timer.start(self.AUTO_SCROLL_INTERVAL_MS)
        elif not self._selection_auto_scroll_direction:
            self._selection_scroll_timer.stop()

    def _stop_selection_auto_scroll(self) -> None:
        self._selection_auto_scroll_direction = 0
        self._selection_scroll_timer.stop()
        self._last_mouse_position = None

    def _auto_scroll_selection(self) -> None:
        if not self._selecting or self._last_mouse_position is None or not self._selection_auto_scroll_direction:
            self._stop_selection_auto_scroll()
            return
        before = self._scroll_offset
        self._scroll_by(self._selection_auto_scroll_direction)
        if self._scroll_offset == before:
            return
        self._selection_cursor = self._cell_at_position(self._last_mouse_position)
        self.update()

    def _cell_at_position(self, position: QPoint) -> tuple[int, int]:
        columns, lines = self._screen_dimensions()
        column = (position.x() - self.PADDING_LEFT) // self._cell_width
        viewport_row = (position.y() - self.PADDING_TOP) // self._cell_height
        absolute_row = self._first_visible_line_index() + int(viewport_row)
        return (
            max(0, min(absolute_row, max(0, self._total_line_count() - 1))),
            max(0, min(int(column), max(0, columns - 1))),
        )

    def _screen_dimensions(self) -> tuple[int, int]:
        if self._screen is None or self._plain_fast_mode:
            columns, lines = self.terminal_dimensions()
            return columns, max(lines, len(self._active_plain_lines()))
        return (
            int(getattr(self._screen, "columns", self.DEFAULT_COLUMNS)),
            int(getattr(self._screen, "lines", self.DEFAULT_LINES)),
        )

    def _viewport_dimensions(self) -> tuple[int, int]:
        return self.terminal_dimensions()

    def _normalized_selection(self) -> tuple[int, int, int, int] | None:
        if not self.has_selection() or self._selection_anchor is None or self._selection_cursor is None:
            return None
        anchor_row, anchor_col = self._selection_anchor
        cursor_row, cursor_col = self._selection_cursor
        if (cursor_row, cursor_col) < (anchor_row, anchor_col):
            return cursor_row, cursor_col, anchor_row, anchor_col
        return anchor_row, anchor_col, cursor_row, cursor_col

    def _is_cell_selected(self, row: int, column: int) -> bool:
        selection = self._normalized_selection()
        if selection is None:
            return False
        start_row, start_col, end_row, end_col = selection
        if row < start_row or row > end_row:
            return False
        if start_row == end_row:
            return start_col <= column <= end_col
        if row == start_row:
            return column >= start_col
        if row == end_row:
            return column <= end_col
        return True

    def _visible_line_text(self, row: int) -> str:
        if self._screen is None:
            if 0 <= row < len(self._fallback_lines):
                return self._fallback_lines[row]
            return ""
        line = self._line_at_absolute_index(row)
        if line is not None:
            return self._line_to_text(line)
        return ""

    def _scroll_by(self, delta: int) -> None:
        max_offset = self._max_scroll_offset()
        next_offset = max(0, min(self._scroll_offset + delta, max_offset))
        if next_offset == self._scroll_offset:
            return
        self._scroll_offset = next_offset
        self._update_scrollbar()
        self.update()

    def _layout_scrollbar(self) -> None:
        self._scrollbar.setGeometry(
            max(0, self.width() - self.SCROLLBAR_WIDTH),
            0,
            self.SCROLLBAR_WIDTH,
            self.height(),
        )

    def _update_scrollbar(self) -> None:
        if not hasattr(self, "_scrollbar"):
            return
        _columns, lines = self._viewport_dimensions()
        max_offset = self._max_scroll_offset()
        value = max_offset - self._scroll_offset
        self._updating_scrollbar = True
        try:
            self._scrollbar.setRange(0, max_offset)
            self._scrollbar.setPageStep(max(1, lines))
            self._scrollbar.setSingleStep(1)
            self._scrollbar.setValue(value)
            self._scrollbar.setVisible(max_offset > 0)
        finally:
            self._updating_scrollbar = False

    def _handle_scrollbar_value_changed(self, value: int) -> None:
        if self._updating_scrollbar:
            return
        max_offset = self._max_scroll_offset()
        self._scroll_offset = max(0, min(max_offset - value, max_offset))
        self.update()

    def _max_scroll_offset(self) -> int:
        if self._screen is not None and not self._plain_fast_mode:
            return self._follow_anchor_first_visible_line()
        _columns, lines = self._viewport_dimensions()
        return max(0, self._total_line_count() - lines)

    def _total_line_count(self) -> int:
        if self._screen is None or self._plain_fast_mode:
            return len(self._active_plain_lines())
        return self._history_top_length() + int(getattr(self._screen, "lines", self.DEFAULT_LINES))

    def _first_visible_line_index(self) -> int:
        return max(0, self._follow_anchor_first_visible_line() - self._scroll_offset)

    def _follow_anchor_first_visible_line(self) -> int:
        _columns, lines = self._viewport_dimensions()
        total_lines = self._total_line_count()
        max_first_line = max(0, total_lines - lines)
        if self._screen is None:
            return max_first_line
        cursor_line = self._cursor_absolute_line_index()
        return min(max_first_line, max(0, cursor_line - lines + 1))

    def _all_terminal_lines(self) -> list[Any]:
        if self._screen is None or self._plain_fast_mode:
            return list(self._active_plain_lines())
        history = getattr(self._screen, "history", None)
        top = list(getattr(history, "top", [])) if history is not None else []
        screen_lines = [self._screen.buffer.get(row, {}) for row in range(self._screen.lines)]
        return top + screen_lines

    def _visible_terminal_lines(self) -> list[Any]:
        _columns, lines = self._viewport_dimensions()
        start = self._first_visible_line_index()
        return [self._line_at_absolute_index(index) or {} for index in range(start, start + lines)]

    def _history_top_length(self) -> int:
        if self._screen is None or self._plain_fast_mode:
            return 0
        history = getattr(self._screen, "history", None)
        return len(getattr(history, "top", [])) if history is not None else 0

    def _cursor_absolute_line_index(self) -> int:
        if self._screen is None or self._plain_fast_mode:
            return max(0, self._total_line_count() - 1)
        cursor = getattr(self._screen, "cursor", None)
        cursor_row = int(getattr(cursor, "y", 0))
        return self._history_top_length() + max(0, cursor_row)

    def _line_at_absolute_index(self, index: int) -> Any | None:
        if self._screen is None or self._plain_fast_mode:
            lines = self._active_plain_lines()
            if 0 <= index < len(lines):
                return lines[index]
            return None
        if index < 0:
            return None
        history = getattr(self._screen, "history", None)
        top = getattr(history, "top", []) if history is not None else []
        history_count = len(top)
        if index < history_count:
            return top[index]
        screen_row = index - history_count
        screen_lines = int(getattr(self._screen, "lines", self.DEFAULT_LINES))
        if 0 <= screen_row < screen_lines:
            return self._screen.buffer.get(screen_row, {})
        return None

    def _line_to_text(self, line: Any) -> str:
        if isinstance(line, str):
            return line
        if hasattr(line, "items"):
            cells: list[tuple[int, Any]] = []
            for column, cell in line.items():
                try:
                    column_index = int(column)
                except (TypeError, ValueError):
                    continue
                if column_index >= 0:
                    cells.append((column_index, cell))
            if not cells:
                return ""
            chars = [" "] * (max(column for column, _cell in cells) + 1)
            for column, cell in cells:
                data = str(getattr(cell, "data", " ") or " ")
                chars[column] = data[:1]
            return "".join(chars)
        return str(line)

    def _normalize_output_newlines(self, message: str) -> str:
        if not message:
            return message
        previous = self._last_output_char
        self._last_output_char = message[-1]
        if previous == "\r" and message.startswith("\n"):
            return "\n" + message[1:].replace("\r\n", "\n").replace("\n", "\r\n")
        return message.replace("\r\n", "\n").replace("\n", "\r\n")

    @staticmethod
    def _sanitize_output_controls(message: str) -> str:
        allowed_controls = {"\a", "\b", "\t", "\n", "\r", "\x1b", "\x7f"}
        return "".join(char for char in message if char >= " " or char in allowed_controls)

    def _normalize_output_bytes(self, message: bytes) -> bytes:
        if not message:
            return message
        previous = self._last_output_char
        self._last_output_char = chr(message[-1])
        if previous == "\r" and message.startswith(b"\n"):
            return b"\n" + message[1:].replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        return message.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")

    def _should_fast_append_plain_output(self, payload: bytes) -> bool:
        if not payload:
            return False
        if not self._plain_fast_mode and len(payload) < self.FAST_PLAIN_OUTPUT_THRESHOLD:
            return False
        return self._is_plain_stream_bytes(payload)

    @staticmethod
    def _is_plain_stream_bytes(payload: bytes) -> bool:
        index = 0
        while index < len(payload):
            byte = payload[index]
            if byte == 13:
                if index + 1 >= len(payload) or payload[index + 1] != 10:
                    return False
                index += 2
                continue
            if byte in (9, 10) or byte >= 32:
                index += 1
                continue
            return False
        return True

    def _append_plain_fast_output(self, payload: bytes) -> None:
        if not self._plain_fast_mode:
            self._enter_plain_fast_mode()
        text = payload.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        if not text:
            return
        parts = text.split("\n")
        self._plain_fast_lines[-1] += parts[0]
        if len(parts) > 1:
            self._plain_fast_lines.extend(parts[1:])
        if len(self._plain_fast_lines) > self.DEFAULT_HISTORY:
            self._plain_fast_lines = self._plain_fast_lines[-self.DEFAULT_HISTORY :]

    def _enter_plain_fast_mode(self) -> None:
        if self._plain_fast_mode:
            return
        text = self.all_text()
        self._plain_fast_lines = text.split("\n") if text else [""]
        self._plain_fast_mode = True

    def _resync_terminal_from_plain_tail(self) -> None:
        if not self._plain_fast_mode or self._stream is None or self._screen is None:
            return
        tail = "\n".join(self._plain_fast_lines[-self.DEFAULT_LINES :])
        self._plain_fast_mode = False
        self._plain_fast_lines = [""]
        self._screen.reset()
        self._screen.dirty.clear()
        if tail:
            self._stream.feed(tail.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8", errors="replace"))

    def _refresh_font_metrics(self) -> None:
        metrics = self.fontMetrics()
        self._cell_width = max(1, metrics.horizontalAdvance("M"))
        self._cell_height = max(1, metrics.lineSpacing())
        self._baseline_offset = metrics.ascent()
        bold_font = QFont(self.font())
        bold_font.setBold(True)
        self._bold_font = bold_font

    def _sync_terminal_dimensions(self) -> bool:
        if self._screen is None or self._plain_fast_mode:
            return False
        columns, lines = self.terminal_dimensions()
        current_columns = int(getattr(self._screen, "columns", columns))
        current_lines = int(getattr(self._screen, "lines", lines))
        if columns == current_columns and lines == current_lines:
            return False
        if columns == current_columns:
            return False
        self._screen.resize(lines=lines, columns=columns)
        self._screen.dirty.update(range(lines))
        return True

    def _notify_terminal_resize(self) -> None:
        if self._terminal_resize_handler is None:
            return
        dimensions = self.terminal_dimensions()
        if dimensions == self._last_reported_terminal_dimensions:
            return
        self._last_reported_terminal_dimensions = dimensions
        self._terminal_resize_handler(*dimensions)

    def _flush_pending_output(self) -> None:
        if not self._pending_output_chunks:
            return
        payload = b"".join(self._pending_output_chunks)
        if self._stream is not None and self._screen is not None and self._should_fast_append_plain_output(payload):
            self._pending_output_chunks.clear()
            self._append_plain_fast_output(payload)
            self._scroll_offset = min(self._scroll_offset, self._max_scroll_offset())
            self._update_scrollbar()
            self.update()
            return
        if len(payload) > self.MAX_FEED_BYTES_PER_FRAME:
            feed_payload = payload[: self.MAX_FEED_BYTES_PER_FRAME]
            self._pending_output_chunks = [payload[self.MAX_FEED_BYTES_PER_FRAME :]]
            has_more = True
        else:
            feed_payload = payload
            self._pending_output_chunks.clear()
            has_more = False

        if self._stream is not None and self._screen is not None:
            if self._plain_fast_mode:
                self._resync_terminal_from_plain_tail()
            self._sync_terminal_dimensions()
            first_visible_before = self._first_visible_line_index()
            total_lines_before = self._total_line_count()
            old_cursor = self._cursor_position()
            self._stream.feed(feed_payload)
            new_cursor = self._cursor_position()
            self._scroll_offset = min(self._scroll_offset, self._max_scroll_offset())
            dirty_lines = set(getattr(self._screen, "dirty", set()))
            self._screen.dirty.clear()
            self._update_scrollbar()
            visible_range_changed = (
                first_visible_before != self._first_visible_line_index()
                or total_lines_before != self._total_line_count()
                or self._scroll_offset > 0
            )
            if visible_range_changed:
                self.update()
            else:
                self._repaint_dirty_lines(dirty_lines, old_cursor, new_cursor)
        else:
            self._append_fallback_output(feed_payload.decode("utf-8", errors="replace"))
            self._scroll_offset = min(self._scroll_offset, self._max_scroll_offset())
            self._update_scrollbar()
            self.update()

        if has_more:
            self._render_timer.start(self.RENDER_INTERVAL_MS)

    def _cursor_position(self) -> tuple[int, int]:
        if self._screen is None:
            return -1, -1
        cursor = getattr(self._screen, "cursor", None)
        return int(getattr(cursor, "y", -1)), int(getattr(cursor, "x", -1))

    def _repaint_dirty_lines(
        self,
        dirty_lines: set[int],
        old_cursor: tuple[int, int],
        new_cursor: tuple[int, int],
    ) -> None:
        rows = set(dirty_lines)
        for row, _column in (old_cursor, new_cursor):
            if row >= 0:
                rows.add(row)
        if not rows:
            return
        history_lines = self._history_top_length()
        first_visible_line = self._first_visible_line_index()
        _columns, viewport_lines = self._viewport_dimensions()
        for row in rows:
            if row < 0:
                continue
            viewport_row = history_lines + row - first_visible_line
            if viewport_row < 0 or viewport_row >= viewport_lines:
                continue
            y = self.PADDING_TOP + viewport_row * self._cell_height
            self.update(QRect(0, y, self.width(), self._cell_height + 1))

    def _paint_screen(self, painter: QPainter, exposed: QRect) -> None:
        if self._screen is None or self._plain_fast_mode:
            self._paint_fallback_lines(painter, exposed)
            return
        columns = int(getattr(self._screen, "columns", self.DEFAULT_COLUMNS))
        _viewport_columns, viewport_lines = self._viewport_dimensions()
        start_row = max(0, (exposed.top() - self.PADDING_TOP) // self._cell_height)
        end_row = min(viewport_lines - 1, (exposed.bottom() - self.PADDING_TOP) // self._cell_height + 1)
        first_line_index = self._first_visible_line_index()
        visible_lines = self._visible_terminal_lines()
        history_lines = self._history_top_length()
        cursor = getattr(self._screen, "cursor", None)
        cursor_row = history_lines + int(getattr(cursor, "y", -1))
        cursor_col = int(getattr(cursor, "x", -1))
        cursor_hidden = bool(getattr(cursor, "hidden", False)) or self._scroll_offset > 0
        default_cell = self._screen.default_char

        for row in range(start_row, end_row + 1):
            absolute_row = first_line_index + row
            line = visible_lines[row] if 0 <= row < len(visible_lines) else {}
            baseline = self.PADDING_TOP + row * self._cell_height + self._baseline_offset
            self._paint_terminal_row(
                painter,
                line,
                row,
                absolute_row,
                columns,
                baseline,
                cursor_col if absolute_row == cursor_row and not cursor_hidden else -1,
                default_cell,
            )

    def _paint_terminal_row(
        self,
        painter: QPainter,
        line: Any,
        row: int,
        absolute_row: int,
        columns: int,
        baseline: int,
        cursor_col: int,
        default_cell: Any,
    ) -> None:
        if columns <= 0:
            return

        cells = line if hasattr(line, "get") else {}
        segment_start = 0
        segment_chars: list[str] = []
        segment_style: tuple[QColor, QColor, bool, bool, bool, bool] | None = None

        for column in range(columns):
            cell = cells.get(column, default_cell)
            char = str(getattr(cell, "data", " ") or " ")[:1]
            is_cursor = column == cursor_col
            is_selected = self._is_cell_selected(absolute_row, column)
            fg, bg = self._cell_colors(cell)
            bold = bool(getattr(cell, "bold", False))
            underscore = bool(getattr(cell, "underscore", False))
            style = (fg, bg, bold, underscore, is_cursor, is_selected)

            if segment_style is None:
                segment_style = style
                segment_start = column
                segment_chars = [char]
                continue

            if style == segment_style:
                segment_chars.append(char)
                continue

            self._paint_text_segment(painter, row, segment_start, baseline, segment_chars, segment_style)
            segment_style = style
            segment_start = column
            segment_chars = [char]

        if segment_style is not None:
            self._paint_text_segment(painter, row, segment_start, baseline, segment_chars, segment_style)

    def _paint_text_segment(
        self,
        painter: QPainter,
        row: int,
        start_column: int,
        baseline: int,
        chars: list[str],
        style: tuple[QColor, QColor, bool, bool, bool, bool],
    ) -> None:
        if not chars:
            return
        fg, bg, bold, underscore, is_cursor, is_selected = style
        text = "".join(chars)
        rect = QRect(
            self.PADDING_LEFT + start_column * self._cell_width,
            self.PADDING_TOP + row * self._cell_height,
            self._cell_width * len(chars),
            self._cell_height,
        )

        if is_selected:
            painter.fillRect(rect, self.SELECTION_BG)
            painter.setPen(self.SELECTION_FG)
        elif is_cursor:
            painter.fillRect(rect, self.CURSOR_BG)
            painter.setPen(self.CURSOR_FG)
        else:
            if bg != self.DEFAULT_BG:
                painter.fillRect(rect, bg)
            painter.setPen(fg)

        visible_text = text.rstrip()
        if visible_text:
            self._set_painter_font(painter, bold)
            painter.drawText(QPoint(rect.left(), baseline), visible_text)
        if underscore:
            underline_y = rect.bottom() - 2
            painter.drawLine(rect.left(), underline_y, rect.right(), underline_y)

    def _set_painter_font(self, painter: QPainter, bold: bool) -> None:
        if bold:
            if not self._last_painted_bold_font:
                painter.setFont(self._bold_font if self._bold_font is not None else self.font())
                self._last_painted_bold_font = True
                self._last_painted_default_font = False
            return
        if not self._last_painted_default_font:
            painter.setFont(self.font())
            self._last_painted_default_font = True
            self._last_painted_bold_font = False

    def _paint_cell(
        self,
        painter: QPainter,
        cell: Any,
        row: int,
        column: int,
        baseline: int,
        is_cursor: bool,
        is_selected: bool,
    ) -> None:
        rect = QRect(
            self.PADDING_LEFT + column * self._cell_width,
            self.PADDING_TOP + row * self._cell_height,
            self._cell_width,
            self._cell_height,
        )
        char = str(getattr(cell, "data", " ") or " ")[:1]
        fg, bg = self._cell_colors(cell)
        bold = bool(getattr(cell, "bold", False))
        underscore = bool(getattr(cell, "underscore", False))

        if is_selected:
            painter.fillRect(rect, self.SELECTION_BG)
            painter.setPen(self.SELECTION_FG)
        elif is_cursor:
            painter.fillRect(rect, self.CURSOR_BG)
            painter.setPen(self.CURSOR_FG)
        else:
            if bg != self.DEFAULT_BG:
                painter.fillRect(rect, bg)
            painter.setPen(fg)

        painter.setFont(self._bold_font if bold and self._bold_font is not None else self.font())
        painter.drawText(QPoint(rect.left(), baseline), char)
        if underscore:
            underline_y = rect.bottom() - 2
            painter.drawLine(rect.left(), underline_y, rect.right(), underline_y)

    def _cell_colors(self, cell: Any) -> tuple[QColor, QColor]:
        fg_name = str(getattr(cell, "fg", "default") or "default")
        bg_name = str(getattr(cell, "bg", "default") or "default")
        fg = self.ANSI_COLORS.get(fg_name, self.DEFAULT_FG)
        bg = self.ANSI_COLORS.get(bg_name, self.DEFAULT_BG)
        if bool(getattr(cell, "reverse", False)):
            return bg if bg != self.DEFAULT_BG else self.DEFAULT_BG, fg if fg != self.DEFAULT_FG else self.DEFAULT_FG
        return fg, bg

    def _paint_fallback_lines(self, painter: QPainter, exposed: QRect) -> None:
        start_row = max(0, (exposed.top() - self.PADDING_TOP) // self._cell_height)
        _columns, lines = self._viewport_dimensions()
        end_row = min(lines - 1, (exposed.bottom() - self.PADDING_TOP) // self._cell_height + 1)
        first_line_index = self._first_visible_line_index()
        plain_lines = self._active_plain_lines()
        self._set_painter_font(painter, False)
        has_selection = self.has_selection()
        columns, _lines = self._viewport_dimensions()
        for row in range(start_row, end_row + 1):
            absolute_row = first_line_index + row
            baseline = self.PADDING_TOP + row * self._cell_height + self._baseline_offset
            text = plain_lines[absolute_row] if 0 <= absolute_row < len(plain_lines) else ""
            if not has_selection:
                visible_text = text[:columns].rstrip()
                if visible_text:
                    painter.setPen(self.DEFAULT_FG)
                    painter.drawText(QPoint(self.PADDING_LEFT, baseline), visible_text)
                continue
            for column, char in enumerate(text):
                if column >= columns:
                    break
                rect = QRect(
                    self.PADDING_LEFT + column * self._cell_width,
                    self.PADDING_TOP + row * self._cell_height,
                    self._cell_width,
                    self._cell_height,
                )
                if self._is_cell_selected(absolute_row, column):
                    painter.fillRect(rect, self.SELECTION_BG)
                    painter.setPen(self.SELECTION_FG)
                else:
                    painter.setPen(self.DEFAULT_FG)
                painter.drawText(QPoint(rect.left(), baseline), char)

    def _active_plain_lines(self) -> list[str]:
        return self._plain_fast_lines if self._plain_fast_mode else self._fallback_lines

    def _append_fallback_output(self, text: str) -> None:
        for char in text:
            if char == "\r":
                self._fallback_lines[-1] = ""
            elif char == "\n":
                self._fallback_lines.append("")
            elif char in ("\b", "\x7f"):
                self._fallback_lines[-1] = self._fallback_lines[-1][:-1]
            elif char >= " ":
                self._fallback_lines[-1] += char
        if len(self._fallback_lines) > self.DEFAULT_HISTORY:
            self._fallback_lines = self._fallback_lines[-self.DEFAULT_HISTORY :]

    def _forward_text(self, text: str) -> None:
        if self._raw_sender is not None:
            self._scroll_to_live_input()
            self._raw_sender(text)

    def _paste_clipboard(self) -> None:
        clipboard_text = QApplication.clipboard().text()
        if clipboard_text:
            if self._confirm_multiline_paste and self._is_multiline_paste(clipboard_text):
                line_count = len(clipboard_text.replace("\r\n", "\n").replace("\r", "\n").splitlines())
                confirmed = QMessageBox.question(
                    self,
                    "确认粘贴",
                    f"将粘贴 {line_count} 行到当前终端，是否继续？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if confirmed != QMessageBox.Yes:
                    return
            self._send_paste_text(clipboard_text)

    def _send_paste_text(self, text: str) -> None:
        self._scroll_to_live_input()
        self._record_local_text(text)
        payload = f"\x1b[200~{text}\x1b[201~" if self._bracketed_paste_enabled else text
        for index in range(0, len(payload), self.PASTE_CHUNK_SIZE):
            self._forward_text(payload[index : index + self.PASTE_CHUNK_SIZE])

    def _scroll_to_live_input(self) -> None:
        if self._scroll_offset == 0 and not self.has_selection():
            return
        self._scroll_offset = 0
        self.clear_selection()
        self._update_scrollbar()
        self.update()

    @staticmethod
    def _is_multiline_paste(text: str) -> bool:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        return "\n" in normalized.rstrip("\n")

    def _record_local_text(self, text: str) -> None:
        if len(text) > self.MAX_COMMAND_RECORD_CHARS:
            self._pending_command_chars.clear()
            return
        for char in text:
            if char in ("\r", "\n"):
                self._commit_pending_command()
            elif char in ("\b", "\x7f"):
                if self._pending_command_chars:
                    self._pending_command_chars.pop()
            elif char >= " ":
                self._pending_command_chars.append(char)

    def _sync_pending_command_from_current_line(self) -> None:
        if not self._pending_command_chars:
            return
        prefix = "".join(self._pending_command_chars).strip()
        if not prefix:
            return
        line = self._visible_line_text(self._cursor_absolute_line_index())
        completed = infer_completed_command_from_terminal_line(prefix, line)
        if completed:
            self._pending_command_chars = list(completed)

    def _commit_pending_command(self) -> None:
        command = "".join(self._pending_command_chars).strip()
        self._pending_command_chars.clear()
        if command and self._command_recorder is not None:
            self._command_recorder(command)
