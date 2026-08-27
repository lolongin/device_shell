from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pytest

from device_tui.application.terminal.orchestration import (
    TerminalExecutionCoordinator,
    TerminalInput,
    TerminalPlanError,
    build_batch_plan,
    parse_terminal_plan,
)


@dataclass
class ManualScheduler:
    now: float = 0.0
    callbacks: list[tuple[float, Callable[[], None]]] = field(default_factory=list)

    def schedule(self, delay_ms: int, callback: Callable[[], None]) -> None:
        self.callbacks.append((self.now + delay_ms / 1000, callback))

    def advance(self, seconds: float) -> None:
        target = self.now + seconds
        while True:
            due = [item for item in self.callbacks if item[0] <= target]
            if not due:
                break
            at, callback = min(due, key=lambda item: item[0])
            self.callbacks.remove((at, callback))
            self.now = at
            callback()
        self.now = target


@dataclass
class Harness:
    scheduler: ManualScheduler = field(default_factory=ManualScheduler)
    sent: list[tuple[str, TerminalInput, str]] = field(default_factory=list)

    def coordinator(self) -> TerminalExecutionCoordinator:
        return TerminalExecutionCoordinator(
            send_input=lambda session_id, payload, execution_id: self.sent.append(
                (session_id, payload, execution_id)
            ),
            resolve_secret=lambda name: {
                "transfer.username": "device-user",
                "transfer.password": "super-secret",
            }[name],
            schedule=self.scheduler.schedule,
            clock=lambda: self.scheduler.now,
        )


def test_batch_plan_arms_prompt_before_sending() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = build_batch_plan(["display version"])

    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=plan,
    )

    assert harness.sent[0][1].text == "display version\r"
    assert runner.current_step == 1

    coordinator.on_output("tab-1", "SimOS V2\n<sim> ")

    result = runner.public_dict()
    assert result["status"] == "completed"
    assert result["steps"][1]["matched"] == "<sim>"
    assert coordinator.active_execution_id("tab-1") == ""


def test_vrp_bracket_ftp_prompt_completes_login_step() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "ftp 192.0.2.10 2121"},
            {"type": "expect", "success": ["ftp_prompt"]},
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)
    coordinator.on_output("tab-1", "230 User logged in.\r\n[ftp] ")

    assert runner.public_dict()["status"] == "completed"


def test_interactive_plan_handles_split_prompts_and_local_secrets() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "ftp 192.0.2.10 2121"},
            {
                "type": "expect",
                "success": ["ftp_prompt"],
                "responses": [
                    {
                        "match": "username_prompt",
                        "secret_ref": "transfer.username",
                    },
                    {
                        "match": "password_prompt",
                        "secret_ref": "transfer.password",
                    },
                ],
                "failures": ["Login incorrect", "530 "],
            },
        ]
    )

    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=plan,
    )
    coordinator.on_output("tab-1", "Connected\nUs")
    assert len(harness.sent) == 1
    coordinator.on_output("tab-1", "er: ")
    coordinator.on_output("tab-1", "Pass")
    coordinator.on_output("tab-1", "word: ")
    assert coordinator.redact_output("tab-1", "echo super-secret") == "echo ***"
    coordinator.on_output("tab-1", "230 User logged in.\nftp> ")

    assert [item[1].text for item in harness.sent] == [
        "ftp 192.0.2.10 2121\r",
        "device-user\r",
        "super-secret\r",
    ]
    assert not harness.sent[1][1].sensitive
    assert harness.sent[2][1].secret_ref == "transfer.password"
    result = runner.public_dict()
    assert result["status"] == "completed"
    assert result["steps"][1]["response_count"] == 2
    assert "super-secret" not in str(result)


def test_short_username_is_not_used_as_a_global_output_mask() -> None:
    harness = Harness()
    coordinator = TerminalExecutionCoordinator(
        send_input=lambda session_id, payload, execution_id: harness.sent.append(
            (session_id, payload, execution_id)
        ),
        resolve_secret=lambda name: "p" if name == "transfer.username" else "super-secret",
        schedule=harness.scheduler.schedule,
        clock=lambda: harness.scheduler.now,
    )
    plan = parse_terminal_plan(
        [
            {"type": "send", "secret_ref": "transfer.username"},
            {"type": "expect", "success": ["device_prompt"]},
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)

    # The first send happens during start; the username is allowed to remain
    # visible while later output containing the same character stays intact.
    assert harness.sent[0][1].text == "p\r"
    assert not harness.sent[0][1].sensitive
    assert coordinator.redact_output("tab-1", "copy package.cc\r\n") == "copy package.cc\r\n"


def test_login_does_not_send_password_from_same_coalesced_output_event() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "ftp 192.0.2.10 2121"},
            {
                "type": "expect",
                "success": ["ftp_prompt"],
                "responses": [
                    {"match": "username_prompt", "secret_ref": "transfer.username"},
                    {"match": "password_prompt", "secret_ref": "transfer.password"},
                ],
            },
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)
    coordinator.on_output("tab-1", "Connected\r\r\nUser(10.10.10.1):(none):\r\r\nPassword: ")
    assert [item[1].text for item in harness.sent] == [
        "ftp 192.0.2.10 2121\r",
        "device-user\r",
    ]
    coordinator.on_output("tab-1", "Password: ")
    assert [item[1].text for item in harness.sent] == [
        "ftp 192.0.2.10 2121\r",
        "device-user\r",
        "super-secret\r",
    ]
    coordinator.on_output("tab-1", "230 User logged in.\nftp> ")
    assert runner.public_dict()["status"] == "completed"


def test_login_waits_for_a_fresh_output_after_coalesced_vrp_prompts() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "ftp 192.0.2.10 2121"},
            {
                "type": "expect",
                "success": ["ftp_prompt"],
                "responses": [
                    {"match": "username_prompt", "secret_ref": "transfer.username"},
                    {"match": "password_prompt", "secret_ref": "transfer.password"},
                ],
            },
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)
    coordinator.on_output("tab-1", "User(10.10.10.1:(none)):\nPassword: ")
    assert [item[1].text for item in harness.sent] == [
        "ftp 192.0.2.10 2121\r",
        "device-user\r",
    ]
    # The password prompt was coalesced with the username prompt. It is
    # replayed after the username write has had a chance to reach the device.
    harness.scheduler.advance(1)
    assert [item[1].text for item in harness.sent] == [
        "ftp 192.0.2.10 2121\r",
        "device-user\r",
        "super-secret\r",
    ]
    coordinator.on_output("tab-1", "230 User logged in.\nftp> ")
    assert runner.public_dict()["status"] == "completed"


def test_login_handles_vrp_prompts_on_one_output_line() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "ftp 192.0.2.10 2121"},
            {
                "type": "expect",
                "success": ["ftp_prompt"],
                "responses": [
                    {"match": "username_prompt", "secret_ref": "transfer.username"},
                    {"match": "password_prompt", "secret_ref": "transfer.password"},
                ],
            },
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)
    coordinator.on_output("tab-1", "User(10.10.10.1):(none): Password: ")
    assert [item[1].text for item in harness.sent] == [
        "ftp 192.0.2.10 2121\r",
        "device-user\r",
    ]
    harness.scheduler.advance(0.12)
    assert harness.sent[-1][1].text == "super-secret\r"
    coordinator.on_output("tab-1", "230 User logged in.\nftp> ")
    assert runner.public_dict()["status"] == "completed"


def test_secret_send_affixes_build_linux_sftp_command_and_redact_username() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {
                "type": "send",
                "secret_ref": "transfer.username",
                "secret_prefix": "sftp -P 2222 ",
                "secret_suffix": "@192.0.2.10",
                "label": "connect sftp",
            },
            {
                "type": "expect",
                "success": ["sftp_prompt"],
                "responses": [
                    {"match": "password_prompt", "secret_ref": "transfer.password"}
                ],
            },
        ]
    )

    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)
    assert harness.sent[0][1].text == "sftp -P 2222 device-user@192.0.2.10\r"
    assert not harness.sent[0][1].sensitive
    assert coordinator.redact_output("tab-1", "device-user@192.0.2.10's password:") == "device-user@192.0.2.10's password:"

    coordinator.on_output("tab-1", "device-user@192.0.2.10's password: ")
    coordinator.on_output("tab-1", "Connected\nsftp> ")
    assert runner.public_dict()["status"] == "completed"


def test_linux_ftp_name_prompt_with_default_user_is_detected() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "ftp 192.0.2.10 2121"},
            {
                "type": "expect",
                "success": ["ftp_prompt"],
                "responses": [
                    {"match": "username_prompt", "secret_ref": "transfer.username"},
                ],
            },
        ]
    )

    coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)
    coordinator.on_output("tab-1", "Name (192.0.2.10:local-user): ")

    assert harness.sent[-1][1].text == "device-user\r"


def test_response_limit_stops_repeated_prompt() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "display current-configuration"},
            {
                "type": "expect",
                "success": ["device_prompt"],
                "responses": [
                    {
                        "match": "pagination_prompt",
                        "control": "space",
                        "append_enter": False,
                        "max_matches": 1,
                    }
                ],
            },
        ]
    )
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=plan,
    )

    coordinator.on_output("tab-1", "page 1\n---- More ----")
    coordinator.on_output("tab-1", "page 2\n---- More ----")

    assert runner.public_dict()["error_code"] == "response_limit_exceeded"
    assert [item[1].text for item in harness.sent][-1] == " "


def test_session_lease_rejects_second_execution_and_user_input_cancels() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = build_batch_plan(["display version"])
    first = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=plan,
    )

    with pytest.raises(TerminalPlanError, match="正在执行其他任务") as exc_info:
        coordinator.start(
            session_id="tab-1",
            device_id="device-1",
            plan=plan,
        )

    assert exc_info.value.code == "session_busy"
    assert coordinator.cancel_for_user_input("tab-1") == first.execution_id
    assert first.public_dict()["status"] == "cancelled_by_user"
    assert coordinator.active_execution_id("tab-1") == ""


def test_step_timeout_preserves_partial_output() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "slow command"},
            {
                "type": "expect",
                "success": ["device_prompt"],
                "timeout_seconds": 2,
            },
        ],
        total_timeout_seconds=10,
    )
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=plan,
    )

    coordinator.on_output("tab-1", "working...")
    harness.scheduler.advance(2)

    result = runner.public_dict()
    assert result["status"] == "timed_out"
    assert result["error_code"] == "step_timeout"
    assert result["steps"][1]["output"] == "working..."


def test_step_timeout_exposes_phase_and_safe_response_diagnostics() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "ftp 192.0.2.10 21"},
            {
                "type": "expect",
                "success": ["ftp_prompt"],
                "responses": [
                    {"match": "username_prompt", "secret_ref": "transfer.username"},
                    {"match": "password_prompt", "secret_ref": "transfer.password"},
                ],
                "timeout_seconds": 2,
                "timeout_code": "ftp_password_prompt_timeout",
                "label": "等待 FTP 密码提示",
            },
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)
    coordinator.on_output("tab-1", "User(10.10.10.1):(none):\r\n")
    harness.scheduler.advance(2)

    result = runner.public_dict()
    assert result["error_code"] == "ftp_password_prompt_timeout"
    assert result["failed_step"]["label"] == "等待 FTP 密码提示"
    assert result["failed_step"]["responses_sent"] == ["username_prompt"]
    assert "super-secret" not in str(result)


def test_plan_rejects_unapproved_secret_reference() -> None:
    with pytest.raises(TerminalPlanError) as exc_info:
        parse_terminal_plan(
            [{"type": "send", "secret_ref": "environment.PASSWORD"}]
        )

    assert exc_info.value.code == "secret_ref_not_allowed"


def test_external_workflow_lease_is_restored_after_child_interaction() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    cancelled: list[bool] = []
    coordinator.acquire_external_lease(
        "tab-1",
        "package-upgrade-1",
        on_cancel=lambda: cancelled.append(True),
    )

    with pytest.raises(TerminalPlanError) as exc_info:
        coordinator.start(
            session_id="tab-1",
            device_id="device-1",
            plan=build_batch_plan(["display version"]),
        )
    assert exc_info.value.code == "session_busy"

    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=build_batch_plan(["display version"]),
        lease_owner_id="package-upgrade-1",
    )
    coordinator.on_output("tab-1", "SimOS V2\n<sim> ")

    assert runner.public_dict()["status"] == "completed"
    assert coordinator.active_execution_id("tab-1") == "package-upgrade-1"
    assert coordinator.cancel_for_user_input("tab-1") == "package-upgrade-1"
    assert cancelled == [True]
    assert coordinator.active_execution_id("tab-1") == ""


def test_interactive_plan_can_jump_to_cleanup_after_failure_match() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "name": "check", "text": "check package"},
            {
                "type": "expect",
                "name": "check_result",
                "success": ["OK"],
                "failures": ["NO SPACE"],
                "on_failure": "cleanup",
            },
            {"type": "send", "name": "normal", "text": "install package"},
            {"type": "send", "name": "cleanup", "text": "delete temp package"},
            {"type": "expect", "success": ["device_prompt"]},
        ]
    )
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=plan,
    )

    coordinator.on_output("tab-1", "NO SPACE")
    coordinator.on_output("tab-1", "cleanup complete\n<sim> ")

    assert [item[1].text for item in harness.sent] == [
        "check package\r",
        "delete temp package\r",
    ]
    assert runner.public_dict()["status"] == "completed"


def test_interactive_plan_rejects_unbounded_backward_branch() -> None:
    with pytest.raises(TerminalPlanError, match="max_retries"):
        parse_terminal_plan(
            [
                {"type": "send", "name": "retry_send", "text": "probe"},
                {
                    "type": "expect",
                    "success": ["device_prompt"],
                    "on_match": "retry_send",
                },
            ]
        )


def test_interactive_backward_branch_stops_at_retry_limit() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "name": "retry_send", "text": "probe"},
            {
                "type": "expect",
                "success": ["RETRY"],
                "on_match": "retry_send",
                "max_retries": 1,
            },
        ]
    )
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=plan,
    )

    coordinator.on_output("tab-1", "RETRY")
    coordinator.on_output("tab-1", "RETRY")

    assert [item[1].text for item in harness.sent] == ["probe\r", "probe\r"]
    assert runner.public_dict()["error_code"] == "branch_limit_exceeded"


def test_failure_word_on_confirmation_line_answers_instead_of_aborting() -> None:
    """A confirmation prompt that mentions a failure word on the same line (e.g.
    "…error… Continue? [Y/N]") must be answered, not aborted. Regression:
    failures were matched before responses, so the 'error' word killed the step
    before the 'y' confirmation could be sent."""
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "name": "check", "text": "check package"},
            {
                "type": "expect",
                "name": "confirm",
                "success": ["device_prompt"],
                "responses": [{"match": "confirmation_prompt", "text": "y"}],
                "failures": ["error"],
            },
        ]
    )
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=plan,
    )

    # The device output mentions 'error' on the confirmation line, and needs a
    # 'y' — this must not abort.
    coordinator.on_output("tab-1", "checking package (error 0) Continue? [Y/N]: ")

    assert runner.public_dict()["status"] == "running", (
        "confirm step must stay running to accept the 'y' response"
    )
    # The response 'y' is sent for the confirmation prompt.
    assert any(item[1].text.rstrip("\r") == "y" for item in harness.sent)
    coordinator.on_output("tab-1", "\n<sim> ")
    assert runner.public_dict()["status"] == "completed"


def test_reboot_answers_multiple_device_confirmations() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "reboot"},
            {
                "type": "expect",
                "success": ["device_prompt"],
                "responses": [
                    {"match": "confirmation_prompt", "text": "y", "max_matches": 3},
                ],
            },
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)

    coordinator.on_output("tab-1", "Continue? [Y/N]:\nAre you sure? [Y/N]: ")
    harness.scheduler.advance(0.2)
    assert [item[1].text for item in harness.sent] == ["reboot\r", "y\r", "y\r"]

    coordinator.on_output("tab-1", "\n<sim> ")
    assert runner.public_dict()["status"] == "completed"
    assert runner.public_dict()["steps"][1]["response_count"] == 2


def test_reboot_disconnect_is_activation_signal() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "reboot"},
            {
                "type": "expect",
                "success": ["device_prompt"],
                "disconnect_is_success": True,
            },
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)
    coordinator.on_session_state("tab-1", "disconnected")

    result = runner.public_dict()
    assert result["status"] == "completed"
    assert result["steps"][1]["matched"] == "disconnected"


def test_reboot_prompt_before_disconnect_does_not_complete() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "reboot"},
            {
                "type": "expect",
                "success": ["device_prompt", "login_prompt", "username_prompt"],
                "disconnect_is_success": True,
            },
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)

    coordinator.on_output("tab-1", "<sim> ")
    assert runner.public_dict()["status"] == "running"

    coordinator.on_session_state("tab-1", "disconnected")
    assert runner.public_dict()["status"] == "completed"


def test_success_marker_wins_over_failure_word() -> None:
    """A step with explicit success markers completes when a success marker is
    present, even if a failure-looking word also appears in the output. This
    lets a download that finishes ('Transfer complete') succeed despite a
    benign 'error' mention."""
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "get target.cc flash:/target.cc"},
            {
                "type": "expect",
                "name": "download",
                "success": ["ftp_prompt"],
                "success_markers": ["Transfer complete"],
                "failures": ["error"],
            },
        ]
    )
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=plan,
    )

    # The FTP output mentions 'error' in a benign line but the transfer
    # completes — success marker must win.
    coordinator.on_output("tab-1", "550 error on a stale line\n")
    coordinator.on_output("tab-1", "226 Transfer complete.\nftp> ")

    result = runner.public_dict()
    assert result["status"] == "completed", f"expected completed, got {result['status']}"
