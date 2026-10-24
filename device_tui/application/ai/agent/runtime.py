"""Application Agent tool policy, approval lifecycle, and event journal."""

from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
import hashlib
import json
import re
import time
from typing import Any, Callable, Protocol
from uuid import uuid4

from pydantic import ValidationError

from device_tui.application.ai.llm.models import ToolCall
from device_tui.application.ai.operations import RiskLevel, classify_command_risk

from .context import AgentContext
from .events import AgentEvent
from .safety import sanitize


class AgentTools(Protocol):
    @property
    def definitions(self) -> list[dict[str, Any]]: ...
    @property
    def read_only_tools(self) -> frozenset[str]: ...
    def validate(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    async def invoke(self, name: str, arguments: dict[str, Any], *, approved: bool = False) -> dict[str, Any]: ...
    async def snapshot(self, name: str, params: dict[str, Any]) -> dict[str, Any]: ...
    async def preview(self, name: str, params: dict[str, Any]) -> dict[str, Any]: ...


_AUTONOMOUS = frozenset("""
app_status device_list device_get device_select device_open session_open session_list connection_open profile_list
transfer_files operation_get operation_wait terminal_read terminal_interact_get
workflow_list workflow_authoring_describe workflow_script_list workflow_script_get workflow_script_create
workflow_script_update workflow_script_validate workflow_definition_list workflow_definition_get
workflow_definition_create workflow_definition_update workflow_definition_validate workflow_plan_validate workflow_plan_get
task_get task_wait task_list task_framework_get decision_get task_pause task_cancel terminal_interact_cancel
""".split())


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class ApplicationAgentExecutor:
    def __init__(self, tools: AgentTools, *, audit: Callable[..., None] | None = None,
                 event_callback: Callable[[AgentEvent], None] | None = None,
                 timeout_seconds: float = 120, approval_ttl: float = 900) -> None:
        self.tools = tools
        self._audit = audit
        self._event_callback = event_callback
        self.timeout_seconds = timeout_seconds
        self.approval_ttl = approval_ttl
        self.bypass_approval = False
        self._approvals: dict[str, dict[str, Any]] = {}
        self._calls: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=500)
        self._sequence = 0
        self._lock = asyncio.Lock()

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return self.tools.definitions

    def record(self, event: AgentEvent) -> None:
        self._sequence += 1
        data = sanitize(event.data)
        self._events.append({"sequence": self._sequence, "type": event.type, "data": data, "created_at": time.time()})
        if self._event_callback:
            self._event_callback(AgentEvent(event.type, data))

    def state(self, conversation_id: str, after: int = 0) -> dict[str, Any]:
        for approval in self._approvals.values():
            if approval["status"] == "pending" and time.time() >= approval["expires_at"]:
                approval["status"] = "expired"
        return {
            "events": [item for item in self._events if item["sequence"] > after and item["data"].get("conversation_id") == conversation_id],
            "cursor": self._sequence,
            "approvals": [self._public(item) for item in self._approvals.values() if item["conversation_id"] == conversation_id],
        }

    def restore_approvals(self, conversation_id: str, items: list[dict[str, Any]]) -> None:
        """Restore history only. Never reauthorize side effects from disk."""
        for original in items[-30:]:
            item = sanitize(deepcopy(original))
            if item.get("conversation_id") != conversation_id or not item.get("id"):
                continue
            if item.get("status") in {"pending", "executing"}:
                item["status"] = "expired"
                item["recovery_reason"] = "Backend restarted; inspect state and prepare a new approval"
            if len(self._approvals) < 500:
                self._approvals[item["id"]] = item

    def forget_conversation(self, conversation_id: str) -> None:
        self._approvals = {key: item for key, item in self._approvals.items() if item.get("conversation_id") != conversation_id}
        self._calls = {key: value for key, value in self._calls.items() if key[0] != conversation_id}
        self._events = deque((item for item in self._events if item["data"].get("conversation_id") != conversation_id), maxlen=500)

    @staticmethod
    def _public(approval: dict[str, Any]) -> dict[str, Any]:
        return sanitize({key: value for key, value in approval.items() if key not in {"snapshot", "call_key"}})

    @staticmethod
    def needs_approval(name: str, params: dict[str, Any]) -> bool:
        if name in _AUTONOMOUS:
            return False
        if name == "session_manage":
            return params["action"] not in {"open", "status"}
        if name == "workflow_definition_run" and params.get("dry_run"):
            return False
        if name in {"terminal_execute", "terminal_batch"}:
            commands = [params["command"]] if name == "terminal_execute" else params["commands"]
            return not commands or any(not command.strip() or re.search(r"[\r\n;&|`$><]", command) or classify_command_risk(command) >= RiskLevel.MEDIUM for command in commands)
        return True

    async def execute(self, tool_call: ToolCall, context: AgentContext) -> dict[str, Any]:
        name = tool_call.name
        key = (context.conversation_id, str(context.variables.get("run_id", "")), tool_call.id)
        fingerprint = _fingerprint([name, tool_call.arguments])
        if key in self._calls:
            old_hash, result = self._calls[key]
            return deepcopy(result) if old_hash == fingerprint else {"ok": False, "error_code": "tool_call_conflict", "error": "Tool call id was reused with different arguments"}
        try:
            params = self.tools.validate(name, tool_call.arguments)
            if name.startswith("terminal_") and "device_id" in params and not params.get("device_id") and not params.get("session_id"):
                params["device_id"] = context.device_id or ""
                if "session_id" in params:
                    params["session_id"] = context.session_id or ""
            if sanitize(params) != params:
                raise ValueError("Secret values must use saved backend credentials or secret_ref")
            if name not in getattr(self.tools, "read_only_tools", ()) and self.needs_approval(name, params) and not self.bypass_approval:
                preview = await asyncio.wait_for(self.tools.preview(name, params), self.timeout_seconds)
                snapshot = await asyncio.wait_for(self.tools.snapshot(name, params), self.timeout_seconds)
                preview = {**preview, "resources": {key: value for key, value in snapshot.items() if key not in {"workflow.list", "studio_versions"}}}
                approval_id = uuid4().hex
                if len(self._approvals) >= 500:
                    raise ValueError("Agent approval capacity reached; restart the backend after resolving pending actions")
                approval = {"id": approval_id, "conversation_id": context.conversation_id, "tool": name,
                            "arguments": deepcopy(params), "snapshot": snapshot, "preview": preview,
                            "content_hash": _fingerprint([name, params, snapshot]), "status": "pending",
                            "created_at": time.time(), "expires_at": time.time() + self.approval_ttl, "call_key": key}
                self._approvals[approval_id] = approval
                result = {"ok": False, "status": "needs_approval", "approval": self._public(approval)}
                self.record(AgentEvent("agent.approval.requested", {"conversation_id": context.conversation_id, "approval": self._public(approval)}))
            else:
                result = await self._invoke(name, params)
            self._remember(key, fingerprint, result)
            self._record_audit(name, params, str(result.get("status") or ("completed" if result.get("ok") else "failed")))
            return result
        except Exception as exc:
            self._record_audit(name, {}, "rejected")
            # ValidationError's default string includes rejected raw values.
            message = json.dumps(exc.errors(include_input=False, include_url=False), ensure_ascii=False, default=str) if isinstance(exc, ValidationError) else str(exc)
            return {"ok": False, "error_code": "invalid_tool_arguments", "error": sanitize(message)}

    def _remember(self, key: tuple[str, str, str], fingerprint: str, result: dict[str, Any]) -> None:
        if len(self._calls) >= 2000:
            self._calls.pop(next(iter(self._calls)))
        self._calls[key] = (fingerprint, deepcopy(result))

    def _record_audit(self, name: str, params: dict[str, Any], status: str) -> None:
        if self._audit:
            safe_params = sanitize(params)
            # The existing audit adapter persists command and target fields;
            # include structured arguments for non-terminal management actions.
            audit_params = {**safe_params, "command": str(safe_params.get("command") or json.dumps(safe_params, ensure_ascii=False, default=str))[:16_384]}
            self._audit("agent." + name, audit_params, status=status)

    async def _invoke(self, name: str, params: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        try:
            result = await asyncio.wait_for(self.tools.invoke(name, params, approved=approved), self.timeout_seconds)
            return sanitize(result)
        except asyncio.TimeoutError:
            return {"ok": False, "status": "outcome_unknown", "error_code": "tool_timeout", "error": "Tool timed out. Inspect tasks/operations before retrying; an external operation may still be running."}
        except Exception as exc:
            return {"ok": False, "error_code": "tool_failed", "error": sanitize(str(exc))}

    async def resolve(self, approval_id: str, context: AgentContext, *, approve: bool) -> dict[str, Any]:
        # Serialize consumption, including duplicate HTTP submissions.
        async with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None or approval["conversation_id"] != context.conversation_id:
                raise ValueError("Unknown approval for this conversation")
            if approval["status"] != "pending":
                return self._public(approval)
            if time.time() >= approval["expires_at"]:
                approval["status"] = "expired"
            elif not approve:
                approval["status"] = "rejected"
            else:
                try:
                    snapshot = await asyncio.wait_for(self.tools.snapshot(approval["tool"], approval["arguments"]), self.timeout_seconds)
                    if _fingerprint(snapshot) != _fingerprint(approval["snapshot"]):
                        approval["status"] = "stale"
                    else:
                        approval["status"] = "executing"
                        approval["result"] = await self._invoke(approval["tool"], approval["arguments"], approved=True)
                        approval["status"] = "completed" if approval["result"].get("ok") else "failed"
                except Exception as exc:
                    approval["status"] = "failed"
                    approval["result"] = {"ok": False, "error": sanitize(str(exc))}
            public = self._public(approval)
            context.messages.append({"role": "user", "content": "Application approval outcome (observe before any retry): " + json.dumps(public, ensure_ascii=False, default=str)})
            self._record_audit(approval["tool"], approval["arguments"], approval["status"])
            self.record(AgentEvent("agent.approval.resolved", {"conversation_id": context.conversation_id, "approval": public}))
            return public
