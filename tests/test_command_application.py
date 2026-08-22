from __future__ import annotations

import json
import sqlite3
import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from device_tui.application import (
    ApplicationConflictError,
    UnsupportedOperationError,
    build_desktop_application,
)
from device_tui.application.commands import CommandService, redact_command_secrets
from device_tui.application.credentials import ConnectionTarget
from device_tui.application.sessions import SessionRecord
from device_tui.infrastructure.persistence.sqlite_desktop import SQLiteDesktopStore
from device_tui.device_sources.sample import SampleDeviceRepository


class FakeSessionManager:
    def __init__(self) -> None:
        self.records: dict[str, SessionRecord] = {}
        self.writes: list[tuple[str, str]] = []
        self.counter = 0

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
        record = self.records[session_id]
        disconnected = replace(record, status="disconnected")
        self.records[session_id] = disconnected
        return disconnected

    async def close(self, session_id: str) -> bool:
        return self.records.pop(session_id, None) is not None

    async def close_all(self) -> None:
        self.records.clear()

    async def write(self, session_id: str, data: str) -> None:
        if session_id not in self.records:
            raise KeyError(session_id)
        self.writes.append((session_id, data))

    def read_log(self, session_id: str, max_chars: int) -> tuple[str, bool]:
        _ = max_chars
        if session_id not in self.records:
            raise KeyError(session_id)
        return "", False


def _application(tmp_path: Path):
    manager = FakeSessionManager()
    store = SQLiteDesktopStore(tmp_path / "device-tui.sqlite3")
    application = build_desktop_application(
        SampleDeviceRepository(),
        manager,
        profile_store=store,
        command_store=store,
    )
    return application, manager, store


def test_command_groups_crud_preferences_and_persistence(tmp_path: Path) -> None:
    application, _manager, store = _application(tmp_path)
    commands = application.commands
    default = commands.list_groups()[0]
    created = commands.create_group("Operations")
    third = commands.create_group("Monitoring")
    assert [group.id for group in commands.list_groups()] == [default.id, created.id, third.id]
    commands.reorder_groups([third.id, default.id, created.id])
    assert [group.id for group in commands.list_groups()] == [third.id, default.id, created.id]
    with pytest.raises(UnsupportedOperationError):
        commands.reorder_groups([default.id])
    updated = commands.update_group(
        created.id,
        content="display version\npassword super-secret",
    )

    assert updated.content == "display version\npassword [REDACTED]"
    assert commands.current_group_id() == third.id
    commands.set_enter_sends(True)
    assert commands.enter_sends()

    restored = CommandService(store, application.sessions)
    assert restored.get_group(created.id).content == updated.content
    assert [group.id for group in restored.list_groups()] == [third.id, default.id, created.id]
    assert restored.current_group_id() == third.id
    assert restored.enter_sends()

    commands.delete_group(created.id)
    assert commands.current_group_id() == third.id
    commands.delete_group(third.id)
    with pytest.raises(ApplicationConflictError):
        commands.delete_group(default.id)


def test_command_send_broadcast_history_and_suggestions(tmp_path: Path) -> None:
    async def scenario() -> None:
        application, manager, _store = _application(tmp_path)
        device_id = application.devices.list_inventory().devices[0].id
        first = await application.sessions.create(device_id, "simulated", "First")
        second = await application.sessions.create(device_id, "simulated", "Second")

        await application.commands.send(first.id, "display version")
        targets = await application.commands.broadcast("password very-secret")

        assert manager.writes[0] == (first.id, "display version\r")
        assert manager.writes[1:] == [
            (first.id, "password very-secret\r"),
            (second.id, "password very-secret\r"),
        ]
        assert targets == [first.id, second.id]
        assert application.commands.history()[0].command == "password [REDACTED]"
        assert application.commands.suggestions("dis", device_id=device_id)[0] == "display version"

    asyncio.run(scenario())


def test_command_legacy_import_is_idempotent_and_preserves_source(tmp_path: Path) -> None:
    application, _manager, _store = _application(tmp_path)
    source = tmp_path / "desktop_state.json"
    payload = {
        "command_record_groups": [
            {"name": "巡检", "content": "display version\ntoken abc123"},
            {"name": "维护", "content": "reboot"},
        ],
        "current_command_group": 1,
        "command_enter_sends": True,
        "command_history": [
            {
                "command": "password old-secret",
                "device_id": "DEVICE-1",
                "session_kind": "telnet",
                "count": 2,
                "last_used_at": 100,
            }
        ],
    }
    original = json.dumps(payload, ensure_ascii=False)
    source.write_text(original, encoding="utf-8")

    first = application.commands.import_legacy_state(source)
    second = application.commands.import_legacy_state(source)

    assert first == {"groups": 2, "history": 1}
    assert second == {"groups": 0, "history": 0}
    assert [group.name for group in application.commands.list_groups()] == ["巡检", "维护"]
    assert application.commands.current_group_id() == "COMMAND-GROUP-LEGACY-2"
    assert application.commands.enter_sends()
    assert application.commands.history()[0].command == "password [REDACTED]"
    assert "abc123" not in application.commands.list_groups()[0].content
    assert source.read_text(encoding="utf-8") == original


def test_sqlite_desktop_schema_version_and_command_tables(tmp_path: Path) -> None:
    database = tmp_path / "device-tui.sqlite3"
    SQLiteDesktopStore(database)

    with sqlite3.connect(database) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert version == SQLiteDesktopStore.SCHEMA_VERSION
    assert {
        "connection_profiles",
        "command_groups",
        "command_history",
        "automation_rules",
        "operations",
    } <= tables


def test_command_secret_redaction_covers_common_assignment_forms() -> None:
    assert redact_command_secrets("password hunter2") == "password [REDACTED]"
    assert redact_command_secrets("token=abc") == "token=[REDACTED]"
    assert redact_command_secrets("set community:public") == "set community:[REDACTED]"
