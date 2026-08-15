from __future__ import annotations

import asyncio

from src.application.credentials import ConnectionTarget, SessionCredential
from src.application.errors import SessionBusyError
from src.desktop_backend.session_hub import ReplayBuffer, SessionHub, TerminalEvent
from src.session_protocol import SessionCallbacks


class FakeAdapter:
    def __init__(
        self,
        callbacks: SessionCallbacks,
        *,
        fail: bool = False,
        block: bool = False,
    ) -> None:
        self.callbacks = callbacks
        self.fail = fail
        self.block = block
        self.is_connected = False
        self.connect_calls: list[tuple[ConnectionTarget, tuple[int, int]]] = []
        self.resize_calls: list[tuple[int, int]] = []
        self.sent: list[str] = []
        self.disconnect_messages: list[str] = []

    async def connect(
        self,
        target: ConnectionTarget,
        term_size: tuple[int, int],
    ) -> None:
        self.connect_calls.append((target, term_size))
        self.callbacks.on_status("Connecting")
        if self.block:
            await asyncio.Event().wait()
        if self.fail:
            raise OSError("expected connection failure")
        self.is_connected = True
        self.callbacks.on_status("Connected")
        self.callbacks.on_output("ready\r\n")

    async def disconnect(self, message: str = "Disconnected.") -> None:
        self.disconnect_messages.append(message)
        self.is_connected = False
        self.callbacks.on_status("Disconnected")

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def send_command(self, command: str) -> None:
        self.sent.append(command + "\n")

    async def resize(self, columns: int, lines: int) -> None:
        self.resize_calls.append((columns, lines))

    def emit(self, data: str) -> None:
        self.callbacks.on_output(data)


class FakeAdapterFactory:
    def __init__(self, *, fail: bool = False, block: bool = False) -> None:
        self.fail = fail
        self.block = block
        self.adapters: list[FakeAdapter] = []

    def create(
        self,
        target: ConnectionTarget,
        callbacks: SessionCallbacks,
    ) -> FakeAdapter:
        del target
        adapter = FakeAdapter(callbacks, fail=self.fail, block=self.block)
        self.adapters.append(adapter)
        return adapter


def _target(protocol: str = "ssh") -> ConnectionTarget:
    return ConnectionTarget(
        device_id="DEVICE-1",
        protocol=protocol,  # type: ignore[arg-type]
        host="127.0.0.1",
        port=22,
        credentials=(SessionCredential("tester", "secret"),),
    )


def test_terminal_event_caches_encoded_size_for_replay_accounting() -> None:
    event = TerminalEvent(
        type="terminal.output",
        session_id="session-1",
        sequence=1,
        data="中文-output",
    )

    assert event.size_bytes == len("中文-output".encode("utf-8")) + 128
    assert event._size_bytes == event.size_bytes


def test_hub_connects_writes_resizes_and_reconnects_through_adapter() -> None:
    async def scenario() -> None:
        factory = FakeAdapterFactory()
        hub = SessionHub(factory)  # type: ignore[arg-type]
        created = await hub.create(_target(), term_size=(120, 36))
        first = factory.adapters[0]

        assert created.kind == "ssh"
        assert created.generation == 1
        assert first.connect_calls[0][1] == (120, 36)
        await hub.write(created.id, "display version\r")
        await hub.resize(created.id, 200, 60)
        assert first.sent == ["display version\r"]
        assert first.resize_calls == [(200, 60)]

        disconnected = await hub.disconnect(created.id)
        assert disconnected.status == "disconnected"

        reconnected = await hub.reconnect(created.id)
        assert reconnected.generation == 2
        assert first.disconnect_messages == ["Disconnected by user."]
        assert len(factory.adapters) == 2
        assert factory.adapters[1].connect_calls[0][1] == (200, 60)
        await hub.close_all()

    asyncio.run(scenario())


def test_failed_connection_remains_available_for_reconnect() -> None:
    async def scenario() -> None:
        factory = FakeAdapterFactory(fail=True)
        hub = SessionHub(factory)  # type: ignore[arg-type]
        created = await hub.create(_target())
        await asyncio.sleep(0)

        managed = hub.get(created.id)
        assert managed.status == "failed"
        assert any(
            event.type == "terminal.output" and "Connection failed" in event.data
            for event in managed.replay.after(0)
        )
        assert await hub.close(created.id)

    asyncio.run(scenario())


def test_callbacks_from_old_reconnect_generation_are_ignored() -> None:
    async def scenario() -> None:
        factory = FakeAdapterFactory()
        hub = SessionHub(factory)  # type: ignore[arg-type]
        created = await hub.create(_target())
        first = factory.adapters[0]
        await hub.reconnect(created.id)
        managed = hub.get(created.id)
        sequence = managed.sequence

        first.emit("stale output")

        assert managed.sequence == sequence
        assert not any(
            "stale output" in event.data for event in managed.replay.after(0)
        )
        await hub.close_all()

    asyncio.run(scenario())


def test_replay_reports_a_gap_when_requested_output_was_evicted() -> None:
    async def scenario() -> None:
        factory = FakeAdapterFactory()
        hub = SessionHub(factory)  # type: ignore[arg-type]
        created = await hub.create(_target())
        managed = hub.get(created.id)
        managed.replay = ReplayBuffer(max_events=3, max_bytes=1_024)
        adapter = factory.adapters[0]
        starting_sequence = managed.sequence
        for index in range(8):
            adapter.emit(f"line-{index}\n")

        queue, replay = hub.subscribe(created.id, after_sequence=starting_sequence)

        assert replay[0].type == "terminal.gap"
        assert replay[0].to_payload()["fromSequence"] == starting_sequence + 1
        assert replay[-1].data == "line-7\n"
        hub.unsubscribe(created.id, queue)
        await hub.close_all()

    asyncio.run(scenario())


def test_lagging_subscriber_receives_explicit_gap_event() -> None:
    async def scenario() -> None:
        factory = FakeAdapterFactory()
        hub = SessionHub(factory)  # type: ignore[arg-type]
        created = await hub.create(_target())
        queue, _replay = hub.subscribe(created.id)
        adapter = factory.adapters[0]

        for index in range(1_002):
            adapter.emit(f"chunk-{index}")

        first = queue.get_nowait()
        assert first.type == "terminal.gap"
        assert first.to_payload()["fromSequence"] < first.to_payload()["toSequence"]
        await hub.close_all()

    asyncio.run(scenario())


def test_session_lease_prevents_unowned_input_and_conflicting_automation() -> None:
    async def scenario() -> None:
        factory = FakeAdapterFactory()
        hub = SessionHub(factory)  # type: ignore[arg-type]
        created = await hub.create(_target())
        adapter = factory.adapters[0]
        queue, _replay = hub.subscribe(created.id, after_sequence=created.sequence)

        hub.acquire_lease(created.id, "operation-1")
        await hub.write(created.id, "manual input")
        assert adapter.sent == []
        busy = await asyncio.wait_for(queue.get(), timeout=1)
        assert busy.type == "terminal.error"
        assert busy.to_payload()["code"] == "session_busy"

        try:
            hub.acquire_lease(created.id, "operation-2")
        except SessionBusyError as exc:
            assert exc.details["lease_owner"] == "operation-1"
        else:
            raise AssertionError("Conflicting lease was accepted")

        await hub.write(created.id, "automated input", lease_owner="operation-1")
        assert adapter.sent == ["automated input"]
        assert hub.release_lease(created.id, "operation-1")
        assert not hub.release_lease(created.id, "operation-1")
        await hub.close_all()

    asyncio.run(scenario())


def test_connection_timeout_transitions_to_failed_and_cleans_adapter() -> None:
    async def scenario() -> None:
        factory = FakeAdapterFactory(block=True)
        hub = SessionHub(  # type: ignore[arg-type]
            factory,
            connect_timeout_seconds=0.01,
        )
        created = await hub.create(_target())
        await asyncio.sleep(1.05)

        managed = hub.get(created.id)
        assert managed.status == "failed"
        assert factory.adapters[0].disconnect_messages == [""]
        assert any(
            event.type == "terminal.output" and "Connection failed" in event.data
            for event in managed.replay.after(0)
        )
        await hub.close_all()

    asyncio.run(scenario())


def test_dynamic_automation_secret_is_redacted_before_replay_and_listeners() -> None:
    async def scenario() -> None:
        factory = FakeAdapterFactory()
        hub = SessionHub(factory)  # type: ignore[arg-type]
        observed = []
        hub.add_event_listener(observed.append)
        created = await hub.create(_target())
        managed = hub.get(created.id)
        starting_sequence = managed.sequence

        hub.protect_sensitive_output(created.id, "vault-secret\r", ttl_seconds=0.5)
        factory.adapters[0].emit("echo vault-")
        factory.adapters[0].emit("secret\r\nprompt>")
        await asyncio.sleep(0.1)

        rendered = "".join(
            event.data
            for event in managed.replay.after(starting_sequence)
            if event.type == "terminal.output"
        )
        listener_rendered = "".join(
            event.data
            for event in observed
            if event.type == "terminal.output" and event.sequence > starting_sequence
        )
        assert "vault-secret" not in rendered
        assert "vault-secret" not in listener_rendered
        assert "***" in rendered
        assert rendered.endswith("\r\nprompt>")
        await hub.close_all()

    asyncio.run(scenario())


def test_terminal_input_listener_metadata_has_origin_but_never_input_data() -> None:
    async def scenario() -> None:
        factory = FakeAdapterFactory()
        hub = SessionHub(factory)  # type: ignore[arg-type]
        observed = []
        hub.add_event_listener(observed.append)
        created = await hub.create(_target())

        await hub.write(created.id, "sensitive manual input", origin="automation")

        input_event = next(event for event in observed if event.type == "terminal.input")
        assert input_event.data == ""
        assert input_event.metadata == {"origin": "automation"}
        await hub.close_all()

    asyncio.run(scenario())
