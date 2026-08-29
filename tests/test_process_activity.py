from __future__ import annotations

import asyncio
import sys

from device_tui.application.workflow_plugins.process import ProcessActivityHandler
from device_tui.application.workflows import (
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
