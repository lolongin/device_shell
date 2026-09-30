"""Queue, progress and cancellation coordination for managed transfers."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import time

from .errors import ApplicationConflictError, ResourceNotFoundError
from .operations import TERMINAL_OPERATION_STATUSES
from .sessions import SessionRecord

class TransferQueueMixin:
    def _enqueue(self, record: OperationRecord) -> None:
        self._event_loop = asyncio.get_running_loop()
        self._cancel_idle_stop()
        queue = self._queues.setdefault(record.session_id, deque())
        queue.append(record.id)
        self._operations.register_canceller(
            record.id,
            lambda: self._cancel_queued(record.id, record.session_id),
        )
        self._refresh_queue_positions(record.session_id)
        self._ensure_worker(record.session_id)

    def _ensure_worker(self, session_id: str) -> None:
        if session_id in self._paused_sessions:
            return
        current = self._workers.get(session_id)
        if current is not None and not current.done():
            return
        worker = asyncio.create_task(
            self._run_session_queue(session_id),
            name=f"managed-transfer-queue-{session_id}",
        )
        self._workers[session_id] = worker

    async def _run_session_queue(self, session_id: str) -> None:
        try:
            while session_id not in self._paused_sessions:
                queue = self._queues.get(session_id)
                if not queue:
                    break
                operation_id = queue.popleft()
                self._refresh_queue_positions(session_id)
                record = self._operations.get(operation_id)
                if record.status != "queued":
                    continue
                try:
                    session = self._connected_session(session_id)
                except (ResourceNotFoundError, ApplicationConflictError) as exc:
                    self._mark_failed(operation_id, "session_unavailable", str(exc))
                    continue
                self._operations.update(
                    operation_id,
                    status="running",
                    stage="prechecking",
                    message="正在准备传输。",
                    clear_queue_position=True,
                )
                if record.direction == "download":
                    runner = self._run_download
                elif str(record.data.get("command_mode") or "vrp") == "ftpget":
                    runner = self._run_ftpget_upload
                else:
                    runner = self._run_upload
                task = asyncio.create_task(
                    runner(operation_id, session),
                    name=f"managed-transfer-{operation_id}",
                )
                self._tasks[operation_id] = task
                self._operations.register_canceller(
                    operation_id,
                    lambda oid=operation_id, sid=session_id: self._cancel_active(
                        oid,
                        sid,
                        pause_queue=False,
                    ),
                )
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                finally:
                    self._tasks.pop(operation_id, None)
                    self._progress_samples.pop(operation_id, None)
                    self._last_progress_emit.pop(operation_id, None)
        finally:
            self._workers.pop(session_id, None)
            if not self._queues.get(session_id):
                self._queues.pop(session_id, None)
            elif session_id not in self._paused_sessions:
                self._ensure_worker(session_id)
            self._schedule_idle_stop()

    def _cancel_queued(self, operation_id: str, session_id: str) -> None:
        queue = self._queues.get(session_id)
        if queue is not None:
            try:
                queue.remove(operation_id)
            except ValueError:
                pass
        self._mark_cancelled(operation_id)
        self._refresh_queue_positions(session_id)
        self._schedule_idle_stop()

    def _cancel_active(
        self,
        operation_id: str,
        session_id: str,
        *,
        pause_queue: bool,
    ) -> None:
        if operation_id in self._cancelling:
            return
        self._cancelling.add(operation_id)
        try:
            if pause_queue:
                self._pause_queue_for_takeover(session_id)
            self._executor.cancel_active(session_id)
            self._executor.release(session_id, f"managed-transfer:{operation_id}")
            task = self._tasks.get(operation_id)
            if task is not None and not task.done():
                task.cancel()
            self._mark_cancelled(operation_id)
        finally:
            self._cancelling.discard(operation_id)

    def _pause_queue_for_takeover(self, session_id: str) -> None:
        self._paused_sessions.add(session_id)
        for operation_id in self._queues.get(session_id, ()):
            record = self._operations.get(operation_id)
            if record.status == "queued":
                self._operations.update(
                    operation_id,
                    stage="paused",
                    message="手工输入已接管终端，队列暂停。",
                )

    def _refresh_queue_positions(self, session_id: str) -> None:
        queue = self._queues.get(session_id, deque())
        paused = session_id in self._paused_sessions
        for position, operation_id in enumerate(queue, start=1):
            record = self._operations.get(operation_id)
            if record.status != "queued":
                continue
            self._operations.update(
                operation_id,
                queue_position=position,
                stage="paused" if paused else "queued",
            )

    def _queue_progress_from_thread(self, operation_id: str, transferred: int) -> None:
        loop = self._event_loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._record_progress, operation_id, transferred)

    def _record_progress(
        self,
        operation_id: str,
        transferred: int,
        *,
        force: bool = False,
    ) -> None:
        record = self._operations.get(operation_id)
        if record.status != "running" or record.stage not in {"transferring", "verifying"}:
            return
        now = time.monotonic()
        safe_bytes = max(record.bytes_transferred, int(transferred))
        samples = self._progress_samples.setdefault(operation_id, deque())
        samples.append((now, safe_bytes))
        while len(samples) > 1 and now - samples[0][0] > 5:
            samples.popleft()
        last_emit = self._last_progress_emit.get(operation_id, 0.0)
        if not force and now - last_emit < 0.25:
            return
        speed = 0
        if len(samples) > 1 and samples[-1][0] > samples[0][0]:
            speed = max(0, int((samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0])))
        total = record.total_bytes
        percent = min(100, int(safe_bytes * 100 / total)) if total else 0
        eta = max(0, int((total - safe_bytes) / speed)) if total and speed else None
        self._last_progress_emit[operation_id] = now
        self._operations.update(
            operation_id,
            bytes_transferred=safe_bytes,
            bytes_per_second=speed,
            eta_seconds=eta,
            clear_eta=eta is None,
            progress_percent=percent,
        )
    def _cancel_idle_stop(self) -> None:
        task = self._idle_stop_task
        self._idle_stop_task = None
        self._idle_stop_at = ""
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    def _schedule_idle_stop(self) -> None:
        if self._tasks or not self._controller.is_running:
            return
        if self._idle_stop_task is not None and not self._idle_stop_task.done():
            return
        self._idle_stop_at = (
            datetime.now(timezone.utc) + timedelta(seconds=self.IDLE_STOP_SECONDS)
        ).isoformat()
        self._publish_service_state("transfer.service.updated")
        self._idle_stop_task = asyncio.create_task(
            self._stop_service_when_idle(),
            name="managed-transfer-idle-stop",
        )
    async def _stop_service_when_idle(self) -> None:
        try:
            await asyncio.sleep(self.IDLE_STOP_SECONDS)
            async with self._service_lifecycle_lock:
                if self._tasks or not self._controller.is_running:
                    return
                await asyncio.to_thread(self._controller.stop)
                self._idle_stop_task = None
                self._idle_stop_at = ""
                self._publish_service_state("transfer.service.stopped")
        except asyncio.CancelledError:
            return

    def _publish_service_state(self, event_type: str) -> None:
        self._events.publish(event_type, data=asdict(self.settings()))

    def _mark_cancelled(self, operation_id: str) -> None:
        record = self._operations.get(operation_id)
        if record.status in TERMINAL_OPERATION_STATUSES:
            return
        self._operations.update(
            operation_id,
            status="cancelled",
            stage="cancelled",
            message="文件传输已取消。",
            bytes_per_second=0,
            clear_eta=True,
            clear_queue_position=True,
            error_code="transfer_cancelled",
        )

    def _mark_failed(self, operation_id: str, code: str, message: str) -> None:
        record = self._operations.get(operation_id)
        if record.status in TERMINAL_OPERATION_STATUSES:
            return
        if code == "transfer_cancelled":
            self._mark_cancelled(operation_id)
            return
        self._operations.update(
            operation_id,
            status="failed",
            stage=record.stage,
            message=message,
            bytes_per_second=0,
            clear_eta=True,
            clear_queue_position=True,
            error_code=code,
        )
