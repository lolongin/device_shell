from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class InputToken:
    kind: str
    value: str = ""


class AnsiKeyParser:
    """Parse single-character terminal input into editing tokens."""

    def __init__(self) -> None:
        self._escape_buffer = ""

    def feed(self, char: str) -> list[InputToken]:
        if self._escape_buffer:
            self._escape_buffer += char
            token = self._consume_escape_buffer()
            return [token] if token is not None else []

        if char == "\x1b":
            self._escape_buffer = char
            return []

        token = self._plain_token(char)
        return [token] if token is not None else []

    def flush(self) -> list[InputToken]:
        self._escape_buffer = ""
        return []

    def _consume_escape_buffer(self) -> InputToken | None:
        if len(self._escape_buffer) == 1:
            return None

        if self._escape_buffer[1] != "[":
            self._escape_buffer = ""
            return None

        final_char = self._escape_buffer[-1]
        if final_char not in "~ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
            if len(self._escape_buffer) > 8:
                self._escape_buffer = ""
            return None

        sequence = self._escape_buffer
        self._escape_buffer = ""
        mapping = {
            "\x1b[A": InputToken("up"),
            "\x1b[B": InputToken("down"),
            "\x1b[C": InputToken("right"),
            "\x1b[D": InputToken("left"),
            "\x1b[H": InputToken("home"),
            "\x1b[F": InputToken("end"),
            "\x1b[1~": InputToken("home"),
            "\x1b[4~": InputToken("end"),
            "\x1b[3~": InputToken("delete"),
        }
        return mapping.get(sequence)

    def _plain_token(self, char: str) -> InputToken | None:
        if char in {"\n", "\x00"}:
            return None
        if char == "\r":
            return InputToken("enter")
        if char in {"\x08", "\x7f"}:
            return InputToken("backspace")
        if char == "\x03":
            return InputToken("interrupt")
        if char == "\x04":
            return InputToken("eof")
        if char == "\t":
            return InputToken("char", "\t")
        if char >= " ":
            return InputToken("char", char)
        return None


class TerminalLineEditor:
    """Minimal line editor with terminal-style redraw sequences."""

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._cursor = 0

    def insert(self, text: str, *, echo: bool) -> str:
        output_parts: list[str] = []
        for char in text:
            tail = "".join(self._buffer[self._cursor :])
            self._buffer.insert(self._cursor, char)
            self._cursor += 1
            if not echo:
                continue
            output_parts.append(char)
            if tail:
                output_parts.append(tail)
                output_parts.append(self._move_left_text(len(tail)))
        return "".join(output_parts)

    def backspace(self, *, echo: bool) -> str:
        if self._cursor == 0:
            return ""
        self._cursor -= 1
        del self._buffer[self._cursor]
        if not echo:
            return ""
        tail = "".join(self._buffer[self._cursor :])
        return "\b" + tail + " " + self._move_left_text(len(tail) + 1)

    def delete(self, *, echo: bool) -> str:
        if self._cursor >= len(self._buffer):
            return ""
        del self._buffer[self._cursor]
        if not echo:
            return ""
        tail = "".join(self._buffer[self._cursor :])
        return tail + " " + self._move_left_text(len(tail) + 1)

    def move_left(self, count: int = 1) -> str:
        step = min(count, self._cursor)
        self._cursor -= step
        return self._move_left_text(step)

    def move_right(self, count: int = 1) -> str:
        step = min(count, len(self._buffer) - self._cursor)
        self._cursor += step
        return self._move_right_text(step)

    def move_home(self) -> str:
        return self.move_left(self._cursor)

    def move_end(self) -> str:
        return self.move_right(len(self._buffer) - self._cursor)

    def clear(self) -> None:
        self._buffer.clear()
        self._cursor = 0

    def submit(self) -> str:
        line = "".join(self._buffer)
        self.clear()
        return line

    def text(self) -> str:
        return "".join(self._buffer)

    def _move_left_text(self, count: int) -> str:
        if count <= 0:
            return ""
        if count == 1:
            return "\b"
        return f"\x1b[{count}D"

    def _move_right_text(self, count: int) -> str:
        if count <= 0:
            return ""
        return f"\x1b[{count}C"
