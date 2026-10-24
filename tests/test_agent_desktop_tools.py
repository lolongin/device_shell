from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from device_tui.application.ai.agent import AgentContext
from device_tui.application.ai.llm import ToolCall
from device_tui.application.secrets import MemorySecretStore
from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub


class AgentHarness:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.ctx = client.app.state.context
        self.conversation = AgentContext("desktop-tools")
        self.ctx.ai_conversations[self.conversation.conversation_id] = self.conversation
        self.sequence = 0

    def call(self, name: str, arguments: dict | None = None) -> dict:
        self.sequence += 1
        return self.client.portal.call(self.ctx.ai_runtime.execute, ToolCall(str(self.sequence), name, arguments or {}), self.conversation)

    def approve(self, result: dict) -> dict:
        assert result.get("status") == "needs_approval", result
        response = self.client.post(f"/api/v1/ai/agent/conversations/desktop-tools/approvals/{result['approval']['id']}/approve")
        assert response.status_code == 200, response.text
        approval = response.json()["approval"]
        assert approval["status"] == "completed", approval
        return approval["result"]

    def run(self, name: str, arguments: dict | None = None) -> dict:
        result = self.call(name, arguments)
        return self.approve(result) if result.get("status") == "needs_approval" else result


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVICE_TUI_DATA_DIR", str(tmp_path / "state"))
    transfer_root = tmp_path / "share"
    transfer_root.mkdir()
    with TestClient(create_app(token="", repository=SampleDeviceRepository(), session_hub=SessionHub(), secret_store=MemorySecretStore(), transfer_root=transfer_root)) as client:
        yield AgentHarness(client)


def test_capability_catalog_covers_management_and_exposes_unavailable_ui(agent) -> None:
    catalog = agent.call("app_capabilities")["data"]
    assert len(catalog["tools"]) == 128
    assert len(set(catalog["tools"])) == 128
    assert {"source_plugin_configure", "source_import_commit", "profile_create", "transfer_managed_start", "package_build_start", "settings_session_logs_update", "command_broadcast", "workflow_export", "workflow_template_create", "terminal_parallel"} <= set(catalog["tools"])
    assert all(item["status"] == "unavailable" and item["reason"] for item in catalog["unavailable"])
    assert "ui.appearance_and_window" in {item["capability"] for item in catalog["unavailable"]}
    response = agent.client.get("/api/v1/ai/agent/capabilities")
    assert response.status_code == 200, response.text
    api = response.json()
    schemas = {item["function"]["name"]: item["function"]["parameters"] for item in api["tools"]}
    assert set(schemas) == set(catalog["tools"])
    assert all(schema["type"] == "object" for schema in schemas.values())
    assert schemas["transfer_files_search"]["properties"]["limit"]["minimum"] == 1
    assert schemas["transfer_files_search"]["properties"]["limit"]["default"] == 200
    assert api["unavailable"] == catalog["unavailable"]
    assert "tool_execute" not in catalog["tools"]
    assert "workflow_plan_approve" not in catalog["tools"]


@pytest.mark.parametrize("name,arguments", [
    ("profile_create", {"request": {"profile_type": "server", "name": "bad", "ssh_password": "sensitive-value"}}),
    ("profile_create", {"request": {"profile_type": "server", "name": "bad", "ssh": {"password": "sensitive-value"}}}),
    ("source_plugin_configure", {"source_id": "sample", "request": {"secrets": {"access": "sensitive-value"}}}),
    ("transfer_settings_update", {"request": {"root": "D:/data", "username": "operator", "password": "sensitive-value"}}),
    ("auth_login_saved", {"username": "operator", "cid": "1", "password": "sensitive-value"}),
    ("package_build_start", {"request": {"mrid": "x"}, "method": "sensitive-value"}),
])
def test_secret_and_dispatch_arguments_are_rejected_without_echo(agent, name, arguments) -> None:
    result = agent.call(name, arguments)
    assert result["ok"] is False
    assert result["error_code"] == "invalid_tool_arguments"
    assert "sensitive-value" not in json.dumps(result)
    assert "sensitive-value" not in json.dumps(agent.ctx.ai_runtime.state("desktop-tools"))
    assert "sensitive-value" not in json.dumps(agent.ctx.ai_service.audit_entries())


def test_profile_edits_preserve_vault_credentials_and_require_approval(agent) -> None:
    request = {"profile_type": "server", "name": "Agent connection", "ssh": {"host": "192.0.2.20", "port": 22, "username": "operator"}}
    pending = agent.call("profile_create", {"request": request})
    assert agent.ctx.desktop.profiles.list_profiles() == []
    created = agent.approve(pending)["data"]
    profile_id = created["id"]
    agent.ctx.desktop.profiles.set_password(profile_id, "ssh", "vault-only-value")
    updated = agent.run("profile_update", {"profile_id": profile_id, "request": {**request, "name": "Renamed connection"}})
    assert updated["data"]["name"] == "Renamed connection"
    assert agent.ctx.desktop.profiles.password(profile_id, "ssh") == "vault-only-value"
    assert "vault-only-value" not in json.dumps([updated, agent.ctx.ai_runtime.state("desktop-tools"), agent.ctx.ai_service.audit_entries()])
    agent.run("profile_group_create", {"request": {"name": "Agent group"}})
    assert "Agent group" in agent.ctx.desktop.profiles.list_groups()
    agent.run("profile_credential_delete", {"profile_id": profile_id, "protocol": "ssh"})
    assert agent.ctx.desktop.profiles.password(profile_id, "ssh") == ""
    agent.run("profile_delete", {"profile_id": profile_id})
    assert agent.ctx.desktop.profiles.list_profiles() == []


def test_device_import_preview_commit_and_source_switch_use_existing_policy(agent, tmp_path) -> None:
    path = tmp_path / "inventory.csv"
    path.write_text("ID,名称,IP,密码\nA,Imported,192.0.2.4,never-return-this\n", encoding="utf-8")
    pending = agent.call("source_import_preview", {"path": str(path)})
    assert not agent.ctx.import_previews
    preview = agent.approve(pending)["data"]
    assert preview["valid_rows"] == 1
    assert preview["preview_id"] != "***"
    assert "never-return-this" not in json.dumps(preview)
    pending = agent.call("source_import_commit", {"preview_id": preview["preview_id"]})
    assert agent.ctx.repository.active_source == "sample"
    committed = agent.approve(pending)["data"]
    assert committed["imported_count"] == 1
    assert agent.ctx.repository.active_source == "imported"
    agent.run("source_switch", {"source": "sample"})
    assert agent.ctx.repository.active_source == "sample"


def test_command_workspace_edits_are_approved_and_audited(agent) -> None:
    before = agent.call("command_workspace")["data"]
    pending = agent.call("command_group_save", {"name": "Agent commands", "content": "display version"})
    assert agent.call("command_workspace")["data"] == before
    group = agent.approve(pending)["data"]["group"]
    assert group["name"] == "Agent commands"
    agent.run("command_preferences", {"current_group_id": group["id"], "enter_sends": False})
    agent.run("command_group_delete", {"group_id": group["id"]})
    entries = agent.ctx.ai_service.audit_entries()
    assert any(item["tool"] == "agent.command_group_save" and "Agent commands" in item["command"] for item in entries)


def test_transfer_download_and_package_build_delegate_once_after_approval(agent, monkeypatch) -> None:
    opened = agent.call("session_open", {"device_id": "MOCK-LAB-000", "protocol": "simulated"})
    session_id = opened["data"]["session"]["session_id"]
    transfers, builds, cancellations = [], [], []

    async def start_transfer(**kwargs):
        transfers.append(kwargs)
        operation = agent.ctx.desktop.operations.create(kind="file_transfer", direction=kwargs["direction"], device_id=kwargs["device_id"], session_id=kwargs["session_id"], stage="queued", message="queued")
        return SimpleNamespace(id="task-run", plan_id="transfer-plan"), operation.id

    def start_build(request, *, builder_id):
        builds.append((request, builder_id))
        operation = agent.ctx.desktop.operations.create(kind="package_build", direction="", device_id="", session_id="", stage="queued", message="queued")
        agent.ctx.desktop.operations.register_canceller(operation.id, lambda: cancellations.append(operation.id))
        return operation

    monkeypatch.setattr(agent.ctx.desktop.task_service, "start_file_transfer", start_transfer)
    monkeypatch.setattr(agent.ctx.desktop.package_builds, "start", start_build)
    pending = agent.call("transfer_managed_start", {"request": {"direction": "download", "device_id": "MOCK-LAB-000", "session_id": session_id, "protocol": "simulated", "source_path": "flash:/version.txt", "destination_path": "version.txt"}})
    assert transfers == []
    downloaded = agent.approve(pending)
    assert agent.approve(pending) == downloaded
    assert len(transfers) == 1 and transfers[0]["direction"] == "download"
    pending = agent.call("package_build_start", {"request": {"mrid": "MR-123", "output_name": "agent.cc"}})
    assert builds == []
    built = agent.approve(pending)
    assert len(builds) == 1 and builds[0][0].mrid == "MR-123"
    operation_id = built["data"]["operation"]["id"]
    assert agent.call("operation_get", {"operation_id": operation_id})["ok"]
    assert agent.run("operation_cancel", {"operation_id": operation_id})["data"]["operation"]["status"] == "cancelled"
    assert cancellations == [operation_id]


def test_workflow_export_import_templates_versions_and_deletion(agent) -> None:
    original = agent.call("workflow_definition_create", {"workflow": {"name": "Portable", "nodes": [{"id": "wait", "action_id": "utility.wait", "config": {"seconds": 0}}], "edges": []}})["data"]["workflow"]
    workflow_id = original["id"]
    exported = agent.call("workflow_export", {"workflow_id": workflow_id, "format": "json"})["data"]
    payload = {"filename": exported["filename"], "content": exported["content"]}
    assert agent.call("workflow_import_preview", {"payload": payload})["data"]["valid"]
    imported = agent.run("workflow_import", {"payload": payload})["data"]
    assert imported["imported"]
    template = agent.run("workflow_template_create", {"payload": {"workflow_id": workflow_id, "name": "Agent template"}})["data"]["template"]
    instantiated = agent.run("workflow_template_instantiate", {"template_id": template["id"], "payload": {"name": "From template"}})["data"]["workflow"]
    assert instantiated["name"] == "From template"
    agent.run("workflow_template_delete", {"template_id": template["id"]})
    assert template["id"] not in {item["id"] for item in agent.call("workflow_template_list")["data"]["templates"]}
    published = agent.run("workflow_definition_publish", {"workflow_id": workflow_id})["data"]
    version = published["workflow"]["version"]
    assert agent.call("workflow_version_list", {"workflow_id": workflow_id})["data"]["versions"]
    agent.run("workflow_version_restore", {"workflow_id": workflow_id, "version": version})
    agent.run("workflow_version_delete", {"workflow_id": workflow_id, "version": version})
    agent.run("workflow_definition_delete", {"workflow_id": workflow_id})
    assert not agent.call("workflow_definition_get", {"workflow_id": workflow_id})["ok"]


def test_parallel_terminal_execution_is_gated_and_retains_results(agent) -> None:
    pending = agent.call("terminal_parallel", {"requests": [{"device_id": "MOCK-LAB-000", "commands": ["display version"]}], "max_concurrency": 2})
    result = agent.approve(pending)
    assert result["data"]["completed_count"] == 1
    assert "SimOS V1.0" in str(result)


def test_custom_action_infers_workflow_call_from_published_source(agent) -> None:
    draft = agent.call("workflow_definition_create", {"workflow": {"name": "Reusable", "nodes": [{"id": "wait", "action_id": "utility.wait", "config": {"seconds": 0}}], "edges": []}})["data"]["workflow"]
    published = agent.run("workflow_definition_publish", {"workflow_id": draft["id"]})["data"]["workflow"]
    action = agent.run("workflow_custom_create", {"payload": {"name": "Reusable action", "workflow_id": draft["id"], "version": published["version"]}})["data"]["action"]
    assert action["action_id"] == "workflow.call"
    assert action["config"]["workflow_id"] == draft["id"]
    agent.run("workflow_custom_delete", {"action_id": action["id"]})
    assert action["id"] not in {item["id"] for item in agent.call("workflow_custom_list")["data"]["actions"]}


def test_desktop_query_constraints_are_enforced_before_invocation(agent) -> None:
    for name, arguments in [("operation_list", {}), ("transfer_files_search", {}), ("command_suggestions", {"query": "display"})]:
        result = agent.call(name, arguments)
        assert result["ok"], result
        assert json.loads(json.dumps(result)) == result
    result = agent.call("transfer_files_search", {"limit": -1})
    assert result["error_code"] == "invalid_tool_arguments"
    result = agent.call("settings_session_logs_update", {"request": {"directory": "D:/logs", "rotate_size_mb": 0}})
    assert result["error_code"] == "invalid_tool_arguments"
