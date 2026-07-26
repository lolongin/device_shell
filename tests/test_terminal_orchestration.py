from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pytest

from src.terminal_orchestration import (
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
    assert harness.sent[1][1].sensitive
    assert harness.sent[2][1].secret_ref == "transfer.password"
    result = runner.public_dict()
    assert result["status"] == "completed"
    assert result["steps"][1]["response_count"] == 2
    assert "super-secret" not in str(result)


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
