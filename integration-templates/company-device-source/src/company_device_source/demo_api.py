"""In-memory company website used before the proprietary adapter is connected."""

from __future__ import annotations

from dataclasses import replace
from threading import Condition, RLock
from time import monotonic

from .web_api import (
    CompanyAuthSession,
    CompanyDevice,
    CompanyWebApiConflict,
    CompanyWebApiError,
)


class DemoCompanyWebApi:
    """A fully working login/inventory/occupancy implementation for migration QA."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._changed = Condition(self._lock)
        self._session = CompanyAuthSession(configured=True, authenticated=False)
        self._revision = 1
        self._devices = [
            CompanyDevice(
                id="INTERNAL-DEMO-01",
                board_id="1",
                name="内部演示设备 01",
                domain="网络设备",
                device_type="router",
                cpu="arm64",
                status_code="idle",
                vendor="Demo Vendor",
                model="VRP-Demo",
                site="Lab-A",
                rack="A01",
                version="V1R1",
                telnet_host="192.0.2.31",
                telnet_username="demo",
                serial_host="192.0.2.131",
                serial_port=2001,
                serial_username="demo",
                supports_power_off=True,
                extra={"board_type": "主控板", "slot_id": "0"},
            ),
            CompanyDevice(
                id="INTERNAL-DEMO-02",
                board_id="2",
                name="内部演示服务器 02",
                domain="Linux",
                device_type="server",
                cpu="x86_64",
                status_code="pipeline",
                vendor="Demo Vendor",
                model="Linux-Demo",
                site="Lab-B",
                rack="B02",
                version="2026.1",
                ssh_host="192.0.2.42",
                ssh_username="demo",
                extra={"board_type": "服务器", "slot_id": "B02"},
            ),
        ]

    def auth_status(self) -> CompanyAuthSession:
        with self._lock:
            return self._session

    def login(self, username: str, password: str, cid: str) -> CompanyAuthSession:
        username = username.strip()
        cid = cid.strip()
        if not username or not password or not cid:
            raise CompanyWebApiError("账号、密码和 CID 不能为空。")
        with self._lock:
            self._session = CompanyAuthSession(True, True, username=username, cid=cid)
            return self._session

    def logout(self) -> None:
        with self._lock:
            self._session = CompanyAuthSession(configured=True, authenticated=False)

    def list_devices(self) -> list[CompanyDevice]:
        with self._lock:
            self._require_login()
            return [replace(item, extra=dict(item.extra)) for item in self._devices]

    def list_owned_device_ids(self) -> set[str]:
        with self._lock:
            self._require_login()
            username = self._session.username
            return {item.id for item in self._devices if item.owner == username}

    def toggle_device(self, device_id: str, user: str) -> str:
        with self._lock:
            device = self._device(device_id)
            if device.owner == user:
                return self.release_device(device_id, user)
            return self.claim_device(device_id, user)

    def claim_device(self, device_id: str, user: str) -> str:
        with self._lock:
            self._require_login()
            index, device = self._device_with_index(device_id)
            if device.owner and device.owner != user:
                raise CompanyWebApiConflict(f"设备已被 {device.owner} 占用。")
            self._devices[index] = replace(device, owner=user, status_code="occupied")
            self._touch()
            return f"已占用 {device.name}"

    def release_device(self, device_id: str, user: str) -> str:
        with self._lock:
            self._require_login()
            index, device = self._device_with_index(device_id)
            if device.owner and device.owner != user:
                raise CompanyWebApiConflict("只能释放自己占用的设备。")
            self._devices[index] = replace(device, owner=None, status_code="idle")
            self._touch()
            return f"已释放 {device.name}"

    def power_off_device(self, device_id: str, user: str) -> str:
        del user
        with self._lock:
            self._require_login()
            _index, device = self._device_with_index(device_id)
            if not device.supports_power_off:
                raise CompanyWebApiConflict("该设备不支持远程下电。")
            self._touch()
            return f"已提交 {device.name} 下电任务"

    def current_revision(self) -> int:
        with self._lock:
            return self._revision

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None:
        deadline = monotonic() + max(0.0, timeout_seconds)
        with self._changed:
            while self._revision <= since_revision:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None
                self._changed.wait(remaining)
            return self._revision

    def _require_login(self) -> None:
        if not self._session.authenticated:
            raise CompanyWebApiError("请先登录公司设备平台。")

    def _device(self, device_id: str) -> CompanyDevice:
        return self._device_with_index(device_id)[1]

    def _device_with_index(self, device_id: str) -> tuple[int, CompanyDevice]:
        for index, device in enumerate(self._devices):
            if device.id == device_id:
                return index, device
        raise CompanyWebApiError(f"设备不存在：{device_id}")

    def _touch(self) -> None:
        self._revision += 1
        self._changed.notify_all()
