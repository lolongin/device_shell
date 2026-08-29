"""Generic process-backed Activity handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from device_tui.framework.activity import (
    ActivityContext,
    ActivityInvocation,
    ActivityResult,
    ActivityStatus,
)
from device_tui.framework.events import Event
from device_tui.infrastructure.processes import LocalProcessAdapter


class ProcessActivityHandler:
    """Activity handler for ``script.run`` and ``artifact.build``."""

    def __init__(self, activity_id: str, adapter: LocalProcessAdapter | None = None) -> None:
        self.activity_id = activity_id
        self._adapter = adapter or LocalProcessAdapter()

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        inputs = invocation.inputs
        argv = inputs.get("argv")
        if isinstance(argv, str):
            raise ValueError("process Activity requires argv as an array")
        if not isinstance(argv, (list, tuple)):
            raise ValueError("process Activity requires argv")
        timeout = float(inputs.get("timeout_seconds") or 3_600)

        def output(text: str) -> None:
            report(Event(
                type="process.output",
                run_id=invocation.workflow_run_id,
                action_id=invocation.activity_id,
                source="process.adapter",
                payload={"chunk": text[-16_384:]},
                progress=True,
            ))

        report(Event(
            type="process.started",
            run_id=invocation.workflow_run_id,
            action_id=invocation.activity_id,
            source="process.adapter",
            payload={"program": str(argv[0])},
        ))
        result = await self._adapter.run(
            invocation.invocation_id,
            argv,
            cwd=str(inputs.get("cwd") or "") or None,
            env=inputs.get("env") if isinstance(inputs.get("env"), dict) else None,
            timeout_seconds=timeout,
            max_output_chars=int(inputs.get("max_output_chars") or 1_048_576),
            on_output=output,
        )
        status = {
            "succeeded": ActivityStatus.SUCCEEDED,
            "failed": ActivityStatus.FAILED,
            "unknown": ActivityStatus.UNKNOWN,
            "cancelled": ActivityStatus.CANCELLED,
        }[result.status]
        error = None
        if status != ActivityStatus.SUCCEEDED:
            error = {
                "code": "process_timeout" if result.timed_out else "process_failed",
                "message": "local process did not complete successfully",
                "class": "timeout" if result.timed_out else "deterministic",
                "returncode": result.returncode,
            }
        artifact_path = str(
            inputs.get("output_path")
            or inputs.get("artifact_path")
            or ""
        ).strip()
        artifact_evidence: dict[str, Any] | None = None
        if status == ActivityStatus.SUCCEEDED and self.activity_id == "artifact.build" and artifact_path:
            path = Path(artifact_path)
            try:
                size_bytes = path.stat().st_size
            except OSError as exc:
                status = ActivityStatus.FAILED
                error = {
                    "code": "artifact_missing",
                    "message": f"build completed but artifact was not found: {artifact_path}",
                    "class": "deterministic",
                    "detail": str(exc),
                }
            else:
                if size_bytes <= 0:
                    status = ActivityStatus.FAILED
                    error = {
                        "code": "artifact_empty",
                        "message": f"build produced an empty artifact: {artifact_path}",
                        "class": "deterministic",
                    }
                artifact_evidence = {
                    "kind": "artifact",
                    "path": str(path),
                    "size_bytes": size_bytes,
                }
        return ActivityResult(
            status=status,
            outputs={
                "output": result.output,
                "returncode": result.returncode,
                "program": str(argv[0]),
                **({"artifact_path": artifact_path} if artifact_path else {}),
            },
            evidence=(
                {"kind": "process", "returncode": result.returncode, "timed_out": result.timed_out},
                *([artifact_evidence] if artifact_evidence is not None else []),
            ),
            error=error,
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        await self._adapter.cancel(invocation.invocation_id)


__all__ = ["ProcessActivityHandler"]
