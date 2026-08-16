"""Persistent client for the Device TUI loopback control API."""

from __future__ import annotations

from http.client import HTTPConnection, HTTPException
import json
from pathlib import Path
import threading
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from .runtime import default_state_path


class AppControlClientError(RuntimeError):
    def __init__(self, message: str, *, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.response = response or {}


class _HttpConnectionPool:
    def __init__(self, host: str, port: int, *, max_size: int = 4) -> None:
        self.host = host
        self.port = port
        self.max_size = max(1, max_size)
        self._available: list[HTTPConnection] = []
        self._lock = threading.Lock()

    def acquire(self, timeout: float) -> HTTPConnection:
        with self._lock:
            connection = self._available.pop() if self._available else None
        if connection is None:
            return HTTPConnection(self.host, self.port, timeout=timeout)
        connection.timeout = timeout
        return connection

    def release(self, connection: HTTPConnection) -> None:
        with self._lock:
            if len(self._available) < self.max_size:
                self._available.append(connection)
                return
        connection.close()

    @staticmethod
    def discard(connection: HTTPConnection) -> None:
        connection.close()

    def close(self) -> None:
        with self._lock:
            connections = self._available
            self._available = []
        for connection in connections:
            connection.close()


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
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise AppControlClientError(
                f"Device TUI 控制服务地址无效: {self.base_url}"
            )
        self._base_path = parsed.path.rstrip("/")
        self._pool = _HttpConnectionPool(parsed.hostname, parsed.port or 80)

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

    def close(self) -> None:
        self._pool.close()

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
        return self._request("GET", f"/v1/sessions?{query}" if query else "/v1/sessions")

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

    def terminal_run(
        self,
        commands: list[str],
        *,
        session_id: str | None = None,
        device_id: str | None = None,
        ensure_session: bool = True,
        protocol: str = "auto",
        command_timeout_seconds: int = 30,
        total_timeout_seconds: int | None = None,
        max_output_chars_per_step: int = 16_384,
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "commands": commands,
            "session_id": session_id,
            "device_id": device_id,
            "ensure_session": ensure_session,
            "protocol": protocol,
            "command_timeout_seconds": command_timeout_seconds,
            "max_output_chars_per_step": max_output_chars_per_step,
            "approval_token": approval_token,
            "idempotency_key": idempotency_key,
        }
        if total_timeout_seconds is not None:
            payload["total_timeout_seconds"] = total_timeout_seconds
        request_timeout = min(total_timeout_seconds or 60, 60) + 25
        return self._request(
            "POST",
            "/v1/terminal/run",
            payload,
            request_timeout_seconds=request_timeout,
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

    def terminal_read(self, device_id: str, *, max_chars: int = 4096) -> dict[str, Any]:
        return self._request(
            "POST", "/v1/terminal/read", {"device_id": device_id, "max_chars": max_chars}
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

    def terminal_execute_batch(
        self,
        commands: list[str],
        *,
        session_id: str | None = None,
        device_id: str | None = None,
        command_timeout_seconds: int = 30,
        total_timeout_seconds: int | None = None,
        max_output_chars_per_step: int = 16_384,
        mode: str = "auto",
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "commands": commands,
            "session_id": session_id,
            "device_id": device_id,
            "command_timeout_seconds": command_timeout_seconds,
            "max_output_chars_per_step": max_output_chars_per_step,
            "mode": mode,
            "approval_token": approval_token,
            "idempotency_key": idempotency_key,
        }
        if total_timeout_seconds is not None:
            payload["total_timeout_seconds"] = total_timeout_seconds
        return self._request(
            "POST",
            "/v1/terminal/execute-batch",
            payload,
            request_timeout_seconds=min(total_timeout_seconds or 60, 60) + 5,
        )

    def terminal_interact(
        self,
        steps: list[dict[str, Any]],
        *,
        session_id: str | None = None,
        device_id: str | None = None,
        total_timeout_seconds: int = 60,
        mode: str = "auto",
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/terminal/interact",
            {
                "steps": steps,
                "session_id": session_id,
                "device_id": device_id,
                "total_timeout_seconds": total_timeout_seconds,
                "mode": mode,
                "approval_token": approval_token,
                "idempotency_key": idempotency_key,
            },
            request_timeout_seconds=min(total_timeout_seconds, 60) + 5,
        )

    def execution_get(self, execution_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/executions/{quote(execution_id, safe='')}")

    def execution_cancel(self, execution_id: str) -> dict[str, Any]:
        return self._request("POST", "/v1/executions/cancel", {"execution_id": execution_id})

    def file_transfer_list(
        self, *, path: str = "", recursive: bool = True, limit: int = 200
    ) -> dict[str, Any]:
        query = urlencode(
            {"path": path, "recursive": "true" if recursive else "false", "limit": limit}
        )
        return self._request("GET", f"/v1/file-transfer/files?{query}")

    def file_transfer_start(
        self,
        device_id: str,
        source_path: str,
        destination_path: str,
        *,
        overwrite: bool = False,
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/file-transfer/start",
            {
                "device_id": device_id,
                "source_path": source_path,
                "destination_path": destination_path,
                "overwrite": overwrite,
                "approval_token": approval_token,
                "idempotency_key": idempotency_key,
            },
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

    def ai_create_session(self, device_id: str) -> dict[str, Any]:
        return self._request("POST", "/v1/ai/create-session", {"device_id": device_id})

    def ai_execute_command(self, *, session_id: str = "", device_id: str = "", command: str = "", timeout_seconds: int = 30, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v1/ai/execute-command", {
            "session_id": session_id, "device_id": device_id, "command": command,
            "timeout_seconds": timeout_seconds, "idempotency_key": idempotency_key,
        })

    def ai_execute_batch(self, *, commands: list[str], session_id: str = "", device_id: str = "", command_timeout_seconds: int = 30, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v1/ai/execute-batch", {
            "commands": commands, "session_id": session_id, "device_id": device_id,
            "command_timeout_seconds": command_timeout_seconds, "idempotency_key": idempotency_key,
        })

    def ai_execute_script(self, *, script: str, session_id: str = "", device_id: str = "", shell: str = "", timeout_seconds: int = 30, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v1/ai/execute-script", {
            "script": script, "session_id": session_id, "device_id": device_id,
            "shell": shell, "timeout_seconds": timeout_seconds, "idempotency_key": idempotency_key,
        })

    def ai_upload_file(self, device_id: str, source_path: str, destination_path: str, *, overwrite: bool = False, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v1/ai/upload-file", {
            "device_id": device_id, "source_path": source_path, "destination_path": destination_path,
            "overwrite": overwrite, "idempotency_key": idempotency_key,
        })

    def ai_download_file(self, device_id: str, source_path: str, destination_path: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v1/ai/download-file", {
            "device_id": device_id, "source_path": source_path, "destination_path": destination_path,
            "idempotency_key": idempotency_key,
        })

    def ai_get_result(self, *, result_id: str, include_raw: bool = False) -> dict[str, Any]:
        return self._request("POST", "/v1/ai/get-result", {"result_id": result_id, "include_raw": include_raw})

    def ai_list_skills(self) -> dict[str, Any]:
        return self._request("POST", "/v1/ai/list-skills", {})

    def ai_run_skill(self, *, skill_name: str, params: dict[str, Any], session_id: str = "", device_id: str = "", timeout_seconds: int = 60, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v1/ai/run-skill", {
            "skill_name": skill_name, "params": params, "session_id": session_id,
            "device_id": device_id, "timeout_seconds": timeout_seconds, "idempotency_key": idempotency_key,
        })

    def approval_get(self, approval_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/approvals/{quote(approval_id, safe='')}")

    def operation_get(self, operation_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/operations/{quote(operation_id, safe='')}")

    def operation_wait(
        self,
        operation_id: str,
        *,
        timeout_seconds: int = 60,
        since_revision: int = 0,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/operations/wait",
            {
                "operation_id": operation_id,
                "timeout_seconds": timeout_seconds,
                "since_revision": since_revision,
            },
            request_timeout_seconds=timeout_seconds + 5,
        )

    def operation_cancel(self, operation_id: str) -> dict[str, Any]:
        return self._request("POST", "/v1/operations/cancel", {"operation_id": operation_id})

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        authenticated: bool = True,
        request_timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        body: bytes | None = None
        headers = {"Accept": "application/json", "X-Device-TUI-Client": self.source}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        timeout = request_timeout_seconds or self.timeout_seconds
        request_path = f"{self._base_path}{path}" or "/"
        attempts = 2 if method == "GET" else 1
        last_error: Exception | None = None
        for _attempt in range(attempts):
            connection = self._pool.acquire(timeout)
            try:
                connection.request(method, request_path, body=body, headers=headers)
                response = connection.getresponse()
                raw = response.read()
                response_payload = self._decode_response(raw)
                if response.will_close:
                    self._pool.discard(connection)
                else:
                    self._pool.release(connection)
                if response.status >= 400:
                    message = str(
                        response_payload.get("message")
                        or f"控制服务返回 HTTP {response.status}"
                    )
                    raise AppControlClientError(message, response=response_payload)
                return response_payload
            except AppControlClientError:
                raise
            except (OSError, HTTPException, TimeoutError) as exc:
                last_error = exc
                self._pool.discard(connection)
        raise AppControlClientError("无法连接 Device TUI，请确认桌面应用正在运行。") from last_error

    @staticmethod
    def _decode_response(raw: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AppControlClientError("控制服务返回了无效 JSON。") from exc
        if not isinstance(payload, dict):
            raise AppControlClientError("控制服务返回值不是 JSON 对象。")
        return payload
