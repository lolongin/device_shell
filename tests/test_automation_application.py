from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from device_tui.application import MemorySecretStore, UnsupportedOperationError, build_desktop_application
from device_tui.application.credentials import ConnectionTarget
from device_tui.application.automation.expressions import SafeAutomationExpression
from device_tui.application.sessions import SessionRecord
from device_tui.application.automation.rules import AutoResponseAction, AutoResponseRule, AutoResponseStep
from device_tui.infrastructure.persistence.sqlite_desktop import SQLiteDesktopStore
from device_tui.device_sources.sample import SampleDeviceRepository


class EventSessionManager:
    def __init__(self) -> None:
        self.records: dict[str, SessionRecord] = {}
        self.writes: list[tuple[str, str, str]] = []
        self.listeners: set[Callable[[object], None]] = set()
        self.counter = 0

    def add_event_listener(self, listener: Callable[[object], None]) -> None:
        self.listeners.add(listener)

    def remove_event_listener(self, listener: Callable[[object], None]) -> None:
        self.listeners.discard(listener)

    def emit(
        self,
        event_type: str,
        session_id: str,
        *,
        data: str = "",
        status: str = "",
        origin: str = "user",
    ) -> None:
        event = SimpleNamespace(
            type=event_type,
            session_id=session_id,
            data=data,
            status=status,
            metadata={"origin": origin},
        )
        for listener in tuple(self.listeners):
            listener(event)

    def list_sessions(self) -> list[SessionRecord]:
        return list(self.records.values())

    async def create(
        self,
        target: ConnectionTarget,
        title: str = "",
        term_size: tuple[int, int] = (160, 40),
    ) -> SessionRecord:
        _ = term_size
        self.counter += 1
        record = SessionRecord(
            id=f"session-{self.counter}",
            device_id=target.device_id,
            kind=target.protocol,
            title=title or target.device_id,
            status="connected",
            sequence=0,
        )
        self.records[record.id] = record
        return record

    async def reconnect(self, session_id: str) -> SessionRecord:
        return self.records[session_id]

    async def disconnect(self, session_id: str) -> SessionRecord:
        disconnected = replace(self.records[session_id], status="disconnected")
        self.records[session_id] = disconnected
        return disconnected

    async def close(self, session_id: str) -> bool:
        return self.records.pop(session_id, None) is not None

    async def close_all(self) -> None:
        self.records.clear()

    async def write(
        self,
        session_id: str,
        data: str,
        *,
        origin: str = "user",
    ) -> None:
        if session_id not in self.records:
            raise KeyError(session_id)
        self.writes.append((session_id, data, origin))
        self.emit("terminal.input", session_id, origin=origin)

    def read_log(self, session_id: str, max_chars: int) -> tuple[str, bool]:
        _ = max_chars
        if session_id not in self.records:
            raise KeyError(session_id)
        return "", False


def _application(tmp_path: Path):
    manager = EventSessionManager()
    store = SQLiteDesktopStore(tmp_path / "device-tui.sqlite3")
    secrets = MemorySecretStore()
    application = build_desktop_application(
        SampleDeviceRepository(),
        manager,
        profile_store=store,
        command_store=store,
        automation_store=store,
        secret_store=secrets,
    )
    return application, manager, store, secrets


async def _sessions(application):
    device_id = application.devices.list_inventory().devices[0].id
    first = await application.sessions.create(device_id, "simulated", "Primary")
    second = await application.sessions.create(device_id, "simulated", "Secondary")
    return first, second


def test_match_steps_and_next_target_are_backend_owned(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Two-step login",
            pattern="Login:",
            response="first\r",
            once=False,
            steps=[
                AutoResponseStep(
                    pattern="Login:",
                    responses=["first\r"],
                    response_targets=["next"],
                    response_delays=[0],
                ),
                AutoResponseStep(
                    pattern="Code:",
                    responses=["second\r"],
                    response_targets=["source"],
                    response_delays=[0],
                ),
            ],
        ))

        manager.emit("terminal.input", first.id)
        manager.emit("terminal.output", first.id, data="Log")
        manager.emit("terminal.output", first.id, data="in:")
        await asyncio.sleep(0.01)
        manager.emit("terminal.output", first.id, data="Code:")
        await asyncio.sleep(0.01)

        assert manager.writes == [
            (second.id, "first\r", "automation"),
            (first.id, "second\r", "automation"),
        ]
        assert all(
            record.id not in status.running_rule_ids
            for status in application.automation.statuses()
        )
        await application.automation.close()

    asyncio.run(scenario())


def test_next_target_requires_another_session_on_the_same_device(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        device_id = application.devices.list_inventory().devices[0].id
        only = await application.sessions.create(device_id, "simulated", "Only session")
        record = application.automation.create_rule(AutoResponseRule(
            name="No next session",
            pattern="",
            response="display version\r",
            trigger_type="manual",
            once=False,
            steps=[AutoResponseStep(
                pattern="",
                responses=["display version\r"],
                response_targets=["next"],
            )],
        ))
        queue, _replay = application.events.subscribe()

        application.automation.trigger_rule(record.id, only.id)
        await asyncio.sleep(0.01)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        failed = next(event for event in events if event.type == "automation.rule.failed")
        assert "目标终端不存在" in failed.data["message"]
        assert manager.writes == []
        application.events.unsubscribe(queue)
        await application.automation.close()

    asyncio.run(scenario())


def test_session_id_target_selects_exact_duplicate_named_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        device_id = application.devices.list_inventory().devices[0].id
        first = await application.sessions.create(device_id, "simulated", "Duplicate")
        second = await application.sessions.create(device_id, "simulated", "Duplicate")
        record = application.automation.create_rule(AutoResponseRule(
            name="Exact target",
            pattern="",
            response="display version\r",
            trigger_type="manual",
            once=False,
            actions=[AutoResponseAction(
                kind="send",
                text="display version",
                append_enter=True,
                target=f"session-id:{second.id}",
            )],
        ))

        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.01)

        assert manager.writes == [
            (second.id, "display version\r", "automation"),
        ]
        await application.automation.close()

    asyncio.run(scenario())


def test_disconnected_exact_target_fails_without_writing(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        device_id = application.devices.list_inventory().devices[0].id
        source = await application.sessions.create(device_id, "simulated", "Source")
        target = await application.sessions.create(device_id, "simulated", "Offline target")
        manager.records[target.id] = replace(target, status="disconnected")
        record = application.automation.create_rule(AutoResponseRule(
            name="Offline target",
            pattern="",
            response="reboot\r",
            trigger_type="manual",
            once=False,
            actions=[AutoResponseAction(
                kind="send",
                text="reboot",
                append_enter=True,
                target=f"session-id:{target.id}",
            )],
        ))
        queue, _replay = application.events.subscribe()

        application.automation.trigger_rule(record.id, source.id)
        await asyncio.sleep(0.01)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        failed = next(event for event in events if event.type == "automation.rule.failed")
        assert "目标终端未连接" in failed.data["message"]
        assert manager.writes == []
        application.events.unsubscribe(queue)
        await application.automation.close()

    asyncio.run(scenario())


def test_step_editor_text_is_decoded_at_execution_without_rewriting_state(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Readable UI step",
            pattern="",
            response="",
            response_text="",
            trigger_type="manual",
            once=False,
            steps=[AutoResponseStep(
                pattern="",
                responses=["display version"],
                response_texts=["display version"],
                response_targets=["source"],
                response_delays=[0],
                response_append_enters=[True],
            )],
        ))

        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.01)

        assert manager.writes[-1] == (first.id, "display version\r", "automation")
        assert application.automation.get_rule(record.id).rule.steps[0].responses == [
            "display version"
        ]
        await application.automation.close()

    asyncio.run(scenario())


def test_manual_multi_step_run_waits_for_each_following_prompt(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Manual staged login",
            pattern="LOGIN>",
            response="admin\r",
            trigger_type="manual",
            once=False,
            steps=[
                AutoResponseStep(pattern="LOGIN>", responses=["admin\r"]),
                AutoResponseStep(pattern="CODE>", responses=["123456\r"]),
                AutoResponseStep(pattern="", responses=["display version\r"]),
            ],
        ))

        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.01)

        assert [data for _session_id, data, _origin in manager.writes] == ["admin\r"]
        status = next(item for item in application.automation.statuses() if item.session_id == first.id)
        assert status.waiting_rule_ids == (record.id,)

        manager.emit("terminal.output", first.id, data="CODE>")
        await asyncio.sleep(0.01)

        assert [data for _session_id, data, _origin in manager.writes] == [
            "admin\r",
            "123456\r",
            "display version\r",
        ]
        assert all(
            record.id not in status.waiting_rule_ids
            for status in application.automation.statuses()
        )
        await application.automation.close()

    asyncio.run(scenario())


def test_manual_multi_step_loop_waits_again_before_next_iteration(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Manual repeated handshake",
            pattern="ROUND>",
            response="begin\r",
            trigger_type="manual",
            loop_count=2,
            once=False,
            steps=[
                AutoResponseStep(pattern="ROUND>", responses=["begin\r"]),
                AutoResponseStep(pattern="DONE>", responses=["confirm\r"]),
            ],
        ))

        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.01)
        manager.emit("terminal.output", first.id, data="DONE>")
        await asyncio.sleep(0.01)

        assert [data for _session_id, data, _origin in manager.writes] == [
            "begin\r",
            "confirm\r",
        ]
        status = next(item for item in application.automation.statuses() if item.session_id == first.id)
        assert status.waiting_rule_ids == (record.id,)

        manager.emit("terminal.output", first.id, data="ROUND>")
        await asyncio.sleep(0.01)
        manager.emit("terminal.output", first.id, data="DONE>")
        await asyncio.sleep(0.01)

        assert [data for _session_id, data, _origin in manager.writes] == [
            "begin\r",
            "confirm\r",
            "begin\r",
            "confirm\r",
        ]
        assert all(
            record.id not in status.waiting_rule_ids
            for status in application.automation.statuses()
        )
        await application.automation.close()

    asyncio.run(scenario())


def test_manual_input_cancels_delayed_automation(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Delayed connect",
            pattern="",
            response="reboot\r",
            trigger_type="connected",
            delay_ms=100,
            once=False,
        ))

        manager.emit("terminal.status", first.id, status="connected")
        assert record.id in application.automation.statuses()[0].running_rule_ids
        manager.emit("terminal.input", first.id, origin="user")
        await asyncio.sleep(0.15)

        assert manager.writes == []
        assert all(
            record.id not in status.running_rule_ids
            for status in application.automation.statuses()
        )
        await application.automation.close()

    asyncio.run(scenario())


def test_one_terminal_event_starts_every_matching_rule(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        records = [
            application.automation.create_rule(AutoResponseRule(
                name=name,
                pattern="",
                response=response,
                trigger_type="connected",
                once=False,
            ))
            for name, response in (
                ("Prepare terminal", "screen-length 0 temporary\r"),
                ("Show version", "display version\r"),
            )
        ]

        manager.emit("terminal.status", first.id, status="connected")
        assert {
            rule_id
            for status in application.automation.statuses()
            for rule_id in status.running_rule_ids
        } == {record.id for record in records}
        await asyncio.sleep(0.01)

        assert {data for _session_id, data, origin in manager.writes if origin == "automation"} == {
            "screen-length 0 temporary\r",
            "display version\r",
        }
        await application.automation.close()

    asyncio.run(scenario())


def test_reconnect_discards_partial_output_and_step_progress(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        application.automation.create_rule(AutoResponseRule(
            name="Two-step prompt",
            pattern="READY>",
            response="first\r",
            once=False,
            steps=[
                AutoResponseStep(pattern="READY>", responses=["first\r"]),
                AutoResponseStep(pattern="NEXT>", responses=["second\r"]),
            ],
        ))

        manager.emit("terminal.input", first.id)
        manager.emit("terminal.output", first.id, data="READY>")
        await asyncio.sleep(0.01)
        assert [data for _session_id, data, _origin in manager.writes] == ["first\r"]

        manager.emit("terminal.output", first.id, data="REA")
        manager.emit("terminal.status", first.id, status="disconnected")
        manager.emit("terminal.status", first.id, status="connected")
        manager.emit("terminal.output", first.id, data="DY>")
        await asyncio.sleep(0.01)
        assert [data for _session_id, data, _origin in manager.writes] == ["first\r"]

        manager.emit("terminal.input", first.id)
        manager.emit("terminal.output", first.id, data="READY>")
        await asyncio.sleep(0.01)
        assert [data for _session_id, data, _origin in manager.writes] == [
            "first\r",
            "first\r",
        ]
        await application.automation.close()

    asyncio.run(scenario())


def test_waiting_step_is_visible_and_manual_input_cancels_it(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Visible waiting flow",
            pattern="FIRST>",
            response="one\r",
            once=False,
            steps=[
                AutoResponseStep(pattern="FIRST>", responses=["one\r"]),
                AutoResponseStep(pattern="SECOND>", responses=["two\r"]),
            ],
        ))

        manager.emit("terminal.input", first.id)
        manager.emit("terminal.output", first.id, data="FIRST>")
        await asyncio.sleep(0.01)

        status = next(item for item in application.automation.statuses() if item.session_id == first.id)
        assert status.running_rule_ids == ()
        assert status.waiting_rule_ids == (record.id,)

        manager.emit("terminal.input", first.id)
        assert all(
            record.id not in status.waiting_rule_ids
            for status in application.automation.statuses()
        )
        manager.emit("terminal.output", first.id, data="SECOND>")
        await asyncio.sleep(0.01)
        assert [data for _session_id, data, _origin in manager.writes] == ["one\r"]
        await application.automation.close()

    asyncio.run(scenario())


def test_waiting_step_timeout_fails_and_clears_progress(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Timed handshake",
            pattern="FIRST>",
            response="one\r",
            trigger_type="manual",
            once=False,
            steps=[
                AutoResponseStep(pattern="FIRST>", responses=["one\r"]),
                AutoResponseStep(pattern="SECOND>", responses=["two\r"], timeout_ms=20),
            ],
        ))
        queue, _replay = application.events.subscribe()

        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.05)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        failed = next(event for event in events if event.type == "automation.rule.failed")
        assert failed.data["name"] == "Timed handshake"
        assert failed.data["reason"] == "step_timeout"
        assert "第 2 步" in failed.data["message"]
        assert manager.writes == [(first.id, "one\r", "automation")]
        assert all(
            record.id not in status.waiting_rule_ids
            for status in application.automation.statuses()
        )
        assert application.automation.activities()[0].event == "failed"
        assert "第 2 步" in application.automation.activities()[0].message
        application.events.unsubscribe(queue)
        await application.automation.close()

    asyncio.run(scenario())


def test_matching_prompt_cancels_waiting_step_timeout(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Prompt before timeout",
            pattern="FIRST>",
            response="one\r",
            trigger_type="manual",
            once=False,
            steps=[
                AutoResponseStep(pattern="FIRST>", responses=["one\r"]),
                AutoResponseStep(pattern="SECOND>", responses=["two\r"], timeout_ms=40),
            ],
        ))
        queue, _replay = application.events.subscribe()

        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.01)
        manager.emit("terminal.output", first.id, data="SECOND>")
        await asyncio.sleep(0.06)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        assert not any(event.type == "automation.rule.failed" for event in events)
        assert manager.writes == [
            (first.id, "one\r", "automation"),
            (first.id, "two\r", "automation"),
        ]
        application.events.unsubscribe(queue)
        await application.automation.close()

    asyncio.run(scenario())


def test_regex_match_spanning_large_output_chunks_triggers_only_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        application.automation.create_rule(AutoResponseRule(
            name="Chunked regex",
            pattern=r"BEGIN.{80}END",
            response="matched\r",
            match_type="regex",
            once=False,
        ))

        manager.emit("terminal.input", first.id)
        manager.emit("terminal.output", first.id, data="BEGIN" + ("x" * 80))
        manager.emit("terminal.output", first.id, data="END")
        await asyncio.sleep(0.01)
        manager.emit("terminal.output", first.id, data="unrelated output")
        await asyncio.sleep(0.01)

        assert [data for _session_id, data, _origin in manager.writes] == ["matched\r"]
        await application.automation.close()

    asyncio.run(scenario())


def test_visible_prompt_matching_handles_split_ansi_and_backspace(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        application.automation.create_rule(AutoResponseRule(
            name="Decorated prompt",
            pattern="Password:",
            response="{{secret:test-visible-password}}",
            once=False,
        ))
        _secrets.set("test-visible-password", "secret\r")

        manager.emit("terminal.input", first.id)
        manager.emit("terminal.output", first.id, data="\x1b[3")
        manager.emit("terminal.output", first.id, data="1mPassworX\b")
        manager.emit("terminal.output", first.id, data="d:\x1b[0m")
        await asyncio.sleep(0.01)
        manager.emit("terminal.output", first.id, data="\x1b[2K")
        await asyncio.sleep(0.01)

        assert manager.writes == [(first.id, "secret\r", "automation")]
        await application.automation.close()

    asyncio.run(scenario())


def test_action_conditions_match_visible_text_across_ansi_sequences(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Visible condition",
            pattern="",
            response="display version\r",
            trigger_type="manual",
            once=False,
            actions=[AutoResponseAction(
                kind="condition",
                condition_pattern="READY>",
                actions=[AutoResponseAction(
                    kind="send",
                    text="display version",
                    append_enter=True,
                )],
            )],
        ))

        manager.emit("terminal.output", first.id, data="RE\x1b[32mADY\x1b[0m>")
        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.01)

        assert manager.writes == [(first.id, "display version\r", "automation")]
        await application.automation.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("rule", "field"),
    [
        (
            AutoResponseRule(
                name="Broken trigger",
                pattern="(",
                response="never\r",
                match_type="regex",
            ),
            "触发文本",
        ),
        (
            AutoResponseRule(
                name="Broken condition",
                pattern="",
                response="",
                trigger_type="manual",
                actions=[AutoResponseAction(
                    kind="condition",
                    condition_pattern="[",
                    condition_match_type="regex",
                    actions=[AutoResponseAction(kind="send", text="never")],
                )],
            ),
            "条件文本",
        ),
    ],
)
def test_invalid_regex_is_rejected_before_rule_is_saved(
    tmp_path: Path,
    rule: AutoResponseRule,
    field: str,
) -> None:
    application, _manager, _store, _secrets = _application(tmp_path)

    with pytest.raises(UnsupportedOperationError, match=field):
        application.automation.create_rule(rule)

    assert application.automation.list_rules() == []


def test_manual_trigger_rejects_disconnected_session(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Connected only",
            pattern="",
            response="display version\r",
            trigger_type="manual",
            once=False,
        ))
        manager.records[first.id] = replace(first, status="disconnected")

        with pytest.raises(UnsupportedOperationError, match="未连接"):
            application.automation.trigger_rule(record.id, first.id)

        assert manager.writes == []
        await application.automation.close()

    asyncio.run(scenario())


def test_missing_target_fails_instead_of_silently_completing_or_misdirecting(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Missing target",
            pattern="",
            response="",
            trigger_type="manual",
            once=False,
            actions=[AutoResponseAction(
                kind="send",
                text="reboot",
                append_enter=True,
                target="session:missing:telnet:Closed terminal",
            )],
        ))
        queue, _replay = application.events.subscribe()

        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.01)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        failed = next(event for event in events if event.type == "automation.rule.failed")
        assert "目标终端不存在" in failed.data["message"]
        assert manager.writes == []
        assert all(
            record.id not in status.waiting_rule_ids
            for status in application.automation.statuses()
        )
        application.events.unsubscribe(queue)
        await application.automation.close()

    asyncio.run(scenario())


def test_missing_secret_reference_reports_failure_without_sending_empty_input(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Missing credential",
            pattern="",
            response="{{secret:missing-login}}",
            trigger_type="manual",
            once=False,
        ))
        queue, _replay = application.events.subscribe()

        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.01)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        failed = next(event for event in events if event.type == "automation.rule.failed")
        assert "凭据不可用" in failed.data["message"]
        assert manager.writes == []
        application.events.unsubscribe(queue)
        await application.automation.close()

    asyncio.run(scenario())


def test_action_loop_manual_trigger_and_explicit_cancel(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Manual heartbeat",
            pattern="",
            response="ping\r",
            trigger_type="manual",
            once=False,
            actions=[AutoResponseAction(
                kind="loop",
                repeat_count=0,
                interval_ms=10,
                actions=[AutoResponseAction(
                    kind="send",
                    text="ping",
                    append_enter=True,
                )],
            )],
        ))

        application.automation.trigger_rule(record.id, first.id)
        for _ in range(20):
            if len(manager.writes) >= 2:
                break
            await asyncio.sleep(0.01)
        application.automation.cancel_session(first.id, reason="test")
        count_after_cancel = len(manager.writes)
        await asyncio.sleep(0.03)

        assert count_after_cancel >= 2
        assert len(manager.writes) == count_after_cancel
        assert all(write[2] == "automation" for write in manager.writes)
        await application.automation.close()

    asyncio.run(scenario())


def test_action_variables_increment_inside_loop_and_render_builtins(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Incrementing ports",
            pattern="",
            response="",
            trigger_type="manual",
            once=False,
            actions=[
                AutoResponseAction(
                    kind="set",
                    variable_name="port",
                    variable_value="2000",
                ),
                AutoResponseAction(
                    kind="loop",
                    repeat_count=3,
                    actions=[
                        AutoResponseAction(
                            kind="send",
                            text="connect {{port}} {{loop.index}}/{{loop.count}}",
                            append_enter=True,
                        ),
                        AutoResponseAction(
                            kind="set",
                            variable_name="port",
                            variable_value="1",
                            variable_operation="add",
                        ),
                    ],
                ),
                AutoResponseAction(
                    kind="send",
                    text="next {{port}}",
                    append_enter=True,
                ),
            ],
        ))

        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.03)

        assert [write[1] for write in manager.writes] == [
            "connect 2000 1/3\r",
            "connect 2001 2/3\r",
            "connect 2002 3/3\r",
            "next 2003\r",
        ]
        await application.automation.close()

    asyncio.run(scenario())


def test_action_expression_preview_is_side_effect_free_and_matches_runtime(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        rule = AutoResponseRule(
            name="Expression ports",
            pattern="",
            response="",
            trigger_type="manual",
            once=False,
            actions=[
                AutoResponseAction(kind="set", variable_name="base", variable_value="2000"),
                AutoResponseAction(kind="set", variable_name="step", variable_value="2"),
                AutoResponseAction(
                    kind="loop",
                    repeat_count=3,
                    actions=[
                        AutoResponseAction(
                            kind="set",
                            variable_name="port",
                            variable_value="{{base + loop.index0 * step}}",
                        ),
                        AutoResponseAction(
                            kind="send",
                            text="connect {{port}} {{upper(session.kind)}}",
                            append_enter=True,
                        ),
                        AutoResponseAction(
                            kind="condition",
                            condition_match_type="expression",
                            condition_pattern="loop.last and port == 2004",
                            actions=[AutoResponseAction(
                                kind="send",
                                text="done {{device.id}}",
                                append_enter=True,
                            )],
                        ),
                    ],
                ),
            ],
        )

        preview = application.automation.preview_rule(rule, session_id=first.id)

        assert manager.writes == []
        assert preview["variables"] == {"base": 2000, "step": 2, "port": 2004}
        send_titles = [
            step["title"]
            for step in preview["steps"]
            if step["kind"] == "send"
        ]
        assert send_titles == [
            "connect 2000 SIMULATED",
            "connect 2002 SIMULATED",
            "connect 2004 SIMULATED",
            f"done {first.device_id}",
        ]

        record = application.automation.create_rule(rule)
        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.03)
        assert [write[1] for write in manager.writes] == [
            "connect 2000 SIMULATED\r",
            "connect 2002 SIMULATED\r",
            "connect 2004 SIMULATED\r",
            f"done {first.device_id}\r",
        ]
        await application.automation.close()

    asyncio.run(scenario())


def test_action_expression_rejects_unsafe_calls_and_private_attributes() -> None:
    with pytest.raises(UnsupportedOperationError, match="函数不受支持"):
        SafeAutomationExpression.evaluate("__import__('os')", {})
    with pytest.raises(UnsupportedOperationError, match="属性不存在"):
        SafeAutomationExpression.evaluate("session.__class__", {"session": {"id": "x"}})


def test_action_variable_validation_and_unknown_reference_are_explicit(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        with pytest.raises(UnsupportedOperationError, match="变量名无效"):
            application.automation.create_rule(AutoResponseRule(
                name="Invalid variable",
                pattern="",
                response="",
                trigger_type="manual",
                actions=[AutoResponseAction(
                    kind="set",
                    variable_name="1bad",
                    variable_value="1",
                )],
            ))

        record = application.automation.create_rule(AutoResponseRule(
            name="Unknown variable",
            pattern="",
            response="",
            trigger_type="manual",
            actions=[AutoResponseAction(kind="send", text="{{missing}}")],
        ))
        queue, _replay = application.events.subscribe()
        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.02)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        failed = next(event for event in events if event.type == "automation.rule.failed")
        assert "变量尚未赋值：missing" in failed.data["message"]
        assert manager.writes == []
        application.events.unsubscribe(queue)
        await application.automation.close()

    asyncio.run(scenario())


def test_automation_activity_records_execution_lifecycle_and_target(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, _secrets = _application(tmp_path)
        first, second = await _sessions(application)
        record = application.automation.create_rule(AutoResponseRule(
            name="Audited dispatch",
            pattern="",
            response="display version\r",
            trigger_type="manual",
            once=False,
            actions=[AutoResponseAction(
                kind="send",
                text="display version",
                append_enter=True,
                target=f"session-id:{second.id}",
            )],
        ))

        application.automation.trigger_rule(record.id, first.id)
        await asyncio.sleep(0.01)

        activity = application.automation.activities()
        assert [item.event for item in activity[:3]] == [
            "completed",
            "sent",
            "started",
        ]
        assert all(item.rule_id == record.id for item in activity[:3])
        assert activity[1].target_session_id == second.id
        assert activity[1].session_id == first.id
        assert manager.writes == [(second.id, "display version\r", "automation")]
        await application.automation.close()

    asyncio.run(scenario())


def test_legacy_secret_moves_to_vault_and_never_returns_from_workspace(tmp_path: Path) -> None:
    application, _manager, store, secrets = _application(tmp_path)
    source = tmp_path / "desktop_state.json"
    plaintext = "legacy-super-secret\r"
    payload = {
        "auto_response_rules": [{
            "name": "Login password",
            "pattern": "Password:",
            "response": plaintext,
            "response_text": "legacy-super-secret",
            "enabled": True,
            "once": False,
        }]
    }
    original = json.dumps(payload, ensure_ascii=False)
    source.write_text(original, encoding="utf-8")

    assert application.automation.import_legacy_state(source) == {"rules": 1, "secrets": 1}
    assert application.automation.import_legacy_state(source) == {"rules": 0, "secrets": 0}
    record = application.automation.list_rules()[0]
    public = application.automation.public_rule(record)
    secret_id = record.rule.response.removeprefix("{{secret:").removesuffix("}}")

    assert public.response == "••••••"
    assert plaintext not in json.dumps(
        application.automation.serialize_rule(public), ensure_ascii=False
    )
    assert secrets.get(secret_id) == plaintext
    assert source.read_text(encoding="utf-8") == original
    with sqlite3.connect(store.path) as connection:
        stored = connection.execute("SELECT payload FROM automation_rules").fetchone()[0]
    assert "legacy-super-secret" not in stored


def test_generic_rule_editor_rejects_plaintext_credentials(tmp_path: Path) -> None:
    application, _manager, _store, _secrets = _application(tmp_path)

    with pytest.raises(UnsupportedOperationError):
        application.automation.create_rule(AutoResponseRule(
            name="Unsafe password",
            pattern="Password:",
            response="plaintext-secret\r",
            once=False,
        ))


def test_clone_rule_resets_runtime_state_and_starts_disabled(tmp_path: Path) -> None:
    application, _manager, _store, _secrets = _application(tmp_path)
    source = application.automation.create_rule(AutoResponseRule(
        name="Reusable workflow",
        pattern="READY>",
        response="display version\r",
        enabled=True,
        once=False,
        trigger_count=7,
        steps=[AutoResponseStep(
            pattern="READY>",
            responses=["display version\r"],
            timeout_ms=12_000,
        )],
    ))

    cloned = application.automation.clone_rule(source.id)

    assert cloned.id != source.id
    assert cloned.rule.name == "Reusable workflow 副本"
    assert cloned.rule.enabled is False
    assert cloned.rule.trigger_count == 0
    assert cloned.rule.steps[0].timeout_ms == 12_000
    assert application.automation.get_rule(source.id).rule.enabled is True
    assert application.automation.get_rule(source.id).rule.trigger_count == 7


def test_clone_rule_copies_secret_before_original_is_deleted(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store, secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        source_secret_id = "automation/source/login"
        secrets.set(source_secret_id, "device-password\r")
        source = application.automation.create_rule(AutoResponseRule(
            name="Secure login",
            pattern="",
            response=f"{{{{secret:{source_secret_id}}}}}",
            response_text=f"{{{{secret:{source_secret_id}}}}}",
            trigger_type="manual",
            enabled=True,
            once=False,
        ))

        cloned = application.automation.clone_rule(source.id)
        cloned_secret_id = (
            cloned.rule.response.removeprefix("{{secret:").removesuffix("}}")
        )

        assert cloned_secret_id != source_secret_id
        assert secrets.get(cloned_secret_id) == "device-password\r"
        assert application.automation.public_rule(cloned).response == "••••••"

        application.automation.delete_rule(source.id)
        assert secrets.get(source_secret_id) is None
        assert secrets.get(cloned_secret_id) == "device-password\r"

        application.automation.set_enabled(cloned.id, True)
        application.automation.trigger_rule(cloned.id, first.id)
        await asyncio.sleep(0.01)
        assert manager.writes == [
            (first.id, "device-password\r", "automation"),
        ]
        await application.automation.close()

    asyncio.run(scenario())


def test_quick_send_buttons_are_persistent_and_write_through_session_service(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, store, _secrets = _application(tmp_path)
        first, _second = await _sessions(application)

        defaults = application.automation.list_quick_send_buttons()
        assert defaults[0].name == "发送 Ctrl+B"
        created = application.automation.create_quick_send_button(
            name="查看版本",
            response_text="display version",
            append_enter=True,
        )
        await application.automation.send_quick_send_button(created.id, first.id)

        assert manager.writes[-1] == (first.id, "display version\r", "user")
        reopened = build_desktop_application(
            SampleDeviceRepository(),
            EventSessionManager(),
            automation_store=SQLiteDesktopStore(store.path),
        )
        assert any(button.id == created.id for button in reopened.automation.list_quick_send_buttons())

    asyncio.run(scenario())


def test_sensitive_quick_send_is_masked_and_vault_backed(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, store, secrets = _application(tmp_path)
        first, _second = await _sessions(application)
        plaintext = "device-password"

        created = application.automation.create_quick_send_button(
            name="登录口令",
            response_text=plaintext,
            append_enter=True,
            sensitive=True,
        )
        await application.automation.send_quick_send_button(created.id, first.id)

        assert created.response_text == "••••••"
        assert secrets.get(f"quick-send/{created.id}") == f"{plaintext}\r"
        assert manager.writes[-1] == (first.id, f"{plaintext}\r", "user")
        with sqlite3.connect(store.path) as connection:
            metadata = connection.execute(
                "SELECT value FROM app_meta WHERE key = ?",
                (application.automation.QUICK_SEND_META_KEY,),
            ).fetchone()[0]
        assert plaintext not in metadata

    asyncio.run(scenario())


def test_legacy_quick_send_buttons_import_once_without_modifying_source(tmp_path: Path) -> None:
    application, _manager, _store, _secrets = _application(tmp_path)
    source = tmp_path / "desktop_state.json"
    original = json.dumps({
        "quick_send_buttons": [{
            "name": "发送 Ctrl+A",
            "response": "\u0001",
            "response_text": "Ctrl+A",
            "append_enter": False,
        }]
    }, ensure_ascii=False)
    source.write_text(original, encoding="utf-8")

    application.automation.import_legacy_state(source)
    application.automation.import_legacy_state(source)
    buttons = application.automation.list_quick_send_buttons()

    assert [(button.id, button.response_text) for button in buttons] == [
        ("QUICK-LEGACY-1", "Ctrl+A")
    ]
    assert source.read_text(encoding="utf-8") == original
