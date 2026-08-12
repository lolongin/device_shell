"""Uniform terminal adapters around the existing protocol implementations."""

from __future__ import annotations

from typing import Protocol

from ..application.credentials import ConnectionTarget
from ..linux_session import LinuxSshSession
from ..session_protocol import SessionCallbacks, SessionUnavailableError
from ..simulated_session import SimulatedTerminalSession
from ..telnet_session import HuaweiTelnetSession, TelnetSessionError


class TerminalAdapter(Protocol):
    @property
    def is_connected(self) -> bool: ...

    async def connect(
        self,
        target: ConnectionTarget,
        term_size: tuple[int, int],
    ) -> None: ...

    async def disconnect(self, message: str = "Disconnected.") -> None: ...

    async def send_text(self, text: str) -> None: ...

    async def send_command(self, command: str) -> None: ...

    async def resize(self, columns: int, lines: int) -> None: ...


class SimulatedAdapter:
    def __init__(self, callbacks: SessionCallbacks) -> None:
        self._session = SimulatedTerminalSession(callbacks)

    @property
    def is_connected(self) -> bool:
        return self._session.is_connected

    async def connect(
        self,
        target: ConnectionTarget,
        term_size: tuple[int, int],
    ) -> None:
        del target, term_size
        await self._session.connect()

    async def disconnect(self, message: str = "Disconnected.") -> None:
        await self._session.disconnect(message)

    async def send_text(self, text: str) -> None:
        await self._session.send_text(text)

    async def send_command(self, command: str) -> None:
        await self._session.send_command(command)

    async def resize(self, columns: int, lines: int) -> None:
        del columns, lines

    def configure_managed_transfer(
        self,
        *,
        username: str,
        password: str,
        source_path: str,
        source_size: int,
        destination_path: str,
    ) -> None:
        self._session.configure_managed_transfer(
            username=username,
            password=password,
            source_path=source_path,
            source_size=source_size,
            destination_path=destination_path,
        )


class SshAdapter:
    def __init__(self, callbacks: SessionCallbacks) -> None:
        self._callbacks = callbacks
        self._session = LinuxSshSession(callbacks)

    @property
    def is_connected(self) -> bool:
        return self._session.is_connected

    async def connect(
        self,
        target: ConnectionTarget,
        term_size: tuple[int, int],
    ) -> None:
        last_error: SessionUnavailableError | None = None
        total = len(target.credentials)
        for index, credential in enumerate(target.credentials, start=1):
            if total > 1:
                self._callbacks.on_output(
                    f"\r\n=== Trying SSH credential {index}/{total}: "
                    f"{credential.username} ===\r\n"
                )
            try:
                await self._session.connect(
                    target.host,
                    target.port,
                    credential.username,
                    credential.password,
                    term_size,
                )
                return
            except SessionUnavailableError as exc:
                last_error = exc
        raise last_error or SessionUnavailableError("No usable SSH credential.")

    async def disconnect(self, message: str = "Disconnected.") -> None:
        await self._session.disconnect(message)

    async def send_text(self, text: str) -> None:
        await self._session.send_text(text)

    async def send_command(self, command: str) -> None:
        await self._session.send_command(command)

    async def resize(self, columns: int, lines: int) -> None:
        await self._session.resize_terminal(columns, lines)


class TelnetAdapter:
    def __init__(self, callbacks: SessionCallbacks, *, serial_mode: bool = False) -> None:
        self._session = HuaweiTelnetSession(callbacks.on_output, callbacks.on_status)
        self._serial_mode = serial_mode

    @property
    def is_connected(self) -> bool:
        return self._session.is_connected

    async def connect(
        self,
        target: ConnectionTarget,
        term_size: tuple[int, int],
    ) -> None:
        if not target.credentials:
            raise SessionUnavailableError("No usable Telnet credential.")
        credential = target.credentials[0]
        try:
            await self._session.connect(
                target.host,
                target.port,
                credential.username,
                credential.password,
                login_timeout_seconds=3.0 if self._serial_mode else 12.0,
                require_prompt=not self._serial_mode,
                term_size=term_size,
            )
        except (TelnetSessionError, OSError) as exc:
            raise SessionUnavailableError(str(exc)) from exc

    async def disconnect(self, message: str = "Disconnected.") -> None:
        await self._session.disconnect(message)

    async def send_text(self, text: str) -> None:
        try:
            await self._session.send_text(text)
        except TelnetSessionError as exc:
            raise SessionUnavailableError(str(exc)) from exc

    async def send_command(self, command: str) -> None:
        try:
            await self._session.send_command(command)
        except TelnetSessionError as exc:
            raise SessionUnavailableError(str(exc)) from exc

    async def resize(self, columns: int, lines: int) -> None:
        await self._session.resize_terminal(columns, lines)


class ProtocolAdapterFactory:
    def create(
        self,
        target: ConnectionTarget,
        callbacks: SessionCallbacks,
    ) -> TerminalAdapter:
        if target.protocol == "simulated":
            return SimulatedAdapter(callbacks)
        if target.protocol == "ssh":
            return SshAdapter(callbacks)
        if target.protocol == "telnet":
            return TelnetAdapter(callbacks)
        if target.protocol == "serial":
            return TelnetAdapter(callbacks, serial_mode=True)
        raise SessionUnavailableError(f"Unsupported protocol: {target.protocol}")
