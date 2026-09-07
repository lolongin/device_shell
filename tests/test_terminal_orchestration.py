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
    assert result["outcome"]["status"] == "success"
    assert result["outcome"]["finished"] is True
    assert result["command_results"][0]["command"] == "display version"
    assert coordinator.active_execution_id("tab-1") == ""


def test_compatibility_actions_normalize_into_existing_plan_steps() -> None:
    plan = parse_terminal_plan(
        [
            {"action": "send", "text": "show version", "enter": True},
            {"action": "expect", "match": "Password:", "respond": {"secret_ref": "transfer.password"}},
            {"action": "done"},
        ]
    )

    assert [type(step).__name__ for step in plan.steps] == ["SendStep", "ExpectStep"]
    expect = plan.steps[1]
    assert expect.pattern == "Password:"
    assert expect.responses[0].secret_ref == "transfer.password"


def test_interactive_execution_rejects_duplicate_response_at_same_prompt() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=build_batch_plan(["copy source target"]),
    )

    coordinator.on_output("tab-1", "Continue? [Y/N]: ")
    runner.send_manual_input(text="y")

    with pytest.raises(TerminalPlanError, match="已经收到应答") as error:
        runner.send_manual_input(text="y")
    assert error.value.code == "duplicate_response"


def test_password_prompt_requires_secret_reference() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=build_batch_plan(["login"]),
    )

    coordinator.on_output("tab-1", "Password: ")
    with pytest.raises(TerminalPlanError) as error:
        runner.send_manual_input(text="plaintext")
    assert error.value.code == "secret_required"
    assert harness.sent == [("tab-1", TerminalInput("login\r"), runner.execution_id)]


def test_batch_plan_honors_custom_prompt_and_failure_patterns() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=build_batch_plan(
            ["show version"],
            terminal_prompt=r"<READY>",
            failure_patterns=["FAILED"],
        ),
    )

    coordinator.on_output("tab-1", "FAILED: operation rejected")

    assert runner.public_dict()["status"] == "failed"
    assert runner.public_dict()["error_code"] == "terminal_failure"


def test_batch_plan_surfaces_unhandled_confirmation_without_completing() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=build_batch_plan(["copy flash:/a flash:/b"]),
    )

    coordinator.on_output("tab-1", "Continue? [Y/N]: ")

    result = runner.public_dict()
    assert runner.attention_event.is_set()
    assert result["status"] == "running"
    assert result["phase"] == "waiting_for_input"
    assert result["waiting_for"] == "confirmation_prompt"
    assert result["outcome"]["status"] == "interaction_required"
    assert result["outcome"]["finished"] is False
    assert coordinator.active_execution_id("tab-1") == runner.execution_id

    runner.send_manual_input(text="y")
    assert not runner.attention_event.is_set()
    coordinator.on_output("tab-1", "Copy complete.\n<sim> ")
    assert runner.public_dict()["status"] == "completed"
    assert coordinator.active_execution_id("tab-1") == ""


def test_indexed_interactive_plan_auto_answers_confirmation() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "copy flash:/elabel.txt flash:/dtui_scratch.txt", "success": [1]},
            {"type": "expect", "pattern": "[Y/N]", "success": [2]},
            {"type": "send", "text": "Y", "success": [3]},
            {"type": "expect", "pattern": "<HUAWEI>", "success": [3]},
        ],
        total_timeout_seconds=30,
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)

    coordinator.on_output("tab-1", "Continue? [Y/N]: ")
    assert runner.public_dict()["current_step"] == 3
    assert harness.sent[-1][1].text == "Y\r"
    assert runner.public_dict()["waiting_for"] == "<HUAWEI>"
    assert not runner.attention_event.is_set()

    coordinator.on_output(
        "tab-1",
        "0% complete\n100% complete\nInfo: Copying file ... Done.\n<HUAWEI> ",
    )
    result = runner.public_dict()
    assert result["status"] == "completed"
    assert result["outcome"]["status"] == "success"
    assert result["outcome"]["finished"] is True
    assert result["lease_released"] is True
    assert coordinator.active_execution_id("tab-1") == ""
    assert [item[1].text for item in harness.sent] == [
        "copy flash:/elabel.txt flash:/dtui_scratch.txt\r",
        "Y\r",
    ]


def test_indexed_plan_auto_answers_two_confirmation_points_without_double_send() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "copy source target", "success": [1]},
            {"type": "expect", "pattern": "[Y/N]", "success": [2]},
            {"type": "send", "text": "Y", "success": [3]},
            {"type": "expect", "pattern": "<sim>", "success": [4]},
            {"type": "send", "text": "delete target", "success": [5]},
            {"type": "expect", "pattern": "[Y/N]", "success": [6]},
            {"type": "send", "text": "Y", "success": [7]},
            {"type": "expect", "pattern": "<sim>", "success": [7]},
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)

    coordinator.on_output("tab-1", "Continue? [Y/N]: ")
    assert runner.current_step == 3
    coordinator.on_output("tab-1", "Copy complete.\n<sim> ")
    assert runner.current_step == 5
    coordinator.on_output("tab-1", "Delete target? [Y/N]: ")
    assert runner.current_step == 7
    coordinator.on_output("tab-1", "Delete complete.\n<sim> ")

    result = runner.public_dict()
    assert result["status"] == "completed"
    assert result["outcome"]["status"] == "success"
    assert [item[1].text for item in harness.sent] == [
        "copy source target\r",
        "Y\r",
        "delete target\r",
        "Y\r",
    ]


def test_expect_can_omit_success_for_terminal_step() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "display version"},
            {"type": "expect", "success": []},
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)

    coordinator.on_output("tab-1", "SimOS V2\n<sim> ")

    assert runner.public_dict()["status"] == "completed"


def test_expect_pattern_can_omit_success_for_terminal_step() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "copy a b"},
            {"type": "expect", "pattern": "Copy complete"},
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)

    coordinator.on_output("tab-1", "Copy complete")

    assert runner.public_dict()["status"] == "completed"


def test_failed_command_has_finished_failure_outcome() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=build_batch_plan(["bad command"]),
    )

    coordinator.on_output(
        "tab-1",
        "Error: Unrecognized command\n<sim> ",
    )

    result = runner.public_dict()
    assert result["status"] == "failed"
    assert result["outcome"]["status"] == "failure"
    assert result["outcome"]["finished"] is True
    assert result["outcome"]["errors"][0]["code"] == "command_rejected"
    assert coordinator.active_execution_id("tab-1") == ""


def test_batch_plan_auto_responds_to_pagination() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=build_batch_plan(["display current-configuration"]),
    )

    coordinator.on_output("tab-1", "line 1\n---- More ----")
    assert harness.sent[-1][1].text == " "

    coordinator.on_output("tab-1", "line 2\n<HUAWEI>")
    result = runner.public_dict()
    assert result["status"] == "completed"
    assert result["steps"][1]["response_count"] == 1
    assert result["steps"][1]["responses_sent"] == ["pagination_prompt"]


def test_batch_plan_does_not_advance_while_paginated_output_is_idle() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    runner = coordinator.start(
        session_id="tab-1",
        device_id="device-1",
        plan=build_batch_plan(["dir flash:/", "display version"]),
    )

    coordinator.on_output("tab-1", "page 1\n---- More ----")
    harness.scheduler.advance(1.0)

    assert runner.public_dict()["status"] == "running"
    assert [item[1].text for item in harness.sent] == ["dir flash:/\r", " "]

    coordinator.on_output("tab-1", "page 2\n<HUAWEI>")
    assert [item[1].text for item in harness.sent][-1] == "display version\r"
    coordinator.on_output("tab-1", "VRP version\n<HUAWEI>")

    assert runner.public_dict()["status"] == "completed"


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


def test_expected_credential_prompt_advances_managed_plan() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "ftp 192.0.2.10 2121"},
            {"type": "expect", "success": ["username_prompt"]},
            {"type": "send", "secret_ref": "transfer.username"},
            {"type": "expect", "success": ["password_prompt"]},
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)

    coordinator.on_output("tab-1", "User(10.10.10.1):(none): ")

    result = runner.public_dict()
    assert result["status"] == "running"
    assert result["current_step"] == 3
    assert result["phase"] == "waiting_for_output"
    assert not runner.attention_event.is_set()
    assert harness.sent[-1][1].text == "device-user\r"


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
    coordinator.on_output("tab-1", "super-secret\r\n230 User logged in.\nftp> ")

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


def test_interactive_execution_accepts_manual_input_and_emits_events() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "delete candidate"},
            {
                "type": "expect",
                "success": ["command complete"],
                "responses": [{"match": "Continue?", "control": "enter"}],
            },
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)

    coordinator.on_output("tab-1", "Continue? [y/n]\n")
    assert harness.sent[-1][1].text == "\r"
    assert runner.public_dict()["phase"] == "waiting_for_output"
    assert any(event["type"] == "auto_response" for event in runner.public_dict()["events"])

    runner.send_manual_input(text="n")
    assert harness.sent[-1][1].text == "n\r"
    snapshot = runner.public_dict()
    assert snapshot["can_send"] is True
    assert snapshot["event_cursor"] >= 3


def test_user_taken_over_interactive_execution_can_resume_from_checkpoint() -> None:
    harness = Harness()
    coordinator = harness.coordinator()
    plan = parse_terminal_plan(
        [
            {"type": "send", "text": "show version"},
            {"type": "expect", "success": ["device_prompt"]},
        ]
    )
    runner = coordinator.start(session_id="tab-1", device_id="device-1", plan=plan)

    assert coordinator.cancel_for_user_input("tab-1") == runner.execution_id
    assert runner.public_dict()["can_resume"] is True

    resumed = coordinator.resume(runner.execution_id)
    assert resumed.public_dict()["status"] == "running"
    assert resumed.public_dict()["current_step"] == 1
    coordinator.on_output("tab-1", "<sim> ")
    assert resumed.public_dict()["status"] == "completed"


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
