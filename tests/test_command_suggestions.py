from __future__ import annotations

from src.command_suggestions import (
    CommandHistoryItem,
    deserialize_command_history_item,
    record_command_history,
    serialize_command_history_item,
    suggest_commands,
)


def test_command_history_records_and_ranks_recent_device_commands() -> None:
    history: list[CommandHistoryItem] = []
    history = record_command_history(
        history,
        "display version",
        device_id="device-a",
        session_kind="device",
        now=100,
    )
    history = record_command_history(
        history,
        "display interface brief",
        device_id="device-b",
        session_kind="device",
        now=200,
    )
    history = record_command_history(
        history,
        "display version",
        device_id="device-a",
        session_kind="device",
        now=300,
    )

    suggestions = suggest_commands(
        history,
        "dis",
        device_id="device-a",
        session_kind="device",
    )

    assert suggestions[0] == "display version"
    assert "display interface brief" in suggestions
    assert history[0].command == "display version"
    assert history[0].count == 2


def test_command_suggestions_support_substring_and_defaults() -> None:
    suggestions = suggest_commands([], "version")

    assert suggestions[0] == "display version"


def test_command_history_round_trip() -> None:
    item = CommandHistoryItem(
        command="display current-configuration",
        device_id="device-a",
        session_kind="linux",
        count=3,
        last_used_at=123.5,
    )

    loaded = deserialize_command_history_item(serialize_command_history_item(item))

    assert loaded == item
