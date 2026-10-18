from __future__ import annotations

import asyncio
import sys

from device_tui.application.workflow_plugins.process import ProcessActivityHandler
from device_tui.framework import (
    ActivityContext,
    ActivityInvocation,
    ActivityResult,
    ActivityStatus,
    Event,
    WorkflowRun,
)


def _run(handler: ProcessActivityHandler, inputs: dict[str, object]) -> tuple[ActivityResult, list[Event]]:
    invocation = ActivityInvocation(handler.activity_id, "inv-1", "run-1", inputs=inputs)
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation)
    events: list[Event] = []
    result = asyncio.run(handler.execute(invocation, context, events.append))
    return result, events


def test_process_activity_returns_output_and_exit_code() -> None:
    result, events = _run(ProcessActivityHandler("script.run"), {
        "argv": [sys.executable, "-c", "print('ok')"],
    })

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["returncode"] == 0
    assert "ok" in result.outputs["output"]
    assert events[0].payload["program"] == sys.executable


def test_script_run_passes_json_input_and_parses_result() -> None:
    result, _ = _run(ProcessActivityHandler("script.run"), {
        "language": "python",
        "script": (
            "import json, os, sys\n"
            "print('warning', file=sys.stderr)\n"
            "payload = json.loads(os.environ['DEVICE_TUI_INPUT_JSON'])\n"
            "print(json.dumps({'device_id': payload['device_id'], 'mode': os.environ['MODE']}))\n"
        ),
        "input_json": {"device_id": "router-1"},
        "env": {"MODE": "check"},
    })

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["stdout"].strip().endswith('{"device_id": "router-1", "mode": "check"}')
    assert result.outputs["stderr"].strip() == "warning"
    assert result.outputs["result"] == {"device_id": "router-1", "mode": "check"}
    assert result.outputs["exit_code"] == 0


def test_script_run_invokes_python_main_with_typed_inputs() -> None:
    result, _ = _run(ProcessActivityHandler("script.run"), {
        "language": "python",
        "entrypoint": "main",
        "script": (
            "def main(name: str, count: int = 2) -> dict:\n"
            "    return {'message': name * count}\n"
        ),
        "input_json": {"name": "ok"},
    })

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["result"] == {"message": "okok"}


def test_script_run_device_rpc_returns_command_result_to_main() -> None:
    calls: list[tuple[str, float]] = []

    async def device_command(invocation, context, command, timeout, connection):
        calls.append((command, timeout))
        assert connection is None
        return {"output": "version 1.2", "status": "completed", "execution_id": "exec-1"}

    handler = ProcessActivityHandler("script.run", device_command=device_command)
    invocation = ActivityInvocation(
        handler.activity_id,
        "inv-rpc",
        "run-rpc",
        inputs={
            "language": "python",
            "entrypoint": "main",
            "script": "def main(device):\n    return device.run('display version', timeout=12)",
        },
        context={"target": {"device_id": "router-1", "session_id": "session-1"}},
    )
    context = ActivityContext(WorkflowRun("run-rpc", "wf", "1", "router-1"), invocation)
    result = asyncio.run(handler.execute(invocation, context, lambda _event: None))

    assert result.status == ActivityStatus.SUCCEEDED
    assert calls == [("display version", 12.0)]
    assert result.outputs["result"] == {
        "output": "version 1.2",
        "status": "completed",
        "execution_id": "exec-1",
    }


def test_script_run_can_list_connections_and_select_one_by_protocol() -> None:
    calls: list[str | None] = []

    async def device_command(invocation, context, command, timeout, connection):
        calls.append(connection)
        return {"output": f"via {connection}", "status": "completed"}

    async def device_connections(invocation, context):
        return [
            {"connection": "ssh", "session_id": "ssh-1", "title": "Primary", "status": "connected"},
            {"connection": "telnet", "session_id": "telnet-1", "title": "Backup", "status": "connected"},
        ]

    handler = ProcessActivityHandler(
        "script.run",
        device_command=device_command,
        device_connections=device_connections,
    )
    invocation = ActivityInvocation(
        handler.activity_id,
        "inv-connections",
        "run-connections",
        inputs={
            "language": "python",
            "entrypoint": "main",
            "script": (
                "def main(device):\n"
                "    available = device.connections\n"
                "    result = device.run('display version', connection='ssh')\n"
                "    return {'connections': available, 'result': result}\n"
            ),
        },
        context={"target": {"device_id": "router-1", "session_id": "default"}},
    )
    context = ActivityContext(WorkflowRun("run-connections", "wf", "1", "router-1"), invocation)
    result = asyncio.run(handler.execute(invocation, context, lambda _event: None))

    assert result.status == ActivityStatus.SUCCEEDED
    assert calls == ["ssh"]
    assert result.outputs["result"]["connections"][1]["session_id"] == "telnet-1"
    assert result.outputs["result"]["result"]["output"] == "via ssh"


def test_script_run_rejects_invalid_json_before_execution() -> None:
    result, _ = _run(ProcessActivityHandler("script.run"), {
        "language": "python",
        "script": "raise RuntimeError('should not run')",
        "input_json": "{invalid",
    })

    assert result.status == ActivityStatus.FAILED
    assert result.error["code"] == "process_input_invalid"
    assert "valid JSON" in result.error["message"]


def test_process_activity_reports_nonzero_exit_as_failed() -> None:
    result, _ = _run(ProcessActivityHandler("script.run"), {
        "argv": [sys.executable, "-c", "raise SystemExit(3)"],
    })

    assert result.status == ActivityStatus.FAILED
    assert result.outputs["returncode"] == 3


def test_process_activity_reports_timeout_as_unknown() -> None:
    result, _ = _run(ProcessActivityHandler("script.run"), {
        "argv": [sys.executable, "-c", "import time; time.sleep(2)"],
        "timeout_seconds": 0.05,
    })

    assert result.status == ActivityStatus.UNKNOWN
    assert result.error["code"] == "process_timeout"


def test_artifact_build_verifies_declared_output(tmp_path) -> None:
    artifact = tmp_path / "image.cc"
    result, _ = _run(ProcessActivityHandler("artifact.build"), {
        "argv": [sys.executable, "-c", f"open(r'{artifact}', 'wb').write(b'image')"],
        "output_path": str(artifact),
    })

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["artifact_path"] == str(artifact)
    assert result.evidence[-1]["size_bytes"] == 5


def test_artifact_build_fails_when_declared_output_is_missing(tmp_path) -> None:
    artifact = tmp_path / "missing.cc"
    result, _ = _run(ProcessActivityHandler("artifact.build"), {
        "argv": [sys.executable, "-c", "pass"],
        "artifact_path": str(artifact),
    })

    assert result.status == ActivityStatus.FAILED
    assert result.error["code"] == "artifact_missing"
