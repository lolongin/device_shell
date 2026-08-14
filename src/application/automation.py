"""UI-independent terminal auto-response rules and execution state."""

from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable, Protocol
from uuid import uuid4

from ..auto_response import (
    AutoResponseAction,
    AutoResponseRule,
    AutoResponseStep,
    auto_response_rule_allows_startup_trigger,
    decode_response_text,
    default_quick_send_buttons,
    deserialize_quick_send_button,
    deserialize_auto_response_rule,
    serialize_auto_response_rule,
)
from ..terminal_execution import ANSI_ESCAPE_RE
from .errors import ResourceNotFoundError, UnsupportedOperationError
from .events import EventBus
from .automation_expressions import SafeAutomationExpression, template_expression_pattern
from .secrets import SecretStore
from .sessions import SessionRecord, SessionService


SECRET_MASK = "••••••"
_SECRET_REFERENCE = re.compile(r"\{\{secret:([^{}]+)}}")
_TEMPLATE_EXPRESSION = template_expression_pattern()
_VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SENSITIVE_PROMPT = re.compile(
    r"(?i)(password|passwd|passphrase|secret|community|token|密码|口令|密钥)"
)
_ANSI_OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")


@dataclass(frozen=True, slots=True)
class AutomationRuleRecord:
    id: str
    rule: AutoResponseRule
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class AutomationSessionStatus:
    session_id: str
    running_rule_ids: tuple[str, ...]
    waiting_rule_ids: tuple[str, ...]
    triggered_rule_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QuickSendButtonRecord:
    id: str
    name: str
    response_text: str
    append_enter: bool
    sensitive: bool = False


@dataclass(frozen=True, slots=True)
class AutomationActivityRecord:
    id: str
    timestamp: str
    event: str
    session_id: str
    rule_id: str
    name: str
    message: str
    target_session_id: str = ""


class AutomationStore(Protocol):
    def list_automation_rules(self) -> list[AutomationRuleRecord]: ...

    def get_automation_rule(self, rule_id: str) -> AutomationRuleRecord | None: ...

    def upsert_automation_rule(self, record: AutomationRuleRecord) -> None: ...

    def delete_automation_rule(self, rule_id: str) -> None: ...

    def get_meta(self, key: str) -> str | None: ...

    def set_meta(self, key: str, value: str) -> None: ...


class MemoryAutomationStore:
    def __init__(self) -> None:
        self._rules: dict[str, AutomationRuleRecord] = {}
        self._meta: dict[str, str] = {}

    def list_automation_rules(self) -> list[AutomationRuleRecord]:
        return [
            replace(record, rule=deepcopy(record.rule))
            for record in sorted(
                self._rules.values(),
                key=lambda item: (item.created_at, item.id),
            )
        ]

    def get_automation_rule(self, rule_id: str) -> AutomationRuleRecord | None:
        record = self._rules.get(rule_id)
        return replace(record, rule=deepcopy(record.rule)) if record is not None else None

    def upsert_automation_rule(self, record: AutomationRuleRecord) -> None:
        self._rules[record.id] = replace(record, rule=deepcopy(record.rule))

    def delete_automation_rule(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)

    def get_meta(self, key: str) -> str | None:
        return self._meta.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self._meta[key] = value


@dataclass(slots=True)
class _SessionRuntime:
    buffer: str = ""
    user_input_seen: bool = False
    step_indexes: dict[str, int] = field(default_factory=dict)
    loop_indexes: dict[str, int] = field(default_factory=dict)
    triggered: set[str] = field(default_factory=set)
    running: set[str] = field(default_factory=set)
    tasks: dict[str, set[asyncio.Task[None]]] = field(default_factory=dict)
    waiting_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)


class AutomationService:
    """Persist and execute terminal automation without depending on Qt or Vue."""

    LEGACY_IMPORT_KEY = "legacy_automation_v1"
    LEGACY_QUICK_SEND_IMPORT_KEY = "legacy_quick_send_v1"
    QUICK_SEND_META_KEY = "terminal_quick_send_buttons_v1"

    def __init__(
        self,
        store: AutomationStore,
        sessions: SessionService,
        secrets: SecretStore,
        events: EventBus,
    ) -> None:
        self._store = store
        self._sessions = sessions
        self._secrets = secrets
        self._events = events
        self._runtimes: dict[str, _SessionRuntime] = {}
        self._activities: deque[AutomationActivityRecord] = deque(maxlen=300)
        self._event_source: Any = None
        self._event_listener: Callable[[Any], None] | None = None

    def bind_event_source(self, source: Any) -> None:
        add_listener = getattr(source, "add_event_listener", None)
        if not callable(add_listener):
            return
        self.unbind_event_source()
        self._event_source = source
        self._event_listener = self.handle_terminal_event
        add_listener(self._event_listener)

    def unbind_event_source(self) -> None:
        if self._event_source is not None and self._event_listener is not None:
            remove_listener = getattr(self._event_source, "remove_event_listener", None)
            if callable(remove_listener):
                remove_listener(self._event_listener)
        self._event_source = None
        self._event_listener = None

    def list_rules(self) -> list[AutomationRuleRecord]:
        return self._store.list_automation_rules()

    def get_rule(self, rule_id: str) -> AutomationRuleRecord:
        record = self._store.get_automation_rule(rule_id)
        if record is None:
            raise ResourceNotFoundError(
                f"Unknown automation rule: {rule_id}",
                details={"resource": "automation_rule", "rule_id": rule_id},
            )
        return record

    def create_rule(self, rule: AutoResponseRule) -> AutomationRuleRecord:
        now = self._now()
        rule_id = f"AUTOMATION-{uuid4().hex[:12].upper()}"
        candidate = deepcopy(rule)
        self._validate_regex_patterns(candidate)
        self._validate_action_variables(candidate.actions)
        self._validate_plaintext_secrets(candidate)
        record = AutomationRuleRecord(rule_id, candidate, now, now)
        self._store.upsert_automation_rule(record)
        self._publish("automation.rule.created", record)
        return self.get_rule(rule_id)

    def update_rule(
        self,
        rule_id: str,
        rule: AutoResponseRule,
    ) -> AutomationRuleRecord:
        current = self.get_rule(rule_id)
        candidate = deepcopy(rule)
        self._restore_masked_secrets(candidate, current.rule)
        self._validate_regex_patterns(candidate)
        self._validate_action_variables(candidate.actions)
        self._validate_plaintext_secrets(candidate)
        updated = replace(current, rule=candidate, updated_at=self._now())
        self.cancel_rule(rule_id)
        self._store.upsert_automation_rule(updated)
        self._publish("automation.rule.updated", updated)
        return self.get_rule(rule_id)

    def clone_rule(self, rule_id: str) -> AutomationRuleRecord:
        source = self.get_rule(rule_id)
        now = self._now()
        clone_id = f"AUTOMATION-{uuid4().hex[:12].upper()}"
        candidate = deepcopy(source.rule)
        candidate.name = f"{candidate.name} 副本"
        candidate.enabled = False
        candidate.trigger_count = 0
        created_secret_ids: list[str] = []
        try:
            self._clone_rule_secrets(candidate, clone_id, created_secret_ids)
            cloned = AutomationRuleRecord(clone_id, candidate, now, now)
            self._store.upsert_automation_rule(cloned)
        except Exception:
            for secret_id in created_secret_ids:
                self._secrets.delete(secret_id)
            raise
        self._publish(
            "automation.rule.created",
            cloned,
            source_rule_id=source.id,
            cloned=True,
        )
        return self.get_rule(clone_id)

    def set_enabled(self, rule_id: str, enabled: bool) -> AutomationRuleRecord:
        current = self.get_rule(rule_id)
        current.rule.enabled = bool(enabled)
        if enabled:
            current.rule.trigger_count = 0
            for runtime in self._runtimes.values():
                runtime.triggered.discard(rule_id)
                runtime.step_indexes.pop(rule_id, None)
                runtime.loop_indexes.pop(rule_id, None)
        else:
            self.cancel_rule(rule_id)
        updated = replace(current, updated_at=self._now())
        self._store.upsert_automation_rule(updated)
        self._publish("automation.rule.enabled", updated, enabled=enabled)
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id: str) -> None:
        record = self.get_rule(rule_id)
        self.cancel_rule(rule_id)
        self._delete_rule_secrets(record.rule)
        self._store.delete_automation_rule(rule_id)
        for runtime in self._runtimes.values():
            runtime.triggered.discard(rule_id)
            runtime.step_indexes.pop(rule_id, None)
            runtime.loop_indexes.pop(rule_id, None)
        self._publish("automation.rule.deleted", record)

    def public_rule(self, record: AutomationRuleRecord) -> AutoResponseRule:
        rule = deepcopy(record.rule)
        self._mask_rule_secrets(rule)
        return rule

    def statuses(self) -> list[AutomationSessionStatus]:
        return [
            AutomationSessionStatus(
                session_id=session_id,
                running_rule_ids=tuple(sorted(runtime.running)),
                waiting_rule_ids=tuple(
                    sorted(set(runtime.step_indexes) - runtime.running)
                ),
                triggered_rule_ids=tuple(sorted(runtime.triggered)),
            )
            for session_id, runtime in sorted(self._runtimes.items())
            if runtime.running or runtime.step_indexes or runtime.triggered
        ]

    def activities(self, limit: int = 100) -> list[AutomationActivityRecord]:
        return list(self._activities)[: max(0, min(300, int(limit)))]

    def preview_rule(
        self,
        rule: AutoResponseRule,
        *,
        session_id: str = "",
        sample_output: str = "",
        max_steps: int = 200,
    ) -> dict[str, object]:
        """Expand a rule without sleeping, writing to sessions, or resolving secrets."""

        candidate = deepcopy(rule)
        self._validate_regex_patterns(candidate)
        self._validate_action_variables(candidate.actions)
        limit = max(1, min(500, int(max_steps)))
        variables = self._initial_variables(session_id, sample_output)
        steps: list[dict[str, object]] = []
        warnings: list[str] = []
        truncated = False

        def public_variables() -> dict[str, object]:
            return {
                key: deepcopy(value)
                for key, value in variables.items()
                if key not in {"session", "device", "trigger", "output"}
            }

        def append_step(
            path: str,
            kind: str,
            title: str,
            detail: str = "",
            **extra: object,
        ) -> bool:
            nonlocal truncated
            if len(steps) >= limit:
                truncated = True
                if "预览步骤过多，结果已截断。" not in warnings:
                    warnings.append("预览步骤过多，结果已截断。")
                return False
            steps.append({
                "path": path,
                "kind": kind,
                "title": title,
                "detail": detail,
                "variables": public_variables(),
                **extra,
            })
            return True

        def preview_actions(
            actions: list[AutoResponseAction],
            prefix: str = "",
        ) -> str | None:
            nonlocal truncated
            for index, action in enumerate(actions, start=1):
                if truncated:
                    return None
                path = f"{prefix}.{index}" if prefix else str(index)
                if action.kind == "wait":
                    append_step(path, "wait", f"等待 {max(0, action.delay_ms)} ms")
                    continue
                if action.kind == "set":
                    self._set_variable(action, variables)
                    value = variables.get(action.variable_name.strip(), "")
                    append_step(
                        path,
                        "set",
                        f"{action.variable_name.strip()} = {SafeAutomationExpression.format_value(value)}",
                        operation=action.variable_operation,
                    )
                    continue
                if action.kind == "send":
                    rendered = self._render_variables(action.text, variables)
                    rendered = _SECRET_REFERENCE.sub(SECRET_MASK, rendered)
                    append_step(
                        path,
                        "send",
                        rendered or "（空发送）",
                        f"目标：{action.target}"
                        + (f" · 延迟 {action.delay_ms} ms" if action.delay_ms else "")
                        + (" · 追加 Enter" if action.append_enter else ""),
                        text=rendered,
                        target=action.target,
                        append_enter=action.append_enter,
                    )
                    continue
                if action.kind == "exit":
                    pattern = self._render_variables(action.exit_pattern, variables)
                    matched = bool(pattern) and self._pattern_matches(
                        candidate,
                        pattern,
                        sample_output,
                    )
                    append_step(
                        path,
                        "exit",
                        "退出条件已命中" if matched else "退出条件未命中",
                        pattern,
                        matched=matched,
                    )
                    if matched:
                        return action.exit_scope
                    continue
                if action.kind == "condition":
                    if action.condition_match_type == "expression":
                        matched = bool(SafeAutomationExpression.evaluate(
                            action.condition_pattern,
                            variables,
                        ))
                        rendered_pattern = action.condition_pattern
                    else:
                        rendered_pattern = self._render_variables(
                            action.condition_pattern,
                            variables,
                        )
                        matched = self._condition_matches(
                            candidate,
                            action,
                            sample_output,
                            rendered_pattern,
                        )
                    append_step(
                        path,
                        "condition",
                        "条件成立" if matched else "条件不成立",
                        rendered_pattern,
                        matched=matched,
                    )
                    if matched:
                        scope = preview_actions(action.actions, path)
                        if scope is not None:
                            return scope
                    continue
                if action.kind == "loop":
                    repeat_count = max(0, action.repeat_count)
                    preview_count = min(repeat_count, 20) if repeat_count else 3
                    if repeat_count == 0:
                        warnings.append("持续循环仅预览前 3 轮。")
                    elif repeat_count > preview_count:
                        warnings.append(f"循环 {repeat_count} 次，仅预览前 {preview_count} 轮。")
                    append_step(
                        path,
                        "loop",
                        "持续循环" if repeat_count == 0 else f"循环 {repeat_count} 次",
                        f"预览 {preview_count} 轮",
                    )
                    had_previous_loop = "loop" in variables
                    previous_loop = variables.get("loop")
                    try:
                        for iteration in range(preview_count):
                            variables["loop"] = {
                                "index": iteration + 1,
                                "index0": iteration,
                                "count": repeat_count,
                                "first": iteration == 0,
                                "last": repeat_count > 0 and iteration + 1 == repeat_count,
                            }
                            scope = preview_actions(
                                action.actions,
                                f"{path}[{iteration + 1}]",
                            )
                            if scope == "rule":
                                return "rule"
                            if scope == "loop" or truncated:
                                break
                    finally:
                        if had_previous_loop:
                            variables["loop"] = previous_loop
                        else:
                            variables.pop("loop", None)
            return None

        if candidate.actions:
            preview_actions(candidate.actions)
        elif candidate.steps:
            for step_index, step in enumerate(candidate.steps, start=1):
                if step.pattern:
                    append_step(
                        str(step_index),
                        "condition",
                        "等待终端输出",
                        step.pattern,
                    )
                for response_index, response in enumerate(step.response_texts, start=1):
                    rendered = self._render_variables(response, variables)
                    append_step(
                        f"{step_index}.{response_index}",
                        "send",
                        _SECRET_REFERENCE.sub(SECRET_MASK, rendered),
                    )
        else:
            rendered = self._render_variables(
                candidate.response_text or candidate.response,
                variables,
            )
            append_step("1", "send", _SECRET_REFERENCE.sub(SECRET_MASK, rendered))

        return {
            "steps": steps,
            "variables": public_variables(),
            "warnings": warnings,
            "truncated": truncated,
            "sample_output": sample_output,
        }

    def list_quick_send_buttons(self) -> list[QuickSendButtonRecord]:
        raw = self._store.get_meta(self.QUICK_SEND_META_KEY)
        if raw is None:
            records = [
                QuickSendButtonRecord(
                    id="QUICK-DEFAULT-CTRL-B",
                    name=button.name,
                    response_text=button.response_text,
                    append_enter=button.append_enter,
                )
                for button in default_quick_send_buttons()
            ]
            self._save_quick_send_buttons(records)
            return records
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            payload = []
        records: list[QuickSendButtonRecord] = []
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, dict):
                    continue
                button_id = str(item.get("id") or "").strip()
                name = str(item.get("name") or "").strip()
                response_text = str(item.get("response_text") or "")
                if not button_id or not name or not response_text:
                    continue
                records.append(QuickSendButtonRecord(
                    id=button_id,
                    name=name,
                    response_text=response_text,
                    append_enter=bool(item.get("append_enter", False)),
                    sensitive=bool(item.get("sensitive", False)),
                ))
        return records

    def create_quick_send_button(
        self,
        *,
        name: str,
        response_text: str,
        append_enter: bool = False,
        sensitive: bool = False,
    ) -> QuickSendButtonRecord:
        button_id = f"QUICK-{uuid4().hex[:12].upper()}"
        record = self._quick_send_candidate(
            button_id,
            name=name,
            response_text=response_text,
            append_enter=append_enter,
            sensitive=sensitive,
        )
        records = self.list_quick_send_buttons()
        records.append(record)
        self._save_quick_send_buttons(records)
        return record

    def update_quick_send_button(
        self,
        button_id: str,
        *,
        name: str,
        response_text: str,
        append_enter: bool = False,
        sensitive: bool = False,
    ) -> QuickSendButtonRecord:
        records = self.list_quick_send_buttons()
        current = next((item for item in records if item.id == button_id), None)
        if current is None:
            raise ResourceNotFoundError(
                f"Unknown quick-send button: {button_id}",
                details={"resource": "quick_send_button", "button_id": button_id},
            )
        effective_text = response_text
        if current.sensitive and response_text == SECRET_MASK:
            effective_text = SECRET_MASK
        updated = self._quick_send_candidate(
            button_id,
            name=name,
            response_text=effective_text,
            append_enter=append_enter,
            sensitive=sensitive,
            current=current,
        )
        self._save_quick_send_buttons([
            updated if item.id == button_id else item for item in records
        ])
        if current.sensitive and not updated.sensitive:
            self._secrets.delete(self._quick_send_secret_id(button_id))
        return updated

    def delete_quick_send_button(self, button_id: str) -> None:
        records = self.list_quick_send_buttons()
        current = next((item for item in records if item.id == button_id), None)
        if current is None:
            raise ResourceNotFoundError(
                f"Unknown quick-send button: {button_id}",
                details={"resource": "quick_send_button", "button_id": button_id},
            )
        self._save_quick_send_buttons([item for item in records if item.id != button_id])
        if current.sensitive:
            self._secrets.delete(self._quick_send_secret_id(button_id))

    async def send_quick_send_button(self, button_id: str, session_id: str) -> None:
        record = next(
            (item for item in self.list_quick_send_buttons() if item.id == button_id),
            None,
        )
        if record is None:
            raise ResourceNotFoundError(
                f"Unknown quick-send button: {button_id}",
                details={"resource": "quick_send_button", "button_id": button_id},
            )
        if record.sensitive:
            response = self._secrets.get(self._quick_send_secret_id(button_id))
            if response is None:
                raise UnsupportedOperationError("The quick-send secret is unavailable.")
        else:
            response = decode_response_text(
                record.response_text,
                append_enter=record.append_enter,
            )
        await self._sessions.write(session_id, response, origin="user")
        self._events.publish(
            "automation.quick_send.sent",
            resource_id=button_id,
            data={"button_id": button_id, "session_id": session_id, "name": record.name},
        )

    def import_legacy_state(self, state_path: Path) -> dict[str, int]:
        if not state_path.exists():
            return {"rules": 0, "secrets": 0}
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"rules": 0, "secrets": 0}
        if not isinstance(payload, dict):
            return {"rules": 0, "secrets": 0}
        self._import_legacy_quick_send_buttons(payload)
        if self._store.get_meta(self.LEGACY_IMPORT_KEY) is not None:
            return {"rules": 0, "secrets": 0}
        raw_rules = payload.get("auto_response_rules", [])
        imported = 0
        protected = 0
        if isinstance(raw_rules, list):
            for index, value in enumerate(raw_rules):
                rule = deserialize_auto_response_rule(value)
                if rule is None:
                    continue
                rule_id = f"AUTOMATION-LEGACY-{index + 1}"
                protected += self._protect_imported_secrets(rule_id, rule)
                now = self._now()
                self._store.upsert_automation_rule(
                    AutomationRuleRecord(rule_id, rule, now, now)
                )
                imported += 1
        result = {"rules": imported, "secrets": protected}
        self._store.set_meta(
            self.LEGACY_IMPORT_KEY,
            json.dumps({"imported_at": self._now(), **result}, ensure_ascii=False),
        )
        return result

    def _quick_send_candidate(
        self,
        button_id: str,
        *,
        name: str,
        response_text: str,
        append_enter: bool,
        sensitive: bool,
        current: QuickSendButtonRecord | None = None,
    ) -> QuickSendButtonRecord:
        normalized_name = name.strip()
        if not normalized_name:
            raise UnsupportedOperationError("A quick-send button name is required.")
        if len(normalized_name) > 160 or len(response_text) > 100_000:
            raise UnsupportedOperationError("The quick-send button is too large.")
        if sensitive:
            if response_text == SECRET_MASK and current is not None and current.sensitive:
                if self._secrets.get(self._quick_send_secret_id(button_id)) is None:
                    raise UnsupportedOperationError("The existing quick-send secret is unavailable.")
            else:
                decoded = decode_response_text(response_text, append_enter=append_enter)
                if not decoded:
                    raise UnsupportedOperationError("Quick-send content is required.")
                self._secrets.set(self._quick_send_secret_id(button_id), decoded)
            return QuickSendButtonRecord(
                id=button_id,
                name=normalized_name,
                response_text=SECRET_MASK,
                append_enter=append_enter,
                sensitive=True,
            )
        if not decode_response_text(response_text, append_enter=append_enter):
            raise UnsupportedOperationError("Quick-send content is required.")
        return QuickSendButtonRecord(
            id=button_id,
            name=normalized_name,
            response_text=response_text,
            append_enter=append_enter,
            sensitive=False,
        )

    def _save_quick_send_buttons(self, records: list[QuickSendButtonRecord]) -> None:
        self._store.set_meta(
            self.QUICK_SEND_META_KEY,
            json.dumps([
                {
                    "id": record.id,
                    "name": record.name,
                    "response_text": record.response_text,
                    "append_enter": record.append_enter,
                    "sensitive": record.sensitive,
                }
                for record in records
            ], ensure_ascii=False, separators=(",", ":")),
        )

    def _import_legacy_quick_send_buttons(self, payload: dict[str, Any]) -> None:
        if self._store.get_meta(self.LEGACY_QUICK_SEND_IMPORT_KEY) is not None:
            return
        raw_buttons = payload.get("quick_send_buttons")
        records: list[QuickSendButtonRecord] = []
        if isinstance(raw_buttons, list):
            for index, value in enumerate(raw_buttons):
                button = deserialize_quick_send_button(value)
                if button is None:
                    continue
                records.append(QuickSendButtonRecord(
                    id=f"QUICK-LEGACY-{index + 1}",
                    name=button.name,
                    response_text=button.response_text or button.response,
                    append_enter=button.append_enter,
                ))
        if records and self._store.get_meta(self.QUICK_SEND_META_KEY) is None:
            self._save_quick_send_buttons(records)
        self._store.set_meta(
            self.LEGACY_QUICK_SEND_IMPORT_KEY,
            json.dumps({"imported_at": self._now(), "buttons": len(records)}, ensure_ascii=False),
        )

    @staticmethod
    def _quick_send_secret_id(button_id: str) -> str:
        return f"quick-send/{button_id}"

    def handle_terminal_event(self, event: Any) -> None:
        event_type = str(getattr(event, "type", ""))
        session_id = str(getattr(event, "session_id", ""))
        if not session_id:
            return
        metadata = getattr(event, "metadata", {})
        if event_type == "terminal.input":
            origin = str(metadata.get("origin") or "user") if isinstance(metadata, dict) else "user"
            if origin != "automation":
                runtime = self._runtime(session_id)
                runtime.user_input_seen = True
                self.cancel_session(session_id, reason="manual_input")
            return
        if event_type == "terminal.output":
            data = str(getattr(event, "data", ""))
            if data:
                self._process_event(session_id, "output", data)
            return
        if event_type == "terminal.status":
            status = str(getattr(event, "status", "")).lower()
            if status == "connected":
                self._reset_transient_session_state(session_id)
                self._process_event(session_id, "connected", "")
            elif status in {"disconnected", "failed", "closed"}:
                self.cancel_session(session_id, reason=status)
                self._reset_transient_session_state(session_id)

    def trigger_rule(self, rule_id: str, session_id: str) -> None:
        record = self.get_rule(rule_id)
        session = self._require_session(session_id)
        if session.status != "connected":
            raise UnsupportedOperationError(
                "当前终端会话未连接，无法启动自动化规则。",
                details={"session_id": session_id, "status": session.status},
            )
        runtime = self._runtime(session_id)
        if rule_id in runtime.running or rule_id in runtime.step_indexes:
            raise UnsupportedOperationError("The automation rule is already running.")
        if not record.rule.enabled:
            raise UnsupportedOperationError("The automation rule is disabled.")
        self._start_rule(session_id, record, runtime.buffer, force=True)

    def cancel_rule(self, rule_id: str, *, reason: str = "rule_changed") -> None:
        for session_id, runtime in self._runtimes.items():
            self._cancel_tasks(session_id, runtime, rule_id, reason)

    def cancel_session(self, session_id: str, *, reason: str = "cancelled") -> None:
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return
        rule_ids = (
            set(runtime.tasks)
            | runtime.running
            | set(runtime.step_indexes)
            | set(runtime.loop_indexes)
            | set(runtime.waiting_tasks)
        )
        for rule_id in rule_ids:
            self._cancel_tasks(session_id, runtime, rule_id, reason)

    async def close(self) -> None:
        self.unbind_event_source()
        tasks: list[asyncio.Task[None]] = []
        for session_id, runtime in self._runtimes.items():
            tasks.extend(runtime.waiting_tasks.values())
            rule_ids = set(runtime.tasks) | set(runtime.waiting_tasks)
            for rule_id in rule_ids:
                tasks.extend(runtime.tasks.get(rule_id, ()))
                self._cancel_tasks(session_id, runtime, rule_id, "shutdown")
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _process_event(self, session_id: str, event_type: str, data: str) -> None:
        runtime = self._runtime(session_id)
        previous_buffer = runtime.buffer
        previous_visible = self._visible_terminal_text(previous_buffer)
        combined_visible = self._visible_terminal_text(previous_buffer + data)
        stable_prefix_length = self._common_prefix_length(
            previous_visible,
            combined_visible,
        )
        stable_visible = combined_visible[:stable_prefix_length]
        visible_message = combined_visible[stable_prefix_length:]
        if data:
            runtime.buffer = (runtime.buffer + data)[-4096:]
        for record in self.list_rules():
            if record.id in runtime.running or record.id in runtime.triggered:
                continue
            rule = record.rule
            if not rule.enabled or (rule.max_triggers and rule.trigger_count >= rule.max_triggers):
                continue
            if not runtime.user_input_seen and not auto_response_rule_allows_startup_trigger(rule):
                continue
            if self._rule_ready(
                record.id,
                rule,
                runtime,
                stable_visible,
                visible_message,
                event_type,
            ):
                self._start_rule(session_id, record, combined_visible)

    def _rule_ready(
        self,
        rule_id: str,
        rule: AutoResponseRule,
        runtime: _SessionRuntime,
        previous_buffer: str,
        data: str,
        event_type: str,
    ) -> bool:
        if rule.trigger_type == "manual" and rule_id not in runtime.step_indexes:
            return False
        if rule.trigger_type in {"immediate", "connected", "delay"}:
            return event_type == "connected"
        pattern = rule.pattern
        if not rule.actions:
            steps = self._effective_steps(rule)
            index = runtime.step_indexes.get(rule_id, 0)
            if index >= len(steps):
                index = 0
            pattern = steps[index].pattern
        if event_type != "output" or not pattern or not data:
            return False
        return self._incremental_pattern_matches(
            rule,
            pattern,
            previous_buffer,
            data,
        )

    def _start_rule(
        self,
        session_id: str,
        record: AutomationRuleRecord,
        scan_text: str,
        *,
        force: bool = False,
    ) -> None:
        runtime = self._runtime(session_id)
        if record.id in runtime.running:
            return
        self._cancel_waiting_task(runtime, record.id)
        rule = record.rule
        rule.trigger_count += 1
        if rule.max_triggers and rule.trigger_count >= rule.max_triggers:
            rule.enabled = False
        self._store.upsert_automation_rule(replace(record, rule=rule, updated_at=self._now()))
        runtime.running.add(record.id)
        task = asyncio.create_task(
            self._run_rule(session_id, record.id, scan_text, force=force),
            name=f"automation-{record.id}-{session_id}",
        )
        runtime.tasks.setdefault(record.id, set()).add(task)
        task.add_done_callback(
            lambda done, sid=session_id, rid=record.id: self._task_finished(sid, rid, done)
        )
        self._record_activity(
            "started",
            session_id=session_id,
            rule_id=record.id,
            name=rule.name,
            message="规则开始执行",
        )
        self._events.publish(
            "automation.rule.started",
            resource_id=record.id,
            data={"session_id": session_id, "rule_id": record.id, "name": rule.name},
        )

    async def _run_rule(
        self,
        session_id: str,
        rule_id: str,
        scan_text: str,
        *,
        force: bool,
    ) -> None:
        record = self.get_rule(rule_id)
        rule = record.rule
        if rule.trigger_type == "delay" and not force:
            await self._sleep(rule.trigger_delay_ms)
        if rule.delay_ms:
            await self._sleep(rule.delay_ms)
        exit_scope: str | None = None
        completed = True
        if rule.actions:
            exit_scope = await self._run_actions(
                session_id,
                rule_id,
                rule,
                rule.actions,
                scan_text,
                self._initial_variables(session_id, scan_text),
            )
        else:
            completed = await self._run_steps(
                session_id,
                rule_id,
                rule,
                force=force,
            )
            if not completed:
                self._schedule_step_timeout(session_id, rule_id, rule)
        latest = self.get_rule(rule_id)
        if exit_scope == "rule":
            latest.rule.enabled = False
        runtime = self._runtime(session_id)
        if completed and rule.once:
            runtime.triggered.add(rule_id)
            latest.rule.enabled = False
        self._store.upsert_automation_rule(replace(latest, updated_at=self._now()))
        activity_event = "completed" if completed else "waiting"
        activity_message = "规则执行完成"
        if not completed:
            step_index = runtime.step_indexes.get(rule_id, 0)
            steps = self._effective_steps(rule)
            timeout_ms = steps[step_index].timeout_ms if step_index < len(steps) else 0
            activity_message = f"等待第 {step_index + 1} 步终端输出"
            if timeout_ms:
                activity_message += f"（超时 {timeout_ms} ms）"
        self._record_activity(
            activity_event,
            session_id=session_id,
            rule_id=rule_id,
            name=rule.name,
            message=activity_message,
        )
        self._events.publish(
            f"automation.rule.{activity_event}",
            resource_id=rule_id,
            data={"session_id": session_id, "rule_id": rule_id, "name": rule.name},
        )

    async def _run_steps(
        self,
        session_id: str,
        rule_id: str,
        rule: AutoResponseRule,
        *,
        force: bool,
    ) -> bool:
        runtime = self._runtime(session_id)
        steps = self._effective_steps(rule)
        step_index = 0 if force else runtime.step_indexes.get(rule_id, 0)
        while step_index < len(steps):
            step = steps[step_index]
            for index, stored_response in enumerate(step.responses):
                delay = step.response_delays[index] if index < len(step.response_delays) else 0
                await self._sleep(delay)
                target = step.response_targets[index] if index < len(step.response_targets) else "source"
                target_id = self._require_target(session_id, target)
                response = stored_response
                if (
                    _SECRET_REFERENCE.search(stored_response) is None
                    and index < len(step.response_texts)
                ):
                    response_text = step.response_texts[index]
                    append_enter = (
                        step.response_append_enters[index]
                        if index < len(step.response_append_enters)
                        else False
                    )
                    if stored_response == response_text or append_enter:
                        response = decode_response_text(
                            response_text,
                            append_enter=append_enter,
                        )
                protected = _SECRET_REFERENCE.search(response) is not None
                payload = self._resolve_secret_text(response)
                if protected:
                    self._sessions.protect_sensitive_output(target_id, payload)
                await self._sessions.write(
                    target_id,
                    payload,
                    origin="automation",
                )
                self._publish_send(rule_id, session_id, target_id)
            step_index += 1
            if step_index >= len(steps):
                loops = runtime.loop_indexes.get(rule_id, 0) + 1
                if loops < self._loop_count(rule):
                    runtime.loop_indexes[rule_id] = loops
                    step_index = 0
                    if steps and not steps[0].pattern:
                        continue
                else:
                    runtime.step_indexes.pop(rule_id, None)
                    runtime.loop_indexes.pop(rule_id, None)
                    return True
            runtime.step_indexes[rule_id] = step_index
            if steps[step_index].pattern:
                return False
        return step_index >= len(steps)

    async def _run_actions(
        self,
        session_id: str,
        rule_id: str,
        rule: AutoResponseRule,
        actions: list[AutoResponseAction],
        scan_text: str,
        variables: dict[str, object],
    ) -> str | None:
        for action in actions:
            if action.kind == "wait":
                await self._sleep(action.delay_ms)
                continue
            if action.kind == "exit":
                current = self._visible_terminal_text(
                    self._runtime(session_id).buffer
                ) or scan_text
                self._update_output_variables(variables, current)
                exit_pattern = self._render_variables(action.exit_pattern, variables)
                if exit_pattern and self._pattern_matches(
                    rule, exit_pattern, current
                ):
                    return action.exit_scope
                continue
            if action.kind == "set":
                self._set_variable(action, variables)
                continue
            if action.kind == "send":
                await self._sleep(action.delay_ms)
                target_id = self._require_target(session_id, action.target)
                rendered = self._render_variables(action.text, variables)
                protected = _SECRET_REFERENCE.search(rendered) is not None
                text = self._resolve_secret_text(rendered)
                payload = decode_response_text(text, append_enter=action.append_enter)
                if payload:
                    if protected:
                        self._sessions.protect_sensitive_output(target_id, payload)
                    await self._sessions.write(target_id, payload, origin="automation")
                    self._publish_send(rule_id, session_id, target_id)
                continue
            if action.kind == "condition":
                current = self._visible_terminal_text(
                    self._runtime(session_id).buffer
                ) or scan_text
                self._update_output_variables(variables, current)
                if action.condition_match_type == "expression":
                    condition_matches = bool(SafeAutomationExpression.evaluate(
                        action.condition_pattern,
                        variables,
                    ))
                else:
                    condition_pattern = self._render_variables(
                        action.condition_pattern,
                        variables,
                    )
                    condition_matches = self._condition_matches(
                        rule,
                        action,
                        current,
                        condition_pattern,
                    )
                if condition_matches:
                    scope = await self._run_actions(
                        session_id,
                        rule_id,
                        rule,
                        action.actions,
                        current,
                        variables,
                    )
                    if scope is not None:
                        return scope
                continue
            if action.kind == "loop":
                iteration = 0
                had_previous_loop = "loop" in variables
                previous_loop = variables.get("loop")
                try:
                    while action.repeat_count == 0 or iteration < max(0, action.repeat_count):
                        variables["loop"] = {
                            "index": iteration + 1,
                            "index0": iteration,
                            "count": action.repeat_count,
                            "first": iteration == 0,
                            "last": (
                                action.repeat_count > 0
                                and iteration + 1 == action.repeat_count
                            ),
                        }
                        scope = await self._run_actions(
                            session_id,
                            rule_id,
                            rule,
                            action.actions,
                            self._visible_terminal_text(
                                self._runtime(session_id).buffer
                            ) or scan_text,
                            variables,
                        )
                        if scope == "rule":
                            return "rule"
                        if scope == "loop":
                            break
                        iteration += 1
                        await self._sleep(max(10, action.interval_ms) if action.repeat_count == 0 else action.interval_ms)
                finally:
                    if had_previous_loop:
                        variables["loop"] = previous_loop
                    else:
                        variables.pop("loop", None)
        return None

    def _task_finished(
        self,
        session_id: str,
        rule_id: str,
        task: asyncio.Task[None],
    ) -> None:
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return
        tasks = runtime.tasks.get(rule_id)
        if tasks is not None:
            tasks.discard(task)
            if not tasks:
                runtime.tasks.pop(rule_id, None)
                runtime.running.discard(rule_id)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            runtime.step_indexes.pop(rule_id, None)
            runtime.loop_indexes.pop(rule_id, None)
            rule_name = self._rule_name(rule_id)
            self._record_activity(
                "failed",
                session_id=session_id,
                rule_id=rule_id,
                name=rule_name,
                message=str(error),
            )
            self._events.publish(
                "automation.rule.failed",
                resource_id=rule_id,
                data={
                    "session_id": session_id,
                    "rule_id": rule_id,
                    "name": rule_name,
                    "message": str(error),
                },
            )

    def _schedule_step_timeout(
        self,
        session_id: str,
        rule_id: str,
        rule: AutoResponseRule,
    ) -> None:
        runtime = self._runtime(session_id)
        step_index = runtime.step_indexes.get(rule_id)
        steps = self._effective_steps(rule)
        if step_index is None or step_index >= len(steps):
            return
        timeout_ms = max(0, int(steps[step_index].timeout_ms or 0))
        self._cancel_waiting_task(runtime, rule_id)
        if timeout_ms <= 0:
            return
        task = asyncio.create_task(
            self._expire_step_wait(
                session_id,
                rule_id,
                rule.name,
                step_index,
                timeout_ms,
            ),
            name=f"automation-wait-{rule_id}-{session_id}",
        )
        runtime.waiting_tasks[rule_id] = task

    async def _expire_step_wait(
        self,
        session_id: str,
        rule_id: str,
        rule_name: str,
        step_index: int,
        timeout_ms: int,
    ) -> None:
        await self._sleep(timeout_ms)
        runtime = self._runtimes.get(session_id)
        if runtime is None:
            return
        current_task = asyncio.current_task()
        if runtime.waiting_tasks.get(rule_id) is not current_task:
            return
        runtime.waiting_tasks.pop(rule_id, None)
        if runtime.step_indexes.get(rule_id) != step_index:
            return
        runtime.step_indexes.pop(rule_id, None)
        runtime.loop_indexes.pop(rule_id, None)
        message = f"等待第 {step_index + 1} 步终端输出超时（{timeout_ms} ms）"
        self._record_activity(
            "failed",
            session_id=session_id,
            rule_id=rule_id,
            name=rule_name,
            message=message,
        )
        self._events.publish(
            "automation.rule.failed",
            resource_id=rule_id,
            data={
                "session_id": session_id,
                "rule_id": rule_id,
                "name": rule_name,
                "message": message,
                "reason": "step_timeout",
            },
        )

    @staticmethod
    def _cancel_waiting_task(runtime: _SessionRuntime, rule_id: str) -> None:
        task = runtime.waiting_tasks.pop(rule_id, None)
        if task is not None:
            task.cancel()

    def _cancel_tasks(
        self,
        session_id: str,
        runtime: _SessionRuntime,
        rule_id: str,
        reason: str,
    ) -> None:
        tasks = runtime.tasks.pop(rule_id, set())
        waiting_task = runtime.waiting_tasks.pop(rule_id, None)
        had_progress = bool(
            tasks
            or waiting_task
            or rule_id in runtime.running
            or rule_id in runtime.step_indexes
            or rule_id in runtime.loop_indexes
        )
        runtime.step_indexes.pop(rule_id, None)
        runtime.loop_indexes.pop(rule_id, None)
        runtime.running.discard(rule_id)
        if not had_progress:
            return
        for task in tasks:
            task.cancel()
        if waiting_task is not None:
            waiting_task.cancel()
        self._record_activity(
            "cancelled",
            session_id=session_id,
            rule_id=rule_id,
            name=self._rule_name(rule_id),
            message=f"规则已取消（{reason}）",
        )
        self._events.publish(
            "automation.rule.cancelled",
            resource_id=rule_id,
            data={"session_id": session_id, "rule_id": rule_id, "reason": reason},
        )

    def _resolve_target(self, source_id: str, target: str) -> str:
        normalized = self._normalize_target(target)
        sessions = self._sessions.list_sessions()
        source = next((item for item in sessions if item.id == source_id), None)
        if source is None:
            return ""
        if normalized in {"source", "current"}:
            return source_id
        if normalized == "next":
            same_device = [
                item
                for item in sessions
                if item.device_id == source.device_id and item.status == "connected"
            ]
            if len(same_device) < 2:
                return ""
            index = next(
                (position for position, item in enumerate(same_device) if item.id == source_id),
                0,
            )
            return same_device[(index + 1) % len(same_device)].id
        if normalized.startswith("title:"):
            needle = normalized[6:].strip().casefold()
            match = next(
                (item for item in sessions if needle in item.title.casefold()),
                None,
            )
            return match.id if match is not None else ""
        if normalized.startswith("session-id:"):
            session_id = normalized.removeprefix("session-id:").strip()
            match = next((item for item in sessions if item.id == session_id), None)
            return match.id if match is not None else ""
        if normalized.startswith("session:"):
            parts = normalized.split(":", 3)
            if len(parts) != 4:
                return ""
            _, device_id, kind, title = parts
            match = next(
                (
                    item
                    for item in sessions
                    if item.device_id == device_id
                    and item.kind == kind
                    and item.title == title
                ),
                None,
            )
            return match.id if match is not None else ""
        return ""

    def _require_target(self, source_id: str, target: str) -> str:
        target_id = self._resolve_target(source_id, target)
        if target_id:
            target_session = next(
                (item for item in self._sessions.list_sessions() if item.id == target_id),
                None,
            )
            if target_session is not None and target_session.status == "connected":
                return target_id
            raise UnsupportedOperationError(
                f"自动化目标终端未连接：{target}",
                details={"source_session_id": source_id, "target": target},
            )
        raise UnsupportedOperationError(
            f"自动化目标终端不存在或已关闭：{target}",
            details={"source_session_id": source_id, "target": target},
        )

    def _require_session(self, session_id: str) -> SessionRecord:
        session = next(
            (item for item in self._sessions.list_sessions() if item.id == session_id),
            None,
        )
        if session is None:
            raise ResourceNotFoundError(
                f"Unknown session: {session_id}",
                details={"resource": "session", "session_id": session_id},
            )
        return session

    def _rule_name(self, rule_id: str) -> str:
        record = self._store.get_automation_rule(rule_id)
        return record.rule.name if record is not None else "自动化规则"

    def _runtime(self, session_id: str) -> _SessionRuntime:
        return self._runtimes.setdefault(session_id, _SessionRuntime())

    def _reset_transient_session_state(self, session_id: str) -> None:
        runtime = self._runtime(session_id)
        for waiting_task in runtime.waiting_tasks.values():
            waiting_task.cancel()
        runtime.waiting_tasks.clear()
        runtime.buffer = ""
        runtime.user_input_seen = False
        runtime.step_indexes.clear()
        runtime.loop_indexes.clear()

    @staticmethod
    def _effective_steps(rule: AutoResponseRule) -> list[AutoResponseStep]:
        if rule.steps:
            return rule.steps
        return [
            AutoResponseStep(
                pattern=rule.pattern,
                responses=[rule.response],
                response_texts=[rule.response_text or rule.response],
                response_targets=["source"],
                response_delays=[0],
                response_append_enters=[rule.append_enter],
            )
        ]

    @staticmethod
    def _pattern_matches(rule: AutoResponseRule, pattern: str, output: str) -> bool:
        if not pattern:
            return False
        if rule.match_type == "regex":
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            try:
                return re.search(pattern, output, flags) is not None
            except re.error:
                return False
        haystack = output if rule.case_sensitive else output.casefold()
        needle = pattern if rule.case_sensitive else pattern.casefold()
        return needle in haystack

    @classmethod
    def _incremental_pattern_matches(
        cls,
        rule: AutoResponseRule,
        pattern: str,
        previous: str,
        message: str,
    ) -> bool:
        if rule.match_type != "regex":
            return cls._pattern_matches(
                rule,
                pattern,
                cls._scan_text(previous, message, pattern),
            )
        flags = 0 if rule.case_sensitive else re.IGNORECASE
        scan_text = previous + message
        boundary = len(previous)
        try:
            return any(
                match.end() > boundary
                or (match.start() == match.end() and match.start() >= boundary)
                for match in re.finditer(pattern, scan_text, flags)
            )
        except re.error:
            return False

    @classmethod
    def _condition_matches(
        cls,
        rule: AutoResponseRule,
        action: AutoResponseAction,
        output: str,
        pattern: str | None = None,
    ) -> bool:
        condition_pattern = action.condition_pattern if pattern is None else pattern
        if action.condition_match_type == "regex":
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            try:
                return re.search(condition_pattern, output, flags) is not None
            except re.error:
                return False
        haystack = output if rule.case_sensitive else output.casefold()
        needle = (
            condition_pattern
            if rule.case_sensitive
            else condition_pattern.casefold()
        )
        return bool(needle) and needle in haystack

    @classmethod
    def _render_variables(
        cls,
        value: str,
        variables: dict[str, object],
    ) -> str:
        return SafeAutomationExpression.render(value, variables)

    def _initial_variables(
        self,
        session_id: str,
        scan_text: str,
    ) -> dict[str, object]:
        session = next(
            (record for record in self._sessions.list_sessions() if record.id == session_id),
            None,
        )
        return {
            "session": {
                "id": session_id,
                "title": session.title if session is not None else "",
                "kind": session.kind if session is not None else "",
                "status": session.status if session is not None else "",
            },
            "device": {
                "id": session.device_id if session is not None else "",
            },
            "trigger": {"text": scan_text},
            "output": {"text": scan_text, "last": scan_text},
        }

    @staticmethod
    def _update_output_variables(
        variables: dict[str, object],
        output: str,
    ) -> None:
        variables["output"] = {"text": output, "last": output}

    @classmethod
    def _set_variable(
        cls,
        action: AutoResponseAction,
        variables: dict[str, object],
    ) -> None:
        name = action.variable_name.strip()
        evaluated = SafeAutomationExpression.value(action.variable_value, variables)
        operand = (
            cls._coerce_variable_value(evaluated)
            if isinstance(evaluated, str)
            else evaluated
        )
        if action.variable_operation == "set":
            variables[name] = operand
            return
        if name not in variables:
            raise UnsupportedOperationError(f"自动化变量尚未赋值：{name}")
        current = cls._numeric_variable(variables[name], name)
        value = cls._numeric_variable(operand, name)
        if action.variable_operation == "add":
            result = current + value
        elif action.variable_operation == "subtract":
            result = current - value
        else:
            result = current * value
        variables[name] = int(result) if result.is_integer() else result

    @staticmethod
    def _coerce_variable_value(value: str) -> object:
        text = value.strip()
        if re.fullmatch(r"[-+]?\d+", text):
            return int(text)
        if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", text):
            return float(text)
        if text.casefold() in {"true", "false"}:
            return text.casefold() == "true"
        return value

    @staticmethod
    def _numeric_variable(value: object, name: str) -> float:
        if isinstance(value, bool):
            raise UnsupportedOperationError(f"自动化变量不是数字：{name}")
        try:
            return float(value)
        except (TypeError, ValueError) as error:
            raise UnsupportedOperationError(
                f"自动化变量不是数字：{name}"
            ) from error

    @staticmethod
    def _scan_text(previous: str, message: str, pattern: str) -> str:
        overlap = max(len(pattern) - 1, 0)
        return previous[-overlap:] + message if message else previous

    @staticmethod
    def _visible_terminal_text(text: str) -> str:
        value = _ANSI_OSC_RE.sub("", ANSI_ESCAPE_RE.sub("", text))
        visible: list[str] = []
        for character in value:
            if character == "\b":
                if visible and visible[-1] != "\n":
                    visible.pop()
                continue
            if character == "\r":
                if not visible or visible[-1] != "\n":
                    visible.append("\n")
                continue
            if character == "\n":
                if not visible or visible[-1] != "\n":
                    visible.append("\n")
                continue
            if character == "\t" or character >= " ":
                visible.append(character)
        return "".join(visible)[-4096:]

    @staticmethod
    def _common_prefix_length(first: str, second: str) -> int:
        limit = min(len(first), len(second))
        index = 0
        while index < limit and first[index] == second[index]:
            index += 1
        return index

    @staticmethod
    def _loop_count(rule: AutoResponseRule) -> int:
        try:
            return max(1, min(10, int(rule.loop_count)))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _normalize_target(target: str) -> str:
        normalized = str(target or "source").strip()
        return normalized if normalized else "source"

    @staticmethod
    async def _sleep(delay_ms: int) -> None:
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)

    def _resolve_secret_text(self, value: str) -> str:
        def replace_secret(match: re.Match[str]) -> str:
            secret_id = match.group(1)
            secret = self._secrets.get(secret_id)
            if secret is None:
                raise UnsupportedOperationError(
                    f"自动化所需凭据不可用：{secret_id}",
                    details={"secret_id": secret_id},
                )
            return secret

        return _SECRET_REFERENCE.sub(replace_secret, value)

    def _protect_imported_secrets(self, rule_id: str, rule: AutoResponseRule) -> int:
        protected = 0

        def protect(pattern: str, value: str, path: str) -> str:
            nonlocal protected
            if not value or not _SENSITIVE_PROMPT.search(pattern):
                return value
            secret_id = f"automation:{rule_id}:{path}"
            self._secrets.set(secret_id, value)
            protected += 1
            return f"{{{{secret:{secret_id}}}}}"

        rule.response = protect(rule.pattern, rule.response, "response")
        if _SECRET_REFERENCE.fullmatch(rule.response):
            rule.response_text = rule.response
        for step_index, step in enumerate(rule.steps):
            for response_index, response in enumerate(step.responses):
                secured = protect(
                    step.pattern,
                    response,
                    f"steps:{step_index}:{response_index}",
                )
                step.responses[response_index] = secured
                if _SECRET_REFERENCE.fullmatch(secured):
                    if response_index < len(step.response_texts):
                        step.response_texts[response_index] = secured
        self._protect_action_secrets(rule_id, rule.pattern, rule.actions, protect, "actions")
        return protected

    def _protect_action_secrets(
        self,
        rule_id: str,
        inherited_pattern: str,
        actions: list[AutoResponseAction],
        protect: Callable[[str, str, str], str],
        prefix: str,
    ) -> None:
        del rule_id
        for index, action in enumerate(actions):
            pattern = action.condition_pattern or inherited_pattern
            if action.kind == "send":
                action.text = protect(pattern, action.text, f"{prefix}:{index}")
            if action.actions:
                self._protect_action_secrets(
                    "",
                    pattern,
                    action.actions,
                    protect,
                    f"{prefix}:{index}:actions",
                )

    def _validate_plaintext_secrets(self, rule: AutoResponseRule) -> None:
        def validate(pattern: str, value: str) -> None:
            if (
                value
                and value != SECRET_MASK
                and _SENSITIVE_PROMPT.search(pattern)
                and _SECRET_REFERENCE.search(value) is None
            ):
                raise UnsupportedOperationError(
                    "Sensitive auto-response values must be saved through the secure credential editor."
                )

        validate(rule.pattern, rule.response)
        for step in rule.steps:
            for response in step.responses:
                validate(step.pattern, response)
        self._validate_action_secrets(rule.pattern, rule.actions, validate)

    def _clone_rule_secrets(
        self,
        rule: AutoResponseRule,
        clone_rule_id: str,
        created_secret_ids: list[str],
    ) -> None:
        mapping: dict[str, str] = {}

        def clone_text(value: str) -> str:
            def replace_secret(match: re.Match[str]) -> str:
                source_secret_id = match.group(1)
                cloned_secret_id = mapping.get(source_secret_id)
                if cloned_secret_id is None:
                    secret = self._secrets.get(source_secret_id)
                    if secret is None:
                        raise UnsupportedOperationError(
                            f"无法复制规则，所需凭据不可用：{source_secret_id}",
                            details={"secret_id": source_secret_id},
                        )
                    cloned_secret_id = (
                        f"automation/{clone_rule_id}/secret-{len(mapping) + 1}"
                    )
                    self._secrets.set(cloned_secret_id, secret)
                    mapping[source_secret_id] = cloned_secret_id
                    created_secret_ids.append(cloned_secret_id)
                return f"{{{{secret:{cloned_secret_id}}}}}"

            return _SECRET_REFERENCE.sub(replace_secret, value)

        rule.response = clone_text(rule.response)
        rule.response_text = clone_text(rule.response_text)
        for step in rule.steps:
            step.responses = [clone_text(value) for value in step.responses]
            step.response_texts = [clone_text(value) for value in step.response_texts]

        def clone_actions(actions: list[AutoResponseAction]) -> None:
            for action in actions:
                action.text = clone_text(action.text)
                clone_actions(action.actions)

        clone_actions(rule.actions)

    def _validate_regex_patterns(self, rule: AutoResponseRule) -> None:
        flags = 0 if rule.case_sensitive else re.IGNORECASE

        def validate(pattern: str, field: str) -> None:
            if not pattern:
                return
            try:
                re.compile(_TEMPLATE_EXPRESSION.sub("value", pattern), flags)
            except re.error as error:
                raise UnsupportedOperationError(
                    f"正则表达式无效（{field}）：{error}",
                    details={"field": field, "pattern": pattern},
                ) from error

        if rule.match_type == "regex":
            validate(rule.pattern, "触发文本")
            for index, step in enumerate(rule.steps):
                validate(step.pattern, f"第 {index + 1} 步等待文本")

        def validate_actions(actions: list[AutoResponseAction], prefix: str) -> None:
            for index, action in enumerate(actions):
                field = f"{prefix}第 {index + 1} 个动作"
                if rule.match_type == "regex" and action.kind == "exit":
                    validate(action.exit_pattern, f"{field}的退出文本")
                if action.kind == "condition" and action.condition_match_type == "regex":
                    validate(action.condition_pattern, f"{field}的条件文本")
                validate_actions(action.actions, field)

        validate_actions(rule.actions, "动作流")

    def _validate_action_variables(
        self,
        actions: list[AutoResponseAction],
        prefix: str = "动作流",
    ) -> None:
        for index, action in enumerate(actions):
            field = f"{prefix}第 {index + 1} 个动作"
            if action.kind == "set":
                name = action.variable_name.strip()
                if not _VARIABLE_NAME.fullmatch(name):
                    raise UnsupportedOperationError(
                        f"变量名无效（{field}）：仅支持字母、数字和下划线，且不能以数字开头。"
                    )
                if name in {"session", "device", "trigger", "output", "loop"}:
                    raise UnsupportedOperationError(
                        f"变量名为系统保留名称（{field}）：{name}"
                    )
                if action.variable_operation not in {
                    "set",
                    "add",
                    "subtract",
                    "multiply",
                }:
                    raise UnsupportedOperationError(f"变量操作无效（{field}）。")
            self._validate_action_variables(action.actions, field)

    def _validate_action_secrets(
        self,
        inherited_pattern: str,
        actions: list[AutoResponseAction],
        validate: Callable[[str, str], None],
    ) -> None:
        for action in actions:
            pattern = action.condition_pattern or inherited_pattern
            if action.kind == "send":
                validate(pattern, action.text)
            self._validate_action_secrets(pattern, action.actions, validate)

    def _restore_masked_secrets(
        self,
        candidate: AutoResponseRule,
        current: AutoResponseRule,
    ) -> None:
        if candidate.response == SECRET_MASK and _SECRET_REFERENCE.search(current.response):
            candidate.response = current.response
            candidate.response_text = current.response_text
        for candidate_step, current_step in zip(candidate.steps, current.steps):
            for index, value in enumerate(candidate_step.responses):
                if (
                    value == SECRET_MASK
                    and index < len(current_step.responses)
                    and _SECRET_REFERENCE.search(current_step.responses[index])
                ):
                    candidate_step.responses[index] = current_step.responses[index]
                    if index < len(candidate_step.response_texts) and index < len(current_step.response_texts):
                        candidate_step.response_texts[index] = current_step.response_texts[index]
        self._restore_masked_action_secrets(candidate.actions, current.actions)

    def _restore_masked_action_secrets(
        self,
        candidates: list[AutoResponseAction],
        current: list[AutoResponseAction],
    ) -> None:
        for candidate, saved in zip(candidates, current):
            if candidate.text == SECRET_MASK and _SECRET_REFERENCE.search(saved.text):
                candidate.text = saved.text
            self._restore_masked_action_secrets(candidate.actions, saved.actions)

    def _mask_rule_secrets(self, rule: AutoResponseRule) -> None:
        rule.response = _SECRET_REFERENCE.sub(SECRET_MASK, rule.response)
        rule.response_text = _SECRET_REFERENCE.sub(SECRET_MASK, rule.response_text)
        for step in rule.steps:
            step.responses = [
                _SECRET_REFERENCE.sub(SECRET_MASK, value) for value in step.responses
            ]
            step.response_texts = [
                _SECRET_REFERENCE.sub(SECRET_MASK, value) for value in step.response_texts
            ]
        self._mask_action_secrets(rule.actions)

    def _mask_action_secrets(self, actions: list[AutoResponseAction]) -> None:
        for action in actions:
            action.text = _SECRET_REFERENCE.sub(SECRET_MASK, action.text)
            self._mask_action_secrets(action.actions)

    def _delete_rule_secrets(self, rule: AutoResponseRule) -> None:
        for value in self._rule_text_values(rule):
            for match in _SECRET_REFERENCE.finditer(value):
                self._secrets.delete(match.group(1))

    @staticmethod
    def _rule_text_values(rule: AutoResponseRule) -> list[str]:
        values = [rule.response, rule.response_text]
        for step in rule.steps:
            values.extend(step.responses)
            values.extend(step.response_texts)

        def action_values(actions: list[AutoResponseAction]) -> None:
            for action in actions:
                values.append(action.text)
                action_values(action.actions)

        action_values(rule.actions)
        return values

    def _publish_send(self, rule_id: str, source_id: str, target_id: str) -> None:
        self._record_activity(
            "sent",
            session_id=source_id,
            rule_id=rule_id,
            name=self._rule_name(rule_id),
            message="已发送自动化响应",
            target_session_id=target_id,
        )
        self._events.publish(
            "automation.response.sent",
            resource_id=rule_id,
            data={
                "rule_id": rule_id,
                "source_session_id": source_id,
                "target_session_id": target_id,
            },
        )

    def _publish(
        self,
        event_type: str,
        record: AutomationRuleRecord,
        **data: object,
    ) -> None:
        self._events.publish(
            event_type,
            resource_id=record.id,
            data={"rule_id": record.id, "name": record.rule.name, **data},
        )

    def _record_activity(
        self,
        event: str,
        *,
        session_id: str,
        rule_id: str,
        name: str,
        message: str,
        target_session_id: str = "",
    ) -> None:
        self._activities.appendleft(AutomationActivityRecord(
            id=f"ACTIVITY-{uuid4().hex[:12].upper()}",
            timestamp=self._now(),
            event=event,
            session_id=session_id,
            rule_id=rule_id,
            name=name,
            message=message,
            target_session_id=target_session_id,
        ))

    @staticmethod
    def serialize_rule(rule: AutoResponseRule) -> dict[str, object]:
        return serialize_auto_response_rule(rule)

    @staticmethod
    def deserialize_rule(payload: dict[str, object]) -> AutoResponseRule:
        rule = deserialize_auto_response_rule(payload)
        if rule is None:
            raise UnsupportedOperationError("The automation rule is invalid.")
        return rule

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
