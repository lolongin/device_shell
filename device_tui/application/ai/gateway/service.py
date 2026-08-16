"""Gateway facade wiring reusable flow, result, and skill services."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .flow_engine import FlowEngine, parse_flow
from .result_store import ResultStore, summarize_output
from .skills import SkillRegistry


class GatewayUnavailableError(ValueError):
    def __init__(self, message: str = "Gateway 执行器尚未就绪。") -> None:
        super().__init__(message)
        self.code = "gateway_unavailable"


class GatewayService:
    def __init__(
        self,
        *,
        result_store: ResultStore | None = None,
        flow_engine: FlowEngine | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.result_store = result_store or ResultStore()
        self.flow_engine = flow_engine or FlowEngine()
        self.skill_registry = skill_registry or SkillRegistry()
        self._lock = threading.RLock()

    def _run_command(
        self,
        command: str,
        session_id: str,
        timeout_seconds: int,
        executor: Callable[[str, str, int], dict[str, Any]] | None,
    ) -> dict[str, Any]:
        if executor is None:
            raise GatewayUnavailableError()
        return executor(command, session_id, timeout_seconds)

    def _store_summary(self, kind: str, output: str, *, status: str, exit_code: int, command_count: int, duration_ms: int, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        started = time.monotonic()
        error_count, important_lines = summarize_output(output)
        summary = {
            "status": status,
            "exit_code": exit_code,
            "command_count": command_count,
            "error_count": error_count,
            "important_lines": important_lines,
            "duration_ms": int(duration_ms),
        }
        result_id = self.result_store.store(
            kind,
            output,
            metadata={
                "status": status,
                "exit_code": exit_code,
                "command_count": command_count,
                "duration_ms": duration_ms,
                **(extra or {}),
            },
        )
        return {
            "result_id": result_id,
            "summary": summary,
            "response_time_ms": round((time.monotonic() - started) * 1000, 2),
        }

    def execute_command(
        self,
        command: str,
        session_id: str,
        *,
        timeout_seconds: int = 30,
        executor: Callable[[str, str, int], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        raw = self._run_command(command, session_id, timeout_seconds, executor)
        status = str(raw.get("status") or "success")
        output = str(raw.get("output") or "")
        exit_code = int(raw.get("exit_code") or 0)
        return self._store_summary(
            "command",
            output,
            status=status,
            exit_code=exit_code,
            command_count=1,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )

    def execute_batch(
        self,
        commands: list[str],
        session_id: str,
        *,
        command_timeout_seconds: int = 30,
        executor: Callable[[str, str, int], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        outputs: list[str] = []
        last_status = "success"
        last_exit = 0
        for command in commands:
            raw = self._run_command(command, session_id, command_timeout_seconds, executor)
            outputs.append(str(raw.get("output") or ""))
            last_status = str(raw.get("status") or "success")
            last_exit = int(raw.get("exit_code") or 0)
            if last_status != "success":
                break
        return self._store_summary(
            "batch",
            "\n".join(outputs),
            status=last_status,
            exit_code=last_exit,
            command_count=len(commands),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )

    def execute_script(
        self,
        script: str,
        session_id: str,
        *,
        shell: str | None = None,
        timeout_seconds: int = 30,
        is_network_device: bool = False,
        executor: Callable[[str, str, int], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        lines = [line for line in script.splitlines() if line.strip()]
        if is_network_device:
            return self.execute_batch(
                lines,
                session_id,
                command_timeout_seconds=timeout_seconds,
                executor=executor,
            )
        raw = self._run_command(script, session_id, timeout_seconds, executor)
        return self._store_summary(
            "script",
            str(raw.get("output") or ""),
            status=str(raw.get("status") or "success"),
            exit_code=int(raw.get("exit_code") or 0),
            command_count=1,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            extra={"shell": shell},
        )

    def skill_flow(self, skill_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Return the substituted skill flow dict, validated via parse_flow."""
        plan = self.skill_registry.instantiate_flow(skill_name, params)
        # Re-serialize from the parsed plan so service.py can re-parse without a
        # registry reference. All fields round-trip through parse_flow.
        return {
            "steps": [
                {
                    "id": step.id,
                    "command": step.command,
                    "depends_on": step.depends_on,
                    "retry": step.retry,
                    "wait_condition": step.wait_condition,
                    "timeout_seconds": step.timeout_seconds,
                }
                for step in plan.steps
            ]
        }

    def run_skill(
        self,
        skill_name: str,
        params: dict[str, Any],
        *,
        session_id: str = "",
        timeout_seconds: int = 60,
        executor: Callable[[str, str, int], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        flow_data = self.skill_flow(skill_name, params)
        plan = parse_flow(flow_data)

        def execute_step(command: str, session: str, timeout: int) -> tuple[str, str]:
            raw = self._run_command(command, session, timeout, executor)
            return str(raw.get("status") or "success"), str(raw.get("output") or "")

        def wait_for_condition(
            condition: dict[str, Any],
            session: str,
            device: str,
        ) -> tuple[str, str]:
            raw = self._run_command(str(condition.get("command") or ""), session, 30, executor)
            output = str(raw.get("output") or "")
            expected = str(condition.get("expected") or "")
            if expected and expected in output:
                return "success", output
            return "not_ready", output

        results = self.flow_engine.run(
            plan,
            session_id=session_id,
            device_id=str(params.get("device_id") or ""),
            execute_step=execute_step,
            wait_for_condition=wait_for_condition,
        )
        all_outputs = "\n".join(result.output for result in results if result.output)
        failed = [r for r in results if r.status == "failed"]
        status = "failed" if failed else "success"
        return self._store_summary(
            "skill",
            all_outputs,
            status=status,
            exit_code=1 if failed else 0,
            command_count=len(plan.steps),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            extra={
                "skill_name": skill_name,
                "step_results": [
                    {
                        "id": r.id,
                        "status": r.status,
                        "output": r.output,
                        "error_code": r.error_code,
                        "message": r.message,
                        "attempt_count": r.attempt_count,
                    }
                    for r in results
                ],
            },
        )

    def get_result(self, result_id: str, *, include_raw: bool = False) -> dict[str, Any] | None:
        entry = self.result_store.get(result_id)
        if entry is None:
            return None
        result = {
            "result_id": entry.result_id,
            "kind": entry.kind,
            "summary": entry.summary,
            "metadata": entry.metadata,
        }
        if include_raw:
            return {"result": result, "raw_output": entry.output}
        return {"result": result}

    def snapshot(self) -> dict[str, Any]:
        return {
            "result_store": self.result_store.snapshot(),
            "skills": self.skill_registry.list_skills(),
        }
