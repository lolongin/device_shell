"""Persistent desktop data preparation and migration safety helpers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class PersistenceMigrationStatus:
    data_root: Path
    database_path: Path
    schema_version_before: int
    schema_version_after: int
    target_schema_version: int
    backup_path: Path | None = None

    @property
    def migrated(self) -> bool:
        return self.schema_version_before < self.schema_version_after

    @property
    def backup_created(self) -> bool:
        return self.backup_path is not None

    def with_schema_version_after(self, version: int) -> "PersistenceMigrationStatus":
        return replace(self, schema_version_after=version)


def sqlite_user_version(path: Path) -> int:
    if not path.exists():
        return 0
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def prepare_persistent_data(
    data_root: Path,
    *,
    database_name: str = "odyterm.sqlite3",
    target_schema_version: int,
    backup_retention: int = 5,
) -> PersistenceMigrationStatus:
    data_root = data_root.resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    database_path = data_root / database_name
    legacy_database_path = data_root / "device-tui.sqlite3"
    if not database_path.exists() and legacy_database_path.exists():
        with (
            sqlite3.connect(legacy_database_path) as source,
            sqlite3.connect(database_path) as target,
        ):
            source.backup(target)
    schema_before = sqlite_user_version(database_path)
    backup_path: Path | None = None
    if database_path.exists() and schema_before < target_schema_version:
        backup_path = _backup_database(
            database_path,
            schema_version=schema_before,
            backup_retention=backup_retention,
        )
    return PersistenceMigrationStatus(
        data_root=data_root,
        database_path=database_path,
        schema_version_before=schema_before,
        schema_version_after=schema_before,
        target_schema_version=target_schema_version,
        backup_path=backup_path,
    )


def _backup_database(
    database_path: Path,
    *,
    schema_version: int,
    backup_retention: int,
) -> Path:
    backup_root = database_path.parent / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_root / f"{database_path.name}.v{schema_version}.{stamp}.bak"
    with sqlite3.connect(database_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    _prune_old_backups(backup_root, database_path.name, backup_retention)
    return backup_path


def _prune_old_backups(backup_root: Path, database_name: str, retention: int) -> None:
    if retention <= 0:
        return
    backups = sorted(
        backup_root.glob(f"{database_name}.v*.bak"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for backup in backups[retention:]:
        backup.unlink(missing_ok=True)
