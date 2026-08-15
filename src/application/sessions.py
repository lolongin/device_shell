"""Terminal-session application service."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol, cast

from .credentials import ConnectionTarget, CredentialResolver, SessionProtocol
from .devices import DeviceService
from .errors import ResourceNotFoundError, UnsupportedOperationError
from .events import EventBus


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: str
    device_id: str
    kind: str
    title: str
    status: str
    sequence: int
    generation: int = 0


@dataclass(frozen=True, slots=True)
class SessionLogRecord:
    session_id: str
    content: str
    truncated: bool


class SessionManager(Protocol):
    def list_sessions(self) -> list[SessionRecord]: ...

    async def create(
        self,
        target: ConnectionTarget,
        title: str = "",
        term_size: tuple[int, int] = (160, 40),
    ) -> SessionRecord: ...

    async def reconnect(self, session_id: str) -> SessionRecord: ...

    async def disconnect(self, session_id: str) -> SessionRecord: ...

    async def close(self, session_id: str) -> bool: ...

    async def close_all(self) -> None: ...

    async def write(
        self,
        session_id: str,
        data: str,
        *,
        origin: str = "user",
    ) -> None: ...

    def protect_sensitive_output(
        self,
        session_id: str,
        value: str,
        ttl_seconds: float = 10.0,
    ) -> None: ...

    def read_log(self, session_id: str, max_chars: int) -> tuple[str, bool]: ...


class SessionService:
    """Validate and coordinate session lifecycle independently of a UI toolkit."""

    def __init__(
        self,
        devices: DeviceService,
        credentials: CredentialResolver,
        manager: SessionManager,
        events: EventBus,
    ) -> None:
        self._devices = devices
        self._credentials = credentials
        self._manager = manager
        self._events = events

    def list_sessions(self) -> list[SessionRecord]:
        return self._manager.list_sessions()

    def connection_target(self, session_id: str) -> ConnectionTarget | None:
        target_for = getattr(self._manager, "target_for", None)
        if not callable(target_for):
            return None
        try:
            target = target_for(session_id)
        except KeyError as exc:
            raise self._not_found(session_id) from exc
        return target if isinstance(target, ConnectionTarget) else None

    async def create(
        self,
        device_id: str,
        kind: str,
        title: str = "",
        term_size: tuple[int, int] = (160, 40),
    ) -> SessionRecord:
        if kind not in {"simulated", "ssh", "telnet", "serial"}:
            raise UnsupportedOperationError(
                f"Unsupported session protocol: {kind}",
                details={"protocol": kind},
            )
        target = self._credentials.resolve(device_id, cast(SessionProtocol, kind))
        return await self.create_target(target, title, term_size)

    async def create_target(
        self,
        target: ConnectionTarget,
        title: str = "",
        term_size: tuple[int, int] = (160, 40),
    ) -> SessionRecord:
        session = await self._manager.create(target, title, term_size)
        self._events.publish(
            "session.created",
            resource_id=session.id,
            data=asdict(session),
        )
        return session

    async def reconnect(self, session_id: str) -> SessionRecord:
        try:
            session = await self._manager.reconnect(session_id)
        except KeyError as exc:
            raise self._not_found(session_id) from exc
        self._events.publish(
            "session.reconnected",
            resource_id=session.id,
            data=asdict(session),
        )
        return session

    async def disconnect(self, session_id: str) -> SessionRecord:
        try:
            session = await self._manager.disconnect(session_id)
        except KeyError as exc:
            raise self._not_found(session_id) from exc
        self._events.publish(
            "session.disconnected",
            resource_id=session.id,
            data=asdict(session),
        )
        return session

    async def write(
        self,
        session_id: str,
        data: str,
        *,
        origin: str = "user",
    ) -> None:
        try:
            if origin == "user":
                # Keep compatibility with legacy/fake managers that implement the
                # original two-argument protocol.
                await self._manager.write(session_id, data)
            else:
                await self._manager.write(session_id, data, origin=origin)
        except KeyError as exc:
            raise self._not_found(session_id) from exc

    def protect_sensitive_output(
        self,
        session_id: str,
        value: str,
        ttl_seconds: float = 10.0,
    ) -> None:
        protect = getattr(self._manager, "protect_sensitive_output", None)
        if not callable(protect):
            return
        try:
            protect(session_id, value, ttl_seconds)
        except KeyError as exc:
            raise self._not_found(session_id) from exc

    def read_log(self, session_id: str, max_chars: int = 200_000) -> SessionLogRecord:
        try:
            content, truncated = self._manager.read_log(session_id, max_chars)
        except KeyError as exc:
            raise self._not_found(session_id) from exc
        return SessionLogRecord(
            session_id=session_id,
            content=content,
            truncated=truncated,
        )

    async def close(self, session_id: str) -> None:
        closed = await self._manager.close(session_id)
        if not closed:
            raise self._not_found(session_id)
        self._events.publish("session.closed", resource_id=session_id)

    async def close_all(self) -> None:
        await self._manager.close_all()

    @staticmethod
    def _not_found(session_id: str) -> ResourceNotFoundError:
        return ResourceNotFoundError(
            f"Unknown session: {session_id}",
            details={"resource": "session", "session_id": session_id},
        )
