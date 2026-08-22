from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from device_tui.application import MemorySecretStore, build_desktop_application
from device_tui.application.errors import UnsupportedOperationError
from device_tui.application.events import EventBus
from device_tui.application.operations import OperationManager
from device_tui.application.transfers import normalize_advertised_host, select_route_local_ipv4
from device_tui.application.credentials import ConnectionTarget
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub
from device_tui.interfaces.desktop_api.terminal_executor import BackendTerminalExecutor
from device_tui.infrastructure.persistence.sqlite_desktop import SQLiteDesktopStore
from device_tui.infrastructure.transfers.file_transfer_service import TransferServiceConfig
from device_tui.device_sources.sample import SampleDeviceRepository


TOKEN = "transfer-test-token"


def test_route_local_ip_uses_the_os_route_for_each_device(monkeypatch) -> None:
    routes = {
        "192.0.2.20": "192.168.10.25",
        "198.51.100.30": "10.8.0.7",
    }

    class RouteProbe:
        def __init__(self, *_args) -> None:
            self.remote = ""

        def connect(self, sockaddr) -> None:
            self.remote = str(sockaddr[0])

        def getsockname(self):
            return routes[self.remote], 49152

        def close(self) -> None:
            return

    monkeypatch.setattr(
        "device_tui.application.transfers.socket.getaddrinfo",
        lambda host, port, **_kwargs: [(2, 2, 17, "", (host, port))],
    )
    monkeypatch.setattr("device_tui.application.transfers.socket.socket", RouteProbe)

    assert select_route_local_ipv4("192.0.2.20", 22) == "192.168.10.25"
    assert select_route_local_ipv4("198.51.100.30", 22) == "10.8.0.7"


def test_device_access_ip_override_rejects_unreachable_address_classes() -> None:
    assert normalize_advertised_host("") == ""
    assert normalize_advertised_host("auto") == ""
    assert normalize_advertised_host("192.168.10.25") == "192.168.10.25"
    for value in ("0.0.0.0", "127.0.0.1", "ff02::1", "vpn-adapter"):
        with pytest.raises(UnsupportedOperationError):
            normalize_advertised_host(value)


def test_managed_transfer_uses_session_route_unless_access_ip_is_overridden(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        hub = SessionHub(connect_timeout_seconds=1)
        application = build_desktop_application(
            SampleDeviceRepository(),
            hub,
            transfer_root=tmp_path,
        )
        session = await application.sessions.create_target(
            ConnectionTarget(
                device_id="route-device",
                protocol="ssh",
                host="192.0.2.20",
                port=22,
            ),
            "Route target",
        )
        selected: list[tuple[str, int]] = []
        monkeypatch.setattr(
            "device_tui.application.transfers.select_route_local_ipv4",
            lambda host, port: selected.append((host, port)) or "192.168.10.25",
        )
        config = TransferServiceConfig(
            protocol="ftp",
            host="0.0.0.0",
            port=2121,
            root=tmp_path,
            username="device",
            password="secret",
        )

        assert application.transfers._device_host(session, config) == "192.168.10.25"
        assert selected == [("192.0.2.20", 22)]

        config.advertised_host = "172.16.20.8"
        assert application.transfers._device_host(session, config) == "172.16.20.8"
        assert selected == [("192.0.2.20", 22)]
        await application.sessions.close_all()

    asyncio.run(scenario())


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
        protocol="ftp",
        host="0.0.0.0",
        port=2121,
        root=str(share),
        username="device",
        writable=True,
    )
    transfers._on_service_log("FTP 登录成功: device")

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        loaded = client.get("/api/v1/file-transfer/service/log", headers=headers)
        addresses = client.get(
            "/api/v1/file-transfer/network-addresses",
            headers=headers,
        )
        cleared = client.delete("/api/v1/file-transfer/service/log", headers=headers)
        reloaded = client.get("/api/v1/file-transfer/service/log", headers=headers)

    assert loaded.status_code == 200
    assert loaded.json()["entries"] == ["FTP 登录成功: device"]
    assert loaded.json()["content"] == "FTP 登录成功: device"
    assert loaded.json()["client_command"] == "ftp <按设备路由自动选择> 2121"
    assert addresses.status_code == 200
    assert isinstance(addresses.json()["addresses"], list)
    assert isinstance(addresses.json()["recommended"], str)
    assert cleared.status_code == 200
    assert cleared.json()["entries"] == []
    assert reloaded.json()["content"] == ""


def test_manual_service_api_keeps_ftp_running_until_explicit_stop(tmp_path: Path) -> None:
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
        protocol="ftp",
        host="127.0.0.1",
        port=0,
        root=str(share),
        username="device",
        writable=True,
    )
    transfers.IDLE_STOP_SECONDS = 0.05
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(app) as client:
        started = client.post("/api/v1/file-transfer/service/start", headers=headers)
        time.sleep(0.15)
        running = client.get("/api/v1/file-transfer/settings", headers=headers)
        stopped = client.post("/api/v1/file-transfer/service/stop", headers=headers)

    assert started.status_code == 200
    assert running.status_code == 200
    assert running.json()["service_running"] is True
    assert running.json()["idle_stop_at"] == ""
    assert stopped.status_code == 200


def test_transfer_settings_save_password_only_in_secret_store(tmp_path: Path) -> None:
    share = tmp_path / "share"
    share.mkdir()
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        transfer_root=share,
    )
    transfers = app.state.desktop_application.transfers
    secret = "manual-ftp-secret"
    payload = {
        "protocol": "ftp",
        "host": "127.0.0.1",
        "advertised_host": "192.168.10.25",
        "port": 2121,
        "root": str(share),
        "username": "device",
        "password": secret,
        "writable": True,
    }

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        saved = client.put(
            "/api/v1/file-transfer/settings",
            headers=headers,
            json=payload,
        )
        retained = client.put(
            "/api/v1/file-transfer/settings",
            headers=headers,
            json={key: value for key, value in payload.items() if key != "password"},
        )
        resolved = client.get(
            "/api/v1/file-transfer/password",
            headers=headers,
        )

    assert saved.status_code == 200
    assert saved.json()["has_password"] is True
    assert saved.json()["advertised_host"] == "192.168.10.25"
    assert "password" not in saved.json()
    assert secret not in saved.text
    assert retained.status_code == 200
    assert retained.json()["has_password"] is True
    assert resolved.status_code == 200
    assert resolved.json()["password"] == secret
    assert transfers.resolve_secret("file_transfer.password") == secret


def test_file_transfer_settings_are_ftp_only(tmp_path: Path) -> None:
    share = tmp_path / "share"
    share.mkdir()
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        transfer_root=share,
    )
    with TestClient(app) as client:
        response = client.put(
            "/api/v1/file-transfer/settings",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "protocol": "sftp",
                "host": "127.0.0.1",
                "port": 2121,
                "root": str(share),
                "username": "device",
                "writable": True,
            },
        )

    assert response.status_code == 422


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
            if operation["status"] not in {"queued", "running"}:
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
        retried = client.post(
            f"/api/v1/file-transfers/{cancellable['id']}/retry",
            headers=headers,
        )
        retried_operation = retried.json()["operation"]
        client.post(
            f"/api/v1/operations/{retried_operation['id']}/cancel",
            headers=headers,
        )
        cleared_history = client.delete(
            "/api/v1/file-transfers/history",
            headers=headers,
        )

    assert files.status_code == 200
    assert files.json()["files"][0]["relative_path"] == "images/target.cc"
    assert started.status_code == 200
    assert operation["status"] == "completed"
    assert operation["progress_percent"] == 100
    assert operation["bytes_transferred"] == len(b"managed-transfer-payload")
    assert operation["total_bytes"] == len(b"managed-transfer-payload")
    assert operation["data"]["source_path"] == "images/target.cc"
    assert operation["data"]["terminal_environment_requested"] == "auto"
    assert operation["data"]["terminal_environment"] == "vrp"
    assert str(share) not in json.dumps(operation, ensure_ascii=False)
    assert settings.json()["has_password"] is True
    assert "service-password" not in settings.text
    assert cancelled.status_code == 200
    assert cancelled.json()["operation"]["status"] == "cancelled"
    assert retried.status_code == 200
    assert retried_operation["retry_of"] == cancellable["id"]
    assert cleared_history.status_code == 200
    assert cleared_history.json()["deleted_count"] >= 2


def test_ftpget_command_mode_runs_one_protected_command_on_current_session(
    tmp_path: Path,
) -> None:
    class FakePort21Controller:
        def __init__(self, root: Path) -> None:
            self.is_running = True
            self.bound_port = 21
            self.config = TransferServiceConfig(
                protocol="ftp",
                host="0.0.0.0",
                port=21,
                root=root,
                username="device",
                password="saved-password",
                writable=True,
            )

        def register_managed_transfer(self, *_args, **_kwargs) -> tuple[str, str]:
            return "managed-user", "managed-password"

        def unregister_managed_transfer(self, _username: str) -> None:
            return

        def stop(self) -> None:
            self.is_running = False

    async def scenario() -> None:
        package = tmp_path / "target.cc"
        package.write_bytes(b"ftpget-payload")
        hub = SessionHub()
        executor = BackendTerminalExecutor(hub, lambda _reference: "")
        application = build_desktop_application(
            SampleDeviceRepository(),
            hub,
            secret_store=MemorySecretStore(),
            terminal_executor=executor,
            transfer_root=tmp_path,
        )
        executor.set_secret_resolver(application.transfers.resolve_secret)
        application.transfers.update_settings(
            protocol="ftp",
            host="0.0.0.0",
            port=21,
            root=str(tmp_path),
            username="device",
            writable=True,
        )
        application.transfers._controller = FakePort21Controller(tmp_path)
        device_id = application.devices.list_inventory().devices[0].id
        session = await application.sessions.create(device_id, "simulated", "ftpget")
        for _ in range(500):
            output = "".join(
                event.data
                for event in hub.get(session.id).replay.after(0)
                if event.type == "terminal.output"
            )
            if "System ready" in output:
                break
            await asyncio.sleep(0.01)

        operation = application.transfers.start_upload(
            session_id=session.id,
            source_path="target.cc",
            destination_path="target.cc",
            command_mode="ftpget",
        )
        for _ in range(500):
            operation = application.operations.get(operation.id)
            if operation.status not in {"queued", "running"}:
                break
            await asyncio.sleep(0.01)

        assert operation.status == "completed", (operation.error_code, operation.message)
        assert operation.data["command_mode"] == "ftpget"
        assert operation.data["command_preview"] == (
            "ftpget -u <临时账号> -p ****** 192.0.2.10 target.cc"
        )
        serialized = json.dumps(operation.data, ensure_ascii=False)
        assert "managed-password" not in serialized
        assert operation.bytes_transferred == len(b"ftpget-payload")

        await application.transfers.close()
        executor.close()
        await application.sessions.close_all()

    asyncio.run(scenario())


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
        startup_output = ""
        for _ in range(600):
            startup_output = "".join(
                event.data
                for event in hub.get(session.id).replay.after(0)
                if event.type == "terminal.output"
            )
            if "System ready" in startup_output:
                break
            await asyncio.sleep(0.01)
        assert "System ready" in startup_output
        operation = application.transfers.start_upload(
            session_id=session.id,
            source_path="target.cc",
            destination_path="flash:/manual-cancel.cc",
        )
        queued = application.transfers.start_upload(
            session_id=session.id,
            source_path="target.cc",
            destination_path="flash:/after-manual.cc",
        )
        assert application.operations.get(queued.id).status == "queued"
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
        paused = application.operations.get(queued.id)
        assert paused.status == "queued"
        assert paused.stage == "paused"
        assert "SimOS V1.0" in output
        assert not any(code == "session_busy" for _, code, _ in error_records), error_records

        assert application.transfers.resume_queue(session.id) == 1
        for _ in range(300):
            resumed = application.operations.get(queued.id)
            if resumed.status != "queued":
                break
            await asyncio.sleep(0.01)
        resumed = application.operations.get(queued.id)
        assert resumed.stage != "paused"
        assert resumed.status != "queued", resumed
        if resumed.status == "running":
            application.transfers.cancel(queued.id)

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
        addresses = client.get("/api/v1/file-transfer/network-addresses")
        operations = client.get("/api/v1/operations")

    assert settings.status_code == 401
    assert files.status_code == 401
    assert addresses.status_code == 401
    assert operations.status_code == 401


def test_managed_transfer_history_persists_interrupts_and_prunes_to_200(
    tmp_path: Path,
) -> None:
    store = SQLiteDesktopStore(tmp_path / "device-tui.sqlite3")
    manager = OperationManager(
        EventBus(),
        store,
        persistent_kinds={"managed_file_transfer"},
        history_limit=200,
    )
    active = manager.create(
        kind="managed_file_transfer",
        direction="upload",
        device_id="device-1",
        session_id="session-1",
        status="queued",
        stage="queued",
        message="queued",
        data={"source_path": "packages/target.cc", "destination_path": "flash:/target.cc"},
    )

    reopened = OperationManager(
        EventBus(),
        store,
        persistent_kinds={"managed_file_transfer"},
        history_limit=200,
    )
    interrupted = reopened.get(active.id)
    assert interrupted.status == "interrupted"
    assert interrupted.error_code == "operation_interrupted"

    for index in range(205):
        reopened.create(
            kind="managed_file_transfer",
            direction="upload",
            device_id="device-1",
            session_id="session-1",
            status="completed",
            stage="completed",
            message=f"completed-{index}",
            data={"source_path": f"packages/{index}.cc", "destination_path": f"flash:/{index}.cc"},
        )

    persisted = store.list_operations(kind="managed_file_transfer", limit=500)
    assert len(persisted) == 200
    assert all(record.status in {"completed", "interrupted"} for record in persisted)
    with sqlite3.connect(store.path) as connection:
        serialized = " ".join(str(row[0]) for row in connection.execute("SELECT data_json FROM operations"))
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert version == 5
    assert str(tmp_path) not in serialized
    assert "password" not in serialized.casefold()


def test_file_service_stops_after_configured_idle_period(tmp_path: Path) -> None:
    async def scenario() -> None:
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(),
            transfer_root=tmp_path,
        )
        application.transfers.IDLE_STOP_SECONDS = 0.05
        await application.transfers.start_service()
        assert application.transfers.settings().service_running
        application.transfers._schedule_idle_stop()
        await asyncio.sleep(0.15)
        assert not application.transfers.settings().service_running
        assert application.transfers.settings().idle_stop_at == ""

    asyncio.run(scenario())


def test_manual_file_service_start_does_not_schedule_idle_stop(tmp_path: Path) -> None:
    async def scenario() -> None:
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(),
            transfer_root=tmp_path,
        )
        application.transfers.IDLE_STOP_SECONDS = 0.05
        await application.transfers.start_service(auto_stop_when_idle=False)
        await asyncio.sleep(0.15)
        assert application.transfers.settings().service_running
        assert application.transfers.settings().idle_stop_at == ""
        await application.transfers.stop_service()

    asyncio.run(scenario())


def test_managed_transfer_retry_preserves_linux_terminal_environment(tmp_path: Path) -> None:
    async def scenario() -> None:
        (tmp_path / "target.cc").write_bytes(b"linux-transfer")
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(),
            transfer_root=tmp_path,
        )
        device_id = application.devices.list_inventory().devices[0].id
        session = await application.sessions.create(device_id, "simulated", "Linux shell")
        for _ in range(100):
            session = next(
                item for item in application.sessions.list_sessions() if item.id == session.id
            )
            if session.status == "connected":
                break
            await asyncio.sleep(0.01)

        original = application.transfers.start_upload(
            session_id=session.id,
            source_path="target.cc",
            destination_path="/tmp/target.cc",
            terminal_environment="linux",
        )
        application.transfers.cancel(original.id)
        retried = application.transfers.retry(original.id)

        assert retried.retry_of == original.id
        assert retried.data["terminal_environment_requested"] == "linux"
        assert retried.data["terminal_environment"] == "linux"
        assert retried.data["destination_path"] == "/tmp/target.cc"

        application.transfers.cancel(retried.id)
        await application.transfers.close()
        await application.sessions.close_all()

    asyncio.run(scenario())
