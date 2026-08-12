"""Versioned SQLite store shared by desktop application services."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..application.automation import AutomationRuleRecord
from ..application.commands import CommandGroup
from ..auto_response import deserialize_auto_response_rule, serialize_auto_response_rule
from ..command_suggestions import CommandHistoryItem
from .sqlite_profiles import SQLiteConnectionProfileStore


class SQLiteDesktopStore(SQLiteConnectionProfileStore):
    SCHEMA_VERSION = 3

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._migrate_desktop_schema()

    def list_command_groups(self) -> list[CommandGroup]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM command_groups ORDER BY sort_order, name, id"
            ).fetchall()
        return [self._command_group(row) for row in rows]

    def get_command_group(self, group_id: str) -> CommandGroup | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM command_groups WHERE id = ?",
                (group_id,),
            ).fetchone()
        return self._command_group(row) if row is not None else None

    def upsert_command_group(self, group: CommandGroup) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO command_groups (
                    id, name, content, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    content=excluded.content,
                    sort_order=excluded.sort_order,
                    updated_at=excluded.updated_at
                """,
                (
                    group.id,
                    group.name,
                    group.content,
                    group.sort_order,
                    group.created_at,
                    group.updated_at,
                ),
            )

    def delete_command_group(self, group_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM command_groups WHERE id = ?", (group_id,))

    def list_command_history(self) -> list[CommandHistoryItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT command, device_id, session_kind, use_count, last_used_at
                FROM command_history
                ORDER BY last_used_at DESC, use_count DESC, command
                """
            ).fetchall()
        return [
            CommandHistoryItem(
                command=str(row["command"]),
                device_id=str(row["device_id"]),
                session_kind=str(row["session_kind"]),
                count=int(row["use_count"]),
                last_used_at=float(row["last_used_at"]),
            )
            for row in rows
        ]

    def replace_command_history(self, history: list[CommandHistoryItem]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM command_history")
            connection.executemany(
                """
                INSERT INTO command_history (
                    command, device_id, session_kind, use_count, last_used_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.command,
                        item.device_id,
                        item.session_kind,
                        item.count,
                        item.last_used_at,
                    )
                    for item in history
                ],
            )

    def list_automation_rules(self) -> list[AutomationRuleRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM automation_rules ORDER BY created_at, id"
            ).fetchall()
        records: list[AutomationRuleRecord] = []
        for row in rows:
            record = self._automation_rule(row)
            if record is not None:
                records.append(record)
        return records

    def get_automation_rule(self, rule_id: str) -> AutomationRuleRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM automation_rules WHERE id = ?",
                (rule_id,),
            ).fetchone()
        return self._automation_rule(row) if row is not None else None

    def upsert_automation_rule(self, record: AutomationRuleRecord) -> None:
        payload = json.dumps(
            serialize_auto_response_rule(record.rule),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO automation_rules (id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (record.id, payload, record.created_at, record.updated_at),
            )

    def delete_automation_rule(self, rule_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM automation_rules WHERE id = ?",
                (rule_id,),
            )

    def _migrate_desktop_schema(self) -> None:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > self.SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported desktop database schema {version}; "
                    f"maximum supported is {self.SCHEMA_VERSION}."
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS command_groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    content TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS command_history (
                    command TEXT NOT NULL,
                    device_id TEXT NOT NULL DEFAULT '',
                    session_kind TEXT NOT NULL DEFAULT '',
                    use_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (command, device_id, session_kind)
                );
                CREATE TABLE IF NOT EXISTS automation_rules (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                PRAGMA user_version = 3;
                """
            )

    @staticmethod
    def _command_group(row: sqlite3.Row) -> CommandGroup:
        return CommandGroup(
            id=str(row["id"]),
            name=str(row["name"]),
            content=str(row["content"]),
            sort_order=int(row["sort_order"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _automation_rule(row: sqlite3.Row) -> AutomationRuleRecord | None:
        try:
            payload = json.loads(str(row["payload"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        rule = deserialize_auto_response_rule(payload)
        if rule is None:
            return None
        return AutomationRuleRecord(
            id=str(row["id"]),
            rule=rule,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
