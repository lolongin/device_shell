"""Tests for api_client module."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from src.api_client import (
    ApiClientError,
    ApiConflictError,
    ApiNotFoundError,
    HttpDeviceApiClient,
    create_http_client_from_env,
)


class _MockHandler(BaseHTTPRequestHandler):
    """Mock HTTP handler that simulates the device web service."""

    last_login_payload: dict[str, Any] = {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/me":
            self._json({"current_user": "test.user"})
        elif path == "/api/devices":
            self._json({
                "revision": 1,
                "devices": [
                    {"device_id": "D1", "display_name": "Device 1"},
                ],
            })
        elif path == "/api/my-occupancy":
            self._json({"revision": 1, "occupancy": []})
        elif path == "/api/events":
            params = parse_qs(parsed.query)
            since = int(params.get("since", ["0"])[0])
            if since > 0:
                self._json({"revision": 2, "changed": True})
            else:
                self._json({"revision": 1, "changed": False})
        elif path == "/api/server-error":
            self._send_error(500)
        elif path == "/api/cookie-check":
            self._json({"cookie": self.headers.get("Cookie", "")})
        elif path == "/api/unauthorized":
            self._send_error(401)
        else:
            self._send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        if path == "/api/login":
            type(self).last_login_payload = json.loads(raw_body.decode("utf-8"))
            self._json(
                {"authenticated": True, "current_user": "cookie.user"},
                headers={"Set-Cookie": "device_session=test-cookie; Path=/; HttpOnly"},
            )
        elif path == "/api/form-login":
            values = parse_qs(raw_body.decode("utf-8"))
            type(self).last_login_payload = {key: items[0] for key, items in values.items()}
            body = b"<html><body>ok</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Set-Cookie", "form_session=form-cookie; Path=/; HttpOnly")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/login-no-cookie":
            self._json({"authenticated": True})
        elif "/toggle" in path:
            self._json({"message": "Toggled D1"})
        elif "/claim" in path:
            self._json({"message": "Claimed D1"})
        elif "/release" in path:
            self._json({"message": "Released D1"})
        elif "/power-off" in path:
            self._json({"message": "Powered off D1"})
        elif path == "/api/conflict":
            self._send_error(409)
        else:
            self._send_error(404)

    def _json(self, data: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code: int) -> None:
        body = json.dumps({"message": f"HTTP {code}"}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # suppress server logs


@pytest.fixture(scope="module")
def mock_server():
    """Run a mock API server on a random port for the duration of the module."""
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


class TestErrorClasses:
    """Custom exception hierarchy."""

    def test_api_client_error_is_exception(self) -> None:
        exc = ApiClientError("msg")
        assert isinstance(exc, Exception)
        assert str(exc) == "msg"

    def test_api_conflict_error_is_api_client_error(self) -> None:
        exc = ApiConflictError("conflict")
        assert isinstance(exc, ApiClientError)
        assert str(exc) == "conflict"

    def test_api_not_found_error_is_api_client_error(self) -> None:
        exc = ApiNotFoundError("not found")
        assert isinstance(exc, ApiClientError)
        assert str(exc) == "not found"


class TestHttpDeviceApiClient:
    """Integration-style tests against the mock HTTP server."""

    # -- read operations ---------------------------------------------------

    def test_login_keeps_cookie_in_memory_for_followup_requests(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")

        status = client.login("operator", "not-persisted", "CID-7")
        cookie_check = client._request_json("GET", "/api/cookie-check")

        assert status.authenticated is True
        assert status.username == "cookie.user"
        assert status.cid == "CID-7"
        assert _MockHandler.last_login_payload == {
            "username": "operator",
            "password": "not-persisted",
            "cid": "CID-7",
        }
        assert "device_session=test-cookie" in cookie_check["cookie"]

    def test_login_requires_session_cookie(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(
            f"http://127.0.0.1:{port}",
            login_path="/api/login-no-cookie",
        )
        with pytest.raises(ApiClientError, match="session cookie"):
            client.login("operator", "secret", "CID-7")

    def test_failed_account_switch_clears_previous_cookie(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        client.login("operator", "secret", "CID-7")
        client._login_path = "/api/login-no-cookie"

        with pytest.raises(ApiClientError, match="session cookie"):
            client.login("second", "secret", "CID-8")

        assert client.auth_status().authenticated is False
        assert client._request_json("GET", "/api/cookie-check")["cookie"] == ""

    def test_form_login_accepts_html_response_with_cookie(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(
            f"http://127.0.0.1:{port}",
            login_path="/api/form-login",
            login_format="form",
        )

        status = client.login("form-user", "form-secret", "CID-FORM")

        assert status.authenticated is True
        assert _MockHandler.last_login_payload == {
            "username": "form-user",
            "password": "form-secret",
            "cid": "CID-FORM",
        }

    def test_logout_clears_in_memory_cookie(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        client.login("operator", "secret", "CID-7")

        client.logout()

        assert client.auth_status().authenticated is False
        assert client._request_json("GET", "/api/cookie-check")["cookie"] == ""

    def test_unauthorized_response_invalidates_cookie_session(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        client.login("operator", "secret", "CID-7")

        with pytest.raises(ApiClientError):
            client._request_json("GET", "/api/unauthorized")

        assert client.auth_status().authenticated is False
        assert client._request_json("GET", "/api/cookie-check")["cookie"] == ""

    def test_get_current_user(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        assert client.get_current_user() == "test.user"

    def test_list_devices(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        devices = client.list_devices()
        assert isinstance(devices, list)
        assert len(devices) == 1
        assert devices[0]["device_id"] == "D1"

    def test_list_devices_updates_revision(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        client.list_devices()
        assert client.current_revision() == 1

    def test_list_my_occupancy(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        result = client.list_my_occupancy()
        assert isinstance(result, dict)
        assert "occupancy" in result

    def test_current_revision_initial(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        assert client.current_revision() == 0

    # -- write operations --------------------------------------------------

    def test_toggle_device(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        result = client.toggle_device("D1", "test.user")
        assert isinstance(result, dict)
        assert "Toggled" in result.get("message", "")

    def test_claim_device(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        result = client.claim_device("D1", "test.user")
        assert "Claimed" in result.get("message", "")

    def test_release_device(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        result = client.release_device("D1", "test.user")
        assert "Released" in result.get("message", "")

    def test_power_off_device(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        result = client.power_off_device("D1", "test.user")
        assert "Powered off" in result.get("message", "")

    # -- long-poll ---------------------------------------------------------

    def test_wait_for_update_no_change(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        result = client.wait_for_update(since_revision=0, timeout_seconds=0.5)
        assert result is None

    def test_wait_for_update_with_change(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        result = client.wait_for_update(since_revision=1, timeout_seconds=0.5)
        assert isinstance(result, int)
        assert result == 2

    def test_wait_for_update_updates_revision(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        client.wait_for_update(since_revision=1, timeout_seconds=0.5)
        assert client.current_revision() == 2

    # -- error handling ----------------------------------------------------

    def test_http_409_raises_api_conflict_error(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        with pytest.raises(ApiConflictError):
            client._request_json("POST", "/api/conflict")

    def test_http_404_raises_api_not_found_error(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        with pytest.raises(ApiNotFoundError):
            client._request_json("GET", "/api/nonexistent")

    def test_http_500_raises_api_client_error(self, mock_server) -> None:
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        with pytest.raises(ApiClientError):
            client._request_json("GET", "/api/server-error")


class TestCreateHttpClientFromEnv:
    """Factory function with environment-variable defaults."""

    def test_default_values(self, monkeypatch) -> None:
        monkeypatch.delenv("DEVICE_TUI_API_BASE_URL", raising=False)
        monkeypatch.delenv("DEVICE_TUI_API_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("DEVICE_TUI_API_LOGIN_PATH", raising=False)
        client = create_http_client_from_env()
        assert client._base_url == "http://127.0.0.1:8765"
        assert client._timeout_seconds == 5.0
        assert client._login_path == "/api/login"

    def test_login_contract_can_be_configured_from_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("DEVICE_TUI_API_LOGIN_PATH", "/session/create")
        monkeypatch.setenv("DEVICE_TUI_API_LOGOUT_PATH", "/session/delete")
        monkeypatch.setenv("DEVICE_TUI_API_LOGIN_USERNAME_FIELD", "account")
        monkeypatch.setenv("DEVICE_TUI_API_LOGIN_PASSWORD_FIELD", "passwd")
        monkeypatch.setenv("DEVICE_TUI_API_LOGIN_CID_FIELD", "customerId")
        monkeypatch.setenv("DEVICE_TUI_API_LOGIN_FORMAT", "form")

        client = create_http_client_from_env()

        assert client._login_path == "/session/create"
        assert client._logout_path == "/session/delete"
        assert client._username_field == "account"
        assert client._password_field == "passwd"
        assert client._cid_field == "customerId"
        assert client._login_format == "form"

    def test_env_base_url(self, monkeypatch) -> None:
        monkeypatch.setenv("DEVICE_TUI_API_BASE_URL", "http://example.com:9999")
        monkeypatch.delenv("DEVICE_TUI_API_TIMEOUT_SECONDS", raising=False)
        client = create_http_client_from_env()
        assert client._base_url == "http://example.com:9999"

    def test_env_timeout(self, monkeypatch) -> None:
        monkeypatch.delenv("DEVICE_TUI_API_BASE_URL", raising=False)
        monkeypatch.setenv("DEVICE_TUI_API_TIMEOUT_SECONDS", "10.0")
        client = create_http_client_from_env()
        assert client._timeout_seconds == 10.0
