from __future__ import annotations

import sqlite3
import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.desktop_backend.app import create_app
from src.desktop_backend.data_migration import prepare_persistent_data, sqlite_user_version
from src.infrastructure.sqlite_desktop import SQLiteDesktopStore
from src.infrastructure.sqlite_profiles import SQLiteConnectionProfileStore
from src.infrastructure.sqlite_settings import SQLiteSettingsStore
from src.repository import SampleDeviceRepository


TOKEN = "desktop-token"


def test_sqlite_settings_store_round_trips_json_values(tmp_path: Path) -> None:
    metadata = SQLiteDesktopStore(tmp_path / "settings.sqlite3")
    settings = SQLiteSettingsStore(metadata)

    settings.set("session_logs.directory", str(tmp_path / "logs"))
    settings.set("session_logs.max_bytes", 8 * 1024 * 1024)

    reopened = SQLiteSettingsStore(SQLiteDesktopStore(tmp_path / "settings.sqlite3"))
    assert reopened.get("session_logs.directory") == str(tmp_path / "logs")
    assert reopened.get("session_logs.max_bytes") == 8 * 1024 * 1024
    reopened.delete("session_logs.directory")
    assert settings.get("session_logs.directory", "fallback") == "fallback"


def test_session_log_settings_survive_backend_restart(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "userdata"
    log_root = tmp_path / "operator-logs"
    monkeypatch.setenv("DEVICE_TUI_DATA_DIR", str(data_root))
    monkeypatch.setenv("DEVICE_TUI_LEGACY_STATE_PATH", str(tmp_path / "missing.json"))
    monkeypatch.delenv("DEVICE_TUI_SESSION_LOG_ROOT", raising=False)
    monkeypatch.delenv("DEVICE_TUI_SESSION_LOG_MAX_BYTES", raising=False)

    first = create_app(token=TOKEN, repository=SampleDeviceRepository())
    with TestClient(first) as client:
        response = client.put(
            "/api/v1/settings/session-logs",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"directory": str(log_root), "rotate_size_mb": 11},
        )
        assert response.status_code == 200

    restarted = create_app(token=TOKEN, repository=SampleDeviceRepository())
    with TestClient(restarted) as client:
        response = client.get(
            "/api/v1/settings/session-logs",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json()["directory"] == str(log_root.resolve())
    assert response.json()["rotate_size_mb"] == 11


def test_legacy_log_settings_import_without_modifying_source(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "userdata"
    legacy_log_root = tmp_path / "legacy-logs"
    legacy_state = tmp_path / "desktop_state.json"
    original = json.dumps(
        {"log_directory": str(legacy_log_root), "log_rotate_size_mb": 19},
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    legacy_state.write_bytes(original)
    monkeypatch.setenv("DEVICE_TUI_DATA_DIR", str(data_root))
    monkeypatch.setenv("DEVICE_TUI_LEGACY_STATE_PATH", str(legacy_state))
    monkeypatch.delenv("DEVICE_TUI_SESSION_LOG_ROOT", raising=False)
    monkeypatch.delenv("DEVICE_TUI_SESSION_LOG_MAX_BYTES", raising=False)

    app = create_app(token=TOKEN, repository=SampleDeviceRepository())
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/settings/session-logs",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert response.status_code == 200
    assert response.json()["directory"] == str(legacy_log_root.resolve())
    assert response.json()["rotate_size_mb"] == 19
    assert legacy_state.read_bytes() == original


def test_sqlite_desktop_store_does_not_downgrade_schema_on_reopen(tmp_path: Path) -> None:
    database = tmp_path / "device-tui.sqlite3"

    SQLiteDesktopStore(database)
    assert sqlite_user_version(database) == SQLiteDesktopStore.SCHEMA_VERSION
    SQLiteDesktopStore(database)

    assert sqlite_user_version(database) == SQLiteDesktopStore.SCHEMA_VERSION


def test_prepare_persistent_data_backs_up_old_schema_before_migration(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    database = data_root / "device-tui.sqlite3"
    profile_store = SQLiteConnectionProfileStore(database)
    profile_store.add_group("Production")
    assert sqlite_user_version(database) == 1

    status = prepare_persistent_data(
        data_root,
        target_schema_version=SQLiteDesktopStore.SCHEMA_VERSION,
    )
    SQLiteDesktopStore(database)
    status = status.with_schema_version_after(sqlite_user_version(database))

    assert status.schema_version_before == 1
    assert status.schema_version_after == SQLiteDesktopStore.SCHEMA_VERSION
    assert status.migrated
    assert status.backup_created
    assert status.backup_path is not None
    assert status.backup_path.exists()
    with sqlite3.connect(status.backup_path) as backup:
        groups = backup.execute("SELECT name FROM profile_groups").fetchall()
        backup_version = backup.execute("PRAGMA user_version").fetchone()[0]
    assert groups == [("Production",)]
    assert backup_version == 1


def test_desktop_backend_diagnostics_reports_persistence_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "userdata"
    database = data_root / "device-tui.sqlite3"
    SQLiteConnectionProfileStore(database).add_group("Legacy")
    monkeypatch.setenv("DEVICE_TUI_DATA_DIR", str(data_root))
    monkeypatch.setenv("DEVICE_TUI_LEGACY_STATE_PATH", str(tmp_path / "missing-legacy.json"))
    monkeypatch.setenv("DEVICE_TUI_SESSION_LOG_MAX_BYTES", "65536")
    monkeypatch.setenv("DEVICE_TUI_SESSION_LOG_BACKUPS", "2")
    monkeypatch.setenv("DEVICE_TUI_AUDIT_LOG_MAX_BYTES", "131072")
    monkeypatch.setenv("DEVICE_TUI_AUDIT_LOG_BACKUPS", "3")

    app = create_app(token=TOKEN, repository=SampleDeviceRepository())

    with TestClient(app) as client:
        unauthorized = client.get("/api/v1/diagnostics")
        response = client.get(
            "/api/v1/diagnostics",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    diagnostics = response.json()
    persistence = diagnostics["persistence"]
    assert persistence["data_root"] == str(data_root.resolve())
    assert persistence["schema_version_before"] == 1
    assert persistence["schema_version_after"] == SQLiteDesktopStore.SCHEMA_VERSION
    assert persistence["target_schema_version"] == SQLiteDesktopStore.SCHEMA_VERSION
    assert persistence["migrated"] is True
    assert persistence["backup_created"] is True
    assert Path(persistence["backup_path"]).exists()
    assert diagnostics["legacy_imports"]["profiles"] == {
        "temporary": 0,
        "servers": 0,
        "groups": 0,
    }
    assert diagnostics["log_policy"] == {
        "session_log_max_bytes": 65536,
        "session_log_backups": 2,
        "audit_log_max_bytes": 131072,
        "audit_log_backups": 3,
    }
