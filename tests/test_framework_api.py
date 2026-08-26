from __future__ import annotations

from fastapi.testclient import TestClient

from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub


def test_framework_api_exposes_definitions_but_not_direct_execution() -> None:
    app = create_app(token="framework-token", repository=SampleDeviceRepository(), session_hub=SessionHub())
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer framework-token"}
        catalog = client.get("/api/v1/framework/workflows", headers=headers)
        preview = client.post(
            "/api/v1/framework/workflows/network.package_upgrade/preview",
            headers=headers,
            json={"package_ref": "flash:/image.cc", "expected_version": "V8"},
        )
        direct_run = client.post(
            "/api/v1/framework/runs",
            headers=headers,
            json={
                "workflow_id": "network.package_upgrade",
                "device_id": "d1",
                "inputs": {"package_ref": "flash:/image.cc", "expected_version": "V8"},
            },
        )

    assert catalog.status_code == 200
    assert catalog.json()["workflows"][0]["id"] == "network.package_upgrade"
    assert preview.status_code == 200
    assert preview.json()["workflow"]["id"] == "network.package_upgrade"
    assert direct_run.status_code == 404
