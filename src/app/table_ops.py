"""Table operations mixin for DeviceDesktopApp."""
from __future__ import annotations

import html
import time
from typing import Any

try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QBrush, QColor
    from PySide6.QtWidgets import QApplication, QMenu, QTableWidget, QTableWidgetItem, QWidget
except ModuleNotFoundError:
    QEvent = None
    Qt = None
    QBrush = None
    QColor = None
    QApplication = None
    QMenu = None
    QTableWidget = None
    QTableWidgetItem = None
    QWidget = None

from .._sample_data import STATUS_IDLE, STATUS_OCCUPIED, STATUS_OTHER, STATUS_PIPELINE
from ..app_state import RepositorySnapshot
from ..data import Device
from ..helpers import status_color

ALL_DOMAINS = "全部领域"
ALL_STATUS = "全部状态"


class TableOpsMixin:
    """Mixin providing device table rendering, filtering, selection, and context menus."""

    def refresh_snapshot(self) -> None:
        if self.loading_snapshot:
            return

        self.loading_snapshot = True
        self.set_status_message("正在刷新设备数据...")
        self.refresh_generation += 1
        generation = self.refresh_generation

        def load_snapshot() -> RepositorySnapshot:
            with self.repository_lock:
                devices = self.repository.fetch_devices()
                owned_device_ids = self.repository.fetch_owned_device_ids()
                current_user = self.repository.current_user()
            return RepositorySnapshot(
                current_user=current_user,
                devices=devices,
                owned_device_ids=owned_device_ids,
            )

        def apply_snapshot(result: object) -> None:
            snapshot = result
            if not isinstance(snapshot, RepositorySnapshot) or generation != self.refresh_generation:
                return
            self.loading_snapshot = False
            self.current_user = snapshot.current_user
            self.devices = snapshot.devices
            self.owned_device_ids = snapshot.owned_device_ids
            self.rebuild_device_indexes()
            self.refresh_domain_options()
            self.apply_filters()
            self.set_status_message(f"已加载 {len(self.devices)} 台设备")
            self.schedule_next_refresh()

        def handle_error(exc: Exception) -> None:
            self.loading_snapshot = False
            self.handle_background_error(exc)
            self.schedule_next_refresh()

        self.run_blocking(load_snapshot, on_success=apply_snapshot, on_error=handle_error)

    def schedule_next_refresh(self) -> None:
        refresh_seconds = getattr(self.repository, "refresh_interval_seconds", 0.0)
        if refresh_seconds and not self.closed:
            self.refresh_timer.start(int(refresh_seconds * 1000))

    def refresh_domain_options(self) -> None:
        current = self.domain_combo.currentText() or ALL_DOMAINS
        domains = sorted({device.domain for device in self.devices})
        self.domain_combo.blockSignals(True)
        self.domain_combo.clear()
        self.domain_combo.addItems([ALL_DOMAINS, *domains])
        self.domain_combo.setCurrentText(current if current in {ALL_DOMAINS, *domains} else ALL_DOMAINS)
        self.domain_combo.blockSignals(False)

    def apply_filters(self) -> None:
        if hasattr(self, "filter_timer"):
            self.filter_timer.stop()
        search_text = self.search_input.text().strip().lower()
        domain_filter = self.domain_combo.currentText().strip()
        status_filter = self.status_combo.currentText().strip()
        cpu_filter = self.cpu_input.text().strip().lower()
        my_occupancy_filter = self.my_occupancy_filter_enabled

        visible_devices: list[Device] = []
        status_counts = {
            STATUS_IDLE: 0,
            STATUS_OCCUPIED: 0,
            STATUS_PIPELINE: 0,
            STATUS_OTHER: 0,
        }
        for device in self.devices:
            if search_text and search_text not in self.device_search_text(device):
                continue
            if domain_filter != ALL_DOMAINS and device.domain != domain_filter:
                continue
            if status_filter != ALL_STATUS and device.status != status_filter:
                continue
            if cpu_filter and cpu_filter not in device.cpu.lower():
                continue
            if my_occupancy_filter and not self.is_my_occupied_device(device):
                continue
            visible_devices.append(device)
            if device.status in status_counts:
                status_counts[device.status] += 1

        self.visible_devices = visible_devices
        self.visible_status_counts = status_counts
        self.owned_visible_devices = [
            device for device in visible_devices if self.is_my_occupied_device(device)
        ]

        self.refresh_my_occupancy_filter_button()
        self.refresh_filter_summary()
        self.refresh_stats()
        self.refresh_device_table()
        self.refresh_owned_table()
        self.ensure_valid_selection()
        self.refresh_device_context()
        self.refresh_workspace_context()
        self.update_controls()

    def refresh_stats(self) -> None:
        total = len(self.visible_devices)
        idle = self.visible_status_counts.get(STATUS_IDLE, 0)
        occupied = self.visible_status_counts.get(STATUS_OCCUPIED, 0)
        pipeline = self.visible_status_counts.get(STATUS_PIPELINE, 0)
        other = self.visible_status_counts.get(STATUS_OTHER, 0)
        self.stats_label.setText(
            " ".join(
                [
                    self.stat_chip_html("设备", total, "#ededed"),
                    self.stat_chip_html("空闲", idle, "#3cc98e"),
                    self.stat_chip_html("占用", occupied, "#f5a623"),
                    self.stat_chip_html("流水线", pipeline, "#5b6ef5"),
                    self.stat_chip_html("其他", other, "#808080"),
                ]
            )
        )

    def stat_chip_html(self, label: str, value: int, color: str) -> str:
        return (
            f"<span style='color:{color};font-weight:800'>{html.escape(label)} {value}</span>"
        )

    def refresh_my_occupancy_filter_button(self) -> None:
        if not hasattr(self, "my_occupancy_filter_button"):
            return
        owned_count = self.my_occupancy_count()
        self.my_occupancy_filter_button.setText(f"我的 {owned_count}")
        self.my_occupancy_filter_button.setEnabled(self.owned_device_ids is not None or bool(self.current_user))
        self.my_occupancy_filter_button.setToolTip(
            "只显示我的占用 API 返回的设备"
            if self.owned_device_ids is not None
            else (
                f"只显示 {self.current_user} 占用的设备"
                if self.current_user
                else "当前用户尚未从 API 加载"
            )
        )

    def my_occupancy_count(self) -> int:
        if self.owned_device_ids is not None:
            return len(self.owned_device_ids)
        if not self.current_user:
            return 0
        return sum(1 for device in self.devices if device.owner == self.current_user)

    def is_my_occupied_device(self, device: Device) -> bool:
        if self.is_temporary_device(device):
            return False
        if self.owned_device_ids is not None:
            return device.id in self.owned_device_ids
        return bool(self.current_user and device.owner == self.current_user)

    def can_power_off_device(self, device: Device) -> bool:
        if self.is_temporary_device(device):
            return False
        return bool(device.supports_power_off and self.is_my_occupied_device(device))

    def cancel_table_render_jobs(self) -> None:
        self._table_render_generation += 1
        self._table_render_jobs.clear()
        if hasattr(self, "table_render_timer"):
            self.table_render_timer.stop()

    def enqueue_table_render_job(
        self,
        table: QTableWidget,
        devices: list[Device],
        keyword: str,
        kind: str,
        generation: int,
        start_row: int,
    ) -> None:
        if start_row >= len(devices):
            return
        self._table_render_jobs.append(
            {
                "table": table,
                "devices": devices,
                "keyword": keyword,
                "kind": kind,
                "generation": generation,
                "row": start_row,
            }
        )
        if not self.table_render_timer.isActive():
            self.table_render_timer.start(0)

    def process_table_render_jobs(self) -> None:
        frame_started = time.perf_counter()
        while self._table_render_jobs:
            job = self._table_render_jobs[0]
            if job.get("generation") != self._table_render_generation:
                self._table_render_jobs.pop(0)
                continue
            table = job["table"]
            if not isinstance(table, QTableWidget):
                self._table_render_jobs.pop(0)
                continue
            table.setUpdatesEnabled(False)
            try:
                self.render_table_job_rows(job, max_rows=180)
            finally:
                table.setUpdatesEnabled(True)
            if int(job["row"]) >= len(job["devices"]):
                self._table_render_jobs.pop(0)
            if (time.perf_counter() - frame_started) >= 0.008:
                break
        if self._table_render_jobs:
            self.table_render_timer.start(0)

    def render_table_job_rows(self, job: dict[str, object], max_rows: int) -> None:
        devices = job["devices"]
        if not isinstance(devices, list):
            return
        keyword = str(job["keyword"])
        kind = str(job["kind"])
        row = int(job["row"])
        end_row = min(len(devices), row + max_rows)
        for current_row in range(row, end_row):
            device = devices[current_row]
            if kind == "owned":
                self.render_owned_table_row(current_row, device, keyword)
            else:
                self.render_device_table_row(current_row, device, keyword)
        job["row"] = end_row

    def render_device_table_row(self, row: int, device: Device, keyword: str) -> None:
        hidden_keyword_match = self.device_matches_hidden_keyword(
            device,
            keyword,
            visible_values=(device.board_id, device.name, device.domain, device.cpu, device.status),
        )
        self._set_table_item(
            self.device_table,
            row,
            0,
            device.board_id,
            device.id,
            highlight=self.text_matches_keyword(device.board_id, keyword),
        )
        self._set_table_item(
            self.device_table,
            row,
            1,
            self.temporary_device_display_name(device),
            device.id,
            highlight=hidden_keyword_match or self.text_matches_keyword(device.name, keyword),
        )
        self._set_table_item(
            self.device_table,
            row,
            2,
            device.domain,
            device.id,
            highlight=self.text_matches_keyword(device.domain, keyword),
        )
        self._set_table_item(
            self.device_table,
            row,
            3,
            device.cpu,
            device.id,
            highlight=self.text_matches_keyword(device.cpu, keyword),
        )
        self._set_table_item(
            self.device_table,
            row,
            4,
            device.status,
            device.id,
            color=status_color(device.status),
            highlight=self.text_matches_keyword(device.status, keyword),
        )

    def render_owned_table_row(self, row: int, device: Device, keyword: str) -> None:
        hidden_keyword_match = self.device_matches_hidden_keyword(
            device,
            keyword,
            visible_values=(device.name, device.domain, device.status),
        )
        self._set_table_item(
            self.owned_table,
            row,
            0,
            device.name,
            device.id,
            highlight=hidden_keyword_match or self.text_matches_keyword(device.name, keyword),
        )
        self._set_table_item(
            self.owned_table,
            row,
            1,
            device.domain,
            device.id,
            highlight=self.text_matches_keyword(device.domain, keyword),
        )
        self._set_table_item(
            self.owned_table,
            row,
            2,
            device.status,
            device.id,
            color=status_color(device.status),
            highlight=self.text_matches_keyword(device.status, keyword),
        )

    def refresh_device_table(self) -> None:
        keyword = self.search_input.text().strip().lower()
        signature = (
            keyword,
            tuple(
                (device.id, device.board_id, device.name, device.domain, device.cpu, device.status)
                for device in self.visible_devices
            ),
            tuple(self.is_temporary_device(device) for device in self.visible_devices),
        )
        if signature == self._last_device_table_signature:
            return
        self._last_device_table_signature = signature
        self.cancel_table_render_jobs()
        generation = self._table_render_generation
        table = self.device_table
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        try:
            table.setRowCount(len(self.visible_devices))
            self.device_table_rows = {}
            for row, device in enumerate(self.visible_devices):
                self.device_table_rows[device.id] = row
            sync_rows = min(80, len(self.visible_devices))
            for row in range(sync_rows):
                self.render_device_table_row(row, self.visible_devices[row], keyword)
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)
        self.enqueue_table_render_job(
            table,
            self.visible_devices,
            keyword,
            "device",
            generation,
            sync_rows,
        )

    def refresh_owned_table(self) -> None:
        if not hasattr(self, "owned_table"):
            self.owned_visible_devices = []
            return
        keyword = self.search_input.text().strip().lower()
        self.owned_count_label.setText(str(len(self.owned_visible_devices)))
        signature = (
            keyword,
            tuple(
                (device.id, device.name, device.domain, device.status)
                for device in self.owned_visible_devices
            ),
        )
        if signature == self._last_owned_table_signature:
            return
        self._last_owned_table_signature = signature
        table = self.owned_table
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        try:
            table.setRowCount(len(self.owned_visible_devices))
            self.owned_table_rows = {}
            for row, device in enumerate(self.owned_visible_devices):
                self.owned_table_rows[device.id] = row
            sync_rows = min(60, len(self.owned_visible_devices))
            for row in range(sync_rows):
                self.render_owned_table_row(row, self.owned_visible_devices[row], keyword)
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)
        self.enqueue_table_render_job(
            table,
            self.owned_visible_devices,
            keyword,
            "owned",
            self._table_render_generation,
            sync_rows,
        )

    def _set_table_item(
        self,
        table: QTableWidget,
        row: int,
        column: int,
        text: str,
        device_id: str,
        color: str | None = None,
        highlight: bool = False,
    ) -> None:
        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            table.setItem(row, column, item)
        if item.text() != text:
            item.setText(text)
        if item.data(Qt.UserRole) != device_id:
            item.setData(Qt.UserRole, device_id)
        if item.toolTip() != text:
            item.setToolTip(text)
        item.setBackground(QBrush())
        item.setForeground(QBrush())
        font = item.font()
        if font.bold():
            font.setBold(False)
            item.setFont(font)
        if color:
            item.setForeground(QBrush(QColor(color)))
        if highlight:
            item.setBackground(QBrush(QColor("#1c1c1c")))
            item.setForeground(QBrush(QColor("#ededed")))
            font = item.font()
            font.setBold(True)
            item.setFont(font)

    def text_matches_keyword(self, value: str, keyword: str) -> bool:
        return bool(keyword and keyword in value.lower())

    def device_search_text(self, device: Device) -> str:
        return self.search_index.get(device.id) or self.temporary_device_search_text(device)

    def device_matches_hidden_keyword(
        self,
        device: Device,
        keyword: str,
        visible_values: tuple[str, ...],
    ) -> bool:
        if not keyword or keyword not in self.device_search_text(device):
            return False
        return not any(self.text_matches_keyword(value, keyword) for value in visible_values)

    def get_device_by_id(self, device_id: str) -> Device | None:
        return self.device_by_id.get(device_id)

    def ensure_valid_selection(self) -> None:
        visible_ids = {device.id for device in self.visible_devices}
        if not self.visible_devices:
            self.selected_device_id = ""
            return
        if self.selected_device_id not in visible_ids:
            self.selected_device_id = self.visible_devices[0].id
        self.select_device_in_table(self.selected_device_id)
        self.sync_auth_fields_from_selected()

    def select_device_in_table(self, device_id: str) -> None:
        self._select_device_row(self.device_table, device_id)
        if hasattr(self, "owned_table"):
            self._select_device_row(self.owned_table, device_id)

    def _select_device_row(self, table: QTableWidget, device_id: str) -> None:
        table.blockSignals(True)
        table.clearSelection()
        row_map = self.owned_table_rows if hasattr(self, "owned_table") and table is self.owned_table else self.device_table_rows
        mapped_row = row_map.get(device_id)
        if mapped_row is not None and 0 <= mapped_row < table.rowCount():
            item = table.item(mapped_row, 0)
            if item is None:
                table.selectRow(mapped_row)
                table.blockSignals(False)
                return
            if item.data(Qt.UserRole) == device_id:
                table.selectRow(mapped_row)
                table.scrollToItem(item)
                table.blockSignals(False)
                return
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == device_id:
                table.selectRow(row)
                table.scrollToItem(item)
                break
        table.blockSignals(False)

    def get_selected_device(self) -> Device | None:
        if not self.selected_device_id:
            return None
        return self.get_device_by_id(self.selected_device_id)

    def get_quick_action_device(self) -> Device | None:
        state = self.current_session_state()
        if state is not None:
            device = self.get_device_by_id(state.device_id)
            if device is not None:
                return device
        device_tab = self.current_device_tab_state()
        if device_tab is not None:
            device = self.get_device_by_id(device_tab.device_id)
            if device is not None:
                return device
        return self.get_selected_device()

    def _device_id_from_table(self, table: QTableWidget, id_column: int = 0) -> str:
        row = table.currentRow()
        if row < 0:
            return ""
        item = table.item(row, id_column)
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def _device_from_table(self, table: QTableWidget) -> Device | None:
        return self.get_device_by_id(self._device_id_from_table(table, 0))

    def copy_text_to_clipboard(self, text: str, message: str) -> None:
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.set_status_message(message)

    def device_row_copy_text(self, device: Device) -> str:
        return "\t".join([
            device.board_id,
            self.temporary_device_display_name(device),
            device.domain,
            device.cpu,
            device.status,
        ])

    def device_connection_copy_text(self, device: Device) -> str:
        serial_text = (
            f"{device.serial_ip}:{device.serial_port}"
            if self.can_view_serial_connection(device)
            else "占用后可见"
        )
        return (
            f"设备: {device.name}\n"
            f"Telnet: {device.telnet_ip}:{device.telnet_port}\n"
            f"Telnet 账号: {device.username}\n"
            f"Telnet 密码: {device.password}\n"
            f"串口: {serial_text}\n"
            f"SSH: {device.ssh_ip}:{device.ssh_port}\n"
            f"SSH 账号: {self.device_ssh_username(device)}\n"
            f"SSH 密码: {self.device_ssh_password(device)}"
        )

    def copy_device_field(self, device: Device, field: str) -> None:
        serial_endpoint = (
            f"{device.serial_ip}:{device.serial_port}"
            if self.can_view_serial_connection(device)
            else "占用后可见"
        )
        field_map = {
            "name": ("设备名", device.name),
            "ssh_ip": ("SSH IP", device.ssh_ip),
            "ssh_endpoint": ("SSH 地址", f"{device.ssh_ip}:{device.ssh_port}"),
            "telnet_ip": ("Telnet IP", device.telnet_ip),
            "telnet_endpoint": ("Telnet 地址", f"{device.telnet_ip}:{device.telnet_port}"),
            "serial_ip": ("串口 IP", device.serial_ip if self.can_view_serial_connection(device) else ""),
            "serial_endpoint": ("串口地址", serial_endpoint),
            "username": ("Telnet 账号", device.username),
            "password": ("Telnet 密码", device.password),
            "ssh_username": ("SSH 账号", self.device_ssh_username(device)),
            "ssh_password": ("SSH 密码", self.device_ssh_password(device)),
        }
        label, value = field_map[field]
        if field == "serial_ip" and not value:
            self.show_warning("请先占用设备后再查看串口 IP。")
            return
        self.copy_text_to_clipboard(value, f"已复制{label}: {value}")

    def device_ssh_username(self, device: Device) -> str:
        if self.is_temporary_device(device):
            return device.ssh_username
        return device.ssh_username or device.username

    def device_ssh_password(self, device: Device) -> str:
        if self.is_temporary_device(device):
            return device.ssh_password
        return device.ssh_password or device.password

    def device_serial_username(self, device: Device) -> str:
        if self.is_temporary_device(device):
            return device.serial_username
        return device.serial_username or device.username

    def device_serial_password(self, device: Device) -> str:
        if self.is_temporary_device(device):
            return device.serial_password
        return device.serial_password or device.password

    def can_view_serial_connection(self, device: Device) -> bool:
        if self.is_temporary_device(device):
            return bool(device.serial_ip.strip())
        return bool(device.serial_ip.strip() and self.is_my_occupied_device(device))

    def copy_selected_device_field(self, table: QTableWidget, field: str) -> None:
        device = self._device_from_table(table)
        if device is None:
            self.set_status_message("请先选择一台设备。")
            return
        self.copy_device_field(device, field)

    def copy_selected_table_row(self, table: QTableWidget) -> None:
        device = self._device_from_table(table)
        if device is None:
            self.set_status_message("请先选择一台设备。")
            return
        self.copy_text_to_clipboard(self.device_row_copy_text(device), f"已复制设备行: {device.name}")

    def _mark_recent_device(self, device_id: str) -> None:
        if not device_id:
            return
        if device_id in self.recent_device_ids:
            self.recent_device_ids.remove(device_id)
        self.recent_device_ids.insert(0, device_id)
        self.recent_device_ids = self.recent_device_ids[:8]

    def handle_device_table_selected(self) -> None:
        device_id = self._device_id_from_table(self.device_table, 0)
        if not device_id:
            return
        self.activate_device(device_id)

    def handle_owned_table_selected(self) -> None:
        device_id = self._device_id_from_table(self.owned_table, 0)
        if not device_id:
            return
        self.activate_device(device_id)

    def activate_device(self, device_id: str) -> None:
        self.selected_device_id = device_id
        self._mark_recent_device(device_id)
        self.select_device_in_table(device_id)
        self.sync_auth_fields_from_selected()
        self.refresh_device_context()
        self.refresh_workspace_context()
        self.update_controls()

    def locate_device_in_list(self, device_id: str) -> None:
        device = self.get_device_by_id(device_id)
        if device is None:
            self.set_status_message("未找到当前会话对应的设备。")
            return
        visible_ids = {item.id for item in self.visible_devices}
        if device_id not in visible_ids:
            self.clear_filters()
        self.activate_device(device_id)
        self.device_table.setFocus()
        self.set_status_message(f"已定位到设备: {device.name}")

    def refresh_filter_summary(self) -> None:
        active_filters: list[str] = []
        search_text = self.search_input.text().strip()
        domain_filter = self.domain_combo.currentText().strip()
        status_filter = self.status_combo.currentText().strip()
        cpu_filter = self.cpu_input.text().strip()

        if search_text:
            active_filters.append(self.filter_chip_html("关键词", search_text))
        if self.my_occupancy_filter_enabled:
            label = self.current_user or "我的占用"
            active_filters.append(self.filter_chip_html("占用", label))
        if domain_filter and domain_filter != ALL_DOMAINS:
            active_filters.append(self.filter_chip_html("领域", domain_filter))
        if status_filter and status_filter != ALL_STATUS:
            active_filters.append(self.filter_chip_html("状态", status_filter))
        if cpu_filter:
            active_filters.append(self.filter_chip_html("CPU", cpu_filter))

        has_filters = bool(active_filters)
        summary = " / ".join(active_filters) if has_filters else "当前显示全部设备"
        self.filter_summary_label.setText(summary)
        self.clear_filters_button.setEnabled(has_filters)

    def filter_chip_html(self, label: str, value: str) -> str:
        return (
            f"<span style='color:#c0c0c0;font-weight:600;background:#181818;"
            f"padding:2px 6px;border-radius:4px'>{html.escape(label)}: {html.escape(value)}</span>"
        )

    def show_device_table_context_menu(self, pos: Any) -> None:
        table = self.sender()
        if not isinstance(table, QTableWidget):
            table = self.device_table

        item = table.itemAt(pos)
        if item is None:
            return

        device_id = str(item.data(Qt.UserRole) or "")
        if not device_id:
            return

        self.select_device_in_table(device_id)
        self.activate_device(device_id)
        device = self.get_device_by_id(device_id)
        if device is None:
            return

        menu = QMenu(table)
        copy_ssh_ip_action = menu.addAction("复制 SSH IP")
        copy_telnet_ip_action = menu.addAction("复制 Telnet IP")
        copy_serial_ip_action = menu.addAction("复制串口 IP")
        copy_connection_action = menu.addAction("复制连接信息")
        menu.addSeparator()
        toggle_action = menu.addAction("占用 / 释放")
        power_off_action = menu.addAction("掉电")
        menu.addSeparator()
        open_device_action = menu.addAction("打开设备管理口")
        open_linux_action = menu.addAction("打开 Linux 后台")
        open_serial_action = menu.addAction("打开串口")
        serial_available = self.can_view_serial_connection(device)
        copy_serial_ip_action.setEnabled(serial_available)
        open_serial_action.setEnabled(serial_available)
        power_off_action.setEnabled(self.can_power_off_device(device))

        chosen = menu.exec(table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == copy_ssh_ip_action:
            self.copy_device_field(device, "ssh_ip")
            return
        if chosen == copy_telnet_ip_action:
            self.copy_device_field(device, "telnet_ip")
            return
        if chosen == copy_serial_ip_action:
            self.copy_device_field(device, "serial_ip")
            return
        if chosen == copy_connection_action:
            self.copy_text_to_clipboard(
                self.device_connection_copy_text(device),
                f"已复制连接信息: {device.name}",
            )
            return
        if chosen == toggle_action:
            self.toggle_occupancy(device)
            return
        if chosen == power_off_action:
            self.power_off_device(device)
            return
        if chosen == open_device_action:
            self.open_device_session(device)
            return
        if chosen == open_linux_action:
            self.open_linux_session(device)
            return
        if chosen == open_serial_action:
            self.open_serial_session(device)

    def show_device_quick_context_menu(self, device_id: str, widget: QWidget, pos: Any) -> None:
        device = self.get_device_by_id(device_id)
        if device is None:
            return
        menu = QMenu(widget)
        actions = self._add_device_quick_actions(menu)
        self.update_device_quick_actions_for_device(actions, device)
        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen is None:
            return
        self._handle_device_quick_action(chosen, actions, device)

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802
        if QEvent is not None:
            event_type = event.type()
            if event_type == QEvent.MouseButtonPress and hasattr(watched, "property"):
                if watched.property("sessionDragTabId"):
                    watched.setProperty("sessionDragStart", event.pos())
            elif event_type == QEvent.MouseMove and hasattr(watched, "property"):
                tab_id = str(watched.property("sessionDragTabId") or "")
                start_pos = watched.property("sessionDragStart")
                if tab_id and start_pos is not None and event.buttons() & Qt.LeftButton:
                    distance = (event.pos() - start_pos).manhattanLength()
                    if distance >= QApplication.startDragDistance():
                        self.start_session_tab_drag(watched, tab_id)
                        return True
            elif event_type in {QEvent.DragEnter, QEvent.DragMove}:
                if self.event_has_session_tab(event):
                    event.acceptProposedAction()
                    return True
            elif event_type == QEvent.Drop:
                if self.handle_session_tab_drop(watched, event):
                    return True
        return super().eventFilter(watched, event)

    def _add_device_quick_actions(self, menu: QMenu) -> dict[str, Any]:
        actions = {
            "locate": menu.addAction("定位到设备列表"),
        }
        menu.addSeparator()
        actions["clone_telnet"] = menu.addAction("复制 Telnet")
        actions["clone_ssh"] = menu.addAction("复制 SSH")
        actions["clone_serial"] = menu.addAction("复制串口")
        actions["copy_telnet_ip"] = menu.addAction("复制 Telnet IP")
        actions["copy_ssh_ip"] = menu.addAction("复制 SSH IP")
        actions["copy_serial_ip"] = menu.addAction("复制串口 IP")
        actions["copy_connection"] = menu.addAction("复制连接信息")
        menu.addSeparator()
        actions["power_off"] = menu.addAction("掉电")
        return actions

    def sync_auth_fields_from_selected(self) -> None:
        device = self.get_quick_action_device()
        if device is None:
            return
        self.device_telnet_ip_value.setText(device.telnet_ip)
        self.device_username_input.setText(device.username)
        self.device_password_input.setText(device.password)
        self.device_ssh_ip_value.setText(device.ssh_ip)
        self.device_serial_ip_value.setText(
            f"{device.serial_ip}:{device.serial_port}" if self.can_view_serial_connection(device) else ""
        )
        self.linux_username_input.setText(self.device_ssh_username(device))
        self.linux_password_input.setText(self.device_ssh_password(device))

    def refresh_device_context(self) -> None:
        device = self.get_selected_device()
        if device is None:
            self.device_summary_card.setText("请选择一台设备。")
            self.device_ssh_ip_value.clear()
            self.device_telnet_ip_value.clear()
            self.device_serial_ip_value.clear()
            return

        self.device_ssh_ip_value.setText(device.ssh_ip)
        self.device_telnet_ip_value.setText(device.telnet_ip)
        serial_visible = self.can_view_serial_connection(device)
        self.device_serial_ip_value.setText(
            f"{device.serial_ip}:{device.serial_port}" if serial_visible else ""
        )
        owner_text = device.owner or "未占用"
        owner_color = "#c0c0c0" if device.owner else "#808080"
        telnet_text = f"{device.telnet_ip}:{device.telnet_port}"
        ssh_text = f"{device.ssh_ip}:{device.ssh_port}"
        serial_text = f"{device.serial_ip}:{device.serial_port}" if serial_visible else "占用后可见"
        serial_color = "#c0c0c0" if serial_visible else "#707070"
        if self.is_temporary_device(device):
            serial_text = "-"
            serial_color = "#707070"
        self.device_summary_card.setText(
            (
                f"<div style='font-size:15px;font-weight:600;color:#ededed'>"
                f"{html.escape(self.temporary_device_display_name(device))}</div>"
                f"<div style='margin-top:4px;color:#808080;font-size:11px'>"
                f"<span style='color:#c0c0c0;font-weight:600'>{html.escape(device.id)}</span>"
                f" &nbsp;·&nbsp; {html.escape(device.domain)}"
                f"</div>"
                f"{self.temporary_device_detail_badge(device)}"
                f"<div style='margin-top:10px;color:#c0c0c0;line-height:1.8'>"
                f"<span style='color:#808080'>状态</span>&nbsp;&nbsp;"
                f"<span style='color:{status_color(device.status)};font-weight:700'>{html.escape(device.status)}</span><br>"
                f"<span style='color:#808080'>占用</span>&nbsp;&nbsp;"
                f"<span style='color:{owner_color};font-weight:600'>{html.escape(owner_text)}</span><br>"
                f"<span style='color:#808080'>Telnet</span>&nbsp;&nbsp;"
                f"<span style='font-weight:600'>{html.escape(telnet_text)}</span><br>"
                f"<span style='color:#808080'>串口</span>&nbsp;&nbsp;"
                f"<span style='color:{serial_color};font-weight:600'>{html.escape(serial_text)}</span><br>"
                f"<span style='color:#808080'>SSH</span>&nbsp;&nbsp;"
                f"<span style='font-weight:600'>{html.escape(ssh_text)}</span>"
                f"</div>"
            )
        )
