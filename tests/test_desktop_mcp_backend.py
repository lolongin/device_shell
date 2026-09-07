from __future__ import annotations

import sys
import time

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


def _wait_for_terminal_status(
    client: TestClient,
    execution_id: str,
    status: str,
) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    for _ in range(50):
        snapshot = _call(
            client,
            "terminal_interact_get",
            {"execution_id": execution_id},
        )
        if snapshot["data"]["status"] == status:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"terminal execution did not reach {status}: {snapshot}")


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


def test_qt_free_mcp_facade_runs_parallel_terminal_batches() -> None:
    with _client() as client:
        devices = _call(client, "device_list")["data"]["devices"]
        device_id = devices[0]["id"]
        result = _call(client, "terminal_execute_parallel", {
            "requests": [
                {"device_id": device_id, "commands": ["display version"]},
                {"device_id": device_id, "commands": ["display version"]},
            ],
            "max_concurrency": 2,
        })

    assert result["data"]["status"] == "success"
    assert result["data"]["request_count"] == 2
    assert result["data"]["completed_count"] == 2


def test_qt_free_mcp_facade_supports_incremental_interactive_execution() -> None:
    with _client() as client:
        device_id = _call(client, "device_list")["data"]["devices"][0]["id"]
        session_id = _call(client, "session_open", {"device_id": device_id})["data"]["session"]["session_id"]
        adapter = client.app.state.session_hub.get(session_id).adapter
        adapter._session.configure_package_upgrade(
            "current.cc",
            123_456,
            require_startup_confirmation=True,
        )
        started = _call(client, "terminal_interact_start", {
            "session_id": session_id,
            "steps": [
                {"type": "send", "text": "display version"},
                {"type": "expect", "success": ["__manual_completion__"]},
            ],
            "total_timeout_seconds": 30,
        })
        execution_id = started["data"]["execution_id"]
        snapshot = _call(client, "terminal_interact_get", {
            "execution_id": execution_id,
            "since_cursor": 0,
        })
        sent = _call(client, "terminal_interact_send", {
            "execution_id": execution_id,
            "text": "continue",
        })
        cancelled = _call(client, "terminal_interact_cancel", {
            "execution_id": execution_id,
        })

    assert started["data"]["execution_id"] == execution_id
    assert snapshot["data"]["event_cursor"] >= 1
    assert sent["data"]["execution_id"] == execution_id
    assert cancelled["data"]["status"] == "cancelled"


def test_terminal_execute_surfaces_interaction_and_attach_resumes_existing_prompt() -> None:
    with _client() as client:
        device_id = _call(client, "device_list")["data"]["devices"][0]["id"]
        opened = _call(client, "session_open", {"device_id": device_id})
        session_id = opened["data"]["session"]["session_id"]
        adapter = client.app.state.session_hub.get(session_id).adapter
        adapter._session.configure_package_upgrade(
            "target.cc",
            123_456,
            require_startup_confirmation=True,
        )

        paused = _call(client, "terminal_execute", {
            "session_id": session_id,
            "command": "startup system-software flash:/current.cc",
            "timeout_seconds": 5,
        })
        execution_id = paused["data"]["execution_id"]

        assert paused["data"]["status"] == "running"
        assert paused["data"]["phase"] == "waiting_for_input"
        assert paused["data"]["completion_reason"] == "interaction_required"
        assert paused["data"]["outcome"]["status"] == "interaction_required"
        assert paused["data"]["outcome"]["finished"] is False

        _call(client, "terminal_interact_send", {
            "execution_id": execution_id,
            "text": "y",
        })
        completed = _wait_for_terminal_status(client, execution_id, "completed")

        assert completed["data"]["outcome"]["status"] == "success"
        assert completed["data"]["lease_released"] is True

        paused_again = _call(client, "terminal_execute", {
            "session_id": session_id,
            "command": "startup system-software flash:/current.cc",
            "timeout_seconds": 5,
        })
        _call(client, "terminal_interact_cancel", {
            "execution_id": paused_again["data"]["execution_id"],
        })
        terminal = _call(client, "terminal_read", {
            "session_id": session_id,
        })

        assert terminal["data"]["prompt"]["type"] == "confirmation_prompt"
        fresh = client.post(
            "/api/v1/mcp/terminal_interact_start",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "session_id": session_id,
                "steps": [{"type": "expect", "success": ["device_prompt"]}],
            },
        )
        assert fresh.status_code == 400
        assert fresh.json()["error"]["code"] == "session_not_ready"

        stale = client.post(
            "/api/v1/mcp/terminal_interact_start",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "session_id": session_id,
                "attach_mode": "attach",
                "output_cursor": terminal["data"]["output_cursor"] - 1,
                "generation": terminal["data"]["generation"],
                "expected_prompt": "confirmation_prompt",
                "steps": [{"type": "expect", "success": ["device_prompt"]}],
            },
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "stale_terminal_cursor"

        stale_generation = client.post(
            "/api/v1/mcp/terminal_interact_start",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "session_id": session_id,
                "attach_mode": "attach",
                "output_cursor": terminal["data"]["output_cursor"],
                "generation": terminal["data"]["generation"] - 1,
                "expected_prompt": "confirmation_prompt",
                "steps": [{"type": "expect", "success": ["device_prompt"]}],
            },
        )
        assert stale_generation.status_code == 409
        assert stale_generation.json()["error"]["code"] == "stale_terminal_generation"

        attached = _call(client, "terminal_interact_start", {
            "session_id": session_id,
            "attach_mode": "attach",
            "output_cursor": terminal["data"]["output_cursor"],
            "generation": terminal["data"]["generation"],
            "expected_prompt": "confirmation_prompt",
            "steps": [
                {
                    "type": "expect",
                    "success": ["device_prompt"],
                    "responses": [
                        {"match": "confirmation_prompt", "text": "y"},
                    ],
                },
            ],
        })
        attached_result = _wait_for_terminal_status(
            client,
            attached["data"]["execution_id"],
            "completed",
        )

    assert attached_result["data"]["outcome"]["status"] == "success"


def test_terminal_interact_start_indexed_confirmation_chain_auto_completes() -> None:
    with _client() as client:
        device_id = _call(client, "device_list")["data"]["devices"][0]["id"]
        session_id = _call(client, "session_open", {"device_id": device_id})["data"]["session"]["session_id"]
        adapter = client.app.state.session_hub.get(session_id).adapter
        adapter._session.configure_package_upgrade(
            "current.cc",
            123_456,
            require_startup_confirmation=True,
        )
        started = _call(client, "terminal_interact_start", {
            "session_id": session_id,
            "total_timeout_seconds": 10,
            "steps": [
                {"type": "send", "text": "startup system-software flash:/current.cc", "success": [1]},
                {"type": "expect", "pattern": "[Y/N]", "success": [2]},
                {"type": "send", "text": "Y", "success": [3]},
                {"type": "expect", "pattern": "<sim>", "success": [3]},
            ],
        })
        execution_id = started["data"]["execution_id"]
        completed = _wait_for_terminal_status(client, execution_id, "completed")

    assert completed["data"]["current_step"] == 3
    assert completed["data"]["outcome"]["status"] == "success"
    assert completed["data"]["lease_released"] is True


def test_terminal_execute_reports_finished_command_failure() -> None:
    with _client() as client:
        device_id = _call(client, "device_list")["data"]["devices"][0]["id"]
        result = _call(client, "terminal_execute", {
            "device_id": device_id,
            "command": "definitely-not-a-command",
            "timeout_seconds": 5,
        })

    assert result["data"]["status"] == "failed"
    assert result["data"]["outcome"]["status"] == "failure"
    assert result["data"]["outcome"]["finished"] is True
    assert result["data"]["outcome"]["errors"]


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
        "terminal_run", "terminal_execute", "terminal_execute_batch", "terminal_execute_parallel",
        "terminal_interact", "terminal_interact_start", "terminal_interact_get",
        "terminal_interact_send", "terminal_interact_cancel", "terminal_interact_resume",
        "terminal_send_command", "terminal_read",
        "execution_get", "execution_cancel", "file_transfer_list",
        "file_transfer_start", "package_upgrade_start", "operation_get",
        "operation_wait", "operation_cancel", "ai_create_session",
        "ai_execute_command", "ai_execute_batch", "ai_execute_script",
        "ai_upload_file", "ai_download_file", "ai_get_result", "ai_run_skill",
        "ai_list_skills", "approval_get",
        "task_create", "task_get", "task_list", "task_resume", "task_cancel",
        "task_framework_start", "task_framework_execute", "task_framework_get",
        "workflow_list", "workflow_plan_validate", "workflow_plan_get", "workflow_plan_approve", "workflow_run",
        "task_replan", "decision_get", "decision_apply", "tool_execute",
    }

    assert all(callable(getattr(service, f"_tool_{tool}", None)) for tool in expected)


def test_generic_task_framework_mcp_composes_workflows_and_persists_run() -> None:
    with _client() as client:
        device_id = _call(client, "device_list")["data"]["devices"][0]["id"]
        plan = {
            "id": "build-and-test",
            "nodes": [
                {
                    "id": "build",
                    "workflow_id": "script.run",
                    "input_mapping": {"argv": "${build_argv}"},
                },
                {
                    "id": "test",
                    "workflow_id": "script.run",
                    "depends_on": ["build"],
                    "input_mapping": {
                        "argv": "${test_argv}",
                        "previous": "${build.run.output}",
                    },
                },
            ],
        }
        started = _call(client, "task.framework.start", {
            "plan": plan,
            "device_id": device_id,
            "inputs": {
                "build_argv": [sys.executable, "-c", "print('built')"],
                "test_argv": [sys.executable, "-c", "print('tested')"],
            },
        })
        task_run_id = started["data"]["task_run"]["id"]
        executed = _call(client, "task.framework.execute", {
            "task_run_id": task_run_id,
            "plan": plan,
        })
        fetched = _call(client, "task.framework.get", {"task_run_id": task_run_id})

    task_run = executed["data"]["task_run"]
    assert task_run["status"] == "succeeded"
    assert set(task_run["node_runs"]) == {"build", "test"}
    assert task_run["outputs"]["test"]["run"]["output"].strip() == "tested"
    assert fetched["data"]["task_run"]["id"] == task_run_id


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


def test_mcp_application_control_plane_discovers_and_controls_app_resources() -> None:
    with _client() as client:
        capabilities = _call(client, "app.capabilities")
        devices = _call(client, "device.list")
        sources = _call(client, "source.status")
        denied_response = client.post(
            "/api/v1/mcp/device.action",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "device_id": devices["data"]["devices"][0]["id"],
                "action": "power_off",
            },
        )
        denied = denied_response.json()

    assert capabilities["data"]["resources"]["workflows"]["write"] == [
        "run", "plan.validate", "plan.approve", "replan",
    ]
    assert sources["data"]["active_source"]
    assert denied_response.status_code == 400
    assert denied["ok"] is False
    assert denied["error"]["code"] == "unsupported_operation"


def test_mcp_device_open_accepts_explicit_transport_protocol() -> None:
    with _client() as client:
        devices = _call(client, "device.list")
        device_id = devices["data"]["devices"][0]["id"]
        opened = _call(client, "device.open", {"device_id": device_id, "protocol": "simulated"})

    assert opened["ok"] is True
    assert opened["data"]["requested_protocol"] == "simulated"
    assert opened["data"]["protocol"] == "simulated"
    assert opened["data"]["session"]["device_id"] == device_id


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
