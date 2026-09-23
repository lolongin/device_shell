from fastapi.testclient import TestClient

from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.application.workflow_studio import build_action_catalog
from device_tui.application.workflow_studio.models import WorkflowEdge, WorkflowNode, WorkflowVersion
from device_tui.interfaces.desktop_api.routers.workflow_definitions import (
    _compile_task_plan,
    _normalize_action_inputs,
    _prepare_workflow_file_inputs,
    _validate_workflow_script_inputs,
)
from device_tui.application.errors import UnsupportedOperationError
from device_tui.application.composition.workflows import build_default_activity_executor
from device_tui.framework import ActivityContext, ActivityInvocation, WorkflowRun
import asyncio


def test_workflow_upload_input_is_prepared_before_plan_compilation() -> None:
    class Transfers:
        def prepare_workflow_source(self, value: str, *, staging_id: str) -> str:
            assert staging_id == "run-1"
            return ".workflow-staging/run-1/device.cc"

    version = WorkflowVersion(
        "workflow",
        1,
        "Upload",
        inputs=(),
        nodes=(WorkflowNode("upload", "file.upload", {"source": "${package_path}", "destination": "flash:/device.cc"}),),
    )
    prepared, overrides = _prepare_workflow_file_inputs(
        version,
        {"package_path": r"D:\\packages\\device.cc"},
        Transfers(),
        staging_id="run-1",
    )

    assert prepared["package_path"] == ".workflow-staging/run-1/device.cc"
    assert overrides == {}


def test_workflow_upload_defaults_to_overwrite_but_preserves_explicit_false() -> None:
    assert _normalize_action_inputs("file.upload", {"source": "a.cc"})["overwrite"] is True
    assert _normalize_action_inputs(
        "file.upload",
        {"source": "a.cc", "overwrite": False},
    )["overwrite"] is False


def test_workflow_upload_does_not_stage_device_name_inputs_as_local_files() -> None:
    class Transfers:
        def prepare_workflow_source(self, value: str, *, staging_id: str) -> str:
            raise AssertionError("device name must not be treated as a local file")

    version = WorkflowVersion(
        "workflow",
        1,
        "Upload",
        inputs=(),
        nodes=(WorkflowNode("upload", "file.upload", {"source": "${package_name}", "destination": "flash:/device.cc"}),),
    )
    prepared, overrides = _prepare_workflow_file_inputs(version, {"package_name": "device.cc"}, Transfers(), staging_id="run-1")
    assert prepared["package_name"] == "device.cc"
    assert overrides == {}


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


def test_workflow_custom_command_action_crud() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions/custom-actions",
            json={
                "name": "检查本机版本",
                "description": "可复用的版本检查",
                "action_id": "device.command",
                "config": {
                    "execution_mode": "shell",
                    "command": "tool --version ${inputs.channel}",
                    "timeout_seconds": 15,
                    "failure_strategy": "continue",
                },
            },
        )
        assert created.status_code == 200
        action = created.json()["action"]
        assert action["config"]["execution_mode"] == "shell"

        listed = client.get("/api/v1/workflow-definitions/custom-actions")
        assert listed.status_code == 200
        assert action in listed.json()["actions"]

        deleted = client.delete(f"/api/v1/workflow-definitions/custom-actions/{action['id']}")
        assert deleted.status_code == 204
        assert action["id"] not in {
            item["id"]
            for item in client.get("/api/v1/workflow-definitions/custom-actions").json()["actions"]
        }


def test_workflow_script_resource_crud_and_language_validation() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        rejected = client.post(
            "/api/v1/workflow-definitions/scripts",
            json={"name": "Invalid", "language": "ruby", "script": "puts 'no'"},
        )
        assert rejected.status_code == 400
        assert rejected.json()["detail"] == "unsupported script language"

        created = client.post(
            "/api/v1/workflow-definitions/scripts",
            json={
                "name": "Inspect device",
                "description": "Reusable diagnostic",
                "language": "python",
                "script": "print('first')",
                "input_schema": [{"name": "mode", "type": "string"}],
            },
        )
        assert created.status_code == 200
        script = created.json()["script"]
        assert script["id"].startswith("script_")
        assert script["input_schema"] == [{"name": "mode", "type": "string", "required": False}]
        assert script in client.get("/api/v1/workflow-definitions/scripts").json()["scripts"]

        invalid_schema = client.put(
            f"/api/v1/workflow-definitions/scripts/{script['id']}",
            json={"input_schema": [{"name": "mode", "type": "string"}, {"name": "mode", "type": "number"}]},
        )
        assert invalid_schema.status_code == 400
        assert "duplicate script input parameter" in invalid_schema.json()["detail"]

        updated = client.put(
            f"/api/v1/workflow-definitions/scripts/{script['id']}",
            json={"name": "Inspect device v2", "language": "bash", "script": "printf ok"},
        )
        assert updated.status_code == 200
        assert updated.json()["script"]["name"] == "Inspect device v2"
        assert updated.json()["script"]["script"] == "printf ok"

        deleted = client.delete(f"/api/v1/workflow-definitions/scripts/{script['id']}")
        assert deleted.status_code == 204
        assert script["id"] not in {
            item["id"]
            for item in client.get("/api/v1/workflow-definitions/scripts").json()["scripts"]
        }


def test_workflow_script_main_signature_generates_input_schema() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions/scripts",
            json={
                "name": "Function inputs",
                "language": "python",
                "script": (
                    "def main(name: str, count: int = 2, enabled: bool = False, "
                    "options: dict | None = None, items: list[str] = []):\n"
                    "    return {'name': name}\n"
                ),
            },
        )

        assert created.status_code == 200
        script = created.json()["script"]
        assert script["entrypoint"] == "main"
        assert script["input_schema_source"] == "function"
        assert script["input_schema"] == [
            {"name": "name", "type": "string", "required": True},
            {"name": "count", "type": "number", "required": False, "default": 2},
            {"name": "enabled", "type": "boolean", "required": False, "default": False},
            {"name": "options", "type": "object", "required": False},
            {"name": "items", "type": "array", "required": False, "default": []},
        ]


def test_workflow_script_reference_validates_publishes_and_resolves_for_dry_run() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        script = client.post(
            "/api/v1/workflow-definitions/scripts",
            json={"name": "Referenced", "language": "python", "script": "print('ok')"},
        ).json()["script"]
        workflow = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Referenced script",
                "nodes": [
                    {
                        "id": "script",
                        "action_id": "script.run",
                        "config": {"script_id": script["id"]},
                    }
                ],
            },
        ).json()["workflow"]

        validation = client.post(f"/api/v1/workflow-definitions/{workflow['id']}/validate")
        assert validation.status_code == 200
        assert validation.json()["valid"] is True
        published = client.post(f"/api/v1/workflow-definitions/{workflow['id']}/publish")
        assert published.status_code == 200
        assert published.json()["published"] is True

        preview = client.post(
            f"/api/v1/workflow-definitions/{workflow['id']}/run",
            json={"device_id": "sim-1", "draft": True, "dry_run": True},
        )
        assert preview.status_code == 200
        assert preview.json()["preview"]["steps"] == [
            {"id": "script", "action": "script.run", "depends_on": []}
        ]


def test_workflow_script_reference_reports_missing_resource() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        workflow = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Missing script",
                "nodes": [
                    {
                        "id": "script",
                        "action_id": "script.run",
                        "config": {"script_id": "script_missing"},
                    }
                ],
            },
        ).json()["workflow"]

        validation = client.post(f"/api/v1/workflow-definitions/{workflow['id']}/validate")
        assert validation.status_code == 400
        assert "script resource not found" in validation.json()["detail"]


def test_workflow_script_test_requires_confirmation_and_creates_task() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        script = client.post(
            "/api/v1/workflow-definitions/scripts",
            json={
                "name": "Testable",
                "language": "python",
                "script": "print('ok')",
                "input_schema": [{"name": "mode", "type": "string"}],
            },
        ).json()["script"]

        rejected = client.post(
            f"/api/v1/workflow-definitions/scripts/{script['id']}/test",
            json={"device_id": "sim-1", "protocol": "simulated"},
        )
        assert rejected.status_code == 400
        assert rejected.json()["error"]["details"]["code"] == "risk_confirmation_required"

        accepted = client.post(
            f"/api/v1/workflow-definitions/scripts/{script['id']}/test",
            json={
                "device_id": "sim-1",
                "protocol": "simulated",
                "inputs": {"mode": "check"},
                "confirmed_risks": True,
            },
        )
        assert accepted.status_code == 200
        assert accepted.json()["task"]["workflow_id"].startswith("script_test_")


def test_workflow_script_test_enforces_input_schema_and_applies_defaults() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        script = client.post(
            "/api/v1/workflow-definitions/scripts",
            json={
                "name": "Typed inputs",
                "language": "python",
                "script": "print('ok')",
                "input_schema": [
                    {"name": "mode", "type": "string", "required": True},
                    {"name": "count", "type": "number", "default": 2},
                    {"name": "enabled", "type": "boolean", "default": True},
                    {"name": "options", "type": "object"},
                    {"name": "items", "type": "array"},
                ],
            },
        ).json()["script"]

        missing = client.post(
            f"/api/v1/workflow-definitions/scripts/{script['id']}/test",
            json={"inputs": {}, "confirmed_risks": True},
        )
        assert missing.status_code == 400
        assert missing.json()["error"]["details"] == {
            "code": "missing_script_input",
            "name": "mode",
        }

        unknown = client.post(
            f"/api/v1/workflow-definitions/scripts/{script['id']}/test",
            json={"inputs": {"mode": "check", "extra": 1}, "confirmed_risks": True},
        )
        assert unknown.status_code == 400
        assert unknown.json()["error"]["details"]["code"] == "unknown_script_input"

        wrong_number = client.post(
            f"/api/v1/workflow-definitions/scripts/{script['id']}/test",
            json={"inputs": {"mode": "check", "count": "2"}, "confirmed_risks": True},
        )
        assert wrong_number.status_code == 400
        assert wrong_number.json()["error"]["details"] == {
            "code": "invalid_script_input",
            "name": "count",
            "type": "number",
        }

        wrong_object = client.post(
            f"/api/v1/workflow-definitions/scripts/{script['id']}/test",
            json={"inputs": {"mode": "check", "options": []}, "confirmed_risks": True},
        )
        assert wrong_object.status_code == 400

        wrong_array = client.post(
            f"/api/v1/workflow-definitions/scripts/{script['id']}/test",
            json={"inputs": {"mode": "check", "items": {}}, "confirmed_risks": True},
        )
        assert wrong_array.status_code == 400

        assert _validate_workflow_script_inputs(script["input_schema"], {"mode": "check"}) == {
            "mode": "check",
            "count": 2,
            "enabled": True,
        }


def test_workflow_definition_compiles_shell_command_controls() -> None:
    version = WorkflowVersion(
        "shell-workflow",
        1,
        "Shell",
        nodes=(WorkflowNode("command", "device.command", {
            "execution_mode": "bash",
            "command": "printf '%s' '${inputs.value}'",
            "timeout_seconds": 12,
            "retry_attempts": 3,
            "retry_backoff_seconds": 0.25,
            "failure_strategy": "continue",
        }),),
    )

    plan = _compile_task_plan(version, "router-1")

    assert plan.nodes[0].workflow_id == "shell.command"
    assert plan.nodes[0].input_mapping["execution_mode"] == "bash"
    assert plan.nodes[0].input_mapping["timeout_seconds"] == 12
    assert plan.nodes[0].retry_policy == {
        "max_attempts": 3,
        "backoff_seconds": 0.25,
        "on_failure": "continue",
    }


def test_workflow_definition_cannot_be_renamed_to_blank() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post("/api/v1/workflow-definitions", json={"name": "Named workflow"}).json()["workflow"]

        response = client.put(
            f"/api/v1/workflow-definitions/{created['id']}",
            json={"name": "   ", "nodes": [], "edges": []},
        )

        assert response.status_code == 400
        assert "workflow name is required" in response.json()["detail"]


def test_workflow_published_versions_can_be_listed_and_deleted_until_referenced() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Version management",
                "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "show version"}}],
                "edges": [],
            },
        ).json()["workflow"]
        workflow_id = created["id"]
        first = client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish").json()["workflow"]
        second = client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish").json()["workflow"]

        versions = client.get(f"/api/v1/workflow-definitions/{workflow_id}/versions")
        assert versions.status_code == 200
        assert [(item["version"], item["referenced"]) for item in versions.json()["versions"]] == [(2, False), (1, False)]

        deleted = client.delete(f"/api/v1/workflow-definitions/{workflow_id}/versions/{second['version']}")
        assert deleted.status_code == 204
        missing = client.delete(f"/api/v1/workflow-definitions/{workflow_id}/versions/{second['version']}")
        assert missing.status_code == 404

        started = client.post(
            f"/api/v1/workflow-definitions/{workflow_id}/run",
            json={"device_id": "sim-1", "protocol": "simulated", "version": first["version"]},
        )
        assert started.status_code == 200
        referenced = client.get(f"/api/v1/workflow-definitions/{workflow_id}/versions").json()["versions"]
        assert referenced[0]["referenced"] is True
        blocked = client.delete(f"/api/v1/workflow-definitions/{workflow_id}/versions/{first['version']}")
        assert blocked.status_code == 409
        assert "已被任务引用" in blocked.json()["detail"]


def test_workflow_version_listing_keeps_runtime_inputs_and_version_numbers_monotonic() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Monotonic versions",
                "inputs": [{"name": "package_path", "type": "file", "required": True}],
                "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "show version"}}],
            },
        ).json()["workflow"]
        workflow_id = created["id"]
        first = client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish").json()["workflow"]
        assert client.get(f"/api/v1/workflow-definitions/{workflow_id}/versions").json()["versions"][0]["inputs"][0]["name"] == "package_path"
        assert client.delete(f"/api/v1/workflow-definitions/{workflow_id}/versions/{first['version']}").status_code == 204
        next_version = client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish").json()["workflow"]
        assert next_version["version"] == first["version"] + 1


def test_workflow_published_version_can_be_exported_and_restored_without_changing_snapshot() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Restore version",
                "description": "original",
                "nodes": [{"id": "command", "action_id": "device.command", "config": {"command": "show version"}}],
                "edges": [],
            },
        ).json()["workflow"]
        workflow_id = created["id"]
        published = client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish").json()["workflow"]
        client.put(f"/api/v1/workflow-definitions/{workflow_id}", json={"name": "Changed draft", "description": "changed", "nodes": [], "edges": []})

        exported = client.get(f"/api/v1/workflow-definitions/{workflow_id}/export?version={published['version']}&format=json")
        assert exported.status_code == 200
        assert exported.json()["workflow"]["workflow"]["description"] == "original"
        assert exported.json()["workflow"]["workflow"]["steps"][0]["with"]["command"] == "show version"

        restored = client.post(f"/api/v1/workflow-definitions/{workflow_id}/versions/{published['version']}/restore")
        assert restored.status_code == 200
        assert restored.json()["workflow"]["version"] == "draft"
        assert restored.json()["workflow"]["description"] == "original"
        assert client.get(f"/api/v1/workflow-definitions/{workflow_id}").json()["workflow"]["name"] == "Restore version"
        assert client.get(f"/api/v1/workflow-definitions/{workflow_id}/export?version={published['version']}").json()["workflow"]["workflow"]["description"] == "original"


def test_workflow_action_catalog_is_exposed_for_studio_clients() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        response = client.get("/api/v1/workflow-definitions/actions")
        assert response.status_code == 200
        actions = {item["id"]: item for item in response.json()["actions"]}
        assert {"device.command", "file.upload", "utility.wait"}.issubset(actions)
        assert actions["file.upload"]["risk"] == "high"
        assert "required" in actions["device.command"]["input_schema"]


def test_workflow_action_catalog_exposes_referenceable_outputs() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        response = client.get("/api/v1/workflow-definitions/actions")

    assert response.status_code == 200
    actions = {item["id"]: item for item in response.json()["actions"]}
    expected_fields = {
        "device.command": {
            "output",
            "stdout",
            "stderr",
            "exitCode",
            "exit_code",
            "status",
            "duration",
            "data",
            "error",
        },
        "device.info": {"device_id", "name", "address", "model", "output", "status", "software_version"},
        "device.connect": {"session_id", "device_id", "status", "cli_status"},
        "device.ssh": {"session_id", "device_id", "status", "cli_status"},
        "device.telnet": {"session_id", "device_id", "status", "cli_status"},
        "terminal.wait": {"output", "status", "matched", "sequence", "session_id"},
        "variable.set": {"name", "value", "matched", "source"},
        "expression.evaluate": {"value", "status"},
        "loop.for_each": {"items", "results", "count"},
        "loop.until": {"status", "matched", "iterations", "result", "results"},
        "result.save": {"key", "value", "status"},
    }
    for action_id, fields in expected_fields.items():
        schema = actions[action_id]["output_schema"]
        assert schema["type"] == "object"
        assert fields <= set(schema["properties"])


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


def test_workflow_run_exposes_device_reference_context() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Device context",
                "nodes": [
                    {
                        "id": "value",
                        "action_id": "variable.set",
                        "config": {"name": "device_name", "value": "${device.name}"},
                    }
                ],
            },
        )
        workflow_id = created.json()["workflow"]["id"]

        response = client.post(
            f"/api/v1/workflow-definitions/{workflow_id}/run",
            json={"device_id": "sim-1", "protocol": "simulated", "draft": True},
        )

        assert response.status_code == 200
        context = response.json()["task"]["context"]
        assert context["device"]["id"] == "sim-1"
        if "version" in context["device"]:
            assert context["device"]["software_version"] == context["device"]["version"]
        assert "password" not in context["device"]
        assert "ssh_password" not in context["device"]


def test_workflow_batch_runs_keep_device_context_per_target() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Batch device context",
                "nodes": [
                    {
                        "id": "value",
                        "action_id": "variable.set",
                        "config": {"name": "device_id", "value": "${device.id}"},
                    }
                ],
            },
        )
        workflow_id = created.json()["workflow"]["id"]

        response = client.post(
            f"/api/v1/workflow-definitions/{workflow_id}/run",
            json={
                "device_ids": ["sim-1", "sim-2"],
                "protocol": "simulated",
                "draft": True,
            },
        )

        assert response.status_code == 200
        assert [task["context"]["device"]["id"] for task in response.json()["tasks"]] == ["sim-1", "sim-2"]


def test_workflow_run_rejects_invalid_definition_before_creating_task() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Invalid draft",
                "nodes": [{"id": "command", "action_id": "device.command", "config": {}}],
                "edges": [],
            },
        )
        workflow_id = created.json()["workflow"]["id"]

        response = client.post(
            f"/api/v1/workflow-definitions/{workflow_id}/run",
            json={"device_id": "sim-1", "protocol": "simulated", "draft": True, "dry_run": True},
        )

        assert response.status_code == 400
        body = response.json()
        assert body["error"]["details"]["errors"][0]["code"] == "missing_required_config"
        assert body["error"]["details"]["errors"][0]["node_id"] == "command"


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


def test_published_workflow_directory_marks_loop_risk_from_input_mapping() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Mapped risk",
                "nodes": [
                    {
                        "id": "loop",
                        "action_id": "loop.for_each",
                        "config": {"items": [1]},
                        "input_mapping": {"action_id": "device.reboot", "action_inputs": {}},
                    }
                ],
            },
        )
        workflow_id = created.json()["workflow"]["id"]
        published = client.post(f"/api/v1/workflow-definitions/{workflow_id}/publish")
        assert published.status_code == 200

        directory = client.get("/api/v1/workflow-definitions/published")

    assert directory.status_code == 200
    item = next(item for item in directory.json()["workflows"] if item["id"] == workflow_id)
    assert item["requires_confirmation"] is True


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


def test_workflow_definition_compiles_variable_extraction_unchanged() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="variable-extraction",
        nodes=(
            WorkflowNode("command", "device.command", {"command": "dir flash:/"}),
            WorkflowNode(
                "variable",
                "variable.set",
                {
                    "name": "cc_path",
                    "value": "${command.output}",
                    "extract": {"pattern": r"flash:/\S+", "group": 0},
                },
            ),
        ),
        edges=(WorkflowEdge("command", "variable"),),
    )
    plan = _compile_task_plan(version, "router-1")
    assert plan.nodes[1].workflow_id == "variable.set"
    assert plan.nodes[1].input_mapping["extract"] == {"pattern": r"flash:/\S+", "group": 0}


def test_workflow_definition_normalizes_file_paths_from_input_mapping() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="mapped-transfer",
        nodes=(
            WorkflowNode(
                "upload",
                "file.upload",
                {},
                {"source": "${package_path}", "destination": "flash:/target.cc"},
            ),
        ),
    )

    plan = _compile_task_plan(version, "router-1")

    assert plan.nodes[0].input_mapping["source_path"] == "${package_path}"
    assert plan.nodes[0].input_mapping["destination_path"] == "flash:/target.cc"
    assert "source" not in plan.nodes[0].input_mapping
    assert "destination" not in plan.nodes[0].input_mapping


def test_workflow_definition_execution_order_follows_inserted_dependencies() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="inserted-variable",
        nodes=(
            WorkflowNode("command_2", "device.command", {"command": "set current-configuration"}),
            WorkflowNode("variable", "variable.set", {"name": "cc", "value": "${command_1.output}"}),
            WorkflowNode("command_1", "device.command", {"command": "display cc"}),
        ),
        edges=(
            WorkflowEdge("command_1", "variable"),
            WorkflowEdge("variable", "command_2"),
        ),
    )

    plan = _compile_task_plan(version, "router-1")

    assert [node.id for node in plan._ordered_nodes()] == ["command_1", "variable", "command_2"]


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


def test_workflow_definition_preserves_custom_endpoint_for_connection_node() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="custom-endpoint",
        nodes=(WorkflowNode("ssh", "device.ssh", {"host": "10.20.30.40", "port": 2222}),),
    )

    plan = _compile_task_plan(version, "router-1")

    assert plan.nodes[0].input_mapping["host"] == "10.20.30.40"
    assert plan.nodes[0].input_mapping["port"] == 2222


def test_workflow_definition_keeps_protocol_for_connection_node_without_timeout() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="connection-protocol",
        nodes=(WorkflowNode("telnet", "device.telnet", {"host": "10.20.30.40"}),),
    )

    plan = _compile_task_plan(version, "router-1")

    assert plan.nodes[0].input_mapping["recovery_protocol"] == "telnet"


def test_workflow_definition_keeps_protocol_for_nested_connection_node_without_timeout() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="nested-connection-protocol",
        nodes=(WorkflowNode(
            "loop",
            "loop.for_each",
            {
                "items": ["router-1"],
                "action_id": "device.telnet",
                "action_inputs": {"host": "10.20.30.40"},
            },
        ),),
    )

    plan = _compile_task_plan(version, "router-1")

    assert plan.nodes[0].input_mapping["action_inputs"]["recovery_protocol"] == "telnet"


def test_workflow_definition_normalizes_nested_download_action_inputs() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="nested-download",
        nodes=(
            WorkflowNode(
                "loop",
                "loop.for_each",
                {
                    "items": ["a"],
                    "action_id": "file.download",
                    "action_inputs": {
                        "source": "flash:/a.cc",
                        "destination": "a.cc",
                    },
                },
            ),
        ),
    )

    plan = _compile_task_plan(version, "router-1")

    assert plan.nodes[0].input_mapping["action_inputs"] == {
        "direction": "download",
        "source_path": "flash:/a.cc",
        "destination_path": "a.cc",
    }


def _minimal_workflow_config(action_id: str) -> dict[str, object]:
    return {
        "device.select": {"device_id": "router-1"},
        "device.connect": {},
        "device.ssh": {"host": "router-1"},
        "device.telnet": {"host": "router-1"},
            "device.info": {},
            "device.command": {"command": "display version"},
            "script.run": {"script": "print('ok')"},
            "file.upload": {"source": "a.cc", "destination": "flash:/a.cc"},
        "file.download": {"source": "flash:/a.cc", "destination": "a.cc"},
        "device.reboot": {},
        "utility.wait": {"seconds": 0},
        "terminal.wait": {"pattern": "Huawei", "send_enter": False, "timeout_seconds": 1},
        "utility.confirm": {"prompt": "确认继续？"},
        "result.save": {"key": "result"},
        "variable.set": {"name": "value", "value": "ok"},
        "expression.evaluate": {"expression": "1 + 1"},
        "loop.for_each": {"items": ["a"], "action_id": "result.save", "action_inputs": {"key": "${item}"}},
        "loop.until": {"action_id": "result.save", "condition": "result.status == 'saved'", "max_iterations": 1, "interval_seconds": 0},
    }[action_id]


def test_workflow_definition_compiles_every_executable_catalog_action() -> None:
    compile_time_only = {"utility.condition", "workflow.call"}

    for action in build_action_catalog().list():
        if action.id in compile_time_only:
            continue
        version = WorkflowVersion(
            workflow_id=f"wf-{action.id}",
            version=1,
            name=action.name,
            nodes=(WorkflowNode("node", action.id, _minimal_workflow_config(action.id)),),
        )

        plan = _compile_task_plan(version, "router-1")

        assert len(plan.nodes) == 1
        assert plan.nodes[0].id == "node"


def test_workflow_definition_rejects_device_connect_target_mismatch() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="wrong-target",
        nodes=(WorkflowNode("connect", "device.connect", {"device_id": "router-2"}),),
    )

    try:
        _compile_task_plan(version, "router-1")
    except UnsupportedOperationError as exc:
        assert "selects device router-2" in str(exc)
    else:
        raise AssertionError("device.connect accepted a different target device")


def test_workflow_definition_rejects_non_executable_loop_children_at_compile_time() -> None:
    for child_action in ("loop.for_each", "utility.condition", "utility.confirm", "workflow.call"):
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


def test_workflow_templates_cover_builtin_and_user_lifecycle() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        listed = client.get("/api/v1/workflow-definitions/templates")
        assert listed.status_code == 200
        assert {item["id"] for item in listed.json()["templates"]} >= {
            "builtin_device_inspection",
            "builtin_command_result",
        }

        builtin = client.post(
            "/api/v1/workflow-definitions/templates/builtin_command_result/instantiate",
            json={"name": "Inspect from template"},
        )
        assert builtin.status_code == 200
        assert builtin.json()["workflow"]["name"] == "Inspect from template"
        assert [item["name"] for item in builtin.json()["workflow"]["outputs"]] == [
            "stdout",
            "exit_code",
        ]

        source = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Reusable source",
                "nodes": [
                    {"id": "value", "action_id": "variable.set", "config": {"name": "answer", "value": 42}},
                ],
                "outputs": [{"name": "answer", "value": "${value.value}", "type": "integer"}],
            },
        ).json()["workflow"]
        created = client.post(
            "/api/v1/workflow-definitions/templates",
            json={"name": "Answer template", "workflow_id": source["id"]},
        )
        assert created.status_code == 200
        template = created.json()["template"]
        assert template["built_in"] is False
        assert template["workflow"]["outputs"][0]["name"] == "answer"

        instantiated = client.post(
            f"/api/v1/workflow-definitions/templates/{template['id']}/instantiate",
            json={"name": "Answer copy"},
        )
        assert instantiated.status_code == 200
        assert instantiated.json()["workflow"]["id"] != source["id"]
        assert instantiated.json()["workflow"]["name"] == "Answer copy"
        assert instantiated.json()["workflow"]["outputs"] == template["workflow"]["outputs"]

        assert client.delete(f"/api/v1/workflow-definitions/templates/{template['id']}").status_code == 204
        assert template["id"] not in {
            item["id"] for item in client.get("/api/v1/workflow-definitions/templates").json()["templates"]
        }
        assert client.delete(
            "/api/v1/workflow-definitions/templates/builtin_command_result"
        ).status_code == 400


def test_custom_actions_support_catalog_nodes_and_published_workflows() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        wait = client.post(
            "/api/v1/workflow-definitions/custom-actions",
            json={
                "name": "Short wait",
                "action_id": "utility.wait",
                "config": {"seconds": 0.25},
            },
        )
        assert wait.status_code == 200
        assert wait.json()["action"]["action_id"] == "utility.wait"
        assert "seconds" in wait.json()["action"]["output_schema"]["properties"]

        child = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Published action",
                "nodes": [
                    {"id": "value", "action_id": "variable.set", "config": {"name": "answer", "value": 42}},
                ],
                "outputs": [{"name": "answer", "value": "${value.value}", "type": "integer"}],
            },
        ).json()["workflow"]
        published = client.post(
            f"/api/v1/workflow-definitions/{child['id']}/publish"
        ).json()["workflow"]
        action_response = client.post(
            "/api/v1/workflow-definitions/custom-actions",
            json={
                "name": "Answer action",
                "workflow_id": child["id"],
                "version": published["version"],
            },
        )
        assert action_response.status_code == 200
        action = action_response.json()["action"]
        assert action["action_id"] == "workflow.call"
        assert action["config"] == {
            "workflow_id": child["id"],
            "version": published["version"],
            "inputs": {},
        }
        assert action["output_schema"]["properties"]["answer"] == {"type": "integer"}
        versions = client.get(
            f"/api/v1/workflow-definitions/{child['id']}/versions"
        ).json()["versions"]
        assert versions[0]["referenced"] is True
        assert client.delete(f"/api/v1/workflow-definitions/custom-actions/{wait.json()['action']['id']}").status_code == 204
        assert client.delete(f"/api/v1/workflow-definitions/custom-actions/{action['id']}").status_code == 204


def test_subworkflow_api_expands_inputs_outputs_and_protects_versions() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        child = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Echo child",
                "inputs": [{"name": "message", "type": "string", "required": True}],
                "nodes": [
                    {
                        "id": "capture",
                        "action_id": "variable.set",
                        "config": {"name": "captured", "value": "${inputs.message}"},
                    },
                ],
                "outputs": [{"name": "echo", "value": "${capture.value}", "type": "string"}],
            },
        ).json()["workflow"]
        child_version = client.post(
            f"/api/v1/workflow-definitions/{child['id']}/publish"
        ).json()["workflow"]
        assert child_version["outputs"][0]["name"] == "echo"

        parent = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Echo parent",
                "inputs": [{"name": "message", "type": "string", "required": True}],
                "nodes": [
                    {
                        "id": "call",
                        "action_id": "workflow.call",
                        "config": {
                            "workflow_id": child["id"],
                            "version": child_version["version"],
                            "inputs": {"message": "${inputs.message}"},
                        },
                    },
                    {
                        "id": "save",
                        "action_id": "result.save",
                        "config": {"key": "echo", "value": "${call.echo}"},
                    },
                ],
                "edges": [{"source": "call", "target": "save"}],
            },
        ).json()["workflow"]
        validation = client.post(f"/api/v1/workflow-definitions/{parent['id']}/validate")
        assert validation.status_code == 200
        assert validation.json()["valid"] is True

        preview = client.post(
            f"/api/v1/workflow-definitions/{parent['id']}/run",
            json={
                "device_id": "sim-1",
                "draft": True,
                "dry_run": True,
                "inputs": {"message": "hello"},
            },
        )
        assert preview.status_code == 200
        steps = preview.json()["preview"]["steps"]
        assert [(step["id"], step["depends_on"]) for step in steps] == [
            ("call__capture", []),
            ("call", ["call__capture"]),
            ("save", ["call"]),
        ]

        parent_version = client.post(
            f"/api/v1/workflow-definitions/{parent['id']}/publish"
        ).json()["workflow"]
        child_versions = client.get(
            f"/api/v1/workflow-definitions/{child['id']}/versions"
        ).json()["versions"]
        assert child_versions[0]["referenced"] is True

        started = client.post(
            f"/api/v1/workflow-definitions/{parent['id']}/run",
            json={
                "device_id": "sim-1",
                "version": parent_version["version"],
                "inputs": {"message": "hello"},
            },
        )
        assert started.status_code == 200
        parent_versions = client.get(
            f"/api/v1/workflow-definitions/{parent['id']}/versions"
        ).json()["versions"]
        assert parent_versions[0]["referenced"] is True


def test_subworkflow_high_risk_action_requires_parent_confirmation() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        child = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Risky child",
                "nodes": [{"id": "reboot", "action_id": "device.reboot", "config": {}}],
            },
        ).json()["workflow"]
        child_version = client.post(
            f"/api/v1/workflow-definitions/{child['id']}/publish"
        ).json()["workflow"]
        parent = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Risky parent",
                "nodes": [
                    {
                        "id": "call",
                        "action_id": "workflow.call",
                        "config": {
                            "workflow_id": child["id"],
                            "version": child_version["version"],
                        },
                    },
                ],
            },
        ).json()["workflow"]

        response = client.post(
            f"/api/v1/workflow-definitions/{parent['id']}/run",
            json={"device_id": "sim-1", "draft": True},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "high-risk workflow run requires confirmation"


def test_workflow_outputs_round_trip_through_publish_export_and_import() -> None:
    with TestClient(create_app(token="", repository=SampleDeviceRepository())) as client:
        created = client.post(
            "/api/v1/workflow-definitions",
            json={
                "name": "Output round trip",
                "nodes": [
                    {"id": "value", "action_id": "variable.set", "config": {"name": "answer", "value": 42}},
                ],
                "outputs": [
                    {
                        "name": "answer",
                        "value": "${value.value}",
                        "type": "integer",
                        "description": "Computed answer",
                    },
                ],
            },
        ).json()["workflow"]
        published = client.post(
            f"/api/v1/workflow-definitions/{created['id']}/publish"
        ).json()["workflow"]
        assert published["outputs"] == created["outputs"]

        exported = client.get(
            f"/api/v1/workflow-definitions/{created['id']}/export?version={published['version']}&format=json"
        )
        imported = client.post(
            "/api/v1/workflow-definitions/import",
            json={"filename": "roundtrip.workflow.json", "content": exported.json()["content"]},
        )

        assert imported.status_code == 200
        assert imported.json()["workflow"]["outputs"] == created["outputs"]
