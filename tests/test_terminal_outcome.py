from __future__ import annotations

from device_tui.application.terminal.outcome import (
    classify_command_outcome,
    classify_terminal_prompt,
)


def test_prompt_classifier_prioritizes_interaction_over_bracket_prompt() -> None:
    confirmation = classify_terminal_prompt("Copy file? [Y/N]:")
    system_view = classify_terminal_prompt("entered\r\n[HUAWEI]")

    assert confirmation is not None
    assert confirmation.type == "confirmation_prompt"
    assert system_view is not None
    assert system_view.type == "command_prompt"
    assert system_view.view == "system"


def test_prompt_classifier_detects_host_key_and_control_menu_input() -> None:
    host_key = classify_terminal_prompt(
        "Are you sure you want to continue connecting (yes/no/[fingerprint])?"
    )
    menu = classify_terminal_prompt("Press Ctrl+B to enter BOOT menu: ")

    assert host_key is not None
    assert host_key.type == "credential_prompt"
    assert menu is not None
    assert menu.type == "unknown_input_prompt"


def test_outcome_distinguishes_failure_from_finished_state() -> None:
    outcome = classify_command_outcome(
        "bad command\r\nError: Unrecognized command\r\n<HUAWEI>",
        lifecycle_status="completed",
        command="bad command",
        matched="<HUAWEI>",
        duration_ms=12.3,
    )

    assert outcome["status"] == "failure"
    assert outcome["finished"] is True
    assert outcome["errors"][0]["code"] == "command_rejected"
    assert outcome["result_text"] == "Error: Unrecognized command"


def test_outcome_marks_confirmation_as_interaction_required() -> None:
    outcome = classify_command_outcome(
        "copy flash:/a flash:/b\r\nContinue? [Y/N]:",
        lifecycle_status="running",
        command="copy flash:/a flash:/b",
    )

    assert outcome["status"] == "interaction_required"
    assert outcome["finished"] is False
    assert outcome["prompt"]["type"] == "confirmation_prompt"
    assert outcome["basis"] == "confirmation_prompt"


def test_outcome_does_not_treat_idle_completion_as_success() -> None:
    outcome = classify_command_outcome(
        "partial output without prompt",
        lifecycle_status="completed",
        command="custom command",
        matched="idle",
    )

    assert outcome["status"] == "unknown"
    assert outcome["finished"] is False
    assert outcome["basis"] == "completion_without_terminal_evidence"
