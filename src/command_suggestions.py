"""Local command history and suggestion ranking."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any


DEFAULT_COMMAND_SUGGESTIONS = [
    "display version",
    "display current-configuration",
    "display interface brief",
    "display ip interface brief",
    "system-view",
    "save",
    "reboot",
]


@dataclass(slots=True)
class CommandHistoryItem:
    command: str
    device_id: str = ""
    session_kind: str = ""
    count: int = 0
    last_used_at: float = 0.0


def normalize_command_text(command: str) -> str:
    return " ".join(command.strip().split())


def record_command_history(
    history: list[CommandHistoryItem],
    command: str,
    *,
    device_id: str = "",
    session_kind: str = "",
    now: float | None = None,
    limit: int = 1000,
) -> list[CommandHistoryItem]:
    normalized = normalize_command_text(command)
    if not normalized:
        return history
    timestamp = time.time() if now is None else now
    for item in history:
        if item.command == normalized and item.device_id == device_id and item.session_kind == session_kind:
            item.count += 1
            item.last_used_at = timestamp
            break
    else:
        history.append(
            CommandHistoryItem(
                command=normalized,
                device_id=device_id,
                session_kind=session_kind,
                count=1,
                last_used_at=timestamp,
            )
        )
    history.sort(key=lambda item: (item.last_used_at, item.count), reverse=True)
    return history[:limit]


def suggest_commands(
    history: list[CommandHistoryItem],
    query: str,
    *,
    device_id: str = "",
    session_kind: str = "",
    limit: int = 5,
) -> list[str]:
    normalized_query = normalize_command_text(query).casefold()
    if not normalized_query:
        return []
    candidates: dict[str, tuple[float, int]] = {}
    now = time.time()

    for command in DEFAULT_COMMAND_SUGGESTIONS:
        score = _score_command(command, normalized_query, 0, 0, now, default=True)
        if score > 0:
            candidates[command] = _best_candidate(candidates.get(command), score, 2)

    for item in history:
        score = _score_command(item.command, normalized_query, item.count, item.last_used_at, now)
        if item.device_id and item.device_id == device_id:
            score += 30
        if item.session_kind and item.session_kind == session_kind:
            score += 12
        if score > 0:
            candidates[item.command] = _best_candidate(candidates.get(item.command), score, 0)

    ranked = [
        (command, score, source_priority)
        for command, (score, source_priority) in candidates.items()
        if score > 0 and command.casefold() != normalized_query
    ]
    ranked.sort(key=lambda pair: (-pair[1], pair[2], pair[0]))
    return [command for command, _score, _source_priority in ranked[:limit]]


def _best_candidate(current: tuple[float, int] | None, score: float, source_priority: int) -> tuple[float, int]:
    if current is None:
        return score, source_priority
    current_score, current_priority = current
    if score > current_score:
        return score, source_priority
    if score == current_score and source_priority < current_priority:
        return score, source_priority
    return current


def _score_command(
    command: str,
    query: str,
    count: int,
    last_used_at: float,
    now: float,
    *,
    default: bool = False,
) -> float:
    lowered = command.casefold()
    if lowered.startswith(query):
        score = 120.0
        first_word = lowered.split(maxsplit=1)[0]
        if first_word == query:
            score += 16
    elif query in lowered:
        score = 46.0
    elif _fuzzy_initials_match(lowered, query):
        score = 32.0
    else:
        return 0.0
    score += min(count, 50) * 3
    if last_used_at > 0:
        age_hours = max((now - last_used_at) / 3600, 0)
        score += max(0.0, 32.0 - age_hours)
    if default:
        score -= 18
    return score


def _fuzzy_initials_match(command: str, query: str) -> bool:
    initials = "".join(part[:1] for part in command.split() if part)
    return bool(initials and initials.startswith(query))


def serialize_command_history_item(item: CommandHistoryItem) -> dict[str, object]:
    return {
        "command": item.command,
        "device_id": item.device_id,
        "session_kind": item.session_kind,
        "count": item.count,
        "last_used_at": item.last_used_at,
    }


def deserialize_command_history_item(value: Any) -> CommandHistoryItem | None:
    if not isinstance(value, dict):
        return None
    command = normalize_command_text(str(value.get("command") or ""))
    if not command:
        return None
    try:
        count = max(0, int(value.get("count", 0)))
    except (TypeError, ValueError):
        count = 0
    try:
        last_used_at = max(0.0, float(value.get("last_used_at", 0.0)))
    except (TypeError, ValueError):
        last_used_at = 0.0
    return CommandHistoryItem(
        command=command,
        device_id=str(value.get("device_id") or ""),
        session_kind=str(value.get("session_kind") or ""),
        count=count,
        last_used_at=last_used_at,
    )
