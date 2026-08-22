from __future__ import annotations

from fastapi.testclient import TestClient

from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub
from device_tui.device_sources.sample import SampleDeviceRepository


TOKEN = "desktop-mcp-test-token"


def _client() -> TestClient:
    return TestClient(create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
    ))


def _call(client: TestClient, tool: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    response = client.post(
        f"/api/v1/mcp/{tool}",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json=payload or {},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_qt_free_mcp_facade_runs_device_session_and_terminal_tools() -> None:
    with _client() as client:
        devices = _call(client, "device_list")
        assert devices["ok"] is True
        device_id = devices["data"]["devices"][0]["id"]
        selected = _call(client, "device_select", {"device_id": device_id})
        opened = _call(client, "session_open", {"device_id": device_id})
        session_id = opened["data"]["session"]["session_id"]
        terminal = _call(client, "terminal_run", {
            "session_id": session_id,
            "commands": ["display version", "dir flash:/"],
            "command_timeout_seconds": 3,
            "total_timeout_seconds": 10,
        })
        execution = _call(client, "execution_get", {
            "execution_id": terminal["data"]["execution_id"],
        })
        status = _call(client, "system_status")

    assert selected["data"]["selected_device_id"] == device_id
    assert terminal["data"]["status"] == "completed"
    assert "SimOS V1.0" in terminal["data"]["steps"][1]["output"]
    assert execution["data"]["status"] == "completed"
    assert status["data"]["approval_mode"] == "disabled"


def test_qt_free_mcp_facade_exposes_skills_and_direct_ai_execution() -> None:
    with _client() as client:
        device_id = _call(client, "device_list")["data"]["devices"][0]["id"]
        session_id = _call(client, "session_open", {"device_id": device_id})["data"]["session"]["session_id"]
        skills = _call(client, "ai_list_skills")
        result = _call(client, "ai_execute_command", {
            "session_id": session_id,
            "command": "display version",
        })
        skill = _call(client, "ai_run_skill", {
            "session_id": session_id,
            "skill_name": "version_check",
            "params": {},
        })

    assert any(skill["name"] == "driver_reload" for skill in skills["data"]["skills"])
    assert any(skill["name"] == "version_check" for skill in skills["data"]["skills"])
    assert result["data"]["ok"] is True
    assert skill["data"]["status"] == "success"


def test_qt_free_mcp_facade_covers_registered_tool_surface() -> None:
    app = create_app(
        token=TOKEN,
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
    )
    service = app.state.mcp_service
    expected = {
        "system_status", "device_list", "device_get", "device_select",
        "session_open", "session_list", "session_manage",
        "terminal_run", "terminal_execute", "terminal_execute_batch",
        "terminal_interact", "terminal_send_command", "terminal_read",
        "execution_get", "execution_cancel", "file_transfer_list",
        "file_transfer_start", "package_upgrade_start", "operation_get",
        "operation_wait", "operation_cancel", "ai_create_session",
        "ai_execute_command", "ai_execute_batch", "ai_execute_script",
        "ai_upload_file", "ai_download_file", "ai_get_result", "ai_run_skill",
        "ai_list_skills", "approval_get",
        "task_create", "task_get", "task_list", "task_resume", "task_cancel",
        "workflow_list", "workflow_plan_validate", "workflow_plan_get", "workflow_plan_approve", "workflow_run",
        "task_replan", "decision_get", "decision_apply", "tool_execute",
    }

    assert all(callable(getattr(service, f"_tool_{tool}", None)) for tool in expected)


def test_qt_free_mcp_facade_is_idempotent_and_audited() -> None:
    with _client() as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        device_id = _call(client, "device_list")["data"]["devices"][0]["id"]
        session_id = _call(client, "session_open", {"device_id": device_id})["data"]["session"]["session_id"]
        first = _call(client, "terminal_run", {
            "session_id": session_id,
            "commands": ["display version"],
            "idempotency_key": "repeat-once",
            "command_timeout_seconds": 3,
        })
        second = _call(client, "terminal_run", {
            "session_id": session_id,
            "commands": ["display version"],
            "idempotency_key": "repeat-once",
            "command_timeout_seconds": 3,
        })
        audit = client.get("/api/v1/ai/audit", headers=headers)

    assert first["data"]["execution_id"] == second["data"]["execution_id"]
    assert any(entry["tool"] == "terminal_run" for entry in audit.json()["entries"])


def test_unified_agent_workflow_capabilities_are_backend_only() -> None:
    with _client() as client:
        workflows = _call(client, "workflow.list")
        devices = _call(client, "device_list")
        device_id = devices["data"]["devices"][0]["id"]
        tool = _call(client, "tool.execute", {
            "name": "terminal_execute",
            "params": {"device_id": device_id, "command": "display version"},
        })

    workflow_ids = {item["id"] for item in workflows["data"]["workflows"]}
    assert "device_upgrade" in workflow_ids
    assert "package.upgrade" not in workflows["data"]["capabilities"]
    assert tool["data"]["status"] == "completed"


def test_agent_plan_is_validated_before_running() -> None:
    with _client() as client:
        device_id = _call(client, "device_list")["data"]["devices"][0]["id"]
        planned = _call(client, "workflow.plan.validate", {
            "plan": {
                "plan_id": "agent-version-check",
                "objective": "读取设备版本",
                "target": {"device_id": device_id},
                "steps": [
                    {
                        "id": "version",
                        "capability": "terminal.command",
                        "params": {"command": "display version"},
                    }
                ],
            }
        })
        assert planned["data"]["status"] == "validated"
        assert planned["data"]["workflow"]["metadata"]["plan_hash"] == planned["data"]["plan_hash"]
        started = _call(client, "workflow.run", {
            "plan_id": planned["data"]["plan_id"],
            "plan_hash": planned["data"]["plan_hash"],
            "source": "agent",
        })
        task_id = started["data"]["task"]["id"]
        task = _call(client, "task.get", {"task_id": task_id})

    assert task["data"]["task"]["workflow_id"] == "agent-version-check"


def test_agent_replan_creates_linked_task_revision() -> None:
    with _client() as client:
        device_id = _call(client, "device_list")["data"]["devices"][0]["id"]
        first = _call(client, "workflow.plan.validate", {
            "plan": {
                "plan_id": "agent-first",
                "objective": "first check",
                "target": {"device_id": device_id},
                "steps": [{"id": "version", "capability": "terminal.command", "params": {"command": "display version"}}],
            }
        })
        started = _call(client, "workflow.run", {"plan_id": first["data"]["plan_id"], "plan_hash": first["data"]["plan_hash"]})
        replanned = _call(client, "task.replan", {
            "parent_task_id": started["data"]["task"]["id"],
            "plan": {
                "plan_id": "agent-second",
                "objective": "second check",
                "target": {"device_id": device_id},
                "steps": [{"id": "dir", "capability": "terminal.command", "params": {"command": "dir flash:/"}}],
            },
        })

    assert replanned["data"]["task"]["parent_task_id"] == started["data"]["task"]["id"]
    assert replanned["data"]["task"]["plan_revision"] == 2


def test_high_risk_plan_requires_explicit_approval() -> None:
    with _client() as client:
        device_id = _call(client, "device_list")["data"]["devices"][0]["id"]
        planned = _call(client, "workflow.plan.validate", {
            "plan": {
                "plan_id": "agent-reboot",
                "objective": "reboot device",
                "target": {"device_id": device_id},
                "steps": [{"id": "reboot", "capability": "device.reboot"}],
            }
        })
        assert planned["data"]["status"] == "requires_confirmation"
        blocked = client.post(
            "/api/v1/mcp/workflow.run",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"plan_id": planned["data"]["plan_id"], "plan_hash": planned["data"]["plan_hash"]},
        )
        assert blocked.status_code == 400
        approved = _call(client, "workflow.plan.approve", {
            "plan_id": planned["data"]["plan_id"],
            "plan_hash": planned["data"]["plan_hash"],
            "reason": "approved for maintenance window",
        })
        started = _call(client, "workflow.run", {
            "plan_id": planned["data"]["plan_id"],
            "plan_hash": planned["data"]["plan_hash"],
        })

    assert approved["data"]["approved"] is True
    assert started["data"]["task"]["plan_id"] == "agent-reboot"
