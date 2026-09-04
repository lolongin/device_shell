"""Backend-owned terminal sessions with resumable output subscriptions."""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from device_tui.application.credentials import ConnectionTarget
from device_tui.application.errors import SessionBusyError
from device_tui.application.sessions import SessionRecord
from device_tui.infrastructure.transports.session_protocol import SessionCallbacks
from .protocol_adapters import ProtocolAdapterFactory, TerminalAdapter
from .secret_filter import SecretOutputFilter
from .session_logging import FileSessionLogSink, NullSessionLogSink, SessionLogSink


DEFAULT_REPLAY_EVENTS = 2_000
DEFAULT_REPLAY_BYTES = 4 * 1024 * 1024
SUBSCRIBER_QUEUE_SIZE = 1_000


@dataclass(frozen=True, slots=True)
class TerminalEvent:
    type: str
    session_id: str
    sequence: int
    data: str = ""
    status: str = ""
    generation: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    _size_bytes: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_size_bytes",
            len(self.data.encode("utf-8", errors="replace")) + 128,
        )

    @property
    def size_bytes(self) -> int:
        return self._size_bytes

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "version": 1,
            "type": self.type,
            "sessionId": self.session_id,
            "sequence": self.sequence,
            "generation": self.generation,
        }
        if self.data:
            payload["data"] = self.data
        if self.status:
            payload["status"] = self.status
        payload.update(self.metadata)
        return payload


class ReplayBuffer:
    def __init__(
        self,
        *,
        max_events: int = DEFAULT_REPLAY_EVENTS,
        max_bytes: int = DEFAULT_REPLAY_BYTES,
    ) -> None:
        self._events: deque[TerminalEvent] = deque()
        self._max_events = max(2, max_events)
        self._max_bytes = max(1_024, max_bytes)
        self._size_bytes = 0

    def append(self, event: TerminalEvent) -> None:
        self._events.append(event)
        self._size_bytes += event.size_bytes
        while (
            len(self._events) > self._max_events
            or self._size_bytes > self._max_bytes
        ):
            removed = self._events.popleft()
            self._size_bytes -= removed.size_bytes

    def after(self, sequence: int) -> list[TerminalEvent]:
        return [event for event in self._events if event.sequence > sequence]

    @property
    def oldest_sequence(self) -> int | None:
        return self._events[0].sequence if self._events else None


@dataclass(slots=True)
class ManagedSession:
    id: str
    target: ConnectionTarget
    title: str
    term_size: tuple[int, int]
    status: str = "creating"
    sequence: int = 0
    generation: int = 0
    adapter: TerminalAdapter | None = None
    connect_task: asyncio.Task[None] | None = None
    lease_owner: str = ""
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    output_filter: SecretOutputFilter = field(
        default_factory=lambda: SecretOutputFilter(())
    )
    dynamic_sensitive_values: tuple[str, ...] = ()
    filter_dynamic_output: bool = False
    sensitive_settle_task: asyncio.Task[None] | None = None
    sensitive_expiry_task: asyncio.Task[None] | None = None
    replay: ReplayBuffer = field(default_factory=ReplayBuffer)
    subscribers: set[asyncio.Queue[TerminalEvent]] = field(default_factory=set)

    @property
    def session(self) -> TerminalAdapter | None:
        """Compatibility alias for callers from the first vertical slice."""
        return self.adapter

    def summary(self) -> SessionRecord:
        return SessionRecord(
            id=self.id,
            device_id=self.target.device_id,
            kind=self.target.protocol,
            title=self.title,
            status=self.status,
            sequence=self.sequence,
            generation=self.generation,
        )


class SessionHub:
    """Own terminal connections independently of renderer and browser lifecycles."""

    def __init__(
        self,
        adapter_factory: ProtocolAdapterFactory | None = None,
        log_sink: SessionLogSink | None = None,
        connect_timeout_seconds: float = 30.0,
    ) -> None:
        self._sessions: dict[str, ManagedSession] = {}
        self._lock = asyncio.Lock()
        self._adapter_factory = adapter_factory or ProtocolAdapterFactory()
        self._log_sink = log_sink or NullSessionLogSink()
        self._connect_timeout_seconds = max(1.0, float(connect_timeout_seconds))
        self._event_listeners: set[Callable[[TerminalEvent], None]] = set()

    def add_event_listener(self, listener: Callable[[TerminalEvent], None]) -> None:
        self._event_listeners.add(listener)

    def remove_event_listener(self, listener: Callable[[TerminalEvent], None]) -> None:
        self._event_listeners.discard(listener)

    def list_sessions(self) -> list[SessionRecord]:
        return [session.summary() for session in self._sessions.values()]

    def get(self, session_id: str) -> ManagedSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Unknown session: {session_id}") from exc

    def target_for(self, session_id: str) -> ConnectionTarget:
        return self.get(session_id).target

    async def create(
        self,
        target: ConnectionTarget,
        title: str = "",
        term_size: tuple[int, int] = (160, 40),
    ) -> SessionRecord:
        async with self._lock:
            session_id = uuid4().hex
            managed = ManagedSession(
                id=session_id,
                target=target,
                title=title.strip() or self._default_title(target),
                term_size=self._clamp_term_size(*term_size),
            )
            self._sessions[session_id] = managed
            self._start_connect(managed)
        await asyncio.sleep(0)
        return managed.summary()

    async def create_simulated(self, device_id: str, title: str = "") -> SessionRecord:
        """Compatibility helper retained for tests and the legacy first slice."""
        return await self.create(
            ConnectionTarget(
                device_id=device_id,
                protocol="simulated",
                host="",
                port=0,
            ),
            title,
        )

    async def write(
        self,
        session_id: str,
        data: str,
        *,
        lease_owner: str = "",
        origin: str = "user",
    ) -> None:
        managed = self.get(session_id)
        async with managed.write_lock:
            self._notify_listeners(TerminalEvent(
                type="terminal.input",
                session_id=managed.id,
                sequence=managed.sequence,
                generation=managed.generation,
                metadata={"origin": origin},
            ))
            if managed.lease_owner and managed.lease_owner != lease_owner:
                self._publish(
                    managed,
                    event_type="terminal.error",
                    data="Session is reserved by an active operation.",
                    metadata={
                        "code": "session_busy",
                        "leaseOwner": managed.lease_owner,
                    },
                )
                return
            if managed.adapter is None or not managed.adapter.is_connected:
                self._publish(
                    managed,
                    event_type="terminal.error",
                    data="Session is not connected.",
                    metadata={"code": "session_not_connected"},
                )
                return
            try:
                await managed.adapter.send_text(data)
            except Exception as exc:
                self._publish(
                    managed,
                    event_type="terminal.error",
                    data=str(exc),
                    metadata={"code": "terminal_write_failed"},
                )

    async def resize(self, session_id: str, cols: int, rows: int) -> None:
        managed = self.get(session_id)
        managed.term_size = self._clamp_term_size(cols, rows)
        if managed.adapter is not None:
            await managed.adapter.resize(*managed.term_size)

    def protect_sensitive_output(
        self,
        session_id: str,
        value: str,
        ttl_seconds: float = 10.0,
    ) -> None:
        managed = self.get(session_id)
        candidates = {value.rstrip("\r\n")}
        candidates.discard("")
        if not candidates:
            return
        self._flush_sensitive_output(managed, managed.generation)
        managed.dynamic_sensitive_values = tuple(sorted(
            set(managed.dynamic_sensitive_values).union(candidates),
            key=len,
            reverse=True,
        ))
        managed.filter_dynamic_output = True
        self._reset_output_filter(managed)
        if managed.sensitive_expiry_task is not None:
            managed.sensitive_expiry_task.cancel()
        managed.sensitive_expiry_task = asyncio.create_task(
            self._expire_sensitive_output(
                managed,
                managed.generation,
                max(0.5, float(ttl_seconds)),
            ),
            name=f"terminal-secret-expiry-{managed.id}-{managed.generation}",
        )

    def configure_managed_transfer(
        self,
        session_id: str,
        *,
        username: str,
        password: str,
        source_path: str,
        source_size: int,
        destination_path: str,
    ) -> None:
        managed = self.get(session_id)
        configure = getattr(managed.adapter, "configure_managed_transfer", None)
        if callable(configure):
            configure(
                username=username,
                password=password,
                source_path=source_path,
                source_size=source_size,
                destination_path=destination_path,
            )

    async def reconnect(self, session_id: str) -> SessionRecord:
        managed = self.get(session_id)
        await self._cancel_connect(managed)
        adapter = managed.adapter
        managed.adapter = None
        if adapter is not None:
            await adapter.disconnect("Reconnecting terminal.")
        self._start_connect(managed)
        await asyncio.sleep(0)
        return managed.summary()

    async def disconnect(self, session_id: str) -> SessionRecord:
        managed = self.get(session_id)
        await self._cancel_connect(managed)
        adapter = managed.adapter
        managed.adapter = None
        if adapter is not None:
            await adapter.disconnect("Disconnected by user.")
        managed.status = "disconnected"
        return managed.summary()

    async def close(self, session_id: str) -> bool:
        async with self._lock:
            managed = self._sessions.pop(session_id, None)
        if managed is None:
            return False
        self._cancel_sensitive_filter_tasks(managed)
        await self._cancel_connect(managed)
        adapter = managed.adapter
        managed.adapter = None
        if adapter is not None:
            await adapter.disconnect("Session closed.")
        managed.status = "closed"
        self._log_sink.record(managed.id, managed.target.device_id, "SYS", "Session closed.")
        self._log_sink.close_session(managed.id)
        managed.subscribers.clear()
        return True

    async def close_all(self) -> None:
        for session_id in list(self._sessions):
            await self.close(session_id)

    def shutdown_logging(self) -> None:
        self._log_sink.shutdown()

    def read_log(self, session_id: str, max_chars: int = 200_000) -> tuple[str, bool]:
        managed = self.get(session_id)
        return self._log_sink.read_tail(
            managed.id,
            managed.target.device_id,
            max_chars,
        )

    def log_configuration(self) -> dict[str, object] | None:
        if not isinstance(self._log_sink, FileSessionLogSink):
            return None
        return self._log_sink.configuration()

    def reconfigure_logging(
        self,
        root: Path,
        *,
        max_bytes: int,
        backup_count: int | None = None,
    ) -> dict[str, object]:
        if not isinstance(self._log_sink, FileSessionLogSink):
            raise RuntimeError("Session logging is not configurable.")
        return self._log_sink.reconfigure(
            root,
            max_bytes=max_bytes,
            backup_count=backup_count,
        )

    def start_new_log(self, session_id: str) -> str:
        managed = self.get(session_id)
        if not isinstance(self._log_sink, FileSessionLogSink):
            raise RuntimeError("Session logging is not configurable.")
        return self._log_sink.start_new_log(managed.id, managed.target.device_id)

    def log_path(self, session_id: str) -> Path:
        managed = self.get(session_id)
        if not isinstance(self._log_sink, FileSessionLogSink):
            raise RuntimeError("Session logging is not file-backed.")
        return self._log_sink.path_for(managed.id, managed.target.device_id)

    def acquire_lease(self, session_id: str, owner_id: str) -> None:
        managed = self.get(session_id)
        normalized = owner_id.strip()
        if not normalized:
            raise ValueError("A session lease owner is required.")
        if managed.lease_owner and managed.lease_owner != normalized:
            raise SessionBusyError(
                f"Session is reserved by {managed.lease_owner}",
                details={
                    "session_id": session_id,
                    "lease_owner": managed.lease_owner,
                },
            )
        managed.lease_owner = normalized

    def release_lease(self, session_id: str, owner_id: str) -> bool:
        managed = self.get(session_id)
        if managed.lease_owner != owner_id.strip():
            return False
        managed.lease_owner = ""
        return True

    def subscribe(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> tuple[asyncio.Queue[TerminalEvent], list[TerminalEvent]]:
        managed = self.get(session_id)
        queue: asyncio.Queue[TerminalEvent] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        managed.subscribers.add(queue)
        replay = managed.replay.after(after_sequence)
        oldest = managed.replay.oldest_sequence
        if after_sequence > 0 and oldest is not None and oldest > after_sequence + 1:
            replay.insert(
                0,
                self._gap_event(
                    managed,
                    after_sequence + 1,
                    oldest - 1,
                    sequence=oldest - 1,
                ),
            )
        return queue, replay

    def unsubscribe(
        self,
        session_id: str,
        queue: asyncio.Queue[TerminalEvent],
    ) -> None:
        managed = self._sessions.get(session_id)
        if managed is not None:
            managed.subscribers.discard(queue)

    def _start_connect(self, managed: ManagedSession) -> None:
        self._cancel_sensitive_filter_tasks(managed)
        managed.dynamic_sensitive_values = ()
        managed.filter_dynamic_output = False
        managed.generation += 1
        generation = managed.generation
        managed.status = "connecting"
        callbacks = SessionCallbacks(
            on_output=lambda data: self._adapter_output(managed, generation, data),
            on_status=lambda status: self._adapter_status(managed, generation, status),
        )
        managed.output_filter = SecretOutputFilter(
            tuple(credential.password for credential in managed.target.credentials)
        )
        managed.adapter = self._adapter_factory.create(managed.target, callbacks)
        managed.connect_task = asyncio.create_task(
            self._run_connect(managed, generation),
            name=f"terminal-connect-{managed.id}-{generation}",
        )

    async def _run_connect(self, managed: ManagedSession, generation: int) -> None:
        adapter = managed.adapter
        if adapter is None:
            return
        try:
            await asyncio.wait_for(
                adapter.connect(managed.target, managed.term_size),
                timeout=self._connect_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._is_current(managed, generation):
                with suppress(Exception):
                    await adapter.disconnect("")
                self._flush_sensitive_output(managed, generation)
                managed.status = "failed"
                reason = (
                    f"Timed out after {self._connect_timeout_seconds:g} seconds"
                    if isinstance(exc, TimeoutError)
                    else str(exc)
                )
                self._publish(
                    managed,
                    event_type="terminal.output",
                    data=f"\r\n=== Connection failed: {reason} ===\r\n",
                    generation=generation,
                )
                self._publish(
                    managed,
                    event_type="terminal.status",
                    status="failed",
                    generation=generation,
                )
        finally:
            if self._is_current(managed, generation):
                managed.connect_task = None

    async def _cancel_connect(self, managed: ManagedSession) -> None:
        task = managed.connect_task
        managed.connect_task = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _adapter_output(self, managed: ManagedSession, generation: int, data: str) -> None:
        if self._is_current(managed, generation):
            if (
                managed.status in {"creating", "connecting", "authenticating"}
                or managed.filter_dynamic_output
            ):
                data = managed.output_filter.feed(data)
                if managed.filter_dynamic_output:
                    self._schedule_sensitive_output_settle(managed, generation)
            if not data:
                return
            self._publish(
                managed,
                event_type="terminal.output",
                data=data,
                generation=generation,
            )

    def _adapter_status(self, managed: ManagedSession, generation: int, status: str) -> None:
        if not self._is_current(managed, generation):
            return
        normalized = status.strip().lower() or "unknown"
        if managed.status == normalized:
            return
        if normalized in {"connected", "disconnected", "failed"}:
            self._flush_sensitive_output(managed, generation)
        managed.status = normalized
        self._publish(
            managed,
            event_type="terminal.status",
            status=managed.status,
            generation=generation,
        )

    def _flush_sensitive_output(self, managed: ManagedSession, generation: int) -> None:
        pending = managed.output_filter.flush()
        if pending:
            self._publish(
                managed,
                event_type="terminal.output",
                data=pending,
                generation=generation,
            )

    def _schedule_sensitive_output_settle(
        self,
        managed: ManagedSession,
        generation: int,
    ) -> None:
        if managed.sensitive_settle_task is not None:
            managed.sensitive_settle_task.cancel()
        managed.sensitive_settle_task = asyncio.create_task(
            self._settle_sensitive_output(managed, generation),
            name=f"terminal-secret-settle-{managed.id}-{generation}",
        )

    async def _settle_sensitive_output(
        self,
        managed: ManagedSession,
        generation: int,
    ) -> None:
        try:
            await asyncio.sleep(0.08)
            if not self._is_current(managed, generation):
                return
            self._flush_sensitive_output(managed, generation)
            self._reset_output_filter(managed)
        except asyncio.CancelledError:
            raise
        finally:
            if managed.sensitive_settle_task is asyncio.current_task():
                managed.sensitive_settle_task = None

    async def _expire_sensitive_output(
        self,
        managed: ManagedSession,
        generation: int,
        ttl_seconds: float,
    ) -> None:
        try:
            await asyncio.sleep(ttl_seconds)
            if not self._is_current(managed, generation):
                return
            if managed.sensitive_settle_task is not None:
                managed.sensitive_settle_task.cancel()
                managed.sensitive_settle_task = None
            self._flush_sensitive_output(managed, generation)
            managed.dynamic_sensitive_values = ()
            managed.filter_dynamic_output = False
            self._reset_output_filter(managed)
        except asyncio.CancelledError:
            raise
        finally:
            if managed.sensitive_expiry_task is asyncio.current_task():
                managed.sensitive_expiry_task = None

    def _reset_output_filter(self, managed: ManagedSession) -> None:
        authentication_values = tuple(
            credential.password for credential in managed.target.credentials
        )
        dynamic_values = (
            managed.dynamic_sensitive_values if managed.filter_dynamic_output else ()
        )
        managed.output_filter = SecretOutputFilter(
            tuple(value for value in (*authentication_values, *dynamic_values) if value)
        )

    @staticmethod
    def _cancel_sensitive_filter_tasks(managed: ManagedSession) -> None:
        for task in (managed.sensitive_settle_task, managed.sensitive_expiry_task):
            if task is not None:
                task.cancel()
        managed.sensitive_settle_task = None
        managed.sensitive_expiry_task = None

    def _is_current(self, managed: ManagedSession, generation: int) -> bool:
        return (
            self._sessions.get(managed.id) is managed
            and managed.generation == generation
        )

    def _publish(
        self,
        managed: ManagedSession,
        *,
        event_type: str,
        data: str = "",
        status: str = "",
        generation: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        managed.sequence += 1
        event = TerminalEvent(
            type=event_type,
            session_id=managed.id,
            sequence=managed.sequence,
            data=data,
            status=status,
            generation=managed.generation if generation is None else generation,
            metadata=dict(metadata or {}),
        )
        managed.replay.append(event)
        if event_type == "terminal.output":
            self._log_sink.record(managed.id, managed.target.device_id, "OUT", data)
        elif event_type == "terminal.error":
            self._log_sink.record(managed.id, managed.target.device_id, "ERR", data)
        elif event_type == "terminal.status":
            self._log_sink.record(managed.id, managed.target.device_id, "SYS", status)
        for queue in tuple(managed.subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._replace_lagging_queue(managed, queue, event)
        self._notify_listeners(event)

    def _notify_listeners(self, event: TerminalEvent) -> None:
        for listener in tuple(self._event_listeners):
            try:
                listener(event)
            except Exception:
                continue

    def _replace_lagging_queue(
        self,
        managed: ManagedSession,
        queue: asyncio.Queue[TerminalEvent],
        current: TerminalEvent,
    ) -> None:
        first_dropped: TerminalEvent | None = None
        last_dropped: TerminalEvent | None = None
        while not queue.empty():
            try:
                dropped = queue.get_nowait()
                if first_dropped is None:
                    first_dropped = dropped
                last_dropped = dropped
            except asyncio.QueueEmpty:
                break
        if first_dropped is not None and last_dropped is not None:
            queue.put_nowait(
                self._gap_event(
                    managed,
                    first_dropped.sequence,
                    max(last_dropped.sequence, current.sequence - 1),
                    sequence=current.sequence - 1,
                )
            )
        queue.put_nowait(current)

    @staticmethod
    def _gap_event(
        managed: ManagedSession,
        from_sequence: int,
        to_sequence: int,
        *,
        sequence: int,
    ) -> TerminalEvent:
        return TerminalEvent(
            type="terminal.gap",
            session_id=managed.id,
            sequence=sequence,
            generation=managed.generation,
            metadata={
                "fromSequence": from_sequence,
                "toSequence": to_sequence,
            },
        )

    @staticmethod
    def _clamp_term_size(cols: int, rows: int) -> tuple[int, int]:
        return max(20, min(1_000, int(cols))), max(5, min(500, int(rows)))

    @staticmethod
    def _default_title(target: ConnectionTarget) -> str:
        labels = {
            "simulated": "模拟终端",
            "ssh": "SSH",
            "telnet": "Telnet",
            "serial": "串口",
        }
        return f"{labels[target.protocol]} · {target.device_id}"
