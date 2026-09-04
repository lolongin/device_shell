from __future__ import annotations

import asyncio
import re
from collections.abc import Callable


IAC = 255
DONT = 254
DO = 253
WONT = 252
WILL = 251
SB = 250
SE = 240

NEGOTIATION_COMMANDS = {DO, DONT, WILL, WONT}
OPTION_ECHO = 1
OPTION_SUPPRESS_GO_AHEAD = 3
OPTION_TERMINAL_TYPE = 24
OPTION_NAWS = 31
TERMINAL_TYPE_IS = 0
TERMINAL_TYPE_SEND = 1
TERM_TYPE = "xterm-256color"

USERNAME_PATTERNS = ("username:", "login:")
PASSWORD_PATTERNS = ("password:",)
# Huawei devices commonly keep a Telnet socket open after rejecting a
# password and show the username prompt again.  Treat these messages as an
# authentication state, rather than a transport failure, so the user can
# retry credentials in the same terminal.
AUTHENTICATION_FAILURE_PATTERNS = (
    "authentication fail",
    "authentication failed",
    "login failed",
    "invalid password",
    "incorrect password",
    "access denied",
)
READ_CHUNK_SIZE = 16384
PROMPT_PATTERN = re.compile(r"(<[^<>\r\n]+>|\[[^\[\]\r\n]+\]|[^\r\n]+[>#])\s*$")


class TelnetSessionError(Exception):
    """Raised when the lightweight Telnet session cannot complete an operation."""


class HuaweiTelnetSession:
    """Async Telnet session for common Huawei CLI interactions."""

    def __init__(
        self,
        on_output: Callable[[str], None],
        on_status: Callable[[str], None],
    ) -> None:
        self._on_output = on_output
        self._on_status = on_status
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._read_lock = asyncio.Lock()
        self._pending_iac = bytearray()
        self._closed = True
        self._terminal_columns = 160
        self._terminal_lines = 40
        self._naws_enabled = False

    @property
    def is_connected(self) -> bool:
        return not self._closed and self._writer is not None

    async def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        login_timeout_seconds: float = 12.0,
        require_prompt: bool = True,
        setup_command: str | None = None,
        term_size: tuple[int, int] = (160, 40),
    ) -> None:
        if self.is_connected:
            await self.disconnect("Disconnected previous session.")

        self.set_terminal_size(*term_size)
        self._on_status("Connecting")
        self._on_output(f"\n=== Connecting to {host}:{port} ===\n")
        self._reader, self._writer = await asyncio.open_connection(host, port)
        self._closed = False

        try:
            await self._login(
                username,
                password,
                login_timeout_seconds,
                require_prompt=require_prompt,
                setup_command=setup_command,
            )
        except Exception:
            await self.disconnect("Connection closed.")
            raise

        self._reader_task = asyncio.create_task(self._reader_loop())

    async def disconnect(self, message: str = "Disconnected.") -> None:
        self._closed = True
        task = self._reader_task
        self._reader_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass

        self._reader = None
        self._writer = None
        self._pending_iac.clear()
        self._safe_status("Disconnected")
        if message:
            self._safe_output(f"\n=== {message} ===\n")

    async def send_command(self, command: str) -> None:
        if not self.is_connected or self._writer is None:
            raise TelnetSessionError("Not connected.")

        line = command.rstrip()
        await self.send_text(line + "\n")

    async def send_text(self, text: str) -> None:
        if not self.is_connected or self._writer is None:
            raise TelnetSessionError("Not connected.")

        payload = text.replace("\r\n", "\n").replace("\n", "\r\n")
        try:
            self._writer.write(payload.encode("utf-8"))
            await self._writer.drain()
        except OSError as exc:
            await self.disconnect("Connection lost.")
            raise TelnetSessionError(str(exc)) from exc

    def set_terminal_size(self, columns: int, lines: int) -> None:
        self._terminal_columns = self._clamp_terminal_dimension(columns)
        self._terminal_lines = self._clamp_terminal_dimension(lines)

    async def resize_terminal(self, columns: int, lines: int) -> None:
        self.set_terminal_size(columns, lines)
        if not self.is_connected or self._writer is None or not self._naws_enabled:
            return
        self._writer.write(self._naws_subnegotiation())
        try:
            await self._writer.drain()
        except OSError:
            return

    async def _login(
        self,
        username: str,
        password: str,
        login_timeout_seconds: float,
        *,
        require_prompt: bool,
        setup_command: str | None,
    ) -> None:
        self._on_status("Authenticating")
        try:
            stage = await self._read_until_stage(login_timeout_seconds)
        except TelnetSessionError as exc:
            if require_prompt or not self._is_login_timeout(exc):
                raise
            self._on_status("Connected")
            return

        if stage == "authentication_failed":
            self._on_status("Connected")
            return

        if stage == "username" and username:
            await self._write_line(username)
            try:
                stage = await self._read_until_stage(login_timeout_seconds)
            except TelnetSessionError as exc:
                if require_prompt or not self._is_login_timeout(exc):
                    raise
                self._on_status("Connected")
                return

            if stage == "authentication_failed":
                self._on_status("Connected")
                return

        if stage == "password" and password:
            await self._write_line(password)
            try:
                stage = await self._read_until_stage(login_timeout_seconds)
            except TelnetSessionError as exc:
                if require_prompt or not self._is_login_timeout(exc):
                    raise
                self._on_status("Connected")
                return

            # A rejected password is not a disconnected Telnet session.  The
            # server normally leaves the socket open and prompts for a new
            # username.  Return successfully so connect() starts the reader
            # loop and forwards subsequent user input to that prompt.
            if stage in {"authentication_failed", "username"}:
                self._on_status("Connected")
                return

        if stage != "prompt":
            if require_prompt:
                raise TelnetSessionError("Did not reach a Huawei CLI prompt.")
            self._on_status("Connected")
            return

        self._on_status("Connected")
        if setup_command:
            await self.send_command(setup_command)

    async def _write_line(self, value: str) -> None:
        if self._writer is None:
            raise TelnetSessionError("Connection is not open.")
        self._writer.write((value + "\r\n").encode("utf-8"))
        await self._writer.drain()

    async def _read_until_stage(self, timeout_seconds: float) -> str:
        if self._reader is None:
            raise TelnetSessionError("Connection is not open.")

        buffer = ""
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        async with self._read_lock:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TelnetSessionError("Timed out waiting for device prompt.")

                try:
                    chunk = await asyncio.wait_for(self._reader.read(READ_CHUNK_SIZE), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    raise TelnetSessionError("Timed out waiting for device prompt.") from exc
                if not chunk:
                    raise TelnetSessionError("Connection closed during login.")

                text = self._process_bytes(chunk)
                if text:
                    self._on_output(text)
                    buffer = (buffer + text)[-4096:]

                lowered = buffer.lower()
                if any(pattern in lowered for pattern in AUTHENTICATION_FAILURE_PATTERNS):
                    return "authentication_failed"
                if any(pattern in lowered for pattern in USERNAME_PATTERNS):
                    return "username"
                if any(pattern in lowered for pattern in PASSWORD_PATTERNS):
                    return "password"
                if self._looks_like_prompt(buffer):
                    return "prompt"

    async def _reader_loop(self) -> None:
        if self._reader is None:
            return

        try:
            while not self._closed:
                chunk = await self._reader.read(READ_CHUNK_SIZE)
                if not chunk:
                    break
                text = self._process_bytes(chunk)
                if text:
                    self._safe_output(text)
        except asyncio.CancelledError:
            self._closed = True
            raise
        except Exception as exc:
            self._safe_output(f"\n=== Read error: {exc} ===\n")
        finally:
            if not self._closed:
                await self.disconnect("Connection closed by remote host.")

    def _process_bytes(self, data: bytes) -> str:
        if self._writer is None:
            return ""

        outgoing = bytearray()
        visible = bytearray()
        payload = self._pending_iac + bytearray(data)
        self._pending_iac.clear()

        index = 0
        while index < len(payload):
            byte = payload[index]
            if byte != IAC:
                if byte not in (0,):
                    visible.append(byte)
                index += 1
                continue

            if index + 1 >= len(payload):
                self._pending_iac.extend(payload[index:])
                break

            command = payload[index + 1]
            if command == IAC:
                visible.append(IAC)
                index += 2
                continue

            if command in NEGOTIATION_COMMANDS:
                if index + 2 >= len(payload):
                    self._pending_iac.extend(payload[index:])
                    break
                option = payload[index + 2]
                outgoing.extend(self._negotiate_option(command, option))
                index += 3
                continue

            if command == SB:
                end_index = payload.find(bytes([IAC, SE]), index + 2)
                if end_index == -1:
                    self._pending_iac.extend(payload[index:])
                    break
                outgoing.extend(self._handle_subnegotiation(payload[index + 2 : end_index]))
                index = end_index + 2
                continue

            index += 2

        if outgoing:
            self._writer.write(bytes(outgoing))
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.create_task(self._drain_writer())

        text = visible.replace(b"\r\x00", b"\r").replace(b"\x00", b"").decode("utf-8", errors="ignore")
        return text

    def _negotiate_option(self, command: int, option: int) -> bytes:
        if command == WILL:
            if option in {OPTION_ECHO, OPTION_SUPPRESS_GO_AHEAD}:
                return bytes([IAC, DO, option])
            return bytes([IAC, DONT, option])

        if command == DO:
            if option == OPTION_SUPPRESS_GO_AHEAD:
                return bytes([IAC, WILL, option])
            if option == OPTION_NAWS:
                self._naws_enabled = True
                return bytes([IAC, WILL, option]) + self._naws_subnegotiation()
            if option == OPTION_TERMINAL_TYPE:
                return bytes([IAC, WILL, option])
            return bytes([IAC, WONT, option])

        if command == WONT:
            if option == OPTION_NAWS:
                self._naws_enabled = False
            return bytes([IAC, DONT, option])

        return bytes([IAC, WONT, option])

    def _handle_subnegotiation(self, payload: bytes | bytearray) -> bytes:
        if not payload:
            return b""
        option = payload[0]
        if option == OPTION_TERMINAL_TYPE and len(payload) >= 2 and payload[1] == TERMINAL_TYPE_SEND:
            return self._terminal_type_subnegotiation()
        return b""

    def _naws_subnegotiation(self) -> bytes:
        columns = self._terminal_columns
        lines = self._terminal_lines
        payload = bytes(
            [
                OPTION_NAWS,
                (columns >> 8) & 0xFF,
                columns & 0xFF,
                (lines >> 8) & 0xFF,
                lines & 0xFF,
            ]
        )
        return self._subnegotiation(payload)

    def _terminal_type_subnegotiation(self) -> bytes:
        payload = bytes([OPTION_TERMINAL_TYPE, TERMINAL_TYPE_IS]) + TERM_TYPE.encode("ascii")
        return self._subnegotiation(payload)

    def _subnegotiation(self, payload: bytes) -> bytes:
        escaped = bytearray()
        for byte in payload:
            escaped.append(byte)
            if byte == IAC:
                escaped.append(IAC)
        return bytes([IAC, SB]) + bytes(escaped) + bytes([IAC, SE])

    @staticmethod
    def _clamp_terminal_dimension(value: int) -> int:
        try:
            dimension = int(value)
        except (TypeError, ValueError):
            dimension = 0
        return max(1, min(65535, dimension))

    async def _drain_writer(self) -> None:
        if self._writer is None:
            return
        try:
            await self._writer.drain()
        except OSError:
            return

    def _looks_like_prompt(self, text: str) -> bool:
        tail = text.replace("\r", "\n").split("\n")[-1]
        return bool(PROMPT_PATTERN.search(tail))

    @staticmethod
    def _is_login_timeout(exc: TelnetSessionError) -> bool:
        return "timed out" in str(exc).lower()

    def _safe_output(self, message: str) -> None:
        try:
            self._on_output(message)
        except Exception:
            return

    def _safe_status(self, status: str) -> None:
        try:
            self._on_status(status)
        except Exception:
            return
