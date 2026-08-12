from __future__ import annotations

from fastapi.testclient import TestClient

from src.desktop_backend.app import create_app
from src.desktop_backend.session_hub import SessionHub
from src.repository import SampleDeviceRepository


TOKEN = "ai-test-token"


def _client(*, approval_mode: str = "disabled", monkeypatch=None) -> TestClient:
    if monkeypatch is not None:
        monkeypatch.setenv("DEVICE_TUI_APPROVAL_MODE", approval_mode)
    return TestClient(
        create_app(
            token=TOKEN,
            repository=SampleDeviceRepository(),
            session_hub=SessionHub(),
        )
    )


def _session(client: TestClient) -> str:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"device_id": "MOCK-LAB-000", "kind": "simulated"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_ai_plan_and_command_use_application_services_without_qt() -> None:
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        plan = client.post(
            "/api/v1/ai/plan",
            headers=headers,
            json={"objective": "查看设备版本", "selected_device_id": "MOCK-LAB-000"},
        )
        session_id = _session(client)
        result = client.post(
            "/api/v1/ai/execute-command",
            headers=headers,
            json={"session_id": session_id, "command": "display version", "idempotency_key": "v1"},
        )
        repeat = client.post(
            "/api/v1/ai/execute-command",
            headers=headers,
            json={"session_id": session_id, "command": "display version", "idempotency_key": "v1"},
        )

    assert plan.status_code == 200
    assert plan.json()["actions"][1]["command"] == "display version"
    assert result.status_code == 200
    assert result.json()["result"]["ok"] is True
    assert repeat.json()["result"]["result_id"] == result.json()["result"]["result_id"]


def test_ai_high_risk_command_executes_without_interactive_approval_and_is_audited(monkeypatch) -> None:
    with _client(approval_mode="required", monkeypatch=monkeypatch) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        session_id = _session(client)
        executed = client.post(
            "/api/v1/ai/execute-command",
            headers=headers,
            json={"session_id": session_id, "command": "reboot"},
        )
        approvals = client.get("/api/v1/ai/approvals", headers=headers)
        audit = client.get("/api/v1/ai/audit", headers=headers)

    assert executed.status_code == 200
    assert approvals.json()["approvals"] == []
    assert audit.status_code == 200
    assert any(item["tool"] == "ai_execute_command" for item in audit.json()["entries"])


def test_ai_batch_executes_high_risk_steps_without_approval(monkeypatch) -> None:
    with _client(approval_mode="required", monkeypatch=monkeypatch) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        session_id = _session(client)
        executed = client.post(
            "/api/v1/ai/execute-batch",
            headers=headers,
            json={"session_id": session_id, "commands": ["display version", "reboot"]},
        )

    assert executed.status_code == 200
    assert executed.json()["result"]["command_count"] == 2
