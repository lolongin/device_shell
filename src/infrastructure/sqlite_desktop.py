"""Versioned SQLite store shared by desktop application services."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..application.automation import AutomationRuleRecord
from ..application.commands import CommandGroup
from ..application.operations import OperationRecord, TERMINAL_OPERATION_STATUSES
from ..auto_response import deserialize_auto_response_rule, serialize_auto_response_rule
from ..command_suggestions import CommandHistoryItem
from ..data import Device
from ..imported_devices import (
    ImportedDeviceMetadata,
    deserialize_imported_device,
    serialize_imported_device,
)
from .sqlite_profiles import SQLiteConnectionProfileStore


class SQLiteDesktopStore(SQLiteConnectionProfileStore):
    SCHEMA_VERSION = 5

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

    def list_operations(self, *, kind: str, limit: int) -> list[OperationRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM operations
                WHERE kind = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (kind, max(0, int(limit))),
            ).fetchall()
        return [self._operation(row) for row in rows]

    def upsert_operation(self, record: OperationRecord) -> None:
        payload = json.dumps(record.data, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO operations (
                    id, kind, direction, device_id, session_id, status, stage,
                    message, progress_percent, bytes_transferred, total_bytes,
                    bytes_per_second, eta_seconds, queue_position, retry_of,
                    cancellable, error_code, revision, created_at, updated_at, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    stage=excluded.stage,
                    message=excluded.message,
                    progress_percent=excluded.progress_percent,
                    bytes_transferred=excluded.bytes_transferred,
                    total_bytes=excluded.total_bytes,
                    bytes_per_second=excluded.bytes_per_second,
                    eta_seconds=excluded.eta_seconds,
                    queue_position=excluded.queue_position,
                    retry_of=excluded.retry_of,
                    cancellable=excluded.cancellable,
                    error_code=excluded.error_code,
                    revision=excluded.revision,
                    updated_at=excluded.updated_at,
                    data_json=excluded.data_json
                """,
                (
                    record.id,
                    record.kind,
                    record.direction,
                    record.device_id,
                    record.session_id,
                    record.status,
                    record.stage,
                    record.message,
                    record.progress_percent,
                    record.bytes_transferred,
                    record.total_bytes,
                    record.bytes_per_second,
                    record.eta_seconds,
                    record.queue_position,
                    record.retry_of,
                    int(record.cancellable),
                    record.error_code,
                    record.revision,
                    record.created_at,
                    record.updated_at,
                    payload,
                ),
            )

    def delete_terminal_operations(self, *, kind: str) -> int:
        statuses = tuple(sorted(TERMINAL_OPERATION_STATUSES))
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM operations WHERE kind = ? AND status IN ({placeholders})",
                (kind, *statuses),
            )
            return max(0, int(cursor.rowcount))

    def list_imported_devices(self) -> list[Device]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM imported_devices ORDER BY position"
            ).fetchall()
        devices: list[Device] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload"]))
                if isinstance(payload, dict):
                    devices.append(deserialize_imported_device(payload))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return devices

    def imported_device_metadata(self) -> ImportedDeviceMetadata:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM device_import_state WHERE id = 1"
            ).fetchone()
        if row is None:
            return ImportedDeviceMetadata()
        return ImportedDeviceMetadata(
            source_name=str(row["source_name"]),
            sheet_name=str(row["sheet_name"]),
            imported_at=str(row["imported_at"]),
            row_count=int(row["row_count"]),
            revision=int(row["revision"]),
        )

    def replace_imported_devices(
        self,
        devices: list[Device],
        *,
        source_name: str,
        sheet_name: str,
        imported_at: str,
    ) -> ImportedDeviceMetadata:
        payloads = [
            json.dumps(
                serialize_imported_device(device),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for device in devices
        ]
        with self._connect() as connection:
            current = connection.execute(
                "SELECT revision FROM device_import_state WHERE id = 1"
            ).fetchone()
            revision = (int(current["revision"]) if current is not None else 0) + 1
            connection.execute("DELETE FROM imported_devices")
            connection.executemany(
                "INSERT INTO imported_devices (position, payload) VALUES (?, ?)",
                [(index, payload) for index, payload in enumerate(payloads)],
            )
            connection.execute(
                """
                INSERT INTO device_import_state (
                    id, source_name, sheet_name, imported_at, row_count, revision
                ) VALUES (1, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source_name=excluded.source_name,
                    sheet_name=excluded.sheet_name,
                    imported_at=excluded.imported_at,
                    row_count=excluded.row_count,
                    revision=excluded.revision
                """,
                (source_name, sheet_name, imported_at, len(devices), revision),
            )
        return self.imported_device_metadata()

    def prune_terminal_operations(self, *, kind: str, keep: int) -> None:
        statuses = tuple(sorted(TERMINAL_OPERATION_STATUSES))
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            connection.execute(
                f"""
                DELETE FROM operations
                WHERE kind = ? AND status IN ({placeholders}) AND id NOT IN (
                    SELECT id FROM operations
                    WHERE kind = ? AND status IN ({placeholders})
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                )
                """,
                (kind, *statuses, kind, *statuses, max(0, int(keep))),
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
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    direction TEXT NOT NULL DEFAULT '',
                    device_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    progress_percent INTEGER NOT NULL DEFAULT 0,
                    bytes_transferred INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    bytes_per_second INTEGER NOT NULL DEFAULT 0,
                    eta_seconds INTEGER,
                    queue_position INTEGER,
                    retry_of TEXT,
                    cancellable INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_operations_kind_created
                    ON operations(kind, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_operations_kind_status_updated
                    ON operations(kind, status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS imported_devices (
                    position INTEGER PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS device_import_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    source_name TEXT NOT NULL DEFAULT '',
                    sheet_name TEXT NOT NULL DEFAULT '',
                    imported_at TEXT NOT NULL DEFAULT '',
                    row_count INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 0
                );
                PRAGMA user_version = 5;
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

    @staticmethod
    def _operation(row: sqlite3.Row) -> OperationRecord:
        try:
            data = json.loads(str(row["data_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        return OperationRecord(
            id=str(row["id"]),
            kind=str(row["kind"]),
            direction=str(row["direction"]),
            device_id=str(row["device_id"]),
            session_id=str(row["session_id"]),
            status=str(row["status"]),
            stage=str(row["stage"]),
            message=str(row["message"]),
            progress_percent=int(row["progress_percent"]),
            bytes_transferred=int(row["bytes_transferred"]),
            total_bytes=int(row["total_bytes"]),
            bytes_per_second=int(row["bytes_per_second"]),
            eta_seconds=(None if row["eta_seconds"] is None else int(row["eta_seconds"])),
            queue_position=(None if row["queue_position"] is None else int(row["queue_position"])),
            retry_of=(None if row["retry_of"] is None else str(row["retry_of"])),
            cancellable=bool(row["cancellable"]),
            error_code=str(row["error_code"]),
            revision=int(row["revision"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            data={str(key): value for key, value in data.items()},
        )
