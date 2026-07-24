"""Local-only HTTP server exposing the running desktop application."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .app_control import AppControlService, utc_timestamp


MAX_REQUEST_BYTES = 65_536


def default_runtime_directory() -> Path:
    root = os.getenv("LOCALAPPDATA")
    if root:
        return Path(root) / "DeviceTUI"
    return Path.home() / ".device_tui"


def default_state_path() -> Path:
    override = os.getenv("DEVICE_TUI_CONTROL_STATE", "").strip()
    if override:
        return Path(override).expanduser()
    return default_runtime_directory() / "app-control.json"


def default_audit_path() -> Path:
    override = os.getenv("DEVICE_TUI_CONTROL_AUDIT", "").strip()
    if override:
        return Path(override).expanduser()
    return default_runtime_directory() / "app-control-audit.jsonl"


class _ControlHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        service: AppControlService,
        token: str,
    ) -> None:
        super().__init__(server_address, _ControlRequestHandler)
        self.service = service
        self.token = token


class _ControlRequestHandler(BaseHTTPRequestHandler):
    server: _ControlHttpServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/v1/health":
            self._invoke("health", {})
            return
        if not self._authorized():
            return
        if path == "/v1/status":
            self._invoke("system_status", {})
            return
        if path == "/v1/devices":
            self._invoke("device_list", {})
            return
        if path.startswith("/v1/devices/"):
            self._invoke(
                "device_get",
                {"device_id": unquote(path.removeprefix("/v1/devices/"))},
            )
            return
        if path == "/v1/sessions":
            query = parse_qs(parsed.query)
            self._invoke(
                "session_list",
                {"device_id": str(query.get("device_id", [""])[0])},
            )
            return
        if path.startswith("/v1/approvals/"):
            self._invoke("approval_get", {"approval_id": path.rsplit("/", 1)[-1]})
            return
        if path.startswith("/v1/operations/"):
            self._invoke("operation_get", {"operation_id": path.rsplit("/", 1)[-1]})
            return
        self._send_error(404, "not_found", "接口不存在。")

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        routes = {
            "/v1/devices/select": "device_select",
            "/v1/sessions/open": "session_open",
            "/v1/sessions/manage": "session_manage",
            "/v1/terminal/send": "terminal_send_command",
            "/v1/terminal/read": "terminal_read",
            "/v1/terminal/execute": "terminal_execute",
            "/v1/package-upgrade/start": "package_upgrade_start",
        }
        tool = routes.get(urlparse(self.path).path)
        if tool is None:
            self._send_error(404, "not_found", "接口不存在。")
            return
        params = self._read_json()
        if params is None:
            return
        self._invoke(tool, params)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.token}"
        if secrets.compare_digest(self.headers.get("Authorization", ""), expected):
            return True
        self._send_error(401, "unauthorized", "控制服务认证失败。")
        return False

    def _read_json(self) -> dict[str, Any] | None:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            self._send_error(400, "invalid_request", "Content-Length 无效。")
            return None
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._send_error(413, "request_too_large", "请求体过大。")
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error(400, "invalid_json", "请求体不是有效 JSON。")
            return None
        if not isinstance(payload, dict):
            self._send_error(400, "invalid_request", "请求体必须是 JSON 对象。")
            return None
        return payload

    def _invoke(self, tool: str, params: dict[str, Any]) -> None:
        status, body = self.server.service.invoke(
            tool,
            params,
            source=self.headers.get("X-Device-TUI-Client", "http-client")[:100],
            request_id=self.headers.get("X-Request-ID") or None,
        )
        self._send_json(status, body)

    def _send_error(self, status: int, code: str, message: str) -> None:
        self._send_json(
            status,
            {
                "ok": False,
                "request_id": "",
                "message": message,
                "data": {},
                "approval": None,
                "error": {"code": code, "message": message, "details": {}},
            },
        )

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


class AppControlHttpServer:
    def __init__(
        self,
        service: AppControlService,
        *,
        state_path: Path | None = None,
        token: str | None = None,
    ) -> None:
        self.service = service
        self.state_path = state_path or default_state_path()
        self.token = token or secrets.token_urlsafe(32)
        self._server: _ControlHttpServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            return ""
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def is_running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    def start(self) -> str:
        if self.is_running:
            return self.base_url
        self._server = _ControlHttpServer(("127.0.0.1", 0), self.service, self.token)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="device-tui-app-control",
        )
        self._thread.start()
        self._write_state_file()
        return self.base_url

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._remove_state_file()

    def _write_state_file(self) -> None:
        payload = {
            "pid": os.getpid(),
            "base_url": self.base_url,
            "token": self.token,
            "started_at": utc_timestamp(),
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.state_path)

    def _remove_state_file(self) -> None:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("pid") == os.getpid() and payload.get("token") == self.token:
            try:
                self.state_path.unlink()
            except OSError:
                pass
