from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.application.credentials import RepositoryCredentialResolver
from src.application.errors import ApplicationConflictError
from src.application.profiles import (
    CompositeCredentialResolver,
    ConnectionProfileDraft,
    ConnectionProfileService,
    ProfileEndpoint,
)
from src.application.secrets import MemorySecretStore
from src.infrastructure.sqlite_profiles import SQLiteConnectionProfileStore
from src.repository import SampleDeviceRepository


def _service(tmp_path: Path) -> tuple[ConnectionProfileService, MemorySecretStore, Path]:
    database = tmp_path / "data" / "device-tui.sqlite3"
    secrets = MemorySecretStore()
    return (
        ConnectionProfileService(SQLiteConnectionProfileStore(database), secrets),
        secrets,
        database,
    )


def test_sqlite_profile_metadata_and_secret_store_are_separated(tmp_path: Path) -> None:
    service, secrets, database = _service(tmp_path)

    saved = service.save(ConnectionProfileDraft(
        profile_type="temporary",
        name="Lab console",
        preferred_protocol="ssh",
        ssh=ProfileEndpoint("10.0.0.10", 2222, "operator"),
        passwords={"ssh": "top-secret-password"},
    ))

    loaded = service.get_profile(saved.id)
    target = service.resolve_target(saved.id, "ssh")
    database_bytes = database.read_bytes()
    assert loaded.ssh == ProfileEndpoint("10.0.0.10", 2222, "operator")
    assert target.credentials[0].password == "top-secret-password"
    assert b"top-secret-password" not in database_bytes
    assert service.has_password(saved.id, "ssh")

    service.delete(saved.id)
    assert service.list_profiles() == []
    assert secrets.get(service.secret_id(saved.id, "ssh")) is None


def test_profile_duplicate_server_endpoint_is_rejected(tmp_path: Path) -> None:
    service, _secrets, _database = _service(tmp_path)
    first = ConnectionProfileDraft(
        profile_type="server",
        name="Primary",
        ssh=ProfileEndpoint("server.example", 22, "root"),
    )
    second = ConnectionProfileDraft(
        profile_type="server",
        name="Duplicate",
        ssh=ProfileEndpoint("SERVER.EXAMPLE", 22, "admin"),
    )

    service.save(first)
    with pytest.raises(ApplicationConflictError):
        service.save(second)
    duplicate = service.save(second, allow_duplicate=True)
    assert duplicate.name == "Duplicate"


def test_profile_groups_can_be_created_without_a_server(tmp_path: Path) -> None:
    service, _secrets, _database = _service(tmp_path)

    assert service.create_group("  Production  ") == "Production"
    assert service.create_group("Production") == "Production"
    assert service.list_groups() == ["Production"]


def test_profile_one_time_password_does_not_modify_secret_store(tmp_path: Path) -> None:
    service, secrets, _database = _service(tmp_path)
    profile = service.save(ConnectionProfileDraft(
        profile_type="server",
        name="Prompted server",
        ssh=ProfileEndpoint("server.example", 22, "root"),
    ))

    target = service.resolve_target_with_password(profile.id, "ssh", "one-time-secret")

    assert target.credentials[0].password == "one-time-secret"
    assert secrets.get(service.secret_id(profile.id, "ssh")) is None

    service.set_password(profile.id, "ssh", "vault-secret")
    assert service.has_password(profile.id, "ssh")
    service.set_password(profile.id, "ssh", "")
    assert not service.has_password(profile.id, "ssh")


def test_legacy_import_is_idempotent_and_preserves_source_file(tmp_path: Path) -> None:
    service, secrets, database = _service(tmp_path)
    state_path = tmp_path / "desktop_state.json"
    payload = {
        "temporary_devices": [
            {
                "id": "TEMP-LAB",
                "name": "Temporary lab",
                "ssh_ip": "10.0.0.20",
                "ssh_port": 22,
                "ssh_username": "lab",
                "ssh_password": "temporary-secret",
                "preferred_kind": "linux",
            }
        ],
        "saved_server_groups": ["Production"],
        "saved_servers": [
            {
                "id": "SERVER-LEGACY",
                "name": "Legacy server",
                "host": "10.0.0.30",
                "port": 2222,
                "username": "root",
                "password": "server-secret",
                "group": "Production",
                "notes": "import me",
            }
        ],
    }
    original = json.dumps(payload, ensure_ascii=False)
    state_path.write_text(original, encoding="utf-8")

    first = service.import_legacy_state(state_path)
    second = service.import_legacy_state(state_path)

    assert first == {"temporary": 1, "servers": 1, "groups": 1}
    assert second == {"temporary": 0, "servers": 0, "groups": 0}
    assert {profile.id for profile in service.list_profiles()} == {"TEMP-LAB", "SERVER-LEGACY"}
    assert service.list_groups() == ["Production"]
    assert secrets.get(service.secret_id("TEMP-LAB", "ssh")) == "temporary-secret"
    assert secrets.get(service.secret_id("SERVER-LEGACY", "ssh")) == "server-secret"
    assert state_path.read_text(encoding="utf-8") == original
    assert b"temporary-secret" not in database.read_bytes()
    assert b"server-secret" not in database.read_bytes()


def test_legacy_import_preserves_duplicate_endpoints_from_old_ui(tmp_path: Path) -> None:
    service, _secrets, _database = _service(tmp_path)
    state_path = tmp_path / "desktop_state.json"
    state_path.write_text(json.dumps({
        "temporary_devices": [
            {
                "id": "TEMP-FIRST",
                "name": "First",
                "ssh_ip": "127.0.0.1",
                "ssh_port": 22,
                "ssh_username": "root",
                "preferred_kind": "linux",
            },
            {
                "id": "TEMP-SECOND",
                "name": "Second",
                "ssh_ip": "127.0.0.1",
                "ssh_port": 22,
                "ssh_username": "root",
                "preferred_kind": "linux",
            },
        ]
    }), encoding="utf-8")

    imported = service.import_legacy_state(state_path)

    assert imported == {"temporary": 2, "servers": 0, "groups": 0}
    assert {profile.id for profile in service.list_profiles()} == {
        "TEMP-FIRST",
        "TEMP-SECOND",
    }


def test_composite_resolver_routes_profiles_without_breaking_repository_devices(
    tmp_path: Path,
) -> None:
    service, _secrets, _database = _service(tmp_path)
    profile = service.save(ConnectionProfileDraft(
        profile_type="server",
        name="Saved server",
        ssh=ProfileEndpoint("10.0.0.40", 22, "root"),
        passwords={"ssh": "saved-secret"},
    ))
    repository = SampleDeviceRepository()
    resolver = CompositeCredentialResolver(RepositoryCredentialResolver(repository), service)

    profile_target = resolver.resolve(profile.id, "ssh")
    device = repository.fetch_devices()[0]
    device_target = resolver.resolve(device.id, "simulated")

    assert profile_target.host == "10.0.0.40"
    assert profile_target.credentials[0].password == "saved-secret"
    assert device_target.device_id == device.id


def test_sqlite_schema_version_is_recorded(tmp_path: Path) -> None:
    _service(tmp_path)
    database = tmp_path / "data" / "device-tui.sqlite3"
    with sqlite3.connect(database) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1
