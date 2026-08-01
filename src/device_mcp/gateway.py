"""Long-lived gateway between MCP tools and the desktop control API."""

from __future__ import annotations

from pathlib import Path
import threading
import time
from typing import Any

from .client import AppControlClient, AppControlClientError
from .runtime import default_state_path


def unavailable_response(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "message": message,
        "data": {},
        "approval": None,
        "error": {
            "code": "app_unavailable",
            "message": message,
            "details": {},
        },
    }


class McpGateway:
    """Cache desktop discovery state and provide one stable call boundary."""

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or default_state_path()
        self._client: AppControlClient | None = None
        self._state_signature: tuple[int, int] | None = None
        self._lock = threading.RLock()

    def call(self, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        started = time.monotonic()
        try:
            response = getattr(self.client(), method)(*args, **kwargs)
        except AppControlClientError as exc:
            response = exc.response or unavailable_response(str(exc))
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        timing = response.setdefault("timing", {})
        if isinstance(timing, dict):
            timing["gateway_ms"] = elapsed_ms
        return response

    def client(self) -> AppControlClient:
        with self._lock:
            signature = self._signature()
            if self._client is None or signature != self._state_signature:
                previous = self._client
                self._client = AppControlClient.from_state_file(self.state_path)
                self._state_signature = signature
                if previous is not None:
                    previous.close()
            return self._client

    def invalidate(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
            self._state_signature = None
        if client is not None:
            client.close()

    def _signature(self) -> tuple[int, int]:
        try:
            stat = self.state_path.stat()
        except OSError as exc:
            raise AppControlClientError(
                f"未找到可用的 Device TUI 控制服务状态: {self.state_path}"
            ) from exc
        return stat.st_mtime_ns, stat.st_size
