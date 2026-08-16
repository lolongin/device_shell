"""Complete Device TUI repository backed by the normalized company web API."""

from __future__ import annotations

from typing import Callable

from device_tui.plugin_api.repository import (
    Device,
    InternalAuthStatus,
    RepositoryConflictError,
    RepositoryError,
    STATUS_IDLE,
    STATUS_OCCUPIED,
    STATUS_OTHER,
    STATUS_PIPELINE,
)

from .web_api import CompanyDevice, CompanyWebApi, CompanyWebApiConflict, CompanyWebApiError


STATUS_BY_CODE = {
    "idle": STATUS_IDLE,
    "occupied": STATUS_OCCUPIED,
    "pipeline": STATUS_PIPELINE,
    "other": STATUS_OTHER,
}


class CompanyDeviceRepository:
    def __init__(
        self,
        api: CompanyWebApi,
        *,
        refresh_interval_seconds: float = 30.0,
    ) -> None:
        self._api = api
        self.refresh_interval_seconds = refresh_interval_seconds
        self.live_update_timeout_seconds = 25.0

    def internal_auth_status(self) -> InternalAuthStatus:
        status = self._api.auth_status()
        return InternalAuthStatus(
            available=True,
            configured=status.configured,
            authenticated=status.authenticated,
            username=status.username,
            cid=status.cid,
        )

    def login_internal(self, username: str, password: str, cid: str) -> InternalAuthStatus:
        try:
            self._api.login(username, password, cid)
        except CompanyWebApiError as exc:
            raise RepositoryError(str(exc)) from exc
        return self.internal_auth_status()

    def logout_internal(self) -> InternalAuthStatus:
        try:
            self._api.logout()
        except CompanyWebApiError as exc:
            raise RepositoryError(str(exc)) from exc
        return self.internal_auth_status()

    def current_user(self) -> str:
        return self._api.auth_status().username

    def fetch_devices(self) -> list[Device]:
        try:
            return [self._device(item) for item in self._api.list_devices()]
        except CompanyWebApiError as exc:
            raise RepositoryError(str(exc)) from exc

    def fetch_owned_device_ids(self) -> set[str] | None:
        try:
            return set(self._api.list_owned_device_ids())
        except CompanyWebApiError as exc:
            raise RepositoryError(str(exc)) from exc

    def toggle_device(self, device_id: str, user: str) -> str:
        return self._action(self._api.toggle_device, device_id, user)

    def claim_device(self, device_id: str, user: str) -> str:
        return self._action(self._api.claim_device, device_id, user)

    def release_device(self, device_id: str, user: str) -> str:
        return self._action(self._api.release_device, device_id, user)

    def power_off_device(self, device_id: str, user: str) -> str:
        return self._action(self._api.power_off_device, device_id, user)

    def current_revision(self) -> int:
        return self._api.current_revision()

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None:
        try:
            return self._api.wait_for_update(since_revision, timeout_seconds)
        except CompanyWebApiError as exc:
            raise RepositoryError(str(exc)) from exc

    @staticmethod
    def _action(
        action: Callable[[str, str], str],
        device_id: str,
        user: str,
    ) -> str:
        try:
            return str(action(device_id, user))
        except CompanyWebApiConflict as exc:
            raise RepositoryConflictError(str(exc)) from exc
        except CompanyWebApiError as exc:
            raise RepositoryError(str(exc)) from exc

    @staticmethod
    def _device(item: CompanyDevice) -> Device:
        return Device(
            id=item.id,
            board_id=item.board_id,
            name=item.name,
            domain=item.domain,
            device_type=item.device_type,
            cpu=item.cpu,
            status=STATUS_BY_CODE.get(item.status_code.lower(), STATUS_OTHER),
            owner=item.owner,
            ssh_ip=item.ssh_host,
            telnet_ip=item.telnet_host,
            username=item.telnet_username,
            password=item.telnet_password,
            vendor=item.vendor,
            model=item.model,
            site=item.site,
            rack=item.rack,
            version=item.version,
            notes=item.notes,
            ssh_port=item.ssh_port,
            telnet_port=item.telnet_port,
            ssh_username=item.ssh_username,
            ssh_password=item.ssh_password,
            serial_ip=item.serial_host,
            serial_port=item.serial_port,
            serial_username=item.serial_username,
            serial_password=item.serial_password,
            supports_power_off=item.supports_power_off,
            extra=dict(item.extra),
        )
