from __future__ import annotations

import time

from device_tui.application.commands.suggestions import (
    CommandHistoryItem,
    deserialize_command_history_item,
    infer_completed_command_from_terminal_line,
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


def test_command_suggestions_include_common_shell_defaults() -> None:
    suggestions = suggest_commands([], "ls")

    assert suggestions[0] == "ls -la"


def test_command_suggestions_use_environment_specific_defaults() -> None:
    linux = suggest_commands([], "ip", environment="linux")
    network = suggest_commands([], "ls", environment="network")

    assert linux[0] == "ip addr"
    assert network == []


def test_most_used_candidate_stays_first_within_environment() -> None:
    history = [
        CommandHistoryItem(command="display interface brief", count=8),
        CommandHistoryItem(command="display ip interface brief", count=1),
    ]

    suggestions = suggest_commands(history, "display", environment="network")

    assert suggestions[0] == "display interface brief"


def test_command_suggestions_can_use_history_only_for_terminal_hints() -> None:
    history = [CommandHistoryItem(command="display version", count=1, last_used_at=100)]

    assert suggest_commands(history, "dis", include_defaults=False) == ["display version"]
    assert suggest_commands([], "dis", include_defaults=False) == []


def test_command_suggestions_ignore_history_suffix_after_path_prefix() -> None:
    history = [CommandHistoryItem(command="cat /proc/disp status", count=1, last_used_at=100)]

    assert suggest_commands(history, "cat /proc/d", include_defaults=False) == []


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


def test_command_suggestions_keep_most_used_command_ahead_of_recent_one() -> None:
    history = [
        CommandHistoryItem(command="show interfaces", count=5, last_used_at=1),
        CommandHistoryItem(command="show version", count=1, last_used_at=time.time()),
    ]

    suggestions = suggest_commands(history, "show", include_defaults=False)

    assert suggestions[0] == "show interfaces"


def test_command_suggestions_match_tokens_and_keep_full_prefix_first() -> None:
    history = [
        CommandHistoryItem(command="display interface brief", count=1, last_used_at=100),
        CommandHistoryItem(command="display ip interface brief", count=50, last_used_at=500),
    ]

    suggestions = suggest_commands(history, "display int", include_defaults=False)

    assert suggestions == ["display interface brief"]


def test_command_suggestions_deduplicate_case_variants_and_clamp_limit() -> None:
    history = [
        CommandHistoryItem(command="Display Version", count=1, last_used_at=100),
        CommandHistoryItem(command="display version", count=3, last_used_at=200),
    ]

    assert suggest_commands(history, "dis", include_defaults=False) == ["display version"]
    assert suggest_commands(history, "dis", include_defaults=False, limit=-1) == []


def test_command_history_negative_limit_returns_no_entries() -> None:
    history = [CommandHistoryItem(command="display version", count=1, last_used_at=100)]

    assert record_command_history(history, "save", now=200, limit=-1) == []


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


def test_infer_completed_command_from_terminal_line_supports_token_completion() -> None:
    assert (
        infer_completed_command_from_terminal_line("dis", "<RTN-1>display interface brief")
        == "display interface brief"
    )
    assert (
        infer_completed_command_from_terminal_line("dis int", "[~RTN-1]display interface brief")
        == "display interface brief"
    )
    assert (
        infer_completed_command_from_terminal_line("cd d", r"lon@HOST C:\Users\74527>cd d:\\")
        == r"cd d:\\"
    )
    assert (
        infer_completed_command_from_terminal_line("cat /proc/k", "root@box:~# cat /proc/kbox")
        == "cat /proc/kbox"
    )


def test_infer_completed_command_from_terminal_line_ignores_history_suffix_after_path() -> None:
    assert (
        infer_completed_command_from_terminal_line(
            "cat /proc/d",
            "root@box:~# cat /proc/disp status",
        )
        == ""
    )


def test_infer_completed_command_from_terminal_line_refreshes_after_shell_history_recall() -> None:
    assert (
        infer_completed_command_from_terminal_line(
            "display version",
            "root@box:~# display interface brief",
        )
        == "display interface brief"
    )
