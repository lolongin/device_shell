"""Generic process-backed Activity handlers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from device_tui.framework.activity import (
    ActivityContext,
    ActivityInvocation,
    ActivityResult,
    ActivityStatus,
)
from device_tui.framework.events import Event
from device_tui.infrastructure.processes import LocalProcessAdapter
from device_tui.application.workflow_plugins.shell import ShellCommandActivityHandler


class ProcessActivityHandler:
    """Activity handler for ``script.run`` and ``artifact.build``."""

    def __init__(self, activity_id: str, adapter: LocalProcessAdapter | None = None) -> None:
        self.activity_id = activity_id
        self._adapter = adapter or LocalProcessAdapter()

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        inputs = invocation.inputs
        script_path: str | None = None
        script_inputs = dict(inputs)
        if self.activity_id == "script.run" and str(inputs.get("script") or "").strip():
            argv, script_path, script_error = self._script_argv(inputs)
            if script_error:
                return self._invalid_input(script_error)
            script_inputs["argv"] = argv
        else:
            argv = inputs.get("argv")
        if isinstance(argv, str):
            return self._invalid_input("process Activity requires argv as an array")
        if not isinstance(argv, (list, tuple)):
            return self._invalid_input("process Activity requires argv")
        if not argv or not all(isinstance(item, (str, int, float)) for item in argv):
            return self._invalid_input("process Activity argv must contain command arguments")
        try:
            timeout = float(inputs.get("timeout_seconds") or 3_600)
        except (TypeError, ValueError):
            return self._invalid_input("timeout_seconds must be a number")
        if timeout <= 0:
            return self._invalid_input("timeout_seconds must be greater than zero")

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
        try:
            env = script_inputs.get("env") if isinstance(script_inputs.get("env"), dict) else None
            if self.activity_id == "script.run":
                if script_inputs.get("input_json") not in (None, ""):
                    raw_input = script_inputs["input_json"]
                    if isinstance(raw_input, str):
                        try:
                            json.loads(raw_input)
                        except json.JSONDecodeError as exc:
                            return self._invalid_input(f"input_json must be valid JSON: {exc.msg}")
                        input_json = raw_input
                    else:
                        try:
                            input_json = json.dumps(raw_input, ensure_ascii=False)
                        except (TypeError, ValueError) as exc:
                            return self._invalid_input(f"input_json must be JSON serializable: {exc}")
                else:
                    input_json = "{}"
                merged_env = dict(os.environ)
                if env:
                    merged_env.update({str(key): str(value) for key, value in env.items()})
                merged_env["DEVICE_TUI_INPUT_JSON"] = input_json
                env = merged_env
            result = await self._adapter.run(
                invocation.invocation_id,
                argv,
                cwd=str(script_inputs.get("cwd") or "") or None,
                env=env,
                timeout_seconds=timeout,
                max_output_chars=int(script_inputs.get("max_output_chars") or 1_048_576),
                on_output=output,
            )
        except Exception as exc:
            return ActivityResult(
                status=ActivityStatus.FAILED,
                outputs=self._failure_outputs(argv),
                error={"code": "process_failed", "message": str(exc), "class": "transient"},
            )
        finally:
            if script_path:
                try:
                    Path(script_path).unlink(missing_ok=True)
                except OSError:
                    pass
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
        stdout = getattr(result, "stdout", result.output)
        stderr = getattr(result, "stderr", "")
        parsed_result: Any = None
        if self.activity_id == "script.run":
            for line in reversed(stdout.splitlines()):
                if not line.strip():
                    continue
                try:
                    parsed_result = json.loads(line)
                except json.JSONDecodeError:
                    parsed_result = None
                break
        outputs = {
            "output": result.output,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": result.returncode,
            "exit_code": result.returncode,
            "exitCode": result.returncode,
            "program": str(argv[0]),
            "status": status.value,
        }
        if self.activity_id == "script.run":
            outputs["result"] = parsed_result
        return ActivityResult(
            status=status,
            outputs={**outputs, **({"artifact_path": artifact_path} if artifact_path else {})},
            evidence=(
                {"kind": "process", "returncode": result.returncode, "timed_out": result.timed_out},
                *([artifact_evidence] if artifact_evidence is not None else []),
            ),
            error=error,
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        await self._adapter.cancel(invocation.invocation_id)

    @staticmethod
    def _failure_outputs(argv: Any) -> dict[str, Any]:
        program = str(argv[0]) if isinstance(argv, (list, tuple)) and argv else ""
        return {"output": "", "stdout": "", "stderr": "", "returncode": None, "exit_code": None, "exitCode": None, "program": program, "status": "failed"}

    @staticmethod
    def _script_argv(inputs: dict[str, Any]) -> tuple[list[str], str | None, str | None]:
        language = str(inputs.get("language") or "python").strip().casefold()
        script = str(inputs.get("script") or "")
        suffixes = {"python": ".py", "powershell": ".ps1", "bash": ".sh"}
        if language not in suffixes:
            return [], None, "language must be python, powershell, or bash"
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=suffixes[language],
            prefix="device-tui-script-",
            delete=False,
        )
        try:
            if language == "python" and str(inputs.get("entrypoint") or "").strip() == "main":
                script = ProcessActivityHandler._python_entrypoint_wrapper(script)
            handle.write(script)
            path = handle.name
        finally:
            handle.close()
        if language == "python":
            return [sys.executable, path], path, None
        if language == "powershell":
            executable = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
            if not executable:
                Path(path).unlink(missing_ok=True)
                return [], None, "PowerShell executable was not found"
            return [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", path], path, None
        executable = ShellCommandActivityHandler._bash_executable()
        if not executable:
            Path(path).unlink(missing_ok=True)
            return [], None, "Bash executable was not found"
        return [executable, path], path, None

    @staticmethod
    def _python_entrypoint_wrapper(script: str) -> str:
        """Invoke a Windmill-style ``main`` function and serialize its return value."""
        return f"""{script}\n\nif __name__ == \"__main__\":\n    import asyncio as _device_tui_asyncio\n    import inspect as _device_tui_inspect\n    import json as _device_tui_json\n    import os as _device_tui_os\n\n    _device_tui_inputs = _device_tui_json.loads(_device_tui_os.environ.get(\"DEVICE_TUI_INPUT_JSON\", \"{{}}\"))\n    _device_tui_result = main(**_device_tui_inputs)\n    if _device_tui_inspect.isawaitable(_device_tui_result):\n        _device_tui_result = _device_tui_asyncio.run(_device_tui_result)\n    if _device_tui_result is not None:\n        print(_device_tui_json.dumps(_device_tui_result, ensure_ascii=False, default=str))\n"""

    def _invalid_input(self, message: str) -> ActivityResult:
        return ActivityResult(
            status=ActivityStatus.FAILED,
            outputs=self._failure_outputs(()),
            error={"code": "process_input_invalid", "message": message, "class": "deterministic"},
        )


__all__ = ["ProcessActivityHandler"]
