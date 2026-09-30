"""Session lease coordination for terminal executions."""

from __future__ import annotations

import threading
import time
from typing import Callable
from uuid import uuid4

from .execution_runner import TerminalExecutionRunner
from .plan_models import TerminalExecutionPlan, TerminalInput, TerminalPlanError

class TerminalExecutionCoordinator:
    def __init__(
        self,
        *,
        send_input: Callable[[str, TerminalInput, str], None],
        resolve_secret: Callable[[str], str],
        schedule: Callable[[int, Callable[[], None]], None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.send_input = send_input
        self.resolve_secret = resolve_secret
        self.schedule = schedule
        self.clock = clock
        self._executions: dict[str, TerminalExecutionRunner] = {}
        self._session_leases: dict[str, str] = {}
        self._external_lease_cancellers: dict[str, Callable[[], None]] = {}
        self._runner_parent_leases: dict[str, str] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = threading.RLock()

    def start(
        self,
        *,
        session_id: str,
        device_id: str,
        plan: TerminalExecutionPlan,
        execution_id: str | None = None,
        idempotency_key: str = "",
        lease_owner_id: str = "",
    ) -> TerminalExecutionRunner:
        with self._lock:
            if idempotency_key:
                existing_id = self._idempotency.get(idempotency_key)
                if existing_id:
                    return self._executions[existing_id]
            active_id = self._session_leases.get(session_id)
            can_use_parent_lease = bool(
                active_id
                and active_id == lease_owner_id
                and active_id in self._external_lease_cancellers
            )
            if active_id and not can_use_parent_lease:
                raise TerminalPlanError(
                    "session_busy",
                    f"会话正在执行其他任务: {active_id}",
                )
            run_id = execution_id or str(uuid4())
            runner = TerminalExecutionRunner(
                execution_id=run_id,
                session_id=session_id,
                device_id=device_id,
                plan=plan,
                send_input=self.send_input,
                resolve_secret=self.resolve_secret,
                schedule=self.schedule,
                on_finished=self._runner_finished,
                clock=self.clock,
            )
            self._executions[run_id] = runner
            self._session_leases[session_id] = run_id
            if can_use_parent_lease:
                self._runner_parent_leases[run_id] = active_id
            if idempotency_key:
                self._idempotency[idempotency_key] = run_id
        runner.start()
        return runner

    def get(self, execution_id: str) -> TerminalExecutionRunner:
        with self._lock:
            runner = self._executions.get(execution_id)
        if runner is None:
            raise TerminalPlanError(
                "execution_not_found",
                f"未找到终端执行: {execution_id}",
            )
        return runner

    def wait(self, execution_id: str, timeout_seconds: float) -> bool:
        return self.get(execution_id).completion_event.wait(timeout_seconds)

    def cancel(self, execution_id: str, *, by_user: bool = False) -> TerminalExecutionRunner:
        runner = self.get(execution_id)
        runner.cancel(by_user=by_user)
        return runner

    def resume(self, execution_id: str) -> TerminalExecutionRunner:
        runner = self.get(execution_id)
        with self._lock:
            active_id = self._session_leases.get(runner.session_id)
            if active_id and active_id != execution_id:
                raise TerminalPlanError(
                    "session_busy",
                    f"会话正在执行其他任务: {active_id}",
                )
            self._session_leases[runner.session_id] = execution_id
        try:
            runner.resume()
        except Exception:
            with self._lock:
                if self._session_leases.get(runner.session_id) == execution_id:
                    self._session_leases.pop(runner.session_id, None)
            raise
        return runner

    def cancel_for_user_input(self, session_id: str) -> str:
        with self._lock:
            execution_id = self._session_leases.get(session_id, "")
            external_cancel = self._external_lease_cancellers.get(execution_id)
            runner = self._executions.get(execution_id)
            if external_cancel is not None and runner is None:
                self._session_leases.pop(session_id, None)
                self._external_lease_cancellers.pop(execution_id, None)
        if runner is not None:
            self.cancel(execution_id, by_user=True)
        elif external_cancel is not None:
            external_cancel()
        return execution_id

    def acquire_external_lease(
        self,
        session_id: str,
        owner_id: str,
        *,
        on_cancel: Callable[[], None],
    ) -> None:
        with self._lock:
            active_id = self._session_leases.get(session_id)
            if active_id and active_id != owner_id:
                raise TerminalPlanError(
                    "session_busy",
                    f"会话正在执行其他任务: {active_id}",
                )
            self._session_leases[session_id] = owner_id
            self._external_lease_cancellers[owner_id] = on_cancel

    def release_external_lease(self, session_id: str, owner_id: str) -> None:
        with self._lock:
            if self._session_leases.get(session_id) == owner_id:
                self._session_leases.pop(session_id, None)
            self._external_lease_cancellers.pop(owner_id, None)

    def on_output(self, session_id: str, message: str) -> None:
        runner = self._active_for_session(session_id)
        if runner is not None:
            runner.on_output(message)

    def on_session_state(self, session_id: str, state: str) -> None:
        runner = self._active_for_session(session_id)
        if runner is not None:
            runner.on_session_state(state)

    def active_execution_id(self, session_id: str) -> str:
        with self._lock:
            return self._session_leases.get(session_id, "")

    def redact_output(self, session_id: str, message: str) -> str:
        runner = self._active_for_session(session_id)
        return runner.redact_text(message) if runner is not None else message

    def _active_for_session(self, session_id: str) -> TerminalExecutionRunner | None:
        with self._lock:
            execution_id = self._session_leases.get(session_id)
            return self._executions.get(execution_id) if execution_id else None

    def _runner_finished(self, runner: TerminalExecutionRunner) -> None:
        with self._lock:
            if self._session_leases.get(runner.session_id) == runner.execution_id:
                parent_id = self._runner_parent_leases.pop(
                    runner.execution_id,
                    "",
                )
                if parent_id and parent_id in self._external_lease_cancellers:
                    self._session_leases[runner.session_id] = parent_id
                else:
                    self._session_leases.pop(runner.session_id, None)
