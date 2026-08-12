from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from src.application import MemorySecretStore, UnsupportedOperationError, build_desktop_application
from src.application.credentials import ConnectionTarget
from src.application.sessions import SessionRecord
from src.auto_response import AutoResponseAction, AutoResponseRule, AutoResponseStep
from src.infrastructure.sqlite_desktop import SQLiteDesktopStore
from src.repository import SampleDeviceRepository


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
        await asyncio.sleep(0.04)
        application.automation.cancel_session(first.id, reason="test")
        count_after_cancel = len(manager.writes)
        await asyncio.sleep(0.03)

        assert count_after_cancel >= 2
        assert len(manager.writes) == count_after_cancel
        assert all(write[2] == "automation" for write in manager.writes)
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
