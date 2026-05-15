"""Terminal emulation widget with ANSI support and syntax highlighting."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QSyntaxHighlighter,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextOption,
)
from PySide6.QtWidgets import QApplication, QPlainTextEdit

try:
    import pyte
except ModuleNotFoundError:
    pyte = None


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


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
