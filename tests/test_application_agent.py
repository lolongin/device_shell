from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from device_tui.application.ai.agent import AgentContext, DeviceAgent
from device_tui.application.ai.agent.runtime import ApplicationAgentExecutor
from device_tui.application.ai.llm import LlmClientError, LlmResponse, OpenAiCompatibleClient, ToolCall
from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.agent_tools import LocalAgentTools
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub


class Facade:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.revision = 1

    async def invoke(self, name: str, params: dict):
        self.calls.append((name, params))
        return 200, {"ok": True, "data": {"revision": self.revision, "valid": True}}


def test_registry_uses_shared_schemas_and_argument_translation() -> None:
    facade = Facade()
    tools = LocalAgentTools(facade)
    names = {item["function"]["name"] for item in tools.definitions}
    assert {"device_list", "task_wait", "workflow_definition_run", "decision_apply"} <= names
    assert not {"tool_execute", "workflow_plan_approve", "profile_save", "source_plugin_update"} & names
    with pytest.raises(ValueError):
        tools.validate("terminal_execute", {"command": "show version", "approved": True})
    with pytest.raises(ValueError):
        tools.validate("task_wait", {"task_ids": "not-a-list"})
    asyncio.run(tools.invoke("session_open", {"device_id": "d", "protocol": "simulated"}))
    assert facade.calls == [("session.manage", {"action": "open", "device_id": "d", "protocol": "simulated"})]
    asyncio.run(tools.invoke("decision_apply", {"task_id": "t", "action": {"name": "retry"}}, approved=True))
    assert facade.calls[-1][1]["actor_type"] == "agent"


@pytest.mark.parametrize("name,arguments", [
    ("terminal_execute", {"command": "reboot", "device_id": "d"}),
    ("terminal_execute", {"command": "show version; reboot", "device_id": "d"}),
    ("terminal_batch", {"commands": ["show version", "save"], "device_id": "d"}),
    ("device_action", {"device_id": "d", "action": "power_off", "confirm": True}),
    ("workflow_definition_run", {"workflow_id": "w", "device_id": "d", "confirmed_risks": True}),
    ("transfer_start", {"device_id": "d", "source_path": "a", "destination_path": "b"}),
    ("task_resume", {"task_id": "t"}),
])
def test_mutations_require_user_approval_even_with_model_confirmation(name, arguments) -> None:
    async def run():
        facade = Facade()
        executor = ApplicationAgentExecutor(LocalAgentTools(facade))
        context = AgentContext("c")
        result = await executor.execute(ToolCall("call", name, arguments), context)
        assert result["status"] == "needs_approval"
        assert not any(tool == name.replace("_", ".") and not params.get("dry_run") for tool, params in facade.calls)
        approval_id = result["approval"]["id"]
        first, duplicate = await asyncio.gather(executor.resolve(approval_id, context, approve=True), executor.resolve(approval_id, context, approve=True))
        assert first["status"] == duplicate["status"] == "completed"
        assert first == duplicate
        executed = [entry for entry in executor.state("c")["events"] if entry["type"] == "agent.approval.resolved"]
        assert len(executed) == 1
    asyncio.run(run())


def test_rejection_expiry_and_changed_workflow_never_execute() -> None:
    async def run():
        facade = Facade()
        executor = ApplicationAgentExecutor(LocalAgentTools(facade))
        context = AgentContext("c")
        call = ToolCall("one", "workflow_definition_publish", {"workflow_id": "w"})
        result = await executor.execute(call, context)
        with pytest.raises(ValueError):
            await executor.resolve(result["approval"]["id"], AgentContext("other"), approve=True)
        facade.revision += 1
        assert (await executor.resolve(result["approval"]["id"], context, approve=True))["status"] == "stale"
        result = await executor.execute(ToolCall("two", call.name, call.arguments), context)
        assert (await executor.resolve(result["approval"]["id"], context, approve=False))["status"] == "rejected"
        executor.approval_ttl = -1
        result = await executor.execute(ToolCall("three", call.name, call.arguments), context)
        assert (await executor.resolve(result["approval"]["id"], context, approve=True))["status"] == "expired"
        assert not any(name == "workflow.definition.publish" for name, _ in facade.calls)
    asyncio.run(run())


def test_repeated_calls_are_idempotent_and_conflicting_ids_are_rejected() -> None:
    async def run():
        facade = Facade()
        executor = ApplicationAgentExecutor(LocalAgentTools(facade))
        context = AgentContext("c")
        call = ToolCall("call", "terminal_execute", {"command": "show version"})
        assert (await executor.execute(call, context))["ok"]
        assert (await executor.execute(call, context))["ok"]
        conflict = await executor.execute(ToolCall("call", call.name, {"command": "reboot"}), context)
        assert conflict["error_code"] == "tool_call_conflict"
        assert len(facade.calls) == 1
    asyncio.run(run())


def test_timeout_is_observable_and_not_retried() -> None:
    class SlowFacade(Facade):
        async def invoke(self, name, params):
            self.calls.append((name, params))
            await asyncio.sleep(1)
    async def run():
        facade = SlowFacade()
        executor = ApplicationAgentExecutor(LocalAgentTools(facade), timeout_seconds=.005)
        call, context = ToolCall("call", "device_list", {}), AgentContext("c")
        result = await executor.execute(call, context)
        assert result["status"] == "outcome_unknown"
        assert await executor.execute(call, context) == result
        assert len(facade.calls) == 1
    asyncio.run(run())


def test_agent_stops_at_approval_and_redacts_all_observable_channels() -> None:
    class Model:
        async def chat(self, **kwargs):
            assert "unsafe-password" not in json.dumps(kwargs)
            return LlmResponse(tool_calls=[ToolCall("a", "terminal_execute", {"command": "reboot"}), ToolCall("b", "device_list", {})])
    async def run():
        facade = Facade()
        executor = ApplicationAgentExecutor(LocalAgentTools(facade))
        context = AgentContext("c")
        result = await DeviceAgent(Model(), executor, event_callback=executor.record).run("password=unsafe-password", context)
        assert "审批" in result
        assert not facade.calls
        state = executor.state("c")
        assert all(event["data"]["conversation_id"] == "c" for event in state["events"])
        assert "unsafe-password" not in json.dumps([state, context.messages])
    asyncio.run(run())


@pytest.mark.parametrize("arguments", ["[]", [], 0, False])
def test_llm_rejects_non_object_arguments(arguments) -> None:
    with pytest.raises(LlmClientError):
        OpenAiCompatibleClient._parse_response({"choices": [{"message": {"tool_calls": [{"id": "a", "function": {"name": "device_list", "arguments": arguments}}]}}]})


def test_llm_rejects_duplicate_call_ids() -> None:
    call = {"id": "a", "function": {"name": "device_list", "arguments": "{}"}}
    with pytest.raises(LlmClientError):
        OpenAiCompatibleClient._parse_response({"choices": [{"message": {"tool_calls": [call, call]}}]})


def test_chat_workflow_draft_preview_approval_publish_run_and_observe() -> None:
    headers = {"Authorization": "Bearer agent-test"}
    class WorkflowModel:
        def __init__(self):
            self.step = 0
            self.workflow_id = ""
            self.task_id = ""

        async def chat(self, *, messages, tools):
            assert any(tool["function"]["name"] == "workflow_definition_create" for tool in tools)
            previous = next((json.loads(item["content"]) for item in reversed(messages) if item["role"] == "tool"), {})
            step = self.step
            self.step += 1
            if step == 0:
                return LlmResponse(tool_calls=[
                    ToolCall("discover", "device_list", {"limit": 1}),
                    ToolCall("connect", "session_open", {"device_id": "MOCK-LAB-000", "protocol": "simulated"}),
                ])
            elif step == 1:
                name, args = "workflow_script_create", {"name": "Agent version", "script": "def main(device):\n    return device.run('display version', connection='simulated')\n"}
            elif step == 2:
                assert previous["data"]["script"]["id"]
                name, args = "workflow_definition_create", {"workflow": {"name": "Agent inspection", "nodes": [{"id": "version", "action_id": "device.command", "config": {"command": "display version"}}], "edges": []}}
            elif step == 3:
                self.workflow_id = previous["data"]["workflow"]["id"]
                name, args = "workflow_definition_validate", {"workflow_id": self.workflow_id}
            elif step == 4:
                name, args = "workflow_definition_run", {"workflow_id": self.workflow_id, "device_id": "MOCK-LAB-000", "draft": True, "dry_run": True, "connection": "simulated"}
            elif step == 5:
                name, args = "workflow_definition_publish", {"workflow_id": self.workflow_id}
            elif step == 6:
                name, args = "workflow_definition_run", {"workflow_id": self.workflow_id, "device_id": "MOCK-LAB-000", "connection": "simulated"}
            elif step == 7:
                name, args = "task_get", {"task_id": self.task_id}
            elif step >= 8:
                observation = previous["data"] if step == 8 else previous["data"]["observations"][0]
                if step > 8 and observation["terminal"]:
                    return LlmResponse(text="Workflow 已发布并执行，任务结果已读取。")
                name, args = "task_wait", {"task_ids": [self.task_id], "after_cursors": {self.task_id: observation["cursor"]}, "timeout_seconds": 2}
            else:
                return LlmResponse(text="Workflow 已发布并执行，任务结果已读取。")
            return LlmResponse(tool_calls=[ToolCall(str(step), name, args)])

    with TestClient(create_app(token="agent-test", repository=SampleDeviceRepository(), session_hub=SessionHub())) as client:
        ctx = client.app.state.context
        model = WorkflowModel()
        ctx.ai_agent = DeviceAgent(model, ctx.ai_runtime, event_callback=ctx.ai_runtime.record)
        def chat(message):
            response = client.post("/api/v1/ai/chat", headers=headers, json={"conversation_id": "flow", "message": message})
            assert response.status_code == 200, response.text
            return response.json()
        def state():
            return client.get("/api/v1/ai/agent/conversations/flow", headers=headers).json()
        def approve(approval):
            response = client.post(f"/api/v1/ai/agent/conversations/flow/approvals/{approval['id']}/approve", headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["approval"]["status"] == "completed", response.text
            return response.json()["approval"]
        chat("创建版本检查流程并预览")
        pending = next(item for item in state()["approvals"] if item["status"] == "pending")
        assert pending["tool"] == "workflow_definition_publish"
        assert pending["preview"]["validation"]["data"]["valid"]
        approve(pending)
        chat("继续运行")
        pending = next(item for item in state()["approvals"] if item["status"] == "pending")
        assert pending["tool"] == "workflow_definition_run"
        assert pending["preview"]["preview"]["data"]["dry_run"]
        result = approve(pending)
        model.task_id = result["result"]["data"]["task"]["id"]
        assert approve(pending) == result
        chat("读取任务结果")
        outputs = [event["data"] for event in state()["events"] if event["type"] == "agent.tool.output"]
        assert any(item["tool"] == "task_wait" and item["output"]["ok"] for item in outputs)
        observed = [item["output"]["data"]["observations"][0] for item in outputs if item["tool"] == "task_wait"][-1]
        assert observed["terminal"]
        assert "SimOS V1.0" in str(observed["task"]["result"])
        assert not state()["busy"]
        assert client.get("/api/v1/ai/agent/capabilities").status_code == 401
