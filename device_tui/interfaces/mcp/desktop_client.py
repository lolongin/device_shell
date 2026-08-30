"""MCP client for the Qt-free Electron desktop API."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from typing import Any
from urllib.parse import quote, urlsplit


class DesktopApiClientError(RuntimeError):
    def __init__(self, message: str, *, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.response = response or {}


class DesktopApiClient:
    """Drop-in client for the public MCP tool names served by Electron Backend."""

    def __init__(self, base_url: str, token: str, *, source: str = "odyterm-mcp") -> None:
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme != "http" or not parsed.hostname:
            raise DesktopApiClientError(f"Invalid desktop API URL: {base_url}")
        self.host = parsed.hostname
        self.port = parsed.port or 80
        self.prefix = parsed.path.rstrip("/")
        self.token = token
        self.source = source

    def close(self) -> None:
        return

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/health", authenticated=False)

    def system_status(self) -> dict[str, Any]:
        return self._tool("system_status")

    def app_capabilities(self) -> dict[str, Any]:
        return self._tool("app.capabilities")

    def device_list(self) -> dict[str, Any]:
        return self._tool("device_list")

    def device_get(self, device_id: str) -> dict[str, Any]:
        return self._tool("device_get", device_id=device_id)

    def device_select(self, device_id: str) -> dict[str, Any]:
        return self._tool("device_select", device_id=device_id)

    def device_open(self, device_id: str, protocol: str = "auto") -> dict[str, Any]:
        return self._tool("device.open", device_id=device_id, protocol=protocol)

    def connection_open(self, profile_id: str, protocol: str = "ssh", title: str = "") -> dict[str, Any]:
        return self._tool("connection.open", profile_id=profile_id, protocol=protocol, title=title)

    def session_open(self, device_id: str) -> dict[str, Any]:
        return self._tool("session_open", device_id=device_id)

    def session_list(self, device_id: str | None = None) -> dict[str, Any]:
        return self._tool("session_list", device_id=device_id or "")

    def session_manage(self, action: str, *, device_id: str | None = None, session_id: str | None = None, protocol: str = "auto", timeout_seconds: int = 15) -> dict[str, Any]:
        return self._tool("session_manage", action=action, device_id=device_id or "", session_id=session_id or "", protocol=protocol, timeout_seconds=timeout_seconds)

    def terminal_run(self, commands: list[str], *, session_id: str | None = None, device_id: str | None = None, ensure_session: bool = True, protocol: str = "auto", command_timeout_seconds: int = 30, total_timeout_seconds: int | None = None, max_output_chars_per_step: int = 16_384, approval_token: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("terminal_run", commands=commands, session_id=session_id or "", device_id=device_id or "", ensure_session=ensure_session, protocol=protocol, command_timeout_seconds=command_timeout_seconds, total_timeout_seconds=total_timeout_seconds, max_output_chars_per_step=max_output_chars_per_step, approval_token=approval_token, idempotency_key=idempotency_key)

    def terminal_execute(self, command: str, *, session_id: str | None = None, device_id: str | None = None, timeout_seconds: int = 30, max_output_chars: int = 16_384, approval_token: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("terminal_execute", command=command, session_id=session_id or "", device_id=device_id or "", timeout_seconds=timeout_seconds, max_output_chars=max_output_chars, approval_token=approval_token, idempotency_key=idempotency_key)

    def terminal_execute_batch(self, commands: list[str], *, session_id: str | None = None, device_id: str | None = None, command_timeout_seconds: int = 30, total_timeout_seconds: int | None = None, max_output_chars_per_step: int = 16_384, mode: str = "auto", approval_token: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("terminal_execute_batch", commands=commands, session_id=session_id or "", device_id=device_id or "", command_timeout_seconds=command_timeout_seconds, total_timeout_seconds=total_timeout_seconds, max_output_chars_per_step=max_output_chars_per_step, mode=mode, approval_token=approval_token, idempotency_key=idempotency_key)

    def terminal_interact(self, steps: list[dict[str, Any]], *, session_id: str | None = None, device_id: str | None = None, total_timeout_seconds: int = 60, mode: str = "auto", approval_token: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("terminal_interact", steps=steps, session_id=session_id or "", device_id=device_id or "", total_timeout_seconds=total_timeout_seconds, mode=mode, approval_token=approval_token, idempotency_key=idempotency_key)

    def terminal_send_command(self, device_id: str, command: str, *, approval_token: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("terminal_send_command", device_id=device_id, command=command, approval_token=approval_token, idempotency_key=idempotency_key)

    def terminal_read(self, device_id: str, *, max_chars: int = 4096) -> dict[str, Any]:
        return self._tool("terminal_read", device_id=device_id, max_chars=max_chars)

    def execution_get(self, execution_id: str) -> dict[str, Any]:
        return self._tool("execution_get", execution_id=execution_id)

    def execution_cancel(self, execution_id: str) -> dict[str, Any]:
        return self._tool("execution_cancel", execution_id=execution_id)

    def file_transfer_list(self, *, path: str = "", recursive: bool = True, limit: int = 200) -> dict[str, Any]:
        return self._tool("file_transfer_list", path=path, recursive=recursive, limit=limit)

    def file_transfer_start(self, device_id: str, source_path: str, destination_path: str, *, overwrite: bool = False, approval_token: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("file_transfer_start", device_id=device_id, source_path=source_path, destination_path=destination_path, overwrite=overwrite, approval_token=approval_token, idempotency_key=idempotency_key)

    def package_upgrade_start(self, device_id: str, *, approval_token: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("package_upgrade_start", device_id=device_id, approval_token=approval_token, idempotency_key=idempotency_key)

    def ai_create_session(self, device_id: str) -> dict[str, Any]:
        return self._tool("ai_create_session", device_id=device_id)

    def ai_execute_command(self, *, session_id: str = "", device_id: str = "", command: str = "", timeout_seconds: int = 30, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("ai_execute_command", session_id=session_id, device_id=device_id, command=command, timeout_seconds=timeout_seconds, idempotency_key=idempotency_key)

    def ai_execute_batch(self, *, commands: list[str], session_id: str = "", device_id: str = "", command_timeout_seconds: int = 30, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("ai_execute_batch", commands=commands, session_id=session_id, device_id=device_id, command_timeout_seconds=command_timeout_seconds, idempotency_key=idempotency_key)

    def ai_execute_script(self, *, script: str, session_id: str = "", device_id: str = "", shell: str = "", timeout_seconds: int = 30, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("ai_execute_script", script=script, session_id=session_id, device_id=device_id, shell=shell, timeout_seconds=timeout_seconds, idempotency_key=idempotency_key)

    def ai_upload_file(self, device_id: str, source_path: str, destination_path: str, *, overwrite: bool = False, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("ai_upload_file", device_id=device_id, source_path=source_path, destination_path=destination_path, overwrite=overwrite, idempotency_key=idempotency_key)

    def ai_download_file(self, device_id: str, source_path: str, destination_path: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("ai_download_file", device_id=device_id, source_path=source_path, destination_path=destination_path, idempotency_key=idempotency_key)

    def ai_get_result(self, *, result_id: str, include_raw: bool = False) -> dict[str, Any]:
        return self._tool("ai_get_result", result_id=result_id, include_raw=include_raw)

    def ai_run_skill(self, *, skill_name: str, params: dict[str, Any], session_id: str = "", device_id: str = "", timeout_seconds: int = 60, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._tool("ai_run_skill", skill_name=skill_name, params=params, session_id=session_id, device_id=device_id, timeout_seconds=timeout_seconds, idempotency_key=idempotency_key)

    def ai_list_skills(self) -> dict[str, Any]:
        return self._tool("ai_list_skills")

    def approval_get(self, approval_id: str) -> dict[str, Any]:
        return self._tool("approval_get", approval_id=approval_id)

    def operation_get(self, operation_id: str) -> dict[str, Any]:
        return self._tool("operation_get", operation_id=operation_id)

    def operation_wait(self, operation_id: str, *, timeout_seconds: int = 60, since_revision: int = 0) -> dict[str, Any]:
        return self._tool("operation_wait", operation_id=operation_id, timeout_seconds=timeout_seconds, since_revision=since_revision, timeout_seconds_override=timeout_seconds + 5)

    def operation_cancel(self, operation_id: str) -> dict[str, Any]:
        return self._tool("operation_cancel", operation_id=operation_id)

    def _tool(self, tool: str, **payload: Any) -> dict[str, Any]:
        timeout = payload.pop("timeout_seconds_override", None)
        return self._request("POST", f"/api/v1/mcp/{quote(tool, safe='')}", payload, request_timeout_seconds=timeout)

    def mcp_tool(self, tool: str, **payload: Any) -> dict[str, Any]:
        """Call a namespaced Backend MCP capability without domain logic."""
        return self._tool(tool, **payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, *, authenticated: bool = True, request_timeout_seconds: int | None = None) -> dict[str, Any]:
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if method != "GET" else None
        connection = HTTPConnection(self.host, self.port, timeout=request_timeout_seconds or 30)
        try:
            connection.request(method, f"{self.prefix}{path}", body=body, headers={"Authorization": f"Bearer {self.token}" if authenticated else "", "Content-Type": "application/json", "X-OdyTerm-Client": self.source})
            response = connection.getresponse()
            raw = response.read().decode("utf-8", "replace")
        finally:
            connection.close()
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise DesktopApiClientError("Desktop API returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise DesktopApiClientError("Desktop API returned an invalid response")
        if response.status >= 400:
            raise DesktopApiClientError(str(data.get("message") or data.get("detail") or data.get("error") or "Desktop API request failed"), response=data)
        return data
