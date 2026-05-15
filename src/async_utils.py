"""Async event-loop bridge for Qt applications."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any


class AsyncLoopThread:
    """Dedicated thread running an asyncio event loop for background tasks."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="device-tui-async-loop"
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _cancel_pending_tasks(self) -> None:
        current = asyncio.current_task(self._loop)
        tasks = [
            task
            for task in asyncio.all_tasks(self._loop)
            if task is not current and not task.done()
        ]
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def cancel_pending(self, timeout: float = 2.0) -> None:
        if not self._loop.is_running():
            return
        try:
            self.submit(self._cancel_pending_tasks()).result(timeout=timeout)
        except Exception:
            pass

    def stop(self) -> None:
        self.cancel_pending(timeout=1.0)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)
