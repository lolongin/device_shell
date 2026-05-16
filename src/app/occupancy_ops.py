"""Occupancy management mixin for DeviceDesktopApp."""
from __future__ import annotations

from typing import Any

try:
    from PySide6.QtWidgets import QMessageBox
except ModuleNotFoundError:
    QMessageBox = None

from ..data import Device
from ..repository import RepositoryConflictError


class OccupancyOpsMixin:
    """Mixin providing occupancy toggle and power-off operations."""

    def toggle_occupancy(self, device: Device | None = None) -> None:
        device = device if isinstance(device, Device) else None
        device = device or self.get_quick_action_device()
        if device is not None and self.is_temporary_device(device):
            self.show_warning("临时设备不会同步到资产库，不能执行占用/释放。")
            return
        if device is None:
            self.show_warning("请先选择设备。")
            return

        self.set_status_message(f"正在更新设备占用状态: {device.name}")

        def toggle() -> str:
            with self.repository_lock:
                return self.repository.toggle_device(device.id, self.current_user)

        def done(result: object) -> None:
            self.set_status_message(str(result))
            self.refresh_snapshot()

        self.run_blocking(toggle, on_success=done, on_error=self.handle_toggle_error)

    def power_off_selected_device(self) -> None:
        device = self.get_quick_action_device()
        if device is None:
            self.show_warning("请先选择设备。")
            return
        self.power_off_device(device)

    def power_off_device(self, device: Device) -> None:
        if self.is_temporary_device(device):
            self.show_warning("临时设备不能执行掉电。")
            return
        if not device.supports_power_off:
            self.show_warning("当前设备不支持掉电。")
            return
        if not self.is_my_occupied_device(device):
            self.show_warning("请先占用设备后再执行掉电。")
            return

        confirmed = QMessageBox.question(
            self,
            "设备掉电",
            f"确认对 {device.name} 执行掉电？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed != QMessageBox.Yes:
            return

        self.set_status_message(f"正在执行设备掉电: {device.name}")

        def power_off() -> str:
            with self.repository_lock:
                return self.repository.power_off_device(device.id, self.current_user)

        def done(result: object) -> None:
            self.set_status_message(str(result))
            self.refresh_snapshot()

        self.run_blocking(power_off, on_success=done, on_error=self.handle_toggle_error)

    def handle_toggle_error(self, exc: Exception) -> None:
        if isinstance(exc, RepositoryConflictError):
            self.show_warning(str(exc))
            self.set_status_message(str(exc))
            self.refresh_snapshot()
            return
        self.handle_background_error(exc)
