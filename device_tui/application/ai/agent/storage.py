"""Bounded, redacted Agent snapshots, separate from operational state."""

from __future__ import annotations

from copy import deepcopy
import json
import time
from typing import Any, Protocol

from .context import AgentContext
from .safety import sanitize


class AgentSnapshotStore(Protocol):
    def get(self, conversation_id: str) -> dict[str, Any] | None: ...
    def put(self, conversation_id: str, payload: dict[str, Any]) -> None: ...
    def list(self) -> list[dict[str, Any]]: ...
    def delete(self, conversation_id: str) -> None: ...


class MemoryAgentSnapshotStore:
    def __init__(self, *, max_entries: int = 200, ttl_seconds: float = 30 * 86400) -> None:
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    def _prune(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        self._items = {key: value for key, value in self._items.items() if value[0] > cutoff}
        while len(self._items) > self.max_entries:
            del self._items[min(self._items, key=lambda key: self._items[key][0])]

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        self._prune()
        item = self._items.get(conversation_id)
        return deepcopy(item[1]) if item else None

    def put(self, conversation_id: str, payload: dict[str, Any]) -> None:
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 512_000:
            raise ValueError("Agent snapshot exceeds 512 KB")
        self._items[conversation_id] = (time.time(), deepcopy(sanitize(payload)))
        self._prune()

    def list(self) -> list[dict[str, Any]]:
        self._prune()
        result = []
        for key, (stamp, payload) in sorted(self._items.items(), key=lambda item: item[1][0], reverse=True):
            messages = payload.get("messages", [])
            last_message = next((str(item.get("content") or "") for item in reversed(messages) if item.get("role") == "user"), "")
            first_message = next((str(item.get("content") or "") for item in messages if item.get("role") == "user" and not str(item.get("content") or "").startswith("Backend restarted:")), "")
            result.append({"conversation_id": key, "title": payload.get("title") or first_message[:120] or "新会话", "last_message": last_message[:180], "message_count": sum(item.get("role") == "user" and not str(item.get("content") or "").startswith("Backend restarted:") for item in messages), "updated_at": stamp})
        return result

    def delete(self, conversation_id: str) -> None:
        self._items.pop(conversation_id, None)


def snapshot(context: AgentContext, approvals: list[dict[str, Any]]) -> dict[str, Any]:
    context.compact()
    # Disk retains an approval journal, never executable approval credentials or
    # full workflow/resource previews. Restored records are informational only.
    history_fields = {"id", "conversation_id", "tool", "status", "created_at", "expires_at", "content_hash"}
    history = [{**{key: value for key, value in item.items() if key in history_fields}, "history_only": True} for item in approvals[-30:]]
    return sanitize({
        "version": 1, "title": context.title, "messages": context.messages, "summary": context.summary,
        "device_id": context.device_id,
        # Live terminal handles are process-local and must be rediscovered.
        "protocol": context.variables.get("protocol", "auto"),
        "approvals": history, "traces": context.traces[-30:],
    })


def restore(conversation_id: str, payload: dict[str, Any]) -> AgentContext:
    safe = sanitize(payload)
    context = AgentContext(conversation_id, title=str(safe.get("title", ""))[:120], messages=safe.get("messages", []), device_id=safe.get("device_id"), summary=safe.get("summary", ""), traces=safe.get("traces", [])[-30:])
    context.variables["protocol"] = safe.get("protocol", "auto")
    # A crash can occur after the assistant emitted a tool batch. Supply explicit
    # unknown results; resuming must never send malformed pairs or replay calls.
    repaired: list[dict[str, Any]] = []
    pending: dict[str, str] = {}
    def close_pending() -> None:
        for call_id, name in pending.items():
            repaired.append({"role": "tool", "tool_call_id": call_id, "name": name, "content": '{"ok": false, "status": "outcome_unknown", "reason": "backend restarted; inspect before retry"}'})
        pending.clear()
    for item in context.messages:
        if pending and item.get("role") != "tool":
            close_pending()
        if item.get("role") == "tool":
            if item.get("tool_call_id") not in pending:
                continue
            pending.pop(item["tool_call_id"])
        repaired.append(item)
        for call in item.get("tool_calls", []):
            pending[call["id"]] = call.get("function", {}).get("name", "")
    close_pending()
    context.messages = repaired
    context.messages.append({"role": "user", "content": "Backend restarted: previous live sessions are invalid. Pending approvals expired; interrupted operations have unknown outcomes. Inspect tasks/operations and reconnect before proceeding; do not replay previous commands."})
    context.compact()
    return context
