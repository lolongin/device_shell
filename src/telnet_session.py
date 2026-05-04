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

USERNAME_PATTERNS = ("username:", "login:")
PASSWORD_PATTERNS = ("password:",)
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
    ) -> None:
        if self.is_connected:
            await self.disconnect("Disconnected previous session.")

        self._on_status("Connecting")
        self._on_output(f"\n=== Connecting to {host}:{port} ===\n")
        self._reader, self._writer = await asyncio.open_connection(host, port)
        self._closed = False

        try:
            await self._login(username, password, login_timeout_seconds)
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
        if line:
            self._on_output(f"\n> {line}\n")
        self._writer.write((line + "\r\n").encode("utf-8"))
        await self._writer.drain()

    async def _login(
        self,
        username: str,
        password: str,
        login_timeout_seconds: float,
    ) -> None:
        self._on_status("Authenticating")
        stage = await self._read_until_stage(login_timeout_seconds)

        if stage == "username":
            await self._write_line(username)
            stage = await self._read_until_stage(login_timeout_seconds)

        if stage == "password":
            await self._write_line(password)
            stage = await self._read_until_stage(login_timeout_seconds)

        if stage != "prompt":
            raise TelnetSessionError("Did not reach a Huawei CLI prompt.")

        self._on_status("Connected")
        await self.send_command("screen-length 0 temporary")

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

                chunk = await asyncio.wait_for(self._reader.read(4096), timeout=remaining)
                if not chunk:
                    raise TelnetSessionError("Connection closed during login.")

                text = self._process_bytes(chunk)
                if text:
                    self._on_output(text)
                    buffer = (buffer + text)[-4096:]

                lowered = buffer.lower()
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
                chunk = await self._reader.read(4096)
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
                if command in (DO, DONT):
                    outgoing.extend((IAC, WONT, option))
                else:
                    outgoing.extend((IAC, DONT, option))
                index += 3
                continue

            if command == SB:
                end_index = payload.find(bytes([IAC, SE]), index + 2)
                if end_index == -1:
                    self._pending_iac.extend(payload[index:])
                    break
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
