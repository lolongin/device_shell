from fastapi.testclient import TestClient

from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.app import create_app


def test_workflow_definition_lifecycle() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post("/api/v1/workflow-definitions", json={"name": "Check version"})
        assert created.status_code == 200
        workflow_id = created.json()["workflow"]["id"]
        saved = client.put(
            f"/api/v1/workflow-definitions/{workflow_id}",
            json={
                "name": "Check version",
                "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "show version"}}],
                "edges": [],
            },
        )
        assert saved.status_code == 200
        validation = client.post(f"/api/v1/workflow-definitions/{workflow_id}/validate")
        assert validation.status_code == 200
        assert validation.json()["valid"] is True
        published = client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish")
        assert published.status_code == 200
        assert published.json()["published"] is True
        assert published.json()["workflow"]["version"] == 1
