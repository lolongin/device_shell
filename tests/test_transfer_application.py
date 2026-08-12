from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from src.application import MemorySecretStore, build_desktop_application
from src.desktop_backend.app import create_app
from src.desktop_backend.session_hub import SessionHub
from src.desktop_backend.terminal_executor import BackendTerminalExecutor
from src.infrastructure.sqlite_desktop import SQLiteDesktopStore
from src.repository import SampleDeviceRepository


TOKEN = "transfer-test-token"


def test_file_service_log_and_client_hint_are_backend_owned(tmp_path: Path) -> None:
    share = tmp_path / "share"
    share.mkdir()
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        transfer_root=share,
    )
    transfers = app.state.desktop_application.transfers
    transfers.update_settings(
        protocol="sftp",
        host="0.0.0.0",
        port=2222,
        root=str(share),
        username="device",
        writable=True,
    )
    transfers._on_service_log("SFTP 登录成功: device")

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        loaded = client.get("/api/v1/file-transfer/service/log", headers=headers)
        cleared = client.delete("/api/v1/file-transfer/service/log", headers=headers)
        reloaded = client.get("/api/v1/file-transfer/service/log", headers=headers)

    assert loaded.status_code == 200
    assert loaded.json()["entries"] == ["SFTP 登录成功: device"]
    assert loaded.json()["content"] == "SFTP 登录成功: device"
    assert loaded.json()["client_command"] == "sftp -P 2222 device@<本机IP>"
    assert cleared.status_code == 200
    assert cleared.json()["entries"] == []
    assert reloaded.json()["content"] == ""


def test_backend_managed_upload_completes_and_verifies_simulated_device(
    tmp_path: Path,
) -> None:
    share = tmp_path / "share"
    share.mkdir()
    package = share / "images" / "target.cc"
    package.parent.mkdir()
    package.write_bytes(b"managed-transfer-payload")
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        transfer_root=share,
    )

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        device_id = client.get("/api/v1/devices", headers=headers).json()["devices"][0]["id"]
        session = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": device_id, "kind": "simulated"},
        ).json()
        files = client.get("/api/v1/file-transfer/files", headers=headers)
        started = client.post(
            "/api/v1/file-transfers",
            headers=headers,
            json={
                "direction": "upload",
                "session_id": session["id"],
                "source_path": "images/target.cc",
                "destination_path": "flash:/target.cc",
            },
        )
        operation_id = started.json()["operation"]["id"]
        operation = started.json()["operation"]
        for _ in range(400):
            operation = client.get(
                f"/api/v1/operations/{operation_id}",
                headers=headers,
            ).json()["operation"]
            if operation["status"] != "running":
                break
            time.sleep(0.02)
        settings = client.get("/api/v1/file-transfer/settings", headers=headers)
        cancellable = client.post(
            "/api/v1/file-transfers",
            headers=headers,
            json={
                "direction": "upload",
                "session_id": session["id"],
                "source_path": "images/target.cc",
                "destination_path": "flash:/cancelled.cc",
            },
        ).json()["operation"]
        cancelled = client.post(
            f"/api/v1/operations/{cancellable['id']}/cancel",
            headers=headers,
        )

    assert files.status_code == 200
    assert files.json()["files"][0]["relative_path"] == "images/target.cc"
    assert started.status_code == 200
    assert operation["status"] == "completed"
    assert operation["progress_percent"] == 100
    assert operation["data"]["source_path"] == "images/target.cc"
    assert str(share) not in json.dumps(operation, ensure_ascii=False)
    assert settings.json()["has_password"] is True
    assert "service-password" not in settings.text
    assert cancelled.status_code == 200
    assert cancelled.json()["operation"]["status"] == "cancelled"


def test_transfer_legacy_password_moves_to_secret_store_without_sqlite_plaintext(
    tmp_path: Path,
) -> None:
    share = tmp_path / "share"
    share.mkdir()
    state = tmp_path / "desktop_state.json"
    secret = "legacy-transfer-secret"
    payload = {
        "file_transfer_service": {
            "protocol": "ftp",
            "host": "127.0.0.1",
            "port": 2121,
            "root": str(share),
            "username": "legacy-user",
            "password": secret,
            "writable": False,
        }
    }
    original = json.dumps(payload, ensure_ascii=False)
    state.write_text(original, encoding="utf-8")
    store = SQLiteDesktopStore(tmp_path / "device-tui.sqlite3")
    secrets = MemorySecretStore()
    application = build_desktop_application(
        SampleDeviceRepository(),
        SessionHub(),
        profile_store=store,
        command_store=store,
        automation_store=store,
        transfer_store=store,
        secret_store=secrets,
        transfer_root=share,
    )

    assert application.transfers.import_legacy_state(state) == {"settings": 1, "secrets": 1}
    assert application.transfers.import_legacy_state(state) == {"settings": 0, "secrets": 0}
    assert application.transfers.settings().username == "legacy-user"
    assert application.transfers.settings().has_password
    assert secrets.get(application.transfers.PASSWORD_SECRET_ID) == secret
    assert state.read_text(encoding="utf-8") == original
    with sqlite3.connect(store.path) as connection:
        persisted = " ".join(
            str(row[0])
            for row in connection.execute("SELECT value FROM app_meta")
        )
    assert secret not in persisted


def test_manual_terminal_input_cancels_transfer_and_is_not_dropped(tmp_path: Path) -> None:
    async def scenario() -> None:
        share = tmp_path / "share"
        share.mkdir()
        (share / "target.cc").write_bytes(b"manual-input-precedence")
        hub = SessionHub()
        executor = BackendTerminalExecutor(hub, lambda _reference: "")
        application = build_desktop_application(
            SampleDeviceRepository(),
            hub,
            secret_store=MemorySecretStore(),
            terminal_executor=executor,
            transfer_root=share,
        )
        executor.set_secret_resolver(application.transfers.resolve_secret)
        device_id = application.devices.list_inventory().devices[0].id
        session = await application.sessions.create(device_id, "simulated", "Transfer")
        for _ in range(100):
            session = next(item for item in application.sessions.list_sessions() if item.id == session.id)
            if session.status == "connected":
                break
            await asyncio.sleep(0.01)
        operation = application.transfers.start_upload(
            session_id=session.id,
            source_path="target.cc",
            destination_path="flash:/manual-cancel.cc",
        )
        for _ in range(100):
            if hub.get(session.id).lease_owner:
                break
            await asyncio.sleep(0.01)
        # `bye` leaves an FTP/SFTP phase and is harmless at the simulated CLI;
        # the same keystroke also takes ownership away from the managed plan.
        await hub.write(session.id, "bye\r")
        for _ in range(200):
            if application.operations.get(operation.id).status != "running":
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        await hub.write(session.id, "bye\r")
        await asyncio.sleep(0.05)
        await hub.write(session.id, "display version\r")
        output = ""
        events = []
        for _ in range(100):
            events = hub.get(session.id).replay.after(0)
            output = "".join(event.data for event in events if event.type == "terminal.output")
            if "SimOS V1.0" in output:
                break
            await asyncio.sleep(0.01)
        error_records = [
            (event.sequence, str(event.metadata.get("code") or ""), event.data)
            for event in events
            if event.type == "terminal.error"
        ]

        assert application.operations.get(operation.id).status == "cancelled"
        assert "SimOS V1.0" in output
        assert not any(code == "session_busy" for _, code, _ in error_records), error_records

        await application.transfers.close()
        executor.close()
        await application.sessions.close_all()

    asyncio.run(scenario())


def test_closing_session_cancels_managed_transfer(tmp_path: Path) -> None:
    share = tmp_path / "share"
    share.mkdir()
    (share / "target.cc").write_bytes(b"close-session-cancel")
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        transfer_root=share,
    )

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        device_id = client.get("/api/v1/devices", headers=headers).json()["devices"][0]["id"]
        session = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": device_id, "kind": "simulated"},
        ).json()
        operation = client.post(
            "/api/v1/file-transfers",
            headers=headers,
            json={
                "direction": "upload",
                "session_id": session["id"],
                "source_path": "target.cc",
                "destination_path": "flash:/close-cancel.cc",
            },
        ).json()["operation"]
        closed = client.delete(
            f"/api/v1/sessions/{session['id']}",
            headers=headers,
        )
        latest = client.get(
            f"/api/v1/operations/{operation['id']}",
            headers=headers,
        ).json()["operation"]

    assert closed.status_code == 204
    assert latest["status"] == "cancelled"


def test_file_transfer_routes_require_authorization(tmp_path: Path) -> None:
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        transfer_root=tmp_path,
    )
    with TestClient(app) as client:
        settings = client.get("/api/v1/file-transfer/settings")
        files = client.get("/api/v1/file-transfer/files")
        operations = client.get("/api/v1/operations")

    assert settings.status_code == 401
    assert files.status_code == 401
    assert operations.status_code == 401
