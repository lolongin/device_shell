from __future__ import annotations

import json
import os
from typing import Any, Protocol
from urllib import error, parse, request

try:
    from .data import CURRENT_USER
except ImportError:
    from data import CURRENT_USER


class ApiClientError(Exception):
    """Base exception raised by API client implementations."""


class ApiConflictError(ApiClientError):
    """Raised when a remote occupancy operation cannot be completed."""


class ApiNotFoundError(ApiClientError):
    """Raised when an optional API endpoint is not provided by the service."""


class DeviceApiClient(Protocol):
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
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._current_revision = 0

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
            with request.urlopen(req, timeout=timeout_seconds or self._timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
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
    )
