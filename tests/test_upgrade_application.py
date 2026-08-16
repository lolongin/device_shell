from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from device_tui.application import MemorySecretStore, MemoryTransferStore
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub
from device_tui.device_sources.sample import SampleDeviceRepository


TOKEN = "upgrade-test-token"


def _wait_operation(
    client: TestClient,
    headers: dict[str, str],
    operation_id: str,
    statuses: set[str],
    attempts: int = 700,
) -> dict[str, object]:
    operation: dict[str, object] = {}
    for _ in range(attempts):
        operation = client.get(
            f"/api/v1/operations/{operation_id}",
            headers=headers,
        ).json()["operation"]
        if str(operation["status"]) in statuses:
            return operation
        time.sleep(0.02)
    return operation


def test_backend_package_upgrade_verification_reboot_approval_and_cancel(
    tmp_path: Path,
) -> None:
    share = tmp_path / "share"
    share.mkdir()
    package = share / "images" / "target-v2.cc"
    package.parent.mkdir()
    package.write_bytes(b"verified-package-upgrade")
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
        first = client.post(
            "/api/v1/package-upgrades",
            headers=headers,
            json={
                "session_id": session["id"],
                "package_path": "images/target-v2.cc",
                "include_slave": True,
                "auto_delete_old_packages": True,
                "reboot_after_setting": False,
            },
        )
        first_operation = _wait_operation(
            client,
            headers,
            first.json()["operation"]["id"],
            {"completed", "failed", "cancelled"},
        )

        gated = client.post(
            "/api/v1/package-upgrades",
            headers=headers,
            json={
                "session_id": session["id"],
                "package_path": "images/target-v2.cc",
                "reboot_after_setting": True,
            },
        ).json()["operation"]
        waiting = _wait_operation(
            client,
            headers,
            gated["id"],
            {"waiting_approval", "failed", "cancelled"},
        )
        approved = client.post(
            f"/api/v1/package-upgrades/{gated['id']}/approve-reboot",
            headers=headers,
        )
        rebooted = _wait_operation(
            client,
            headers,
            gated["id"],
            {"completed", "failed", "cancelled"},
        )

        cancellable = client.post(
            "/api/v1/package-upgrades",
            headers=headers,
            json={
                "session_id": session["id"],
                "package_path": "images/target-v2.cc",
                "reboot_after_setting": True,
            },
        ).json()["operation"]
        cancel_waiting = _wait_operation(
            client,
            headers,
            cancellable["id"],
            {"waiting_approval", "failed", "cancelled"},
        )
        cancelled = client.post(
            f"/api/v1/operations/{cancellable['id']}/cancel",
            headers=headers,
        )

    assert first.status_code == 200
    assert first_operation["status"] == "completed", (
        first_operation["stage"],
        first_operation["message"],
        first_operation["error_code"],
        first_operation["data"],
    )
    assert first_operation["progress_percent"] == 100
    assert first_operation["data"]["include_slave"] is True
    assert first_operation["data"]["reboot_required"] is True
    assert str(share) not in json.dumps(first_operation, ensure_ascii=False)
    assert waiting["status"] == "waiting_approval"
    assert waiting["stage"] == "reboot_approval"
    assert approved.status_code == 200
    assert approved.json()["operation"]["status"] == "running"
    assert rebooted["status"] == "completed"
    assert rebooted["data"]["reboot_required"] is False
    assert cancel_waiting["status"] == "waiting_approval"
    assert cancelled.status_code == 200
    assert cancelled.json()["operation"]["status"] == "cancelled"


def test_package_upgrade_routes_require_authorization(tmp_path: Path) -> None:
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        transfer_root=tmp_path,
    )
    with TestClient(app) as client:
        started = client.post(
            "/api/v1/package-upgrades",
            json={"session_id": "session", "package_path": "target.cc"},
        )
        approved = client.post(
            "/api/v1/package-upgrades/operation/approve-reboot",
        )
        manual_terminal = client.get(
            "/api/v1/package-upgrades/manual/session/terminal",
        )
        manual_plan = client.post(
            "/api/v1/package-upgrades/manual/plan",
            json={"session_id": "session", "package_path": "target.cc"},
        )
        manual_send = client.post(
            "/api/v1/package-upgrades/manual/send",
            json={"session_id": "session", "script": "display version"},
        )

    assert started.status_code == 401
    assert approved.status_code == 401
    assert manual_terminal.status_code == 401
    assert manual_plan.status_code == 401
    assert manual_send.status_code == 401


def test_manual_package_upgrade_plan_keeps_secret_in_python_and_sends_script(
    tmp_path: Path,
) -> None:
    share = tmp_path / "share"
    share.mkdir()
    package = share / "images" / "manual-v3.cc"
    package.parent.mkdir()
    package.write_bytes(b"manual-package-upgrade")
    secrets = MemorySecretStore()
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        secret_store=secrets,
        transfer_store=MemoryTransferStore(),
        transfer_root=share,
    )
    app.state.desktop_application.transfers.update_settings(
        protocol="ftp",
        host="0.0.0.0",
        port=0,
        root=str(share),
        username="manual-user",
        writable=False,
    )
    plaintext = "manual-transfer-secret"
    app.state.desktop_application.transfers.set_password(plaintext)

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        device_id = client.get("/api/v1/devices", headers=headers).json()["devices"][0]["id"]
        session = client.post(
            "/api/v1/sessions",
            headers=headers,
            json={"device_id": device_id, "kind": "simulated"},
        ).json()
        terminal = client.get(
            f"/api/v1/package-upgrades/manual/{session['id']}/terminal",
            headers=headers,
        )
        planned = client.post(
            "/api/v1/package-upgrades/manual/plan",
            headers=headers,
            json={
                "session_id": session["id"],
                "package_path": "images/manual-v3.cc",
                "startup_output": "Current startup system software: flash:/current.cc",
                "master_dir_output": "Directory of flash:/\n(1024 MB free)",
                "slave_dir_output": "Directory of slave#flash:/\n(1024 MB free)",
                "include_slave": True,
                "auto_delete_old_packages": True,
            },
        )
        plan = planned.json()
        sent = client.post(
            "/api/v1/package-upgrades/manual/send",
            headers=headers,
            json={
                "session_id": session["id"],
                "script": "display version\n{{file_transfer.password}}\ndisplay startup",
                "interval_ms": 0,
            },
        )
        unsupported = client.post(
            "/api/v1/package-upgrades/manual/send",
            headers=headers,
            json={
                "session_id": session["id"],
                "script": "{{unsupported.secret}}",
                "interval_ms": 0,
            },
        )
        time.sleep(0.05)
        log = client.get(
            f"/api/v1/sessions/{session['id']}/log",
            headers=headers,
        ).json()["content"]

    assert terminal.status_code == 200
    assert planned.status_code == 200
    assert plan["password_placeholder"] == "{{file_transfer.password}}"
    assert "{{file_transfer.password}}" in plan["script"]
    assert "manual-user" in plan["script"]
    assert plaintext not in json.dumps(plan, ensure_ascii=False)
    assert sent.status_code == 200
    assert sent.json()["command_count"] == 3
    assert unsupported.status_code == 400
    assert plaintext not in unsupported.text
    assert plaintext not in log
