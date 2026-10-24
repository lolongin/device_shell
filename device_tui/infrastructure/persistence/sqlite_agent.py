"""Agent snapshots in the existing desktop DB, with an idempotent schema."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from device_tui.application.ai.agent.safety import sanitize


class SQLiteAgentSnapshotStore:
    def __init__(self, path: Path, *, max_entries: int = 200, ttl_seconds: float = 30 * 86400) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        with self._connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS agent_conversations (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS agent_conversations_updated ON agent_conversations(updated_at)")
            self._prune(connection)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def _prune(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM agent_conversations WHERE updated_at <= ?", (time.time() - self.ttl_seconds,))
        connection.execute("DELETE FROM agent_conversations WHERE id IN (SELECT id FROM agent_conversations ORDER BY updated_at DESC LIMIT -1 OFFSET ?)", (self.max_entries,))

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            self._prune(connection)
            row = connection.execute("SELECT payload FROM agent_conversations WHERE id=?", (conversation_id,)).fetchone()
        if row is None:
            return None
        return sanitize(json.loads(row[0]))

    def put(self, conversation_id: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(sanitize(payload), ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 512_000:
            raise ValueError("Agent snapshot exceeds 512 KB")
        with self._connect() as connection:
            connection.execute("INSERT INTO agent_conversations VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at", (conversation_id, encoded, time.time()))
            self._prune(connection)

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            self._prune(connection)
            rows = connection.execute("SELECT id, payload, updated_at FROM agent_conversations ORDER BY updated_at DESC").fetchall()
        result = []
        for conversation_id, raw_payload, updated_at in rows:
            payload = json.loads(raw_payload)
            messages = payload.get("messages", [])
            last_message = next((str(item.get("content") or "") for item in reversed(messages) if item.get("role") == "user"), "")
            first_message = next((str(item.get("content") or "") for item in messages if item.get("role") == "user" and not str(item.get("content") or "").startswith("Backend restarted:")), "")
            result.append({"conversation_id": conversation_id, "title": payload.get("title") or first_message[:120] or "新会话", "last_message": last_message[:180], "message_count": sum(item.get("role") == "user" and not str(item.get("content") or "").startswith("Backend restarted:") for item in messages), "updated_at": updated_at})
        return result

    def delete(self, conversation_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM agent_conversations WHERE id=?", (conversation_id,))
