"""SQLite persistence for connection-profile metadata only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..application.profiles import ConnectionProfile, ProfileEndpoint


class SQLiteConnectionProfileStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def list_profiles(self) -> list[ConnectionProfile]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM connection_profiles ORDER BY profile_type, group_name, name, id"
            ).fetchall()
        return [self._profile(row) for row in rows]

    def get_profile(self, profile_id: str) -> ConnectionProfile | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM connection_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        return self._profile(row) if row is not None else None

    def upsert_profile(self, profile: ConnectionProfile) -> None:
        values = (
            profile.id, profile.profile_type, profile.name, profile.group, profile.notes,
            profile.preferred_protocol,
            profile.telnet.host, profile.telnet.port, profile.telnet.username,
            profile.ssh.host, profile.ssh.port, profile.ssh.username,
            profile.serial.host, profile.serial.port, profile.serial.username,
            profile.created_at, profile.updated_at,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO connection_profiles (
                    id, profile_type, name, group_name, notes, preferred_protocol,
                    telnet_host, telnet_port, telnet_username,
                    ssh_host, ssh_port, ssh_username,
                    serial_host, serial_port, serial_username,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    profile_type=excluded.profile_type, name=excluded.name,
                    group_name=excluded.group_name, notes=excluded.notes,
                    preferred_protocol=excluded.preferred_protocol,
                    telnet_host=excluded.telnet_host, telnet_port=excluded.telnet_port,
                    telnet_username=excluded.telnet_username,
                    ssh_host=excluded.ssh_host, ssh_port=excluded.ssh_port,
                    ssh_username=excluded.ssh_username,
                    serial_host=excluded.serial_host, serial_port=excluded.serial_port,
                    serial_username=excluded.serial_username, updated_at=excluded.updated_at
                """,
                values,
            )

    def delete_profile(self, profile_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM connection_profiles WHERE id = ?", (profile_id,))

    def list_groups(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT name FROM profile_groups ORDER BY sort_order, name").fetchall()
        return [str(row["name"]) for row in rows]

    def add_group(self, name: str) -> None:
        normalized = name.strip()
        if not normalized:
            return
        with self._connect() as connection:
            next_order = connection.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM profile_groups"
            ).fetchone()[0]
            connection.execute(
                "INSERT OR IGNORE INTO profile_groups(name, sort_order) VALUES (?, ?)",
                (normalized, int(next_order)),
            )

    def get_meta(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row is not None else None

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO app_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def delete_meta(self, key: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM app_meta WHERE key = ?", (key,))

    def _migrate(self) -> None:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS connection_profiles (
                    id TEXT PRIMARY KEY,
                    profile_type TEXT NOT NULL CHECK(profile_type IN ('temporary', 'server')),
                    name TEXT NOT NULL,
                    group_name TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    preferred_protocol TEXT NOT NULL,
                    telnet_host TEXT NOT NULL DEFAULT '', telnet_port INTEGER NOT NULL DEFAULT 23,
                    telnet_username TEXT NOT NULL DEFAULT '',
                    ssh_host TEXT NOT NULL DEFAULT '', ssh_port INTEGER NOT NULL DEFAULT 22,
                    ssh_username TEXT NOT NULL DEFAULT '',
                    serial_host TEXT NOT NULL DEFAULT '', serial_port INTEGER NOT NULL DEFAULT 23,
                    serial_username TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_groups (
                    name TEXT PRIMARY KEY,
                    sort_order INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            if version < 1:
                connection.execute("PRAGMA user_version = 1")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _profile(row: sqlite3.Row) -> ConnectionProfile:
        return ConnectionProfile(
            id=str(row["id"]), profile_type=str(row["profile_type"]),  # type: ignore[arg-type]
            name=str(row["name"]), group=str(row["group_name"]), notes=str(row["notes"]),
            preferred_protocol=str(row["preferred_protocol"]),  # type: ignore[arg-type]
            telnet=ProfileEndpoint(str(row["telnet_host"]), int(row["telnet_port"]), str(row["telnet_username"])),
            ssh=ProfileEndpoint(str(row["ssh_host"]), int(row["ssh_port"]), str(row["ssh_username"])),
            serial=ProfileEndpoint(str(row["serial_host"]), int(row["serial_port"]), str(row["serial_username"])),
            created_at=str(row["created_at"]), updated_at=str(row["updated_at"]),
        )
