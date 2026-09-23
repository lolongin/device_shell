"""Local Shell command Activity with a stable command-result contract."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from device_tui.application.workflow_runtime.output_contract import normalize_command_output
from device_tui.framework import ActivityContext, ActivityInvocation, ActivityResult, ActivityStatus, Event


class ShellCommandActivityHandler:
    """Execute an arbitrary local Shell or Bash command without a shell=True hop."""

    activity_id = "shell.command"

    def __init__(self) -> None:
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        command = str(invocation.inputs.get("command") or "")
        if not command.strip():
            return self._invalid("command is required")
        mode = str(invocation.inputs.get("execution_mode") or "shell").strip().casefold()
        if mode not in {"shell", "bash"}:
            return self._invalid("execution_mode must be shell or bash")
        try:
            timeout = float(invocation.inputs.get("timeout_seconds") or 30)
        except (TypeError, ValueError):
            return self._invalid("timeout_seconds must be a number")
        if timeout <= 0 or timeout > 86_400:
            return self._invalid("timeout_seconds must be between 0 and 86400")
        try:
            max_output_chars = int(invocation.inputs.get("max_output_chars") or 1_048_576)
        except (TypeError, ValueError):
            return self._invalid("max_output_chars must be an integer")
        max_output_chars = max(1_024, min(max_output_chars, 16_777_216))

        cwd_value = str(invocation.inputs.get("cwd") or "").strip()
        cwd = str(Path(cwd_value).expanduser().resolve()) if cwd_value else None
        raw_env = invocation.inputs.get("env")
        if raw_env not in (None, {}) and not isinstance(raw_env, Mapping):
            return self._invalid("env must be an object")
        env = dict(os.environ)
        if isinstance(raw_env, Mapping):
            env.update({str(key): str(value) for key, value in raw_env.items()})

        argv = self._command_argv(mode, command)
        if not argv:
            return self._invalid(f"{mode} executable was not found")
        report(Event(
            type="shell.command.started",
            run_id=invocation.workflow_run_id,
            action_id=invocation.activity_id,
            source="shell.command",
            payload={"execution_mode": mode, "program": argv[0]},
        ))
        started = perf_counter()
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._processes[invocation.invocation_id] = process
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                await self._stop(process)
                stdout_bytes, stderr_bytes = await process.communicate()
                return self._result(
                    ActivityStatus.FAILED,
                    stdout_bytes,
                    stderr_bytes,
                    process.returncode,
                    "timeout",
                    perf_counter() - started,
                    max_output_chars,
                    error={"code": "shell_command_timeout", "message": f"command timed out after {timeout:g} seconds", "class": "timeout"},
                )
            status = ActivityStatus.SUCCEEDED if process.returncode == 0 else ActivityStatus.FAILED
            status_text = "succeeded" if status == ActivityStatus.SUCCEEDED else "failed"
            result = self._result(
                status,
                stdout_bytes,
                stderr_bytes,
                process.returncode,
                status_text,
                perf_counter() - started,
                max_output_chars,
                error=None if status == ActivityStatus.SUCCEEDED else {
                    "code": "shell_command_failed",
                    "message": f"command exited with code {process.returncode}",
                    "class": "deterministic",
                },
            )
            report(Event(
                type="shell.command.completed",
                run_id=invocation.workflow_run_id,
                action_id=invocation.activity_id,
                source="shell.command",
                payload={"status": status_text, "exitCode": process.returncode, "duration": result.outputs["duration"]},
            ))
            return result
        except FileNotFoundError as exc:
            return self._result(
                ActivityStatus.FAILED,
                b"",
                str(exc).encode("utf-8", errors="replace"),
                None,
                "failed",
                perf_counter() - started,
                max_output_chars,
                error={"code": "shell_not_found", "message": str(exc), "class": "deterministic"},
            )
        except asyncio.CancelledError:
            if process is not None:
                await self._stop(process)
            raise
        except Exception as exc:
            if process is not None:
                await self._stop(process)
            return self._result(
                ActivityStatus.FAILED,
                b"",
                str(exc).encode("utf-8", errors="replace"),
                process.returncode if process is not None else None,
                "failed",
                perf_counter() - started,
                max_output_chars,
                error={"code": "shell_command_error", "message": str(exc), "class": "transient"},
            )
        finally:
            self._processes.pop(invocation.invocation_id, None)

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        process = self._processes.get(invocation.invocation_id)
        if process is not None:
            await self._stop(process)

    @staticmethod
    def _command_argv(mode: str, command: str) -> tuple[str, ...]:
        if mode == "bash":
            executable = ShellCommandActivityHandler._bash_executable()
            return (executable, "-lc", command) if executable else ()
        if sys.platform == "win32":
            executable = shutil.which("powershell.exe") or shutil.which("powershell")
            return (executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command) if executable else ()
        executable = shutil.which("sh") or "/bin/sh"
        return (executable, "-lc", command)

    @staticmethod
    def _bash_executable() -> str | None:
        """Prefer a native Git Bash on Windows over the legacy WSL launcher."""
        if sys.platform != "win32":
            return shutil.which("bash")
        candidates: list[Path] = []
        git = shutil.which("git")
        if git:
            git_root = Path(git).resolve().parent.parent
            candidates.extend((git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"))
        program_files = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]
        candidates.extend(Path(value) / "Git" / "bin" / "bash.exe" for value in program_files if value)
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return shutil.which("bash")

    @staticmethod
    async def _stop(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    @classmethod
    def _result(
        cls,
        activity_status: ActivityStatus,
        stdout_bytes: bytes,
        stderr_bytes: bytes,
        exit_code: int | None,
        status: str,
        duration: float,
        max_output_chars: int,
        *,
        error: dict[str, Any] | None,
    ) -> ActivityResult:
        stdout = stdout_bytes.decode("utf-8", errors="replace")[-max_output_chars:]
        stderr = stderr_bytes.decode("utf-8", errors="replace")[-max_output_chars:]
        outputs = normalize_command_output(
            {"stdout": stdout, "stderr": stderr},
            status=status,
            exit_code=exit_code,
            duration=duration,
            error=error,
        )
        return ActivityResult(
            status=activity_status,
            outputs=outputs,
            evidence=({"kind": "local_command", "exitCode": exit_code, "status": status},),
            error=error,
        )

    @classmethod
    def _invalid(cls, message: str) -> ActivityResult:
        return cls._result(
            ActivityStatus.FAILED,
            b"",
            message.encode("utf-8"),
            None,
            "failed",
            0.0,
            1_048_576,
            error={"code": "shell_command_invalid", "message": message, "class": "deterministic"},
        )


__all__ = ["ShellCommandActivityHandler"]
