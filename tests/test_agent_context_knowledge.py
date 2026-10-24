from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from device_tui.application.ai.agent import AgentContext, DeviceAgent
from device_tui.application.ai.agent.context import ContextBudgetError
from device_tui.application.ai.agent.runtime import ApplicationAgentExecutor
from device_tui.application.ai.agent.safety import sanitize
from device_tui.application.ai.agent.storage import MemoryAgentSnapshotStore, restore, snapshot
from device_tui.application.ai.knowledge import DeviceKnowledge, KnowledgeDocument
from device_tui.application.ai.llm import LlmResponse, ToolCall
from device_tui.application.settings import MemorySettingsStore
from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.infrastructure.persistence.sqlite_agent import SQLiteAgentSnapshotStore
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub


def tool_pair(call_id: str, payload: dict) -> list[dict]:
    return [
        {"role": "assistant", "content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {"name": "task_wait", "arguments": '{"task_ids": ["t"]}'}}]},
        {"role": "tool", "tool_call_id": call_id, "name": "task_wait", "content": json.dumps(payload)},
    ]


def test_compaction_retains_complete_turns_and_untrusted_summary() -> None:
    context = AgentContext("c", messages=[{"role": "system", "content": "trusted instructions"}])
    for index in range(8):
        context.messages.extend([{"role": "user", "content": f"request {index} password=unsafe-value"}, *tool_pair(str(index), {"ok": True, "data": "x" * 4000})])
    report = context.compact(max_chars=12_000, recent_turns=2)
    assert report["characters"] <= 12_000
    assert context.messages[0]["content"] == "trusted instructions"
    assert report["compacted_turns"] >= 6
    assert "unsafe-value" not in json.dumps([context.messages, context.summary])
    calls = [call["id"] for item in context.messages for call in item.get("tool_calls", [])]
    assert calls == [item["tool_call_id"] for item in context.messages if item["role"] == "tool"]
    messages = context.model_messages()
    assert messages[1]["role"] == "user"
    assert "untrusted" in messages[1]["content"]


def test_compaction_keeps_latest_observation_and_valid_json() -> None:
    context = AgentContext("c", messages=[{"role": "system", "content": "observe"}, {"role": "user", "content": "wait"}])
    payload = {"ok": True, "data": {"observations": [{"task": {"id": "t", "result": {"output": "z" * 50_000}}, "cursor": "a" * 64, "terminal": True}]}}
    for index in range(6):
        context.messages.extend(tool_pair(str(index), payload))
    assert context.compact(max_chars=15_000)["characters"] <= 15_000
    for item in context.messages:
        if item["role"] == "tool":
            json.loads(item["content"])
    latest = json.loads(context.messages[-1]["content"])["data"]["observations"][0]
    assert latest["terminal"] is True
    assert latest["cursor"] == "a" * 64


def test_compaction_rejects_oversized_required_tool_arguments() -> None:
    context = AgentContext("c", messages=[{"role": "user", "content": "run"}, *tool_pair("a", {})])
    context.messages[1]["tool_calls"][0]["function"]["arguments"] = json.dumps({"script": "a" * 20_000})
    with pytest.raises(ContextBudgetError):
        context.compact(max_chars=8000)


def test_redaction_preserves_json_escaping_and_is_idempotent() -> None:
    content = json.dumps({"password": 'unsafe"\\secret', "nested": {"output": "Bearer abcdef123456 and sk-abcdefghijklmno"}, "cursor": "safe"})
    safe = sanitize(content)
    value = json.loads(safe)
    assert value["password"] == "***"
    assert value["cursor"] == "safe"
    assert "abcdef" not in safe
    assert "unsafe" not in safe
    assert sanitize(safe) == safe


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_snapshot_store_capacity_ttl_redaction_and_reopen(kind, tmp_path, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr("time.time", lambda: clock[0])
    store = MemoryAgentSnapshotStore(max_entries=2, ttl_seconds=10) if kind == "memory" else SQLiteAgentSnapshotStore(tmp_path / "state.db", max_entries=2, ttl_seconds=10)
    for key in ["a", "b", "c"]:
        store.put(key, {"message": "password=unsafe-value", "nested": {"api_key": "unsafe"}})
        clock[0] += 1
    if kind == "sqlite":
        store = SQLiteAgentSnapshotStore(tmp_path / "state.db", max_entries=2, ttl_seconds=10)
        with sqlite3.connect(tmp_path / "state.db") as connection:
            assert "unsafe" not in str(connection.execute("SELECT payload FROM agent_conversations").fetchall())
    assert store.get("a") is None
    assert [entry["conversation_id"] for entry in store.list()] == ["c", "b"]
    assert "unsafe" not in json.dumps(store.get("b"))
    value = store.get("b")
    value["nested"]["api_key"] = "changed"
    assert store.get("b")["nested"]["api_key"] == "***"
    clock[0] += 20
    assert store.list() == []


def test_recovery_repairs_missing_results_without_sessions_or_reauthorization() -> None:
    context = AgentContext("c", session_id="live-session", variables={"protocol": "ssh", "run_id": "run", "private": "value"})
    context.messages = [{"role": "user", "content": "run"}, tool_pair("a", {})[0]]
    approvals = [{"id": "approval", "conversation_id": "c", "tool": "terminal_execute", "status": "executing", "arguments": {"command": "reboot"}, "preview": {"huge": "x" * 1000}}]
    payload = snapshot(context, approvals)
    assert "arguments" not in payload["approvals"][0]
    assert "preview" not in payload["approvals"][0]
    assert "live-session" not in json.dumps(payload)
    restored = restore("c", payload)
    assert restored.session_id is None
    assert restored.variables == {"protocol": "ssh"}
    result = next(item for item in restored.messages if item["role"] == "tool")
    assert result["tool_call_id"] == "a"
    assert json.loads(result["content"])["status"] == "outcome_unknown"

    class NeverExecute:
        async def invoke(self, *args, **kwargs):
            raise AssertionError("Recovery replayed a command")

    runtime = ApplicationAgentExecutor(NeverExecute())
    runtime.restore_approvals("c", payload["approvals"])
    assert asyncio.run(runtime.resolve("approval", restored, approve=True))["status"] == "expired"


def test_checkpoint_contains_completed_results_and_bounded_traces() -> None:
    saved = []

    class Model:
        calls = 0

        async def chat(self, **kwargs):
            self.calls += 1
            return LlmResponse(tool_calls=[ToolCall("a", "device_list", {})]) if self.calls == 1 else LlmResponse(text="done")

    class Executor:
        async def execute(self, call, context):
            return {"ok": True, "output": "password=unsafe-value"}

    context = AgentContext("c", traces=[{} for _ in range(40)])
    result = asyncio.run(DeviceAgent(Model(), Executor(), checkpoint=lambda ctx: saved.append(deepcopy(snapshot(ctx, [])))).run("inspect", context))
    assert result == "done"
    assert any(item["role"] == "tool" for item in saved[-1]["messages"])
    assert "unsafe-value" not in json.dumps(saved)
    assert len(context.traces) == 30
    trace = context.traces[-1]
    assert trace["status"] == "completed"
    assert trace["iterations"] == 2
    assert trace["llm"][0]["elapsed_ms"] >= 0
    assert trace["tools"][0]["tool"] == "device_list"


def test_checkpoint_failure_does_not_mask_original_model_failure() -> None:
    class Model:
        async def chat(self, **kwargs):
            raise RuntimeError("original model failure")

    def checkpoint(context):
        if context.traces[-1]["status"] == "failed":
            raise ValueError("final snapshot failure")

    with pytest.raises(RuntimeError, match="original model failure"):
        asyncio.run(DeviceAgent(Model(), object(), checkpoint=checkpoint).run("inspect", AgentContext("c")))


def document(**kwargs) -> KnowledgeDocument:
    return KnowledgeDocument(**{"title": "端口故障诊断", "content": "使用 display interface 检查端口错误计数，确认接口状态。", "source": "Vendor manual section 3", "vendor": "Vendor", "model": "Switch", "software_version": "1.0", **kwargs})


def test_knowledge_retrieves_chinese_passages_with_source_and_exact_version() -> None:
    knowledge = DeviceKnowledge(MemorySettingsStore())
    knowledge.put("doc", document(content="背景资料。" * 500 + "检查端口错误计数，使用 display interface。"))
    knowledge.put("unknown", document(software_version=""))
    matches = knowledge.search("端口错误计数", vendor="vendor", model="SWITCH", software_version="1.0")
    assert len(matches) == 1
    assert matches[0]["id"] == "doc"
    assert matches[0]["source"] == "Vendor manual section 3"
    assert matches[0]["offset"] > 0
    assert len(matches[0]["excerpt"]) <= 1500
    assert matches[0]["static_document"] is True
    assert knowledge.search("端口", software_version="2.0") == []
    assert knowledge.search("unrelatedword") == []


def test_knowledge_rejects_credentials_and_capacity_without_mutating_store() -> None:
    settings = MemorySettingsStore()
    knowledge = DeviceKnowledge(settings)
    with pytest.raises(ValueError, match="credentials"):
        knowledge.put("secret", document(content="password=unsafe-value"))
    with pytest.raises(ValueError):
        knowledge.put("../outside", document())
    with pytest.raises(ValueError):
        knowledge.search("   ")
    for index in range(200):
        knowledge.put(str(index), document())
    with pytest.raises(ValueError, match="capacity"):
        knowledge.put("overflow", document())
    assert len(settings.get(DeviceKnowledge.KEY)) == 200
    knowledge.delete("0")
    with pytest.raises(ValueError, match="Unknown"):
        knowledge.get("0")


def test_knowledge_api_and_read_only_agent_tool_and_lazy_recovery() -> None:
    headers = {"Authorization": "Bearer test"}
    with TestClient(create_app(token="test", repository=SampleDeviceRepository(), session_hub=SessionHub())) as client:
        assert client.put("/api/v1/ai/knowledge/doc", json=document().model_dump()).status_code == 401
        assert client.put("/api/v1/ai/knowledge/doc", headers=headers, json=document().model_dump()).status_code == 200
        result = client.get("/api/v1/ai/knowledge/search", headers=headers, params={"query": "端口", "software_version": "1.0"})
        assert result.json()["documents"][0]["source"] == "Vendor manual section 3"
        context = client.app.state.context
        result = asyncio.run(context.ai_runtime.execute(ToolCall("search", "knowledge_search", {"query": "端口"}), AgentContext("live")))
        assert result["ok"]
        assert result["data"]["documents"][0]["id"] == "doc"
        assert context.ai_runtime.state("live")["approvals"] == []
        context.ai_snapshot_store.put("restored", snapshot(AgentContext("restored", session_id="old", traces=[{"status": "completed"}]), []))
        assert "restored" not in context.ai_conversations
        assert client.get("/api/v1/ai/agent/conversations/restored", headers=headers).json()["context_available"]
        assert context.ai_conversations["restored"].session_id is None
        assert client.get("/api/v1/ai/agent/conversations/restored/trace", headers=headers).json()["runs"] == [{"status": "completed"}]
        assert client.get("/api/v1/ai/agent/conversations", headers=headers).json()["conversations"][0]["conversation_id"] == "restored"
        assert client.get("/api/v1/ai/knowledge/doc", headers=headers).status_code == 200
        assert client.delete("/api/v1/ai/knowledge/doc", headers=headers).status_code == 200
        assert client.get("/api/v1/ai/knowledge/doc", headers=headers).status_code == 404
