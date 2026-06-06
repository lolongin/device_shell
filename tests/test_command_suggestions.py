from __future__ import annotations

from src.command_suggestions import (
    CommandHistoryItem,
    deserialize_command_history_item,
    record_command_history,
    serialize_command_history_item,
    suggest_commands,
)
from src.widgets.xterm_web_widget import XtermWebWidget


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


def test_command_suggestions_prefer_recent_same_device_history_over_defaults() -> None:
    history = [
        CommandHistoryItem(
            command="reset board",
            device_id="device-a",
            session_kind="device",
            count=1,
            last_used_at=500,
        )
    ]

    suggestions = suggest_commands(
        history,
        "re",
        device_id="device-a",
        session_kind="device",
    )

    assert suggestions[0] == "reset board"


def test_command_suggestions_prefer_prefix_matches_over_substring_matches() -> None:
    history = [
        CommandHistoryItem(command="show reboot history", count=10, last_used_at=500),
        CommandHistoryItem(command="reboot", count=1, last_used_at=100),
    ]

    suggestions = suggest_commands(history, "re")

    assert suggestions[0] == "reboot"


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


def test_xterm_command_suggestion_does_not_intercept_tab() -> None:
    terminal = XtermWebWidget.__new__(XtermWebWidget)
    sent: list[str] = []
    terminal._raw_sender = sent.append
    terminal._command_recorder = None
    terminal._command_suggestion_provider = lambda _query: "display version"
    terminal._enter_reconnect_handler = None
    terminal._pending_command_chars = list("di")
    terminal._current_command_suggestion = "display version"
    terminal._local_echo = False
    terminal._ready = False
    terminal._view = None

    terminal._handle_input("\t")

    assert sent == ["\t"]
    assert "".join(terminal._pending_command_chars) == "di"
    assert terminal._current_command_suggestion == ""


def test_xterm_records_tab_completed_command_from_terminal_line() -> None:
    terminal = XtermWebWidget.__new__(XtermWebWidget)
    recorded: list[str] = []
    sent: list[str] = []
    terminal._raw_sender = sent.append
    terminal._command_recorder = recorded.append
    terminal._command_suggestion_provider = None
    terminal._enter_reconnect_handler = None
    terminal._pending_command_chars = list("cd d")
    terminal._current_command_suggestion = ""
    terminal._local_echo = False
    terminal._ready = False
    terminal._view = None

    terminal._handle_input_with_terminal_line("\r", r"lon@HOST C:\Users\74527>cd d:\\")

    assert sent == ["\r"]
    assert recorded == [r"cd d:\\"]
    assert terminal._pending_command_chars == []
