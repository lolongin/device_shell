from __future__ import annotations

from fastapi.testclient import TestClient

from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub


def test_framework_run_api_starts_and_replays_persisted_events() -> None:
    app = create_app(token="framework-token", repository=SampleDeviceRepository(), session_hub=SessionHub())
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer framework-token"}
        created = client.post(
            "/api/v1/framework/runs",
            headers=headers,
            json={
                "workflow_id": "network.package_upgrade",
                "device_id": "d1",
                "inputs": {"package_ref": "flash:/image.cc", "expected_version": "V8"},
            },
        )
        assert created.status_code == 200, created.text
        run = created.json()["run"]
        run_id = run["id"]
        fetched = client.get(f"/api/v1/framework/runs/{run_id}", headers=headers)
        events = client.get(f"/api/v1/framework/runs/{run_id}/events", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["run"]["workflow_id"] == "network.package_upgrade"
    assert events.status_code == 200
    assert events.json()["events"][0]["type"] == "workflow.started"
