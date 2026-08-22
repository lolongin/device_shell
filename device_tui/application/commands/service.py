"""Persistent command workspace and terminal-send application service."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from device_tui.application.commands.suggestions import (
    CommandHistoryItem,
    deserialize_command_history_item,
    record_command_history,
    suggest_commands,
)
from device_tui.application.errors import (
    ApplicationConflictError,
    ResourceNotFoundError,
    UnsupportedOperationError,
)
from device_tui.application.sessions import SessionRecord, SessionService


_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(\b(?:password|passwd|secret|community|token)\b\s*(?:=|:|\s)\s*)(\S+)"
)


def redact_command_secrets(command: str) -> str:
    return _SENSITIVE_ASSIGNMENT.sub(r"\1[REDACTED]", command)


@dataclass(frozen=True, slots=True)
class CommandGroup:
    id: str
    name: str
    content: str = ""
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""


class CommandStore(Protocol):
    def list_command_groups(self) -> list[CommandGroup]: ...

    def get_command_group(self, group_id: str) -> CommandGroup | None: ...

    def upsert_command_group(self, group: CommandGroup) -> None: ...

    def delete_command_group(self, group_id: str) -> None: ...

    def list_command_history(self) -> list[CommandHistoryItem]: ...

    def replace_command_history(self, history: list[CommandHistoryItem]) -> None: ...

    def get_meta(self, key: str) -> str | None: ...

    def set_meta(self, key: str, value: str) -> None: ...


class MemoryCommandStore:
    def __init__(self) -> None:
        self._groups: dict[str, CommandGroup] = {}
        self._history: list[CommandHistoryItem] = []
        self._meta: dict[str, str] = {}

    def list_command_groups(self) -> list[CommandGroup]:
        return sorted(self._groups.values(), key=lambda group: (group.sort_order, group.name, group.id))

    def get_command_group(self, group_id: str) -> CommandGroup | None:
        return self._groups.get(group_id)

    def upsert_command_group(self, group: CommandGroup) -> None:
        self._groups[group.id] = group

    def delete_command_group(self, group_id: str) -> None:
        self._groups.pop(group_id, None)

    def list_command_history(self) -> list[CommandHistoryItem]:
        return [replace(item) for item in self._history]

    def replace_command_history(self, history: list[CommandHistoryItem]) -> None:
        self._history = [replace(item) for item in history]

    def get_meta(self, key: str) -> str | None:
        return self._meta.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self._meta[key] = value


class CommandService:
    DEFAULT_GROUP_ID = "COMMAND-GROUP-DEFAULT"
    CURRENT_GROUP_KEY = "command_workspace_current_group"
    ENTER_SENDS_KEY = "command_workspace_enter_sends"
    LEGACY_IMPORT_KEY = "legacy_commands_v1"

    def __init__(self, store: CommandStore, sessions: SessionService) -> None:
        self._store = store
        self._sessions = sessions
        self._ensure_default_group()

    def list_groups(self) -> list[CommandGroup]:
        return self._store.list_command_groups()

    def get_group(self, group_id: str) -> CommandGroup:
        group = self._store.get_command_group(group_id)
        if group is None:
            raise ResourceNotFoundError(
                f"Unknown command group: {group_id}",
                details={"resource": "command_group", "group_id": group_id},
            )
        return group

    def create_group(self, name: str = "") -> CommandGroup:
        groups = self.list_groups()
        normalized = name.strip() or self._next_group_name(groups)
        self._require_unique_name(normalized)
        now = self._now()
        group = CommandGroup(
            id=f"COMMAND-GROUP-{uuid4().hex[:12].upper()}",
            name=normalized,
            sort_order=max((item.sort_order for item in groups), default=-1) + 1,
            created_at=now,
            updated_at=now,
        )
        self._store.upsert_command_group(group)
        self.set_current_group(group.id)
        return group

    def update_group(
        self,
        group_id: str,
        *,
        name: str | None = None,
        content: str | None = None,
    ) -> CommandGroup:
        group = self.get_group(group_id)
        normalized_name = group.name if name is None else name.strip()
        if not normalized_name:
            raise UnsupportedOperationError("A command-group name is required.")
        self._require_unique_name(normalized_name, ignore_id=group.id)
        safe_content = group.content if content is None else redact_command_secrets(
            content.replace("\r\n", "\n").replace("\r", "\n")
        )
        updated = replace(
            group,
            name=normalized_name,
            content=safe_content,
            updated_at=self._now(),
        )
        self._store.upsert_command_group(updated)
        return updated

    def reorder_groups(self, group_ids: list[str]) -> list[CommandGroup]:
        groups = self.list_groups()
        expected = {group.id for group in groups}
        requested = list(group_ids)
        if len(requested) != len(set(requested)) or set(requested) != expected:
            raise UnsupportedOperationError("The command-group order is invalid.")
        by_id = {group.id: group for group in groups}
        now = self._now()
        reordered: list[CommandGroup] = []
        for sort_order, group_id in enumerate(requested):
            group = by_id[group_id]
            updated = replace(group, sort_order=sort_order, updated_at=now)
            self._store.upsert_command_group(updated)
            reordered.append(updated)
        return reordered

    def delete_group(self, group_id: str) -> str:
        group = self.get_group(group_id)
        groups = self.list_groups()
        if len(groups) <= 1:
            raise ApplicationConflictError("At least one command group must remain.")
        self._store.delete_command_group(group.id)
        remaining = [item for item in groups if item.id != group.id]
        current = self.current_group_id()
        if current == group.id:
            self.set_current_group(remaining[0].id)
        return self.current_group_id()

    def current_group_id(self) -> str:
        configured = self._store.get_meta(self.CURRENT_GROUP_KEY) or ""
        if configured and self._store.get_command_group(configured) is not None:
            return configured
        groups = self.list_groups()
        return groups[0].id

    def set_current_group(self, group_id: str) -> None:
        self.get_group(group_id)
        self._store.set_meta(self.CURRENT_GROUP_KEY, group_id)

    def enter_sends(self) -> bool:
        return self._store.get_meta(self.ENTER_SENDS_KEY) == "1"

    def set_enter_sends(self, enabled: bool) -> None:
        self._store.set_meta(self.ENTER_SENDS_KEY, "1" if enabled else "0")

    def history(self, limit: int = 1_000) -> list[CommandHistoryItem]:
        return self._store.list_command_history()[: max(0, limit)]

    def record(
        self,
        command: str,
        *,
        device_id: str = "",
        session_kind: str = "",
    ) -> None:
        safe_command = redact_command_secrets(command)
        history = record_command_history(
            self._store.list_command_history(),
            safe_command,
            device_id=device_id,
            session_kind=session_kind,
        )
        self._store.replace_command_history(history)

    def suggestions(
        self,
        query: str,
        *,
        device_id: str = "",
        session_kind: str = "",
        limit: int = 5,
    ) -> list[str]:
        history = self._store.list_command_history()
        known = {item.command for item in history}
        for group in self.list_groups():
            for command in self._content_commands(group.content):
                if command not in known:
                    history.append(CommandHistoryItem(command=command, count=1))
                    known.add(command)
        return suggest_commands(
            history,
            query,
            device_id=device_id,
            session_kind=session_kind,
            limit=max(1, min(limit, 20)),
        )

    def record_for_session(self, session_id: str, command: str) -> None:
        session = self._session(session_id)
        self.record(
            command,
            device_id=session.device_id,
            session_kind=session.kind,
        )

    async def send(self, session_id: str, command: str) -> SessionRecord:
        normalized = command.strip()
        if not normalized:
            raise UnsupportedOperationError("A command is required.")
        session = self._session(session_id)
        await self._sessions.write(session_id, self.command_payload(command))
        self.record(
            command,
            device_id=session.device_id,
            session_kind=session.kind,
        )
        return session

    async def broadcast(self, command: str, session_ids: list[str] | None = None) -> list[str]:
        normalized = command.strip()
        if not normalized:
            raise UnsupportedOperationError("A command is required.")
        requested = set(session_ids or [])
        targets = [
            session
            for session in self._sessions.list_sessions()
            if session.status == "connected" and (not requested or session.id in requested)
        ]
        if not targets:
            raise UnsupportedOperationError("No connected terminal session is available.")
        payload = self.command_payload(command)
        for session in targets:
            await self._sessions.write(session.id, payload)
        first = targets[0]
        self.record(command, device_id=first.device_id, session_kind=first.kind)
        return [session.id for session in targets]

    def import_legacy_state(self, state_path: Path) -> dict[str, int]:
        if self._store.get_meta(self.LEGACY_IMPORT_KEY) is not None or not state_path.exists():
            return {"groups": 0, "history": 0}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"groups": 0, "history": 0}
        if not isinstance(payload, dict):
            return {"groups": 0, "history": 0}
        raw_groups = payload.get("command_record_groups", [])
        groups: list[CommandGroup] = []
        if isinstance(raw_groups, list):
            now = self._now()
            for index, item in enumerate(raw_groups):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or f"分组 {index + 1}").strip()
                groups.append(CommandGroup(
                    id=f"COMMAND-GROUP-LEGACY-{index + 1}",
                    name=name or f"分组 {index + 1}",
                    content=redact_command_secrets(str(item.get("content") or "")),
                    sort_order=index,
                    created_at=now,
                    updated_at=now,
                ))
        if groups:
            for existing in self.list_groups():
                self._store.delete_command_group(existing.id)
            for group in groups:
                self._store.upsert_command_group(group)
        raw_history = payload.get("command_history", [])
        history: list[CommandHistoryItem] = []
        if isinstance(raw_history, list):
            for item in raw_history:
                parsed = deserialize_command_history_item(item)
                if parsed is not None:
                    parsed.command = redact_command_secrets(parsed.command)
                    history.append(parsed)
        if history:
            self._store.replace_command_history(history)
        current_index = self._int(payload.get("current_command_group"), 0)
        current_groups = self.list_groups()
        current_index = min(max(current_index, 0), len(current_groups) - 1)
        self.set_current_group(current_groups[current_index].id)
        self.set_enter_sends(bool(payload.get("command_enter_sends", False)))
        counts = {"groups": len(groups), "history": len(history)}
        self._store.set_meta(
            self.LEGACY_IMPORT_KEY,
            json.dumps({"imported_at": self._now(), **counts}, ensure_ascii=False),
        )
        return counts

    @staticmethod
    def command_payload(command: str) -> str:
        normalized = command.replace("\r\n", "\n").replace("\r", "\n")
        return f"{normalized.replace(chr(10), chr(13))}\r"

    def _session(self, session_id: str) -> SessionRecord:
        for session in self._sessions.list_sessions():
            if session.id == session_id:
                return session
        raise ResourceNotFoundError(
            f"Unknown session: {session_id}",
            details={"resource": "session", "session_id": session_id},
        )

    def _ensure_default_group(self) -> None:
        if self._store.list_command_groups():
            return
        now = self._now()
        self._store.upsert_command_group(CommandGroup(
            id=self.DEFAULT_GROUP_ID,
            name="终端",
            sort_order=0,
            created_at=now,
            updated_at=now,
        ))
        self._store.set_meta(self.CURRENT_GROUP_KEY, self.DEFAULT_GROUP_ID)

    def _require_unique_name(self, name: str, *, ignore_id: str = "") -> None:
        if any(
            group.id != ignore_id and group.name.casefold() == name.casefold()
            for group in self.list_groups()
        ):
            raise ApplicationConflictError(f"A command group named '{name}' already exists.")

    @staticmethod
    def _next_group_name(groups: list[CommandGroup]) -> str:
        existing = {group.name for group in groups}
        index = max(len(groups), 1)
        while f"分组 {index}" in existing:
            index += 1
        return f"分组 {index}"

    @staticmethod
    def _content_commands(content: str) -> list[str]:
        return [line.strip() for line in content.splitlines() if line.strip()]

    @staticmethod
    def _int(value: object, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
