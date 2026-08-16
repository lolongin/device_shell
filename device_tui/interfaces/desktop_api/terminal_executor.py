"""Adapt the existing terminal-plan engine to backend-owned SessionHub sessions."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Callable
from uuid import uuid4

from device_tui.application.terminal.orchestration import (
    TerminalExecutionCoordinator,
    TerminalExecutionPlan,
    TerminalInput,
    TerminalPlanError,
)
from .session_hub import SessionHub, TerminalEvent


class BackendTerminalExecutor:
    def __init__(
        self,
        hub: SessionHub,
        resolve_secret: Callable[[str], str],
    ) -> None:
        self._hub = hub
        self._resolve_secret = resolve_secret
        self._execution_owners: dict[str, str] = {}
        self._owner_sessions: dict[str, str] = {}
        self._write_tasks: dict[str, set[asyncio.Task[None]]] = {}
        self._coordinator = TerminalExecutionCoordinator(
            send_input=self._send_input,
            resolve_secret=lambda reference: self._resolve_secret(reference),
            schedule=self._schedule,
        )
        self._hub.add_event_listener(self._on_terminal_event)

    def set_secret_resolver(self, resolver: Callable[[str], str]) -> None:
        self._resolve_secret = resolver

    def acquire(
        self,
        session_id: str,
        owner_id: str,
        *,
        on_cancel: Callable[[], None],
    ) -> None:
        self._hub.acquire_lease(session_id, owner_id)
        try:
            self._coordinator.acquire_external_lease(
                session_id,
                owner_id,
                on_cancel=on_cancel,
            )
        except Exception:
            self._hub.release_lease(session_id, owner_id)
            raise
        self._owner_sessions[owner_id] = session_id

    def release(self, session_id: str, owner_id: str) -> None:
        self._coordinator.release_external_lease(session_id, owner_id)
        with suppress(KeyError):
            self._hub.release_lease(session_id, owner_id)
        self._owner_sessions.pop(owner_id, None)

    async def run(
        self,
        *,
        session_id: str,
        device_id: str,
        plan: TerminalExecutionPlan,
        owner_id: str,
    ) -> dict[str, object]:
        loop = asyncio.get_running_loop()
        execution_id = str(uuid4())
        self._execution_owners[execution_id] = owner_id
        completed: asyncio.Future[dict[str, object]] = loop.create_future()
        try:
            runner = self._coordinator.start(
                session_id=session_id,
                device_id=device_id,
                plan=plan,
                execution_id=execution_id,
                lease_owner_id=owner_id,
            )
        except Exception:
            self._execution_owners.pop(execution_id, None)
            raise

        def finish(_runner: object) -> None:
            result = runner.public_dict()

            def deliver() -> None:
                if not completed.done():
                    completed.set_result(result)

            loop.call_soon_threadsafe(deliver)

        runner.add_done_callback(finish)
        try:
            return await completed
        except asyncio.CancelledError:
            with suppress(TerminalPlanError):
                self._coordinator.cancel(execution_id)
            raise
        finally:
            self._execution_owners.pop(execution_id, None)

    def cancel_active(self, session_id: str) -> str:
        first = self._coordinator.cancel_for_user_input(session_id)
        self._cancel_writes(first)
        # A managed operation owns an external lease around each child plan.
        # Cancelling the child restores that parent lease, so drain it as well.
        second = self._coordinator.cancel_for_user_input(session_id)
        self._cancel_writes(second)
        return first or second

    def get_execution(self, execution_id: str) -> dict[str, object]:
        """Return a redacted terminal-plan snapshot for MCP compatibility."""
        return self._coordinator.get(execution_id).public_dict()

    def cancel_execution(self, execution_id: str) -> dict[str, object]:
        """Cancel one terminal plan and return its final snapshot."""
        self._cancel_writes(execution_id)
        return self._coordinator.cancel(execution_id).public_dict()

    def configure_managed_transfer(
        self,
        session_id: str,
        *,
        username: str,
        password: str,
        source_path: str,
        source_size: int,
        destination_path: str,
    ) -> None:
        self._hub.configure_managed_transfer(
            session_id,
            username=username,
            password=password,
            source_path=source_path,
            source_size=source_size,
            destination_path=destination_path,
        )

    def close(self) -> None:
        self._hub.remove_event_listener(self._on_terminal_event)
        for owner_id, session_id in tuple(self._owner_sessions.items()):
            self.cancel_active(session_id)
            self.release(session_id, owner_id)
        for execution_id in tuple(self._write_tasks):
            self._cancel_writes(execution_id)

    def _send_input(
        self,
        session_id: str,
        payload: TerminalInput,
        execution_id: str,
    ) -> None:
        owner_id = self._execution_owners.get(execution_id, execution_id)
        if payload.sensitive:
            self._hub.protect_sensitive_output(
                session_id,
                payload.text,
                ttl_seconds=15,
            )
        task = asyncio.create_task(
            self._hub.write(
                session_id,
                payload.text,
                lease_owner=owner_id,
                origin="operation",
            ),
            name=f"terminal-plan-write-{execution_id}",
        )
        self._write_tasks.setdefault(execution_id, set()).add(task)
        task.add_done_callback(
            lambda completed, run_id=execution_id: self._write_finished(
                run_id,
                completed,
            )
        )

    def _cancel_writes(self, execution_id: str) -> None:
        if not execution_id:
            return
        for task in tuple(self._write_tasks.pop(execution_id, ())):
            if not task.done():
                task.cancel()

    def _write_finished(
        self,
        execution_id: str,
        task: asyncio.Task[None],
    ) -> None:
        tasks = self._write_tasks.get(execution_id)
        if tasks is not None:
            tasks.discard(task)
            if not tasks:
                self._write_tasks.pop(execution_id, None)
        self._consume_write_failure(task)

    @staticmethod
    def _consume_write_failure(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        with suppress(Exception):
            task.result()

    @staticmethod
    def _schedule(delay_ms: int, callback: Callable[[], None]) -> None:
        loop = asyncio.get_running_loop()
        loop.call_later(max(0, delay_ms) / 1000, callback)

    def _on_terminal_event(self, event: TerminalEvent) -> None:
        if event.type == "terminal.output":
            self._coordinator.on_output(event.session_id, event.data)
        elif event.type == "terminal.status":
            self._coordinator.on_session_state(event.session_id, event.status)
        elif event.type == "terminal.input":
            origin = str(event.metadata.get("origin") or "user")
            if origin in {"user", "command"}:
                self.cancel_active(event.session_id)
                # The input is evaluated by SessionHub immediately after this
                # callback. Release any outer operation lease synchronously so
                # the takeover keystroke itself is delivered, not rejected.
                for owner_id, session_id in tuple(self._owner_sessions.items()):
                    if session_id == event.session_id:
                        self.release(session_id, owner_id)
