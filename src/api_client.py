from __future__ import annotations

import json
import os
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any, Protocol
from urllib import error, parse, request

from ._sample_data import CURRENT_USER


class ApiClientError(Exception):
    """Base exception raised by API client implementations."""


class ApiConflictError(ApiClientError):
    """Raised when a remote occupancy operation cannot be completed."""


class ApiNotFoundError(ApiClientError):
    """Raised when an optional API endpoint is not provided by the service."""


@dataclass(frozen=True, slots=True)
class ApiAuthStatus:
    configured: bool
    authenticated: bool
    username: str = ""
    cid: str = ""


class DeviceApiClient(Protocol):
    def auth_status(self) -> ApiAuthStatus:
        ...

    def login(self, username: str, password: str, cid: str) -> ApiAuthStatus:
        ...

    def logout(self) -> None:
        ...

    def get_current_user(self) -> str:
        ...

    def list_devices(self) -> list[dict[str, Any]]:
        ...

    def list_my_occupancy(self) -> object:
        ...

    def toggle_device(self, device_id: str, user: str) -> dict[str, Any]:
        ...

    def claim_device(self, device_id: str, user: str) -> dict[str, Any]:
        ...

    def release_device(self, device_id: str, user: str) -> dict[str, Any]:
        ...

    def power_off_device(self, device_id: str, user: str) -> dict[str, Any]:
        ...

    def current_revision(self) -> int:
        ...

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None:
        ...


class HttpDeviceApiClient:
    """HTTP-backed client used by the TUI to talk to a device web service."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
        *,
        login_path: str = "/api/login",
        logout_path: str = "",
        username_field: str = "username",
        password_field: str = "password",
        cid_field: str = "cid",
        login_format: str = "json",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._current_revision = 0
        self._login_path = self._normalize_optional_path(login_path)
        self._logout_path = self._normalize_optional_path(logout_path)
        self._username_field = self._normalize_field_name(username_field, "username")
        self._password_field = self._normalize_field_name(password_field, "password")
        self._cid_field = self._normalize_field_name(cid_field, "cid")
        self._login_format = str(login_format or "json").strip().lower()
        if self._login_format not in {"json", "form"}:
            raise ValueError("API login format must be 'json' or 'form'.")
        self._cookie_jar = CookieJar()
        self._opener = request.build_opener(request.HTTPCookieProcessor(self._cookie_jar))
        self._authenticated = False
        self._auth_username = ""
        self._auth_cid = ""

    @staticmethod
    def _normalize_optional_path(value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        if not normalized.startswith("/") or "://" in normalized or ".." in normalized:
            raise ValueError("API authentication paths must be absolute paths on the configured service.")
        return normalized

    @staticmethod
    def _normalize_field_name(value: str, default: str) -> str:
        normalized = str(value or default).strip()
        if not normalized or len(normalized) > 128:
            raise ValueError("API authentication field names must be non-empty and at most 128 characters.")
        return normalized

    def auth_status(self) -> ApiAuthStatus:
        has_live_cookie = any(not cookie.is_expired() for cookie in self._cookie_jar)
        if self._authenticated and not has_live_cookie:
            self._clear_auth_state()
        return ApiAuthStatus(
            configured=bool(self._login_path),
            authenticated=self._authenticated,
            username=self._auth_username,
            cid=self._auth_cid,
        )

    def login(self, username: str, password: str, cid: str) -> ApiAuthStatus:
        normalized_username = username.strip()
        normalized_cid = cid.strip()
        if not self._login_path:
            raise ApiClientError("Internal website login is not configured.")
        if not normalized_username or not password or not normalized_cid:
            raise ApiClientError("Username, password, and CID are required.")
        self._clear_auth_state()
        payload = {
            self._username_field: normalized_username,
            self._password_field: password,
            self._cid_field: normalized_cid,
        }
        headers = {"Accept": "application/json, text/html;q=0.9"}
        if self._login_format == "form":
            body = parse.urlencode(payload).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(
            f"{self._base_url}{self._login_path}",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with self._opener.open(req, timeout=self._timeout_seconds) as login_response:
                raw = login_response.read().decode("utf-8")
        except error.HTTPError as exc:
            if exc.code in {401, 403}:
                self._clear_auth_state()
            raise self._translate_http_error(exc) from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise ApiClientError(f"Unable to reach device service: {reason}") from exc
        try:
            parsed_response = json.loads(raw) if raw else {}
            response = parsed_response if isinstance(parsed_response, dict) else {}
        except json.JSONDecodeError:
            response = {}
        if response.get("success") is False or response.get("authenticated") is False:
            self._clear_auth_state()
            raise ApiClientError("Internal website rejected the login.")
        if not any(True for _cookie in self._cookie_jar):
            self._clear_auth_state()
            raise ApiClientError("Internal website login succeeded but did not return a session cookie.")
        returned_user = (
            response.get("current_user")
            or response.get("username")
            or response.get("user")
            or normalized_username
        )
        if isinstance(returned_user, dict):
            returned_user = returned_user.get("username") or returned_user.get("name") or normalized_username
        self._authenticated = True
        self._auth_username = str(returned_user).strip() or normalized_username
        self._auth_cid = normalized_cid
        return self.auth_status()

    def logout(self) -> None:
        try:
            if self._logout_path and self._authenticated:
                try:
                    self._request_json("POST", self._logout_path)
                except ApiClientError:
                    pass
        finally:
            self._clear_auth_state()

    def _clear_auth_state(self) -> None:
        self._cookie_jar.clear()
        self._authenticated = False
        self._auth_username = ""
        self._auth_cid = ""

    def get_current_user(self) -> str:
        response = self._request_json("GET", "/api/me")
        return str(response.get("current_user", CURRENT_USER))

    def list_devices(self) -> list[dict[str, Any]]:
        response = self._request_json("GET", "/api/devices")
        self._current_revision = int(response.get("revision", self._current_revision or 0))
        devices = response.get("devices", [])
        if not isinstance(devices, list):
            raise ApiClientError("Invalid /api/devices response")
        return devices

    def list_my_occupancy(self) -> object:
        return self._request_json("GET", "/api/my-occupancy")

    def toggle_device(self, device_id: str, user: str) -> dict[str, Any]:
        quoted_id = parse.quote(device_id, safe="")
        return self._request_json(
            "POST",
            f"/api/devices/{quoted_id}/toggle",
            payload={"user": user},
        )

    def claim_device(self, device_id: str, user: str) -> dict[str, Any]:
        quoted_id = parse.quote(device_id, safe="")
        return self._request_json(
            "POST",
            f"/api/devices/{quoted_id}/claim",
            payload={"user": user},
        )

    def release_device(self, device_id: str, user: str) -> dict[str, Any]:
        quoted_id = parse.quote(device_id, safe="")
        return self._request_json(
            "POST",
            f"/api/devices/{quoted_id}/release",
            payload={"user": user},
        )

    def power_off_device(self, device_id: str, user: str) -> dict[str, Any]:
        quoted_id = parse.quote(device_id, safe="")
        return self._request_json(
            "POST",
            f"/api/devices/{quoted_id}/power-off",
            payload={"user": user},
        )

    def current_revision(self) -> int:
        return self._current_revision

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None:
        query = parse.urlencode({"since": since_revision, "timeout": timeout_seconds})
        response = self._request_json(
            "GET",
            f"/api/events?{query}",
            timeout_seconds=timeout_seconds + 5.0,
        )
        revision = int(response.get("revision", self._current_revision or since_revision))
        self._current_revision = revision
        if bool(response.get("changed")):
            return revision
        return None

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with self._opener.open(req, timeout=timeout_seconds or self._timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            if exc.code in {401, 403}:
                self._clear_auth_state()
            raise self._translate_http_error(exc) from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise ApiClientError(f"Unable to reach device service: {reason}") from exc
        except json.JSONDecodeError as exc:
            raise ApiClientError("Device service returned invalid JSON") from exc

    def _translate_http_error(self, exc: error.HTTPError) -> ApiClientError:
        message = f"Device service error: HTTP {exc.code}"
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}

        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("error")
            if detail:
                message = str(detail)

        if exc.code == 409:
            return ApiConflictError(message)
        if exc.code == 404:
            return ApiNotFoundError(message)
        return ApiClientError(message)


def create_http_client_from_env() -> HttpDeviceApiClient:
    base_url = os.getenv("DEVICE_TUI_API_BASE_URL", "http://127.0.0.1:8765")
    timeout_seconds = float(os.getenv("DEVICE_TUI_API_TIMEOUT_SECONDS", "5"))
    return HttpDeviceApiClient(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        login_path=os.getenv("DEVICE_TUI_API_LOGIN_PATH", "/api/login"),
        logout_path=os.getenv("DEVICE_TUI_API_LOGOUT_PATH", ""),
        username_field=os.getenv("DEVICE_TUI_API_LOGIN_USERNAME_FIELD", "username"),
        password_field=os.getenv("DEVICE_TUI_API_LOGIN_PASSWORD_FIELD", "password"),
        cid_field=os.getenv("DEVICE_TUI_API_LOGIN_CID_FIELD", "cid"),
        login_format=os.getenv("DEVICE_TUI_API_LOGIN_FORMAT", "json"),
    )
