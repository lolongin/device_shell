"""Long-lived gateway between MCP tools and the desktop control API."""

from __future__ import annotations

from pathlib import Path
import json
import os
import threading
import time
from typing import Any

from .client import AppControlClient, AppControlClientError
from .desktop_client import DesktopApiClient, DesktopApiClientError
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
        self._desktop_url = os.getenv("DEVICE_TUI_MCP_BACKEND_URL", "").strip()
        self._desktop_token = os.getenv("DEVICE_TUI_MCP_BACKEND_TOKEN", os.getenv("DEVICE_TUI_DESKTOP_TOKEN", ""))
        self._client: AppControlClient | DesktopApiClient | None = None
        self._state_signature: tuple[object, ...] | None = None
        self._lock = threading.RLock()

    def call(self, method: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        started = time.monotonic()
        try:
            response = getattr(self.client(), method)(*args, **kwargs)
        except (AppControlClientError, DesktopApiClientError) as exc:
            response = exc.response or unavailable_response(str(exc))
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        timing = response.setdefault("timing", {})
        if isinstance(timing, dict):
            timing["gateway_ms"] = elapsed_ms
        return response

    def client(self) -> AppControlClient | DesktopApiClient:
        with self._lock:
            signature = self._signature()
            if self._client is None or signature != self._state_signature:
                previous = self._client
                if self._desktop_url and self._desktop_token:
                    self._client = DesktopApiClient(self._desktop_url, self._desktop_token)
                else:
                    self._client = self._client_from_state_file()
                self._state_signature = signature
                if previous is not None:
                    previous.close()
            return self._client

    def _client_from_state_file(self) -> AppControlClient | DesktopApiClient:
        """Select the protocol from the runtime state written by Electron."""
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return AppControlClient.from_state_file(self.state_path)
        if payload.get("transport") == "desktop-api":
            return DesktopApiClient(str(payload["base_url"]), str(payload.get("token") or ""))
        return AppControlClient.from_state_file(self.state_path)

    def invalidate(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
            self._state_signature = None
        if client is not None:
            client.close()

    def _signature(self) -> tuple[object, ...]:
        if self._desktop_url and self._desktop_token:
            return ("desktop-api", self._desktop_url, self._desktop_token)
        try:
            stat = self.state_path.stat()
        except OSError as exc:
            raise AppControlClientError(
                f"未找到可用的 OdyTerm 控制服务状态: {self.state_path}"
            ) from exc
        return stat.st_mtime_ns, stat.st_size
