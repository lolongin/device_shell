from __future__ import annotations

import asyncio

import asyncssh

try:
    from .session_protocol import SessionCallbacks, SessionUnavailableError
except ImportError:
    from session_protocol import SessionCallbacks, SessionUnavailableError


class LinuxSshSession:
    """Interactive async SSH session backed by a persistent shell."""

    def __init__(self, callbacks: SessionCallbacks) -> None:
        self.callbacks = callbacks
        self._connection: asyncssh.SSHClientConnection | None = None
        self._process: asyncssh.SSHClientProcess | None = None
        self._reader_tasks: list[asyncio.Task[None]] = []
        self._write_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and self._process is not None

    async def connect(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> None:
        if self.is_connected:
            await self.disconnect("Disconnected previous Linux session.")

        self.callbacks.on_status("Connecting")
        self.callbacks.on_output(f"\n=== Connecting SSH {host}:{port} ===\n")

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
                term_type="xterm",
                term_size=(160, 40),
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
        self.callbacks.on_output("=== Linux SSH connected ===\n")

    async def disconnect(self, message: str = "Disconnected.") -> None:
        process = self._process
        connection = self._connection
        self._process = None
        self._connection = None

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
            self.callbacks.on_output(f"\n=== {message} ===\n")

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
            process.stdin.write(text)
            await process.stdin.drain()

    async def _pump_stream(self, stream: asyncssh.SSHReader[str]) -> None:
        try:
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    return
                self.callbacks.on_output(chunk)
        except asyncio.CancelledError:
            raise
        except (asyncssh.Error, OSError) as exc:
            self.callbacks.on_output(f"\n=== Linux stream error: {exc} ===\n")
