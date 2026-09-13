from fastapi.testclient import TestClient

from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.application.workflow_studio.models import WorkflowEdge, WorkflowNode, WorkflowVersion
from device_tui.interfaces.desktop_api.routers.workflow_definitions import _compile_task_plan
from device_tui.application.errors import UnsupportedOperationError
from device_tui.application.composition.workflows import build_default_activity_executor
from device_tui.framework import ActivityContext, ActivityInvocation, WorkflowRun
import asyncio


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


def test_workflow_action_catalog_is_exposed_for_studio_clients() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        response = client.get("/api/v1/workflow-definitions/actions")
        assert response.status_code == 200
        actions = {item["id"]: item for item in response.json()["actions"]}
        assert {"device.command", "file.upload", "utility.wait"}.issubset(actions)
        assert actions["file.upload"]["risk"] == "high"
        assert "required" in actions["device.command"]["input_schema"]


def test_workflow_definition_can_test_run_current_draft() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Draft run",
                "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "display version"}}],
                "edges": [],
            },
        )
        workflow_id = created.json()["workflow"]["id"]
        response = client.post(f"/api/v1/workflow-definitions/{workflow_id}/run", json={"device_id": "sim-1", "protocol": "simulated", "draft": True})
        assert response.status_code == 200
        assert response.json()["task"]["workflow_id"] == workflow_id


def test_workflow_definition_requires_explicit_draft_run_before_publish() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={"name": "Draft only", "nodes": [{"id": "wait", "action_id": "utility.wait", "config": {"seconds": 0}}]},
        )
        workflow_id = created.json()["workflow"]["id"]

        response = client.post(
            f"/api/v1/workflow-definitions/{workflow_id}/run",
            json={"device_id": "sim-1", "protocol": "simulated"},
        )

        assert response.status_code == 400
        assert "published" in response.json()["error"]["message"]


def test_workflow_run_uses_latest_published_version_and_marks_reference() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={"name": "Versioned", "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "display version"}}]},
        )
        workflow_id = created.json()["workflow"]["id"]
        published = client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish").json()["workflow"]
        client.put(
            f"/api/v1/workflow-definitions/{workflow_id}",
            json={"name": "Changed draft", "nodes": [{"id": "wait", "action_id": "utility.wait", "config": {"seconds": 0}}]},
        )
        started = client.post(f"/api/v1/workflow-definitions/{workflow_id}/run", json={"device_id": "sim-1", "protocol": "simulated"})
        assert started.status_code == 200
        assert started.json()["task"]["workflow_view"]["version"] == str(published["version"])


def test_workflow_run_merges_input_defaults_into_task_context() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Defaults",
                "inputs": [{"name": "attempts", "type": "integer", "required": True, "default": 3}],
                "nodes": [{"id": "wait", "action_id": "utility.wait", "config": {"seconds": 0}}],
            },
        )
        workflow_id = created.json()["workflow"]["id"]
        client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish")

        started = client.post(
            f"/api/v1/workflow-definitions/{workflow_id}/run",
            json={"device_id": "sim-1", "protocol": "simulated"},
        )

        assert started.status_code == 200
        assert started.json()["task"]["context"]["attempts"] == 3


def test_workflow_run_requires_confirmation_for_direct_and_looped_high_risk_actions() -> None:
    workflows = (
        [{"id": "reboot", "action_id": "device.reboot", "config": {}}],
        [{"id": "loop", "action_id": "loop.for_each", "config": {"items": [1], "action_id": "device.reboot", "action_inputs": {}}}],
    )
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        for index, nodes in enumerate(workflows):
            created = client.post(
                "/api/v1/workflow-definitions",
                json={"name": f"Risk {index}", "nodes": nodes},
            )
            workflow_id = created.json()["workflow"]["id"]
            client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish")

            rejected = client.post(
                f"/api/v1/workflow-definitions/{workflow_id}/run",
                json={"device_id": "sim-1", "protocol": "simulated"},
            )
            accepted = client.post(
                f"/api/v1/workflow-definitions/{workflow_id}/run",
                json={"device_id": "sim-1", "protocol": "simulated", "confirmed_risks": True},
            )

            assert rejected.status_code == 400
            assert rejected.json()["error"]["details"]["code"] == "risk_confirmation_required"
            assert accepted.status_code == 200


def test_workflow_definition_compiles_manual_confirmation_step() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={"name": "Confirm", "nodes": [{"id": "confirm", "action_id": "utility.confirm", "config": {"prompt": "确认继续？"}}], "edges": []},
        )
        workflow_id = created.json()["workflow"]["id"]
        response = client.post(f"/api/v1/workflow-definitions/{workflow_id}/run", json={"device_id": "sim-1", "protocol": "simulated", "dry_run": True, "draft": True})
        assert response.status_code == 200
        assert response.json()["preview"]["steps"][0]["action"] == "utility.confirm"


def test_task_report_returns_business_facing_export_payload() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Report",
                "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "display version"}}],
                "edges": [],
            },
        )
        workflow_id = created.json()["workflow"]["id"]
        client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish")
        started = client.post(f"/api/v1/workflow-definitions/{workflow_id}/run", json={"device_id": "sim-1", "protocol": "simulated"})
        task_id = started.json()["task"]["id"]
        response = client.get(f"/api/v1/tasks/{task_id}/report")
        assert response.status_code == 200
        body = response.json()
        assert body["filename"].endswith(".csv")
        assert body["columns"][:3] == ["流程", "设备", "总体状态"]
        assert "重试次数" in body["columns"]
        assert body["summary"]["task_id"] == task_id


def test_workflow_definition_dry_run_returns_preview_without_creating_task() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Dry run",
                "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "display version"}}],
                "edges": [],
            },
        )
        workflow_id = created.json()["workflow"]["id"]
        response = client.post(
            f"/api/v1/workflow-definitions/{workflow_id}/run",
            json={"device_id": "sim-1", "protocol": "simulated", "dry_run": True, "draft": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["dry_run"] is True
        assert body["preview"]["step_count"] == 1
        assert "task" not in body


def test_workflow_definition_dry_run_reports_batch_targets() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post("/api/v1/workflow-definitions", json={"name": "Batch", "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "display version"}}], "edges": []})
        workflow_id = created.json()["workflow"]["id"]
        response = client.post(f"/api/v1/workflow-definitions/{workflow_id}/run", json={"device_ids": ["sim-1", "sim-2"], "dry_run": True, "draft": True})
        assert response.status_code == 200
        assert response.json()["preview"]["target_count"] == 2


def test_workflow_definition_creates_one_task_per_batch_target() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Batch run",
                "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "display version"}}],
                "edges": [],
            },
        )
        workflow_id = created.json()["workflow"]["id"]
        client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish")
        response = client.post(
            f"/api/v1/workflow-definitions/{workflow_id}/run",
            json={"device_ids": ["sim-1", "sim-2"], "protocol": "simulated"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["target_count"] == 2
        assert [task["device_id"] for task in body["tasks"]] == ["sim-1", "sim-2"]


def test_workflow_definition_maps_batch_sessions_by_device() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post("/api/v1/workflow-definitions", json={"name": "Batch sessions", "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "display version"}}], "edges": []})
        workflow_id = created.json()["workflow"]["id"]
        client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish")

        response = client.post(
            f"/api/v1/workflow-definitions/{workflow_id}/run",
            json={
                "device_ids": ["sim-1", "sim-2"],
                "session_ids": {"sim-2": "session-sim-2", "sim-1": "session-sim-1"},
                "protocol": "simulated",
            },
        )

        assert response.status_code == 200
        assert [task["session_id"] for task in response.json()["tasks"]] == ["session-sim-1", "session-sim-2"]


def test_workflow_definition_dry_run_can_select_a_step_with_prerequisites() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Step test",
                "nodes": [
                    {"id": "info", "action_id": "device.info", "config": {"fields": ["software_version"]}},
                    {"id": "save", "action_id": "result.save", "config": {"key": "version"}},
                ],
                "edges": [{"source": "info", "target": "save"}],
            },
        )
        workflow_id = created.json()["workflow"]["id"]
        response = client.post(
            f"/api/v1/workflow-definitions/{workflow_id}/run",
            json={"device_id": "sim-1", "step_id": "save", "dry_run": True, "draft": True},
        )

        assert response.status_code == 200
        assert response.json()["preview"]["step_count"] == 2


def test_workflow_definition_compiles_retry_policy_into_task_step() -> None:
    version = WorkflowVersion(
        workflow_id="wf", version=1, name="retry",
        nodes=(WorkflowNode("command", "device.command", {"command": "display version", "retry_attempts": 3}),),
    )
    plan = _compile_task_plan(version, "router-1")
    assert plan.nodes[0].retry_policy == {"max_attempts": 3}


def test_workflow_definition_compiles_retry_backoff_into_task_step() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="retry-backoff",
        nodes=(WorkflowNode("command", "device.command", {"command": "display version", "retry_attempts": 3, "retry_backoff_seconds": 2}),),
    )
    plan = _compile_task_plan(version, "router-1")
    assert plan.nodes[0].retry_policy == {"max_attempts": 3, "backoff_seconds": 2}


def test_workflow_definition_compiles_loop_items_from_predecessor_output() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="loop-reference",
        nodes=(
            WorkflowNode("items", "variable.set", {"name": "targets", "value": ["a", "b"]}),
            WorkflowNode("loop", "loop.for_each", {"items": "${targets}", "action_id": "result.save", "action_inputs": {"key": "${item}"}}),
        ),
        edges=(WorkflowEdge("items", "loop"),),
    )
    plan = _compile_task_plan(version, "router-1")
    assert plan.nodes[1].input_mapping["items"] == "${targets}"
    assert plan.nodes[1].depends_on == ("items",)


def test_workflow_definition_compiles_repeat_policy_into_task_step() -> None:
    version = WorkflowVersion("repeat", 0, "Repeat", nodes=(WorkflowNode("command", "device.command", {"command": "display version", "repeat_count": 3}),), edges=())
    plan = _compile_task_plan(version, "router-1")
    assert plan.nodes[0].repeat_policy == {"max_iterations": 3}


def test_workflow_definition_compiles_supported_actions_to_framework_activities() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="full",
        nodes=(
            WorkflowNode("select", "device.select", {"device_id": "router-1"}),
            WorkflowNode("ssh", "device.ssh", {"host": "router-1"}),
            WorkflowNode("telnet", "device.telnet", {"host": "router-1"}),
            WorkflowNode("command", "device.command", {"command": "display version"}),
            WorkflowNode("upload", "file.upload", {"source": "a.cc", "destination": "flash:/a.cc"}),
            WorkflowNode("download", "file.download", {"source": "flash:/a.cc", "destination": "a.cc"}),
            WorkflowNode("reboot", "device.reboot"),
            WorkflowNode("wait", "utility.wait", {"seconds": 0}),
        ),
        edges=tuple(WorkflowEdge(source, target) for source, target in (
            ("select", "ssh"), ("ssh", "telnet"), ("telnet", "command"),
            ("command", "upload"), ("upload", "download"), ("download", "reboot"),
            ("reboot", "wait"),
        )),
    )
    plan = _compile_task_plan(version, "router-1")
    assert [node.workflow_id for node in plan.nodes] == [
        "device.select", "device.wait_online", "device.wait_online",
        "terminal.command", "file.transfer", "file.transfer", "device.reboot", "utility.wait",
    ]
    assert plan.nodes[1].input_mapping["recovery_protocol"] == "ssh"
    assert plan.nodes[2].input_mapping["recovery_protocol"] == "telnet"
    assert plan.nodes[4].input_mapping["direction"] == "upload"
    assert plan.nodes[4].input_mapping["source_path"] == "a.cc"
    assert plan.nodes[4].input_mapping["destination_path"] == "flash:/a.cc"


def test_workflow_definition_rejects_non_executable_loop_children_at_compile_time() -> None:
    for child_action in ("loop.for_each", "utility.condition", "utility.confirm"):
        version = WorkflowVersion(
            workflow_id="wf",
            version=1,
            name="nested",
            nodes=(WorkflowNode("loop", "loop.for_each", {"items": [1], "action_id": child_action}),),
        )
        try:
            _compile_task_plan(version, "router-1")
        except UnsupportedOperationError as exc:
            assert "loop child action" in str(exc)
        else:
            raise AssertionError(f"non-executable loop child was accepted: {child_action}")


def test_workflow_definition_compiles_visual_condition_branches() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="conditional",
        nodes=(
            WorkflowNode("info", "device.info", {"fields": ["software_version"]}),
            WorkflowNode(
                "condition",
                "utility.condition",
                {"rules": [{"field": "software_version", "operator": "小于", "value": "8.200"}]},
            ),
            WorkflowNode("upload", "file.upload", {"source": "a.cc", "destination": "flash:/a.cc"}),
            WorkflowNode("record", "result.save", {"key": "version_check"}),
        ),
        edges=(
            WorkflowEdge("info", "condition"),
            WorkflowEdge("condition", "upload", condition="true"),
            WorkflowEdge("condition", "record", condition="false"),
        ),
    )
    plan = _compile_task_plan(version, "router-1")
    assert [node.id for node in plan.nodes] == ["info", "upload", "record"]
    assert plan.nodes[1].depends_on == ("info",)
    assert plan.nodes[1].run_if == {
        "rules": [{"field": "software_version", "operator": "小于", "value": "8.200"}],
        "logical_operator": "AND",
        "values_from": "info",
        "expected": True,
    }
    assert plan.nodes[2].run_if["expected"] is False
    assert plan.nodes[2].input_mapping["value"] == "${info}"


def test_workflow_definition_rejects_expression_only_condition_until_visual_rules_exist() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="expression-only",
        nodes=(WorkflowNode("condition", "utility.condition", {"expression": "true"}),),
    )
    try:
        _compile_task_plan(version, "router-1")
    except UnsupportedOperationError as exc:
        assert "visual rules" in str(exc)
    else:
        raise AssertionError("expression-only condition must not be silently treated as a branch")


def test_utility_activities_execute_without_a_device_transport() -> None:
    executor = build_default_activity_executor()
    events = []
    async def run() -> None:
        for activity_id, inputs in (("device.select", {"device_id": "router-1"}), ("utility.wait", {"seconds": 0})):
            invocation = ActivityInvocation(activity_id, f"inv-{activity_id}", "run-1", inputs=inputs, context={"target": {"device_id": "router-1"}})
            context = ActivityContext(WorkflowRun("run-1", "wf", "1", "router-1"), invocation)
            result = await executor.execute(invocation, context, events.append)
            assert str(result.status) == "succeeded"
    asyncio.run(run())
