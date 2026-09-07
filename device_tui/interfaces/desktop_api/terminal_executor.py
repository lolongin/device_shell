"""Adapt the existing terminal-plan engine to backend-owned SessionHub sessions."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Callable
from uuid import uuid4

from device_tui.application.terminal.orchestration import (
    ExpectStep,
    TerminalExecutionCoordinator,
    TerminalExecutionPlan,
    TerminalInput,
    TerminalPlanError,
)
from device_tui.application.terminal.outcome import PromptMatch, classify_terminal_prompt
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
        execution_id: str | None = None,
        return_on_interaction: bool = False,
    ) -> dict[str, object]:
        return await self._run(
            session_id=session_id,
            device_id=device_id,
            plan=plan,
            owner_id=owner_id,
            execution_id=execution_id,
            return_on_attention=return_on_interaction,
        )

    async def _run(
        self,
        *,
        session_id: str,
        device_id: str,
        plan: TerminalExecutionPlan,
        owner_id: str,
        execution_id: str | None,
        return_on_attention: bool,
    ) -> dict[str, object]:
        execution_id = execution_id or str(uuid4())
        self._execution_owners[execution_id] = owner_id
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

        def cleanup(_runner: object) -> None:
            self._execution_owners.pop(execution_id, None)

        runner.add_done_callback(cleanup)
        try:
            wait_event = (
                runner.attention_event
                if return_on_attention
                else runner.completion_event
            )
            await asyncio.to_thread(wait_event.wait)
            return runner.public_dict()
        except asyncio.CancelledError:
            with suppress(TerminalPlanError):
                self._coordinator.cancel(execution_id)
            raise
        finally:
            if runner.is_terminal:
                self._execution_owners.pop(execution_id, None)

    def start_plan(
        self,
        *,
        session_id: str,
        device_id: str,
        plan: TerminalExecutionPlan,
        execution_id: str | None = None,
        attach_mode: str = "fresh",
        output_cursor: int | None = None,
        generation: int | None = None,
        expected_prompt: str = "",
    ) -> dict[str, object]:
        """Start a plan without waiting for completion."""
        mode = str(attach_mode or "fresh").strip().casefold()
        if mode not in {"fresh", "attach"}:
            raise TerminalPlanError(
                "invalid_attach_mode",
                "attach_mode must be fresh or attach.",
            )
        terminal = self._hub.terminal_snapshot(session_id)
        prompt = classify_terminal_prompt(str(terminal.get("output") or ""))
        if mode == "fresh" and prompt is not None and prompt.type != "command_prompt":
            raise TerminalPlanError(
                "session_not_ready",
                "The terminal is already waiting for input; use attach mode to continue it.",
                details={
                    "generation": terminal["generation"],
                    "output_cursor": terminal["output_cursor"],
                    "prompt": prompt.public_dict(),
                },
            )
        if mode == "attach":
            self._validate_attachment(
                plan=plan,
                terminal=terminal,
                prompt=prompt,
                output_cursor=output_cursor,
                generation=generation,
                expected_prompt=expected_prompt,
            )
        execution_id = execution_id or str(uuid4())
        owner_id = f"mcp-terminal:{execution_id}"
        self._execution_owners[execution_id] = owner_id
        try:
            runner = self._coordinator.start(
                session_id=session_id,
                device_id=device_id,
                plan=plan,
                execution_id=execution_id,
            )
        except Exception:
            self._execution_owners.pop(execution_id, None)
            raise

        def cleanup(_runner: object) -> None:
            self._execution_owners.pop(execution_id, None)

        runner.add_done_callback(cleanup)
        if mode == "attach":
            runner.on_output(str(terminal.get("output") or ""))
        return runner.public_dict()

    def terminal_snapshot(self, session_id: str, *, max_chars: int = 32_768) -> dict[str, object]:
        return self._hub.terminal_snapshot(session_id, max_chars=max_chars)

    @staticmethod
    def _validate_attachment(
        *,
        plan: TerminalExecutionPlan,
        terminal: dict[str, object],
        prompt: PromptMatch | None,
        output_cursor: int | None,
        generation: int | None,
        expected_prompt: str,
    ) -> None:
        if not plan.steps or not isinstance(plan.steps[0], ExpectStep):
            raise TerminalPlanError(
                "invalid_attachment_plan",
                "An attached interaction must start with an expect step.",
            )
        if output_cursor is None or generation is None:
            raise TerminalPlanError(
                "attachment_context_required",
                "Attach mode requires output_cursor and generation.",
            )
        if int(generation) != int(terminal["generation"]):
            raise TerminalPlanError(
                "stale_terminal_generation",
                "The terminal reconnected after the attachment context was observed.",
                details={"generation": terminal["generation"]},
            )
        if int(output_cursor) != int(terminal["output_cursor"]):
            raise TerminalPlanError(
                "stale_terminal_cursor",
                "Terminal output changed after the attachment context was observed.",
                details={"output_cursor": terminal["output_cursor"]},
            )
        if prompt is None:
            raise TerminalPlanError(
                "prompt_mismatch",
                "The current terminal tail does not contain an active prompt.",
            )
        prompt_type = str(getattr(prompt, "type", ""))
        prompt_text = str(getattr(prompt, "text", ""))
        expected = str(expected_prompt or "").strip()
        if not expected or expected not in {prompt_type, prompt_text}:
            raise TerminalPlanError(
                "prompt_mismatch",
                "The current terminal prompt does not match expected_prompt.",
                details={"prompt": prompt.public_dict()},
            )

    def get_execution(self, execution_id: str, *, since_cursor: int = 0, wait_seconds: float = 0.0) -> dict[str, object]:
        """Return a redacted terminal-plan snapshot for MCP compatibility."""
        runner = self._coordinator.get(execution_id)
        if wait_seconds > 0:
            return runner.wait_for_event(since_cursor, wait_seconds)
        return runner.snapshot(since_cursor=since_cursor)

    def send_manual_input(
        self,
        execution_id: str,
        *,
        text: str = "",
        control: str = "",
        secret_ref: str = "",
        append_enter: bool = True,
    ) -> dict[str, object]:
        runner = self._coordinator.get(execution_id)
        runner.send_manual_input(
            text=text,
            control=control,
            secret_ref=secret_ref,
            append_enter=append_enter,
        )
        return runner.public_dict()

    def resume_execution(self, execution_id: str) -> dict[str, object]:
        runner = self._coordinator.resume(execution_id)
        return runner.public_dict()

    def wait_execution(self, execution_id: str, timeout_seconds: float) -> bool:
        return self._coordinator.wait(execution_id, timeout_seconds)

    def cancel_active(self, session_id: str) -> str:
        first = self._coordinator.cancel_for_user_input(session_id)
        self._cancel_writes(first)
        # A managed operation owns an external lease around each child plan.
        # Cancelling the child restores that parent lease, so drain it as well.
        second = self._coordinator.cancel_for_user_input(session_id)
        self._cancel_writes(second)
        return first or second

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
