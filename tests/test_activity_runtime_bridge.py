from __future__ import annotations

import asyncio
import shutil
import sys
import pytest

from device_tui.application.device_control import OperationView
from device_tui.application.composition.workflows import build_default_activity_executor
from device_tui.framework import (
    ActionRegistry,
    ActionSpec,
    ActivityContext,
    ActivityActionHandler,
    ActivityInvocation,
    ActivityStatus,
    StateNode,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRuntime,
)


class _TransferControl:
    def __init__(self) -> None:
        self.revision = 0

    def transfer(self, target, request, *, context=None):
        return OperationView(
            operation_id="op-1", kind="managed_file_transfer", device_id=target.device_id,
            session_id=target.session_id, status="queued", stage="queued", message="queued", revision=0,
        )

    def get_operation(self, operation_id: str) -> OperationView:
        self.revision += 1
        return OperationView(
            operation_id=operation_id, kind="managed_file_transfer", device_id="dev-1",
            session_id="sess-1", status="completed", stage="completed", message="completed", revision=self.revision,
            progress_percent=100, bytes_transferred=10, total_bytes=10,
        )

    def cancel_operation(self, operation_id: str) -> OperationView:
        return self.get_operation(operation_id)


def test_activity_handler_runs_through_workflow_runtime() -> None:
    activities = build_default_activity_executor()
    actions = ActionRegistry()
    actions.register(ActivityActionHandler(activities, "script.run"), item_id="script.run")
    runtime = WorkflowRuntime(actions=actions)
    definition = WorkflowDefinition(
        id="script-workflow",
        version="1",
        start_state="run",
        states=(
            StateNode(
                "run",
                ActionSpec(
                    "run", "script.run",
                    params={"argv": [sys.executable, "-c", "print('runtime-ok')"]},
                ),
                next_state="done",
            ),
            StateNode("done", terminal=True),
        ),
    )
    run = runtime.start(definition, device_id="local")

    result = asyncio.run(runtime.run_until_blocked(run.id))

    assert str(result.status) == "succeeded"
    assert result.outputs["run"]["returncode"] == 0
    assert "runtime-ok" in result.outputs["run"]["output"]


def _shell_invocation(command: str, **inputs) -> tuple[object, ActivityContext]:
    invocation = ActivityInvocation(
        "shell.command",
        "inv-shell",
        "run-shell",
        inputs={"command": command, "execution_mode": "shell", **inputs},
    )
    return invocation, ActivityContext(WorkflowRun("run-shell", "wf", "1", "local"), invocation)


def test_shell_command_activity_returns_standardized_stdout_and_stderr() -> None:
    command = (
        "Write-Output 'shell-ok'; [Console]::Error.Write('shell-warning')"
        if sys.platform == "win32"
        else "printf 'shell-ok'; printf 'shell-warning' >&2"
    )
    invocation, context = _shell_invocation(command)

    result = asyncio.run(build_default_activity_executor().execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert "shell-ok" in result.outputs["stdout"]
    assert "shell-warning" in result.outputs["stderr"]
    assert result.outputs["exitCode"] == 0
    assert result.outputs["status"] == "succeeded"
    assert result.outputs["duration"] >= 0
    assert result.outputs["output"] == result.outputs["stdout"]
    assert result.outputs["exit_code"] == 0
    assert result.outputs["data"]["stdout"] == result.outputs["stdout"]
    assert result.outputs["error"] is None


def test_shell_command_activity_preserves_nonzero_exit_code() -> None:
    command = "Write-Error 'failed'; exit 7" if sys.platform == "win32" else "printf 'failed' >&2; exit 7"
    invocation, context = _shell_invocation(command)

    result = asyncio.run(build_default_activity_executor().execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.FAILED
    assert "failed" in result.outputs["stderr"]
    assert result.outputs["exitCode"] == 7
    assert result.outputs["exit_code"] == 7
    assert result.outputs["status"] == "failed"
    assert result.error["code"] == "shell_command_failed"
    assert result.outputs["error"] == result.error


def test_shell_command_activity_times_out_with_standardized_result() -> None:
    command = "Start-Sleep -Seconds 2" if sys.platform == "win32" else "sleep 2"
    invocation, context = _shell_invocation(command, timeout_seconds=0.05)

    result = asyncio.run(build_default_activity_executor().execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.FAILED
    assert result.outputs["status"] == "timeout"
    assert result.outputs["duration"] < 2
    assert result.error["code"] == "shell_command_timeout"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
def test_bash_command_activity_uses_bash_mode() -> None:
    invocation, context = _shell_invocation("printf '%s' \"$BASH_VERSION\"", execution_mode="bash")

    result = asyncio.run(build_default_activity_executor().execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["stdout"]


def test_process_activity_reports_invalid_inputs_with_structured_outputs() -> None:
    activities = build_default_activity_executor()
    invocation = ActivityInvocation(
        "script.run", "inv-invalid", "run-1", inputs={"argv": "python -c pass"}
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "local"), invocation)

    result = asyncio.run(activities.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.FAILED
    assert result.outputs == {
        "output": "",
        "stdout": "",
        "stderr": "",
        "returncode": None,
        "exit_code": None,
        "exitCode": None,
        "program": "",
        "status": "failed",
    }
    assert result.error["code"] == "process_input_invalid"


def test_default_transfer_registration_wraps_adapter_in_activity_handler() -> None:
    activities = build_default_activity_executor(_TransferControl())
    invocation = ActivityInvocation(
        "file.transfer", "inv-1", "run-1",
        inputs={
            "device_id": "dev-1", "session_id": "sess-1", "direction": "upload",
            "source_path": "firmware.bin", "destination_path": "flash:/firmware.bin",
        },
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)
    events = []

    result = asyncio.run(activities.execute(invocation, context, events.append))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["verified"] is True
    assert any(event.type == "transfer.completed" for event in events)


def test_default_transfer_registration_uses_a_session_status_probe_when_available() -> None:
    class GuardedTransferControl(_TransferControl):
        def __init__(self) -> None:
            super().__init__()
            self.probe_targets = []

        def session_status(self, target):
            self.probe_targets.append(target)
            return {"status": "connected", "value": "connected"}

    control = GuardedTransferControl()
    activities = build_default_activity_executor(control)
    invocation = ActivityInvocation(
        "file.transfer", "inv-1", "run-1",
        inputs={
            "device_id": "dev-1", "session_id": "sess-1", "direction": "upload",
            "source_path": "firmware.bin", "destination_path": "flash:/firmware.bin",
        },
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)

    result = asyncio.run(activities.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert control.probe_targets[0].session_id == "sess-1"


@pytest.mark.parametrize("destination, environment, expected", [
    ("", "auto", "flash:/firmware.bin"),
    ("flash", "auto", "flash:/firmware.bin"),
    ("flash:", "auto", "flash:/firmware.bin"),
    ("flash:/", "vrp", "flash:/firmware.bin"),
    ("flash:/renamed.bin", "auto", "flash:/renamed.bin"),
    ("/tmp/firmware.bin", "auto", "/tmp/firmware.bin"),
    ("/tmp/renamed.bin", "linux", "/tmp/renamed.bin"),
])
def test_upload_expands_flash_storage_without_overriding_environment(destination: str, environment: str, expected: str) -> None:
    from device_tui.infrastructure.transfers.managed_file_transfer import validate_transfer_device_path

    class RecordingTransferControl(_TransferControl):
        def __init__(self) -> None:
            super().__init__()
            self.request = None

        def transfer(self, target, request, *, context=None):
            validate_transfer_device_path(request.destination_path, request.terminal_environment)
            self.request = request
            return super().transfer(target, request, context=context)

    control = RecordingTransferControl()
    activities = build_default_activity_executor(control)
    invocation = ActivityInvocation(
        "file.transfer", "inv-legacy", "run-legacy",
        inputs={
            "device_id": "dev-1", "session_id": "sess-1",
            "direction": "upload",
            "source_path": "packages/firmware.bin",
            "destination_path": destination,
            "terminal_environment": environment,
        },
    )
    context = ActivityContext(WorkflowRun("run-legacy", "wf", "1", "dev-1"), invocation)
    result = asyncio.run(activities.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED, result.error
    assert control.request is not None
    assert control.request.terminal_environment == environment
    assert control.request.destination_path == expected
