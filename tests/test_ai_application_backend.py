from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub
from device_tui.device_sources.sample import SampleDeviceRepository


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


def test_ai_command_opens_or_reuses_session_from_device_id() -> None:
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        executed = client.post(
            "/api/v1/ai/execute-command",
            headers=headers,
            json={"device_id": "MOCK-LAB-000", "command": "display version"},
        )
        sessions = client.get("/api/v1/sessions", headers=headers)

    assert executed.status_code == 200, executed.text
    result = executed.json()["result"]
    assert result["device_id"] == "MOCK-LAB-000"
    assert result["session_id"]
    assert len(sessions.json()["sessions"]) == 1
    assert sessions.json()["sessions"][0]["id"] == result["session_id"]


def test_ai_command_rejects_mismatched_device_and_session() -> None:
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        session_id = _session(client)
        executed = client.post(
            "/api/v1/ai/execute-command",
            headers=headers,
            json={
                "device_id": "SIM-TERMINAL",
                "session_id": session_id,
                "command": "display version",
            },
        )

    assert executed.status_code == 400
    assert "does not belong to device_id" in executed.text


def test_ai_chat_persists_device_and_session_context(monkeypatch) -> None:
    from device_tui.application.ai.agent import AgentContext

    class FakeAgent:
        async def run(self, message: str, context: AgentContext) -> str:
            assert message == "检查 CPU"
            assert context.device_id == "MOCK-LAB-000"
            assert context.session_id == "session-from-ui"
            return "已完成检查"

    with _client() as client:
        context = client.app.state.context
        context.ai_agent = FakeAgent()
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = client.post(
            "/api/ai/chat",
            headers=headers,
            json={
                "conversation_id": "c1",
                "device_id": "MOCK-LAB-000",
                "session_id": "session-from-ui",
                "message": "检查 CPU",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["message"] == "已完成检查"
    assert response.json()["device_id"] == "MOCK-LAB-000"
    assert response.json()["session_id"] == "session-from-ui"


def test_ai_chat_requires_a_device_or_session_target() -> None:
    class FakeAgent:
        async def run(self, message: str, context) -> str:
            del message, context
            raise AssertionError("agent should not run without a target")

    with _client() as client:
        client.app.state.context.ai_agent = FakeAgent()
        response = client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"conversation_id": "c-no-target", "message": "检查 CPU"},
        )

    assert response.status_code == 400
    assert "device_id or session_id is required" in response.text


def test_parallel_batches_run_independent_targets_concurrently_and_serialize_same_target() -> None:
    from device_tui.application.ai.service import AiApplicationService

    service = AiApplicationService(None)  # type: ignore[arg-type]
    active = 0
    max_active = 0
    active_targets: set[str] = set()
    overlap_on_same_target = False

    async def fake_execute_batch(commands, **kwargs):
        nonlocal active, max_active, overlap_on_same_target
        target = str(kwargs.get("device_id") or kwargs.get("session_id"))
        if target in active_targets:
            overlap_on_same_target = True
        active_targets.add(target)
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        active -= 1
        active_targets.remove(target)
        return {"status": "success", "device_id": target, "command_count": len(commands)}

    service.execute_batch = fake_execute_batch  # type: ignore[method-assign]
    result = asyncio.run(service.execute_parallel_batches([
        {"device_id": "device-a", "commands": ["show 1"]},
        {"device_id": "device-a", "commands": ["show 2"]},
        {"device_id": "device-b", "commands": ["show 3"]},
    ], max_concurrency=3))

    assert result["status"] == "success"
    assert result["completed_count"] == 3
    assert max_active == 2
    assert overlap_on_same_target is False


def test_parallel_batches_report_partial_failures_without_aborting_other_requests() -> None:
    from device_tui.application.ai.service import AiApplicationService

    service = AiApplicationService(None)  # type: ignore[arg-type]

    async def fake_execute_batch(commands, **kwargs):
        del commands, kwargs
        return {"status": "success"}

    service.execute_batch = fake_execute_batch  # type: ignore[method-assign]
    result = asyncio.run(service.execute_parallel_batches([
        {"device_id": "device-a", "commands": ["show"]},
        {"device_id": "device-b", "commands": []},
        {"commands": ["show"]},
    ]))

    assert result["status"] == "partial"
    assert result["completed_count"] == 1
    assert result["failed_count"] == 2
    assert result["results"][1]["error"] == "commands must be a non-empty list"
