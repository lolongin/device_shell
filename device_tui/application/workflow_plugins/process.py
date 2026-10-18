"""Generic process-backed Activity handlers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Awaitable, Callable, Mapping

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

    def __init__(
        self,
        activity_id: str,
        adapter: LocalProcessAdapter | None = None,
        *,
        device_command: Callable[[ActivityInvocation, ActivityContext, str, float, str | None], Awaitable[Mapping[str, Any]]] | None = None,
        device_connections: Callable[[ActivityInvocation, ActivityContext], Awaitable[list[Mapping[str, Any]]]] | None = None,
    ) -> None:
        self.activity_id = activity_id
        self._adapter = adapter or LocalProcessAdapter()
        self._device_command = device_command
        self._device_connections = device_connections

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        inputs = invocation.inputs
        script_path: str | None = None
        script_inputs = dict(inputs)
        if self.activity_id == "script.run" and str(inputs.get("script") or "").strip():
            argv, script_path, script_error = self._script_argv(inputs, enable_device=self._device_command is not None)
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
            timeout = float(inputs.get("timeout_seconds", 300))
        except (TypeError, ValueError):
            return self._invalid_input("timeout_seconds must be a number")
        if timeout < 0 or timeout > 86_400:
            return self._invalid_input("timeout_seconds must be between 0 and 86400")

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
                timeout_seconds=timeout or None,
                max_output_chars=int(script_inputs.get("max_output_chars") or 1_048_576),
                on_output=output,
                on_rpc=(lambda request: self._handle_device_rpc(invocation, context, request)) if self._device_command is not None else None,
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
        result_parsed = False
        if self.activity_id == "script.run":
            for line in reversed(stdout.splitlines()):
                if not line.strip():
                    continue
                try:
                    parsed_result = json.loads(line)
                    result_parsed = True
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
            outputs["result_parsed"] = result_parsed
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
    def _script_argv(inputs: dict[str, Any], *, enable_device: bool = False) -> tuple[list[str], str | None, str | None]:
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
            if language == "python" and enable_device:
                script = ProcessActivityHandler._python_device_rpc_bootstrap() + "\n" + script
            if language == "python" and str(inputs.get("entrypoint") or "").strip() == "main":
                script = ProcessActivityHandler._python_entrypoint_wrapper(script, enable_device=enable_device)
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
    def _python_entrypoint_wrapper(script: str, *, enable_device: bool = False) -> str:
        """Invoke a Windmill-style ``main`` function and serialize its return value."""
        return f"""{script}\n\nif __name__ == \"__main__\":\n    import asyncio as _device_tui_asyncio\n    import inspect as _device_tui_inspect\n    import json as _device_tui_json\n    import os as _device_tui_os\n\n    _device_tui_inputs = _device_tui_json.loads(_device_tui_os.environ.get(\"DEVICE_TUI_INPUT_JSON\", \"{{}}\"))\n    if {enable_device!r}:\n        _device_tui_signature = _device_tui_inspect.signature(main)\n        _device_tui_device_parameter = _device_tui_signature.parameters.get(\"device\")\n        if (_device_tui_device_parameter is not None and _device_tui_device_parameter.kind in (\n            _device_tui_inspect.Parameter.POSITIONAL_OR_KEYWORD,\n            _device_tui_inspect.Parameter.KEYWORD_ONLY,\n        )) or any(\n            _parameter.kind == _device_tui_inspect.Parameter.VAR_KEYWORD\n            for _parameter in _device_tui_signature.parameters.values()\n        ):\n            _device_tui_inputs[\"device\"] = device\n    _device_tui_result = main(**_device_tui_inputs)\n    if _device_tui_inspect.isawaitable(_device_tui_result):\n        _device_tui_result = _device_tui_asyncio.run(_device_tui_result)\n    if _device_tui_result is not None:\n        print(_device_tui_json.dumps(_device_tui_result, ensure_ascii=False, default=str))\n"""

    @staticmethod
    def _python_device_rpc_bootstrap() -> str:
        """Expose synchronous ``device.run`` over the parent process stdin/stdout bridge."""
        return '''
import json as _device_tui_json
import sys as _device_tui_sys
import threading as _device_tui_threading

class _DeviceTuiDevice:
    _lock = _device_tui_threading.Lock()
    _prefix = "\\x1eDEVICE_TUI_RPC:"

    def _request(self, request: dict) -> object:
        with self._lock:
            print(self._prefix + _device_tui_json.dumps(request, ensure_ascii=False), flush=True)
            line = _device_tui_sys.stdin.readline()
            if not line:
                raise RuntimeError("device command bridge closed")
            response = _device_tui_json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "device command failed")
        return response["result"]

    @property
    def connections(self) -> list[dict]:
        """Terminal sessions for the workflow's selected device, including status."""
        return self._request({"method": "connections"})

    def run(self, command: str, timeout: float = 30, connection: str | None = None) -> dict:
        """Run a CLI command. connection can be a protocol name or session id."""
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        return self._request({"method": "run", "command": command, "timeout": timeout, "connection": connection})

device = _DeviceTuiDevice()
'''

    async def _handle_device_rpc(
        self,
        invocation: ActivityInvocation,
        context: ActivityContext,
        request: Mapping[str, object],
    ) -> Mapping[str, object]:
        method = request.get("method")
        if method == "connections":
            if self._device_connections is None:
                return {"ok": False, "error": "device connections are unavailable"}
            try:
                connections = await self._device_connections(invocation, context)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "result": [dict(item) for item in connections]}
        if method != "run":
            return {"ok": False, "error": "unsupported device method"}
        command = request.get("command")
        if not isinstance(command, str) or not command.strip():
            return {"ok": False, "error": "command must be a non-empty string"}
        try:
            timeout = float(request.get("timeout", 30))
        except (TypeError, ValueError):
            return {"ok": False, "error": "timeout must be a number"}
        if timeout <= 0 or timeout > 86_400:
            return {"ok": False, "error": "timeout must be greater than 0 and at most 86400 seconds"}
        raw_connection = request.get("connection")
        if raw_connection is not None and (not isinstance(raw_connection, str) or not raw_connection.strip()):
            return {"ok": False, "error": "connection must be a non-empty connection name or session id"}
        if self._device_command is None:
            return {"ok": False, "error": "device command bridge is unavailable"}
        try:
            result = await self._device_command(invocation, context, command, timeout, raw_connection)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "result": dict(result)}

    def _invalid_input(self, message: str) -> ActivityResult:
        return ActivityResult(
            status=ActivityStatus.FAILED,
            outputs=self._failure_outputs(()),
            error={"code": "process_input_invalid", "message": message, "class": "deterministic"},
        )


__all__ = ["ProcessActivityHandler"]
