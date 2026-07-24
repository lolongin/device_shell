"""Client for the Device TUI local application-control API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .app_control_server import default_state_path


class AppControlClientError(RuntimeError):
    def __init__(self, message: str, *, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.response = response or {}


class AppControlClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        source: str = "device-tui-mcp",
        timeout_seconds: float = 12.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.source = source
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_state_file(cls, path: Path | None = None) -> "AppControlClient":
        state_path = path or default_state_path()
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            base_url = str(payload["base_url"])
            token = str(payload["token"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AppControlClientError(
                f"未找到可用的 Device TUI 控制服务状态: {state_path}"
            ) from exc
        return cls(base_url, token)

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/v1/health", authenticated=False)

    def system_status(self) -> dict[str, Any]:
        return self._request("GET", "/v1/status")

    def device_list(self) -> dict[str, Any]:
        return self._request("GET", "/v1/devices")

    def device_get(self, device_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/devices/{quote(device_id, safe='')}")

    def device_select(self, device_id: str) -> dict[str, Any]:
        return self._request("POST", "/v1/devices/select", {"device_id": device_id})

    def session_open(self, device_id: str) -> dict[str, Any]:
        return self._request("POST", "/v1/sessions/open", {"device_id": device_id})

    def session_list(self, device_id: str | None = None) -> dict[str, Any]:
        query = urlencode({"device_id": device_id}) if device_id else ""
        suffix = f"?{query}" if query else ""
        return self._request("GET", f"/v1/sessions{suffix}")

    def session_manage(
        self,
        action: str,
        *,
        device_id: str | None = None,
        session_id: str | None = None,
        protocol: str = "auto",
        timeout_seconds: int = 15,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/sessions/manage",
            {
                "action": action,
                "device_id": device_id,
                "session_id": session_id,
                "protocol": protocol,
                "timeout_seconds": timeout_seconds,
            },
            request_timeout_seconds=timeout_seconds + 5,
        )

    def terminal_send_command(
        self,
        device_id: str,
        command: str,
        *,
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/terminal/send",
            {
                "device_id": device_id,
                "command": command,
                "approval_token": approval_token,
                "idempotency_key": idempotency_key,
            },
        )

    def terminal_read(
        self,
        device_id: str,
        *,
        max_chars: int = 4096,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/terminal/read",
            {"device_id": device_id, "max_chars": max_chars},
        )

    def terminal_execute(
        self,
        command: str,
        *,
        session_id: str | None = None,
        device_id: str | None = None,
        timeout_seconds: int = 30,
        max_output_chars: int = 16_384,
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/terminal/execute",
            {
                "command": command,
                "session_id": session_id,
                "device_id": device_id,
                "timeout_seconds": timeout_seconds,
                "max_output_chars": max_output_chars,
                "approval_token": approval_token,
                "idempotency_key": idempotency_key,
            },
            request_timeout_seconds=timeout_seconds + 5,
        )

    def package_upgrade_start(
        self,
        device_id: str,
        *,
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/package-upgrade/start",
            {
                "device_id": device_id,
                "approval_token": approval_token,
                "idempotency_key": idempotency_key,
            },
        )

    def approval_get(self, approval_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/approvals/{approval_id}")

    def operation_get(self, operation_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/operations/{operation_id}")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
        request_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {
            "Accept": "application/json",
            "X-Device-TUI-Client": self.source,
        }
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            timeout = request_timeout_seconds or self.timeout_seconds
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                response = json.loads(exc.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                response = {}
            message = str(response.get("message") or f"控制服务返回 HTTP {exc.code}")
            raise AppControlClientError(message, response=response) from exc
        except (OSError, URLError) as exc:
            raise AppControlClientError(
                "无法连接 Device TUI，请确认桌面应用正在运行。"
            ) from exc
