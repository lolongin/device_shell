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
        response = client.post(f"/api/v1/workflow-definitions/{workflow_id}/run", json={"device_id": "sim-1", "protocol": "simulated"})
        assert response.status_code == 200
        assert response.json()["task"]["workflow_id"] == workflow_id


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


def test_workflow_definition_rejects_condition_until_branch_compiler_exists() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="conditional",
        nodes=(WorkflowNode("condition", "utility.condition", {"expression": "true"}),),
    )
    try:
        _compile_task_plan(version, "router-1")
    except UnsupportedOperationError as exc:
        assert "branch execution" in str(exc)
    else:
        raise AssertionError("conditional workflow must not be executed as an unconditional task")


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
