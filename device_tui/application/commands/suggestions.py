"""Local command history and suggestion ranking."""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Any


LINUX_COMMAND_SUGGESTIONS = [
    "ls -la",
    "pwd",
    "ip addr",
    "ip route",
    "systemctl status",
]

NETWORK_COMMAND_SUGGESTIONS = [
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


def infer_completed_command_from_terminal_line(prefix: str, terminal_line: str) -> str:
    """Infer a tab-completed command from the current terminal line."""
    typed = prefix.strip()
    line = terminal_line.rstrip()
    if not typed or not line:
        return ""

    candidates = _terminal_line_command_candidates(line, typed)
    for candidate in candidates:
        if _candidate_matches_typed_prefix(candidate, typed):
            return candidate.strip()
    # A shell history recall can replace the whole input line. In that case
    # the shadow model still contains the previous command, so prefix matching
    # cannot identify the command that is actually waiting at the prompt.
    # Trust the prompt suffix for ordinary commands; path queries stay
    # conservative because old arguments must never be copied into history.
    if not any("/" in part or "\\" in part for part in typed.casefold().split()):
        for delimiter in (">", "#", "$", "]"):
            index = line.rfind(delimiter)
            if index >= 0:
                current = line[index + 1 :].strip()
                if current:
                    return current
    return ""


def _terminal_line_command_candidates(line: str, typed: str) -> list[str]:
    candidates: list[str] = []

    def add(value: str) -> None:
        candidate = value.strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    for delimiter in (">", "#", "$", "]"):
        index = line.rfind(delimiter)
        if index >= 0:
            add(line[index + 1 :])

    typed_index = line.casefold().rfind(typed.casefold())
    if typed_index >= 0:
        add(line[typed_index:])

    add(line)
    for match in re.finditer(r"(?<!\S)\S", line):
        add(line[match.start() :])
    return candidates


def _candidate_matches_typed_prefix(candidate: str, typed: str) -> bool:
    candidate_folded = candidate.casefold()
    typed_folded = typed.casefold()
    candidate_parts = candidate_folded.split()
    typed_parts = typed_folded.split()
    # Shell history suggestions can be rendered after a partially typed path
    # (for example ``cat /proc/d`` followed by ``isp status``). Treating the
    # extra words as a completed command would record text the user never
    # entered. Path completion remains valid when it only extends the path
    # token itself.
    if (
        any("/" in part or "\\" in part for part in typed_parts)
        and len(candidate_parts) > len(typed_parts)
    ):
        return False
    if candidate_folded.startswith(typed_folded):
        return True

    if not candidate_parts or len(candidate_parts) < len(typed_parts):
        return False
    return all(
        candidate_part.startswith(typed_part)
        for candidate_part, typed_part in zip(candidate_parts, typed_parts)
    )


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
    history_limit = max(0, int(limit))
    if not normalized:
        return history
    if history_limit == 0:
        return []
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
    return history[:history_limit]


def suggest_commands(
    history: list[CommandHistoryItem],
    query: str,
    *,
    device_id: str = "",
    session_kind: str = "",
    limit: int = 5,
    include_defaults: bool = True,
    environment: str = "auto",
) -> list[str]:
    normalized_query = normalize_command_text(query).casefold()
    result_limit = max(0, int(limit))
    if not normalized_query or result_limit == 0:
        return []
    # Key candidates by their folded text. History can contain entries written
    # with different casing (or imported from older stores), but the terminal
    # should only show one prediction for the same command.
    # Keep frequency and context as separate ranking dimensions. Folding them
    # into one score makes a recent but rarely used command able to displace a
    # command the user relies on repeatedly.
    candidates: dict[str, tuple[str, float, int, int, int, float]] = {}
    now = time.time()

    defaults = _default_commands_for_environment(environment)

    def add_candidate(
        command: str,
        score: float,
        source_priority: int,
        *,
        count: int = 0,
        match_tier: int,
        context_score: float = 0.0,
    ) -> None:
        if score <= 0:
            return
        key = command.casefold()
        current = candidates.get(key)
        candidate = (command, score, source_priority, max(count, 0), match_tier, context_score)
        if current is None:
            candidates[key] = candidate
            return
        if _candidate_rank(candidate) < _candidate_rank(current):
            candidates[key] = candidate

    if include_defaults:
        for command in defaults:
            score = _score_command(command, normalized_query, 0, 0, now, default=True)
            add_candidate(
                command,
                score,
                2,
                match_tier=_match_tier(command, normalized_query),
            )

    for item in history:
        if _path_query_has_history_suffix(item.command, normalized_query):
            continue
        score = _score_command(item.command, normalized_query, item.count, item.last_used_at, now)
        context_score = 0.0
        if item.device_id and item.device_id == device_id:
            context_score += 30
        if item.session_kind and item.session_kind == session_kind:
            context_score += 12
        add_candidate(
            item.command,
            score + context_score,
            0,
            count=item.count,
            match_tier=_match_tier(item.command, normalized_query),
            context_score=context_score,
        )

    ranked = [
        (command, score, source_priority, count, match_tier, context_score)
        for command, score, source_priority, count, match_tier, context_score in candidates.values()
        if command.casefold() != normalized_query
    ]
    ranked.sort(key=lambda pair: (-pair[4], -pair[3], -pair[5], -pair[1], pair[2], pair[0]))
    return [command for command, *_details in ranked[:result_limit]]


def _default_commands_for_environment(environment: str) -> list[str]:
    normalized = environment.strip().casefold()
    if normalized in {"linux", "unix"}:
        return LINUX_COMMAND_SUGGESTIONS
    if normalized in {"network", "vrp", "device"}:
        return NETWORK_COMMAND_SUGGESTIONS
    return [*LINUX_COMMAND_SUGGESTIONS, *NETWORK_COMMAND_SUGGESTIONS]


def _candidate_rank(candidate: tuple[str, float, int, int, int, float]) -> tuple[float, float, float, float, int]:
    _command, score, source_priority, count, match_tier, context_score = candidate
    return (-match_tier, -count, -context_score, -score, source_priority)


def _match_tier(command: str, query: str) -> int:
    lowered = command.casefold()
    if lowered.startswith(query):
        return 4
    if _token_prefix_match(lowered, query):
        return 3
    if query in lowered:
        return 2
    if _fuzzy_initials_match(lowered, query):
        return 1
    return 0


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
    match_tier = _match_tier(lowered, query)
    if match_tier == 4:
        # Keep match quality in a separate, wide tier. A high-frequency
        # fuzzy match must not displace a low-frequency exact prefix match.
        score = 4_000.0
        first_word = lowered.split(maxsplit=1)[0]
        if first_word == query:
            score += 80.0
    elif match_tier == 3:
        # Match the command word by word, e.g. ``display int`` ->
        # ``display interface brief``. Keep this below a full-line prefix so
        # the most obvious completion still wins when both are available.
        score = 3_000.0
    elif match_tier == 2:
        score = 2_000.0
    elif match_tier == 1:
        score = 1_000.0
    else:
        return 0.0
    # Frequency is deliberately stronger than freshness within the same
    # match tier, so the most-used command remains the stable top prediction.
    score += min(max(count, 0), 50) * 10
    if last_used_at > 0:
        age_days = max((now - last_used_at) / 86_400, 0)
        score += max(0.0, 8.0 - age_days)
    if default:
        score -= 18
    return score


def _token_prefix_match(command: str, query: str) -> bool:
    """Return whether every typed token prefixes the corresponding command token."""
    command_parts = command.split()
    query_parts = query.split()
    return bool(query_parts) and len(command_parts) >= len(query_parts) and all(
        command_part.startswith(query_part)
        for command_part, query_part in zip(command_parts, query_parts)
    )


def _path_query_has_history_suffix(command: str, query: str) -> bool:
    """Reject history candidates that append old arguments after a path prefix."""
    command_parts = command.casefold().split()
    query_parts = query.casefold().split()
    if not query_parts or not command_parts:
        return False
    if not any("/" in part or "\\" in part for part in query_parts):
        return False
    return (
        len(command_parts) > len(query_parts)
        and command.casefold().startswith(query.casefold())
    )


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
