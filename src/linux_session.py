from __future__ import annotations

import asyncio

import asyncssh

try:
    from .session_protocol import SessionCallbacks, SessionUnavailableError
except ImportError:
    from session_protocol import SessionCallbacks, SessionUnavailableError


class LinuxSshSession:
    """Async SSH session for Linux-side workflow steps."""

    def __init__(self, callbacks: SessionCallbacks) -> None:
        self.callbacks = callbacks
        self._connection: asyncssh.SSHClientConnection | None = None
        self._command_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connection is not None

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

        self.callbacks.on_status("Connected")
        self.callbacks.on_output("=== Linux SSH connected ===\n")

    async def disconnect(self, message: str = "Disconnected.") -> None:
        connection = self._connection
        self._connection = None
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
        connection = self._connection
        if connection is None:
            raise SessionUnavailableError("Linux SSH session is not connected.")

        line = command.strip()
        if not line:
            return

        async with self._command_lock:
            self.callbacks.on_status("Running")
            self.callbacks.on_output(f"\n$ {line}\n")
            process = await connection.create_process(line)
            try:
                await asyncio.gather(
                    self._pump_stream(process.stdout),
                    self._pump_stream(process.stderr),
                )
                await process.wait_closed()
            finally:
                try:
                    process.stdin.close()
                except Exception:
                    pass

            exit_status = process.exit_status
            self.callbacks.on_status("Connected")
            if exit_status not in (0, None):
                raise SessionUnavailableError(
                    f"Linux command exited with status {exit_status}: {line}"
                )

    async def _pump_stream(self, stream: asyncssh.SSHReader[str]) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            self.callbacks.on_output(chunk)
