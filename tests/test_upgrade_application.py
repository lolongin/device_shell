from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub


TOKEN = "upgrade-test-token"


def _wait_task(client: TestClient, headers: dict[str, str], task_id: str) -> dict[str, object]:
    task: dict[str, object] = {}
    for _ in range(700):
        task = client.get(f"/api/v1/tasks/{task_id}", headers=headers).json()["task"]
        if task["status"] in {"completed", "failed", "cancelled", "waiting_for_decision"}:
            return task
        time.sleep(0.02)
    return task


def test_package_upgrade_is_a_task_and_never_creates_upgrade_operation(tmp_path: Path) -> None:
    share = tmp_path / "share"
    (share / "images").mkdir(parents=True)
    (share / "images" / "target-v2.cc").write_bytes(b"verified-package-upgrade")
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
            "/api/v1/sessions", headers=headers,
            json={"device_id": device_id, "kind": "simulated"},
        ).json()
        created = client.post(
            "/api/v1/tasks", headers=headers,
            json={
                "workflow_id": "device_upgrade",
                "session_id": session["id"],
                "parameters": {
                    "package_path": "images/target-v2.cc",
                    "activation_policy": "stage_only",
                    "cleanup_policy": "auto",
                },
                "source": "desktop",
            },
        )
        assert created.status_code == 200, created.text
        task = _wait_task(client, headers, created.json()["task"]["id"])
        operations = client.get("/api/v1/operations?kind=package_upgrade", headers=headers).json()["operations"]
        removed_route = client.post("/api/v1/package-upgrades", headers=headers, json={})

    assert task["workflow_id"] == "device_upgrade"
    assert task["workflow_view"]["id"] == "network.package_upgrade"
    assert task["status"] == "completed", task
    assert operations == []
    assert removed_route.status_code == 404
