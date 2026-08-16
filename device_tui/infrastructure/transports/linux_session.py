from __future__ import annotations

import asyncio
import codecs

import asyncssh

from .session_protocol import SessionCallbacks, SessionUnavailableError


READ_CHUNK_SIZE = 16384
TERM_TYPE = "xterm-256color"
REMOTE_INPUT_ENCODING = "utf-8"


class RemoteOutputDecoder:
    """Decode SSH output while tolerating legacy Chinese log encodings."""

    def __init__(self) -> None:
        self._mode = "utf-8"
        self._utf8_buffer = bytearray()
        self._gb18030_decoder = codecs.getincrementaldecoder("gb18030")("replace")

    def decode(self, chunk: bytes | str) -> str:
        if isinstance(chunk, str):
            return chunk
        if not chunk:
            return ""
        if self._mode == "gb18030":
            return self._gb18030_decoder.decode(chunk, final=False)

        self._utf8_buffer.extend(chunk)
        data = bytes(self._utf8_buffer)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.reason == "unexpected end of data":
                if exc.start > 0:
                    text = data[: exc.start].decode("utf-8", errors="replace")
                    self._utf8_buffer = bytearray(data[exc.start :])
                    return text
                return ""
            self._mode = "gb18030"
            self._utf8_buffer.clear()
            return self._gb18030_decoder.decode(data, final=False)

        self._utf8_buffer.clear()
        return text


class LinuxSshSession:
    """Interactive async SSH session backed by a persistent shell."""

    def __init__(self, callbacks: SessionCallbacks) -> None:
        self.callbacks = callbacks
        self._connection: asyncssh.SSHClientConnection | None = None
        self._process: asyncssh.SSHClientProcess | None = None
        self._reader_tasks: list[asyncio.Task[None]] = []
        self._write_lock = asyncio.Lock()
        self._remote_close_reported = False

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and self._process is not None

    async def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        term_size: tuple[int, int] = (160, 40),
    ) -> None:
        if self.is_connected:
            await self.disconnect("Disconnected previous Linux session.")

        self._remote_close_reported = False
        self.callbacks.on_status("Connecting")
        self.callbacks.on_output(self._system_message(f"Connecting SSH {host}:{port}"))

        try:
            self._connection = await asyncssh.connect(
                host,
                port=port,
                username=username,
                password=password,
                known_hosts=None,
            )
        except (asyncssh.Error, OSError) as exc:
            self._connection = None
            self.callbacks.on_status("Disconnected")
            raise SessionUnavailableError(str(exc)) from exc

        try:
            self._process = await self._connection.create_process(
                term_type=TERM_TYPE,
                term_size=term_size,
                encoding=None,
            )
        except (asyncssh.Error, OSError) as exc:
            connection = self._connection
            self._connection = None
            if connection is not None:
                connection.close()
                try:
                    await connection.wait_closed()
                except asyncssh.Error:
                    pass
            self.callbacks.on_status("Disconnected")
            raise SessionUnavailableError(str(exc)) from exc

        self._reader_tasks = [
            asyncio.create_task(self._pump_stream(self._process.stdout)),
            asyncio.create_task(self._pump_stream(self._process.stderr)),
        ]
        self.callbacks.on_status("Connected")
        self.callbacks.on_output(self._system_message("Linux SSH connected"))

    async def disconnect(self, message: str = "Disconnected.") -> None:
        process = self._process
        connection = self._connection
        self._process = None
        self._connection = None
        self._remote_close_reported = True

        for task in self._reader_tasks:
            task.cancel()
        if self._reader_tasks:
            await asyncio.gather(*self._reader_tasks, return_exceptions=True)
        self._reader_tasks.clear()

        if process is not None:
            try:
                process.stdin.close()
            except Exception:
                pass
            try:
                await process.wait_closed()
            except (asyncssh.Error, OSError):
                pass

        if connection is not None:
            connection.close()
            try:
                await connection.wait_closed()
            except asyncssh.Error:
                pass

        self.callbacks.on_status("Disconnected")
        if message:
            self.callbacks.on_output(self._system_message(message))

    async def send_command(self, command: str) -> None:
        process = self._process
        if process is None:
            raise SessionUnavailableError("Linux SSH session is not connected.")

        line = command.rstrip()
        await self.send_text(line + "\n")

    async def send_text(self, text: str) -> None:
        process = self._process
        if process is None:
            raise SessionUnavailableError("Linux SSH session is not connected.")

        async with self._write_lock:
            try:
                process.stdin.write(text.encode(REMOTE_INPUT_ENCODING, errors="replace"))
                await process.stdin.drain()
            except (asyncssh.Error, OSError) as exc:
                await self._mark_remote_closed()
                raise SessionUnavailableError(str(exc)) from exc

    async def resize_terminal(self, columns: int, lines: int) -> None:
        process = self._process
        if process is None:
            return
        resize = getattr(process, "change_terminal_size", None)
        if callable(resize):
            resize(columns, lines, 0, 0)

    async def _pump_stream(self, stream: asyncssh.SSHReader[bytes]) -> None:
        decoder = RemoteOutputDecoder()
        try:
            while True:
                chunk = await stream.read(READ_CHUNK_SIZE)
                if not chunk:
                    await self._mark_remote_closed()
                    return
                text = decoder.decode(chunk)
                if text:
                    self.callbacks.on_output(text)
        except asyncio.CancelledError:
            raise
        except (asyncssh.Error, OSError) as exc:
            self.callbacks.on_output(self._system_message(f"Linux stream error: {exc}"))
            await self._mark_remote_closed()

    @staticmethod
    def _system_message(message: str) -> str:
        return f"\r\n=== {message} ===\r\n"

    async def _mark_remote_closed(self) -> None:
        if self._remote_close_reported:
            return
        self._remote_close_reported = True
        process = self._process
        connection = self._connection
        self._process = None
        self._connection = None

        current_task = asyncio.current_task()
        other_tasks = [task for task in self._reader_tasks if task is not current_task]
        for task in other_tasks:
            task.cancel()
        if other_tasks:
            await asyncio.gather(*other_tasks, return_exceptions=True)
        self._reader_tasks.clear()

        if process is not None:
            try:
                process.stdin.close()
            except Exception:
                pass
            try:
                await process.wait_closed()
            except (asyncssh.Error, OSError):
                pass

        if connection is not None:
            connection.close()
            try:
                await connection.wait_closed()
            except asyncssh.Error:
                pass

        self.callbacks.on_status("Disconnected")
