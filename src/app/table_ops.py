"""Table operations mixin for DeviceDesktopApp."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

try:
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QBrush, QColor
    from PySide6.QtWidgets import QApplication, QMenu, QTableWidget, QTableWidgetItem, QWidget
except ModuleNotFoundError:
    QEvent = None
    QPoint = None
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
from ..helpers import html_chip, html_device_summary, html_status_text, status_color
from ..styles import STATUS_COLORS

ALL_DOMAINS = "全部领域"
ALL_STATUS = "全部状态"


HTML_TEXT = "#f8fafc"
HTML_MUTED = "#a7b4c7"
HTML_SOFT = "#718096"
HTML_PANEL = "#08101d"
HTML_LINE = "#243244"
HTML_SELECTED = "#24324a"


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
            if hasattr(self, "restore_remembered_terminal_sessions_once"):
                self.restore_remembered_terminal_sessions_once()
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
        domains = sorted({device.domain for device in self.navigation_devices()})
        self.domain_combo.blockSignals(True)
        self.domain_combo.clear()
        self.domain_combo.addItems([ALL_DOMAINS, *domains])
        self.domain_combo.setCurrentText(current if current in {ALL_DOMAINS, *domains} else ALL_DOMAINS)
        self.domain_combo.blockSignals(False)

    def navigation_devices(self) -> list[Device]:
        devices = list(self.devices)
        if hasattr(self, "simulated_device"):
            simulated = self.simulated_device()
            if simulated.id not in {device.id for device in devices}:
                devices.append(simulated)
        return devices

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
        for device in self.navigation_devices():
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
        self.refresh_device_navigation_web()
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
                    self.stat_chip_html("设备", total, HTML_TEXT),
                    self.stat_chip_html("空闲", idle, STATUS_COLORS[STATUS_IDLE]),
                    self.stat_chip_html("占用", occupied, STATUS_COLORS[STATUS_OCCUPIED]),
                    self.stat_chip_html("流水线", pipeline, STATUS_COLORS[STATUS_PIPELINE]),
                    self.stat_chip_html("其他", other, STATUS_COLORS[STATUS_OTHER]),
                ]
            )
        )

    def stat_chip_html(self, label: str, value: int, color: str) -> str:
        return html_status_text(f"{label} {value}", color, class_name="stat-chip-text")

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
        if self.is_simulated_device(device):
            return False
        if self.is_temporary_device(device):
            return False
        if self.owned_device_ids is not None:
            return device.id in self.owned_device_ids
        return bool(self.current_user and device.owner == self.current_user)

    def can_power_off_device(self, device: Device) -> bool:
        if self.is_simulated_device(device):
            return False
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
        rows = job["devices"]
        if not isinstance(rows, list):
            return
        keyword = str(job["keyword"])
        kind = str(job["kind"])
        row = int(job["row"])
        end_row = min(len(rows), row + max_rows)
        for current_row in range(row, end_row):
            row_data = rows[current_row]
            if kind == "owned":
                device = row_data
                if not isinstance(device, Device):
                    continue
                self.render_owned_table_row(current_row, device, keyword)
            else:
                self.render_device_table_display_row(current_row, row_data, keyword)
        job["row"] = end_row

    def build_device_table_display_rows(self, devices: list[Device]) -> list[dict[str, object]]:
        name_counts: dict[str, int] = {}
        for device in devices:
            name_counts[device.name] = name_counts.get(device.name, 0) + 1

        rows: list[dict[str, object]] = []
        grouped_names: set[str] = set()
        for device in devices:
            if name_counts.get(device.name, 0) <= 1:
                rows.append({"kind": "device", "device": device, "grouped": False})
                continue
            if device.name not in grouped_names:
                grouped_names.add(device.name)
                rows.append(
                    {
                        "kind": "group",
                        "name": device.name,
                        "subdomain": self.device_table_subdomain_text(device),
                        "count": name_counts[device.name],
                    }
                )
            rows.append({"kind": "device", "device": device, "grouped": True})
        return rows

    def render_device_table_display_row(self, row: int, row_data: object, keyword: str) -> None:
        if not isinstance(row_data, dict):
            return
        if row_data.get("kind") == "group":
            self.render_device_group_row(
                row,
                str(row_data.get("name") or ""),
                str(row_data.get("subdomain") or ""),
                int(row_data.get("count") or 0),
                keyword,
            )
            return
        device = row_data.get("device")
        if isinstance(device, Device):
            self.render_device_table_row(row, device, keyword, grouped=bool(row_data.get("grouped")))

    def device_navigation_payload(self) -> dict[str, object]:
        display_rows = self.build_device_table_display_rows(self.visible_devices)
        rows: list[dict[str, object]] = []
        for row_data in display_rows:
            if row_data.get("kind") == "group":
                rows.append(
                    {
                        "kind": "group",
                        "name": str(row_data.get("name") or ""),
                        "subdomain": str(row_data.get("subdomain") or ""),
                        "count": int(row_data.get("count") or 0),
                    }
                )
                continue
            device = row_data.get("device")
            if not isinstance(device, Device):
                continue
            grouped = bool(row_data.get("grouped"))
            rows.append(
                {
                    "kind": "device",
                    "id": device.id,
                    "boardId": self.device_table_board_id_text(device, grouped=grouped),
                    "name": device.device_type if grouped else self.device_table_device_name_text(device),
                    "deviceName": self.temporary_device_display_name(device),
                    "domain": device.domain,
                    "subdomain": self.device_table_subdomain_text(device),
                    "boardType": self.device_table_board_type_text(device),
                    "cpu": device.cpu,
                    "slot": device.slot_id,
                    "statusKind": self.device_status_kind(device),
                    "statusText": self.device_table_status_text(device),
                    "statusTooltip": self.device_occupancy_tooltip(device),
                    "selected": device.id == self.selected_device_id,
                    "telnet": f"{device.telnet_ip}:{device.telnet_port}" if device.telnet_ip else "",
                    "ssh": f"{device.ssh_ip}:{device.ssh_port}" if device.ssh_ip else "",
                    "serial": self.device_serial_connection_text(device)
                    if self.should_show_serial_connection_text(device)
                    else "",
                    "canSerial": self.can_view_serial_connection(device),
                }
            )
        return {
            "domains": [self.domain_combo.itemText(index) for index in range(self.domain_combo.count())],
            "statuses": [self.status_combo.itemText(index) for index in range(self.status_combo.count())],
            "filters": {
                "search": self.search_input.text(),
                "domain": self.domain_combo.currentText(),
                "status": self.status_combo.currentText(),
                "cpu": self.cpu_input.text(),
                "mine": self.my_occupancy_filter_enabled,
            },
            "stats": {
                "total": len(self.visible_devices),
                "idle": self.visible_status_counts.get(STATUS_IDLE, 0),
                "occupied": self.visible_status_counts.get(STATUS_OCCUPIED, 0),
                "pipeline": self.visible_status_counts.get(STATUS_PIPELINE, 0),
                "other": self.visible_status_counts.get(STATUS_OTHER, 0),
                "mine": self.my_occupancy_count(),
            },
            "summary": self.filter_summary_plain_text(),
            "hasFilters": self.has_active_device_filters(),
            "rows": rows,
        }

    def render_device_group_row(self, row: int, name: str, subdomain: str, count: int, keyword: str) -> None:
        self.device_table.setRowHeight(row, 24)
        self._set_table_item(
            self.device_table,
            row,
            0,
            self.device_table_name_text(name, subdomain),
            "",
            highlight=self.text_matches_keyword(name, keyword) or self.text_matches_keyword(subdomain, keyword),
            group=True,
            tooltip=name,
        )
        self._set_table_item(self.device_table, row, 1, "", "", group=True)
        self._set_table_item(self.device_table, row, 2, f"{count} 块板", "", group=True)
        self._set_table_item(self.device_table, row, 3, "", "", group=True)
        self._set_table_item(self.device_table, row, 4, "", "", group=True)
        self._set_table_item(self.device_table, row, 5, "", "", group=True)
        self.device_table.setSpan(row, 0, 1, 2)

    def render_device_table_row(self, row: int, device: Device, keyword: str, *, grouped: bool = False) -> None:
        self.device_table.setRowHeight(row, 26 if grouped else 30)
        board_type = self.device_table_board_type_text(device)
        hidden_keyword_match = self.device_matches_hidden_keyword(
            device,
            keyword,
            visible_values=(
                device.board_id,
                device.name,
                self.device_table_subdomain_text(device),
                device.device_type,
                board_type,
                device.cpu,
                device.slot_id,
                device.status,
                self.device_occupancy_duration_text(device),
            ),
        )
        self._set_table_item(
            self.device_table,
            row,
            0,
            self.device_table_board_id_text(device, grouped=grouped),
            device.id,
            highlight=self.text_matches_keyword(device.board_id, keyword),
            tooltip=device.board_id,
        )
        self._set_table_item(
            self.device_table,
            row,
            1,
            device.device_type if grouped else self.device_table_device_name_text(device),
            device.id,
            highlight=hidden_keyword_match
            or self.text_matches_keyword(device.name, keyword)
            or self.text_matches_keyword(self.device_table_subdomain_text(device), keyword),
            tooltip=device.name if grouped else None,
        )
        self._set_table_item(
            self.device_table,
            row,
            2,
            board_type,
            device.id,
            highlight=self.text_matches_keyword(board_type, keyword),
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
            device.slot_id,
            device.id,
            highlight=self.text_matches_keyword(device.slot_id, keyword),
        )
        status_text = self.device_table_status_text(device)
        self._set_table_item(
            self.device_table,
            row,
            5,
            status_text,
            device.id,
            color=status_color(device.status),
            highlight=self.text_matches_keyword(device.status, keyword)
            or self.text_matches_keyword(self.device_occupancy_duration_text(device), keyword),
            tooltip=self.device_occupancy_tooltip(device),
        )

    def device_table_board_id_text(self, device: Device, *, grouped: bool) -> str:
        if grouped:
            prefix = f"{device.id}-"
            if device.board_id.startswith(prefix):
                return device.board_id[len(prefix):]
            slot_id = str(device.extra.get("slot_id") or "")
            if slot_id and len(slot_id) <= 8:
                return slot_id
        return device.board_id

    def device_table_board_type_text(self, device: Device) -> str:
        return str(device.extra.get("board_type") or device.device_type)

    def device_table_device_name_text(self, device: Device) -> str:
        return self.device_table_name_text(
            self.temporary_device_display_name(device),
            self.device_table_subdomain_text(device),
        )

    def device_table_name_text(self, name: str, subdomain: str) -> str:
        subdomain = subdomain.strip()
        if not subdomain:
            return name
        return f"{name} · {subdomain}"

    def device_table_subdomain_text(self, device: Device) -> str:
        return str(device.extra.get("subdomain") or "").strip()

    def device_table_status_text(self, device: Device) -> str:
        duration = self.device_occupancy_duration_text(device)
        if duration and device.status == STATUS_OCCUPIED:
            return f"{device.status} {duration}"
        return device.status

    def device_status_kind(self, device: Device) -> str:
        if device.status == STATUS_IDLE:
            return "idle"
        if device.status == STATUS_OCCUPIED:
            return "occupied"
        if device.status == STATUS_PIPELINE:
            return "pipeline"
        return "other"

    def device_occupancy_tooltip(self, device: Device) -> str:
        parts = [device.status]
        if device.owner:
            parts.append(f"占用人: {device.owner}")
        started_text = self.device_occupancy_started_text(device)
        if started_text:
            parts.append(f"开始时间: {started_text}")
        duration = self.device_occupancy_duration_text(device)
        if duration:
            parts.append(f"占用时长: {duration}")
        return "\n".join(parts)

    def device_occupancy_started_text(self, device: Device) -> str:
        value = self.device_occupancy_started_value(device)
        if value is None:
            return ""
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def device_occupancy_duration_text(self, device: Device) -> str:
        if device.status != STATUS_OCCUPIED:
            return ""
        started_at = self.device_occupancy_started_value(device)
        if started_at is None:
            return ""
        now = datetime.now(started_at.tzinfo or timezone.utc)
        seconds = max(0, int((now - started_at).total_seconds()))
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _seconds = divmod(remainder, 60)
        if days:
            return f"{days}天{hours}小时"
        if hours:
            return f"{hours}小时{minutes}分"
        return f"{minutes}分"

    def device_occupancy_started_value(self, device: Device) -> datetime | None:
        for key in (
            "occupied_since",
            "occupied_at",
            "occupancy_started_at",
            "claimed_at",
            "claim_time",
            "owner_since",
            "since",
        ):
            value = device.extra.get(key)
            parsed = self.parse_device_datetime(value)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def parse_device_datetime(value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        else:
            text = str(value).strip()
            if not text:
                return None
            if text.isdigit():
                parsed = datetime.fromtimestamp(float(text), tz=timezone.utc)
            else:
                normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
                try:
                    parsed = datetime.fromisoformat(normalized)
                except ValueError:
                    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                        try:
                            parsed = datetime.strptime(text, fmt)
                            break
                        except ValueError:
                            parsed = None
                    if parsed is None:
                        return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

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
                (
                    device.id,
                    device.board_id,
                    device.name,
                    self.device_table_subdomain_text(device),
                    device.device_type,
                    self.device_table_board_type_text(device),
                    device.cpu,
                    device.slot_id,
                    device.status,
                    device.owner,
                    self.device_occupancy_started_text(device),
                    self.device_occupancy_duration_text(device),
                )
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
        display_rows = self.build_device_table_display_rows(self.visible_devices)
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        try:
            table.clearSpans()
            table.setRowCount(len(display_rows))
            self.device_table_rows = {}
            for row, row_data in enumerate(display_rows):
                if row_data.get("kind") != "device":
                    continue
                device = row_data.get("device")
                if isinstance(device, Device):
                    self.device_table_rows.setdefault(device.id, row)
            sync_rows = min(80, len(display_rows))
            for row in range(sync_rows):
                self.render_device_table_display_row(row, display_rows[row], keyword)
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)
        self.enqueue_table_render_job(
            table,
            display_rows,
            keyword,
            "device",
            generation,
            sync_rows,
        )

    def refresh_device_navigation_web(self) -> None:
        web_nav = getattr(self, "device_navigation_web", None)
        if web_nav is not None and hasattr(web_nav, "set_payload"):
            web_nav.set_payload(self.session_navigation_payload())

    def terminal_navigation_default_device_ids(self, limit: int = 10) -> list[str]:
        ids: list[str] = []

        def add(device_id: str) -> None:
            if device_id and device_id not in ids:
                ids.append(device_id)

        add(getattr(self, "selected_device_id", ""))
        if hasattr(self, "ordered_session_states"):
            for state in self.ordered_session_states():
                add(state.device_id)
        for device_id in getattr(self, "recent_device_ids", []):
            add(device_id)
        for device in getattr(self, "owned_visible_devices", []):
            add(device.id)
        for device in getattr(self, "visible_devices", []):
            if device.status == STATUS_IDLE:
                add(device.id)
            if len(ids) >= limit:
                break
        if len(ids) < limit:
            for device in self.navigation_devices():
                add(device.id)
                if len(ids) >= limit:
                    break
        return ids[:limit]

    def terminal_navigation_device_rows(self) -> list[dict[str, object]]:
        return [self.terminal_navigation_device_row(device) for device in self.navigation_devices()]

    def terminal_navigation_device_row(self, device: Device) -> dict[str, object]:
        helper = self.device_short_identity(device)
        detail_parts = [
            ("ID", device.id),
            ("板卡", self.device_table_board_type_text(device)),
            ("CPU", device.cpu),
            ("Slot", device.slot_id),
            ("领域", device.domain),
            ("Telnet", f"{device.telnet_ip}:{device.telnet_port}" if device.telnet_ip else ""),
            ("SSH", f"{device.ssh_ip}:{device.ssh_port}" if device.ssh_ip else ""),
            (
                "串口",
                self.device_serial_connection_text(device)
                if self.should_show_serial_connection_text(device)
                else "",
            ),
        ]
        detail = "\n".join(f"{label}: {value}" for label, value in detail_parts if value)
        return {
            "id": device.id,
            "name": self.temporary_device_display_name(device),
            "shortIdentity": helper,
            "boardId": device.board_id,
            "boardType": self.device_table_board_type_text(device),
            "cpu": device.cpu,
            "slot": device.slot_id,
            "domain": device.domain,
            "statusKind": self.device_status_kind(device),
            "statusText": self.device_table_status_text(device),
            "statusTooltip": self.device_occupancy_tooltip(device),
            "selected": device.id == self.selected_device_id,
            "telnet": f"{device.telnet_ip}:{device.telnet_port}" if device.telnet_ip else "",
            "ssh": f"{device.ssh_ip}:{device.ssh_port}" if device.ssh_ip else "",
            "serial": self.device_serial_connection_text(device)
            if self.should_show_serial_connection_text(device)
            else "",
            "canSerial": self.can_view_serial_connection(device),
            "searchText": self.device_search_text(device),
            "detail": detail,
        }

    @staticmethod
    def compact_endpoint(value: str) -> str:
        text = value.strip()
        if not text:
            return ""
        host = text.split(":", 1)[0]
        parts = host.split(".")
        if len(parts) == 4 and all(part.isdigit() for part in parts):
            return ".".join(parts[-2:])
        return host

    def device_short_identity(self, device: Device) -> str:
        for value in (
            device.ssh_ip,
            device.telnet_ip,
            device.serial_ip if self.can_view_serial_connection(device) else "",
            device.board_id,
            device.id,
        ):
            text = self.compact_endpoint(str(value))
            if text:
                return text
        return "-"

    def session_navigation_payload(self) -> dict[str, object]:
        current_tab_id = self.current_session_key() if hasattr(self, "current_session_key") else ""
        current_device = self.get_selected_device()
        navigation_payload = self.device_navigation_payload()
        sessions: list[dict[str, object]] = []
        connected = 0
        connecting = 0
        disconnected = 0
        if hasattr(self, "ordered_session_states"):
            for state in self.ordered_session_states():
                session_device = self.get_device_by_id(state.device_id)
                status = str(state.status_text or "")
                normalized_status = status.strip().lower()
                if normalized_status == "connected":
                    connected += 1
                elif normalized_status == "connecting":
                    connecting += 1
                else:
                    disconnected += 1
                sessions.append(
                    {
                        "tabId": state.tab_id,
                        "title": self.session_display_title(state, self.session_kind_label(state.kind)),
                        "kind": self.session_kind_label(state.kind),
                        "deviceName": self.temporary_device_display_name(session_device)
                        if session_device is not None
                        else state.device_id,
                        "deviceId": state.device_id,
                        "host": f"{state.host}:{state.port}",
                        "status": status,
                        "statusLabel": self.session_status_label(status),
                        "active": state.tab_id == current_tab_id,
                    }
                )
        selected_device = None
        if current_device is not None:
            selected_device = {
                "id": current_device.id,
                "name": self.temporary_device_display_name(current_device),
                "boardType": self.device_table_board_type_text(current_device),
                "cpu": current_device.cpu,
                "slot": current_device.slot_id,
                "statusText": self.device_table_status_text(current_device),
                "statusKind": self.device_status_kind(current_device),
                "telnet": f"{current_device.telnet_ip}:{current_device.telnet_port}" if current_device.telnet_ip else "",
                "ssh": f"{current_device.ssh_ip}:{current_device.ssh_port}" if current_device.ssh_ip else "",
                "serial": self.device_serial_connection_text(current_device)
                if self.should_show_serial_connection_text(current_device)
                else "",
                "canSerial": self.can_view_serial_connection(current_device),
            }
        return {
            "navigationState": {
                "activeTab": getattr(self, "terminal_navigation_active_tab", "devices"),
                "deviceQuery": getattr(self, "terminal_navigation_device_query", ""),
                "expandedDeviceId": getattr(self, "terminal_navigation_expanded_device_id", ""),
            },
            "summary": f"{len(sessions)} 个终端会话",
            "stats": {
                "total": len(sessions),
                "connected": connected,
                "connecting": connecting,
                "disconnected": disconnected,
            },
            "sessions": sessions,
            "selectedDevice": selected_device,
            "rows": navigation_payload.get("rows", []),
            "devices": self.terminal_navigation_device_rows(),
            "defaultDeviceIds": self.terminal_navigation_default_device_ids(),
            "deviceTotal": len(self.navigation_devices()),
        }

    def web_shell_payload(self) -> dict[str, object]:
        device = self.get_selected_device()
        navigation_payload = self.device_navigation_payload()
        selected_device = None
        if device is not None:
            selected_device = {
                "id": device.id,
                "name": self.temporary_device_display_name(device),
                "domain": device.domain,
                "boardType": self.device_table_board_type_text(device),
                "cpu": device.cpu,
                "slot": device.slot_id,
                "statusText": self.device_table_status_text(device),
                "statusKind": self.device_status_kind(device),
                "owner": device.owner or "未占用",
                "telnet": f"{device.telnet_ip}:{device.telnet_port}" if device.telnet_ip else "",
                "ssh": f"{device.ssh_ip}:{device.ssh_port}" if device.ssh_ip else "",
                "serial": self.device_serial_connection_text(device)
                if self.should_show_serial_connection_text(device)
                else "",
                "canSerial": self.can_view_serial_connection(device),
            }
        sessions: list[dict[str, object]] = []
        current_tab_id = self.current_session_key() if hasattr(self, "current_session_key") else ""
        if hasattr(self, "ordered_session_states"):
            for state in self.ordered_session_states():
                session_device = self.get_device_by_id(state.device_id)
                sessions.append(
                    {
                        "tabId": state.tab_id,
                        "title": state.title,
                        "kind": self.session_kind_label(state.kind),
                        "deviceId": state.device_id,
                        "deviceName": self.temporary_device_display_name(session_device)
                        if session_device is not None
                        else state.device_id,
                        "host": f"{state.host}:{state.port}",
                        "status": state.status_text,
                        "statusLabel": self.session_status_label(state.status_text),
                        "active": state.tab_id == current_tab_id,
                    }
                )
        return {
            "summary": self.filter_summary_plain_text(),
            "domains": navigation_payload.get("domains", []),
            "statuses": navigation_payload.get("statuses", []),
            "filters": navigation_payload.get("filters", {}),
            "hasFilters": navigation_payload.get("hasFilters", False),
            "stats": {
                "total": len(self.visible_devices),
                "idle": self.visible_status_counts.get(STATUS_IDLE, 0),
                "occupied": self.visible_status_counts.get(STATUS_OCCUPIED, 0),
                "pipeline": self.visible_status_counts.get(STATUS_PIPELINE, 0),
                "other": self.visible_status_counts.get(STATUS_OTHER, 0),
                "mine": self.my_occupancy_count(),
            },
            "selectedDevice": selected_device,
            "rows": navigation_payload.get("rows", []),
            "sessions": sessions,
        }

    def refresh_web_shell(self) -> None:
        web_shell = getattr(self, "web_shell", None)
        if web_shell is not None and hasattr(web_shell, "set_payload"):
            web_shell.set_payload(self.web_shell_payload())

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
        group: bool = False,
        tooltip: str | None = None,
    ) -> None:
        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            table.setItem(row, column, item)
        if item.text() != text:
            item.setText(text)
        if item.data(Qt.UserRole) != device_id:
            item.setData(Qt.UserRole, device_id)
        tooltip_text = text if tooltip is None else tooltip
        if item.toolTip() != tooltip_text:
            item.setToolTip(tooltip_text)
        item.setBackground(QBrush())
        item.setForeground(QBrush())
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        font = item.font()
        if font.bold() or group:
            font.setBold(False)
        if group:
            font.setBold(column in {0, 2})
        item.setFont(font)
        if group:
            item.setBackground(QBrush(QColor(HTML_PANEL)))
            group_color = HTML_TEXT if column == 0 else HTML_SOFT
            item.setForeground(QBrush(QColor(group_color)))
            return
        if color:
            item.setForeground(QBrush(QColor(color)))
        if highlight:
            item.setBackground(QBrush(QColor(HTML_SELECTED)))
            item.setForeground(QBrush(QColor(HTML_TEXT)))
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
            self.device_table_device_name_text(device),
            device.device_type,
            device.cpu,
            device.slot_id,
            self.device_table_status_text(device),
        ])

    def device_connection_copy_text(self, device: Device) -> str:
        serial_text = self.device_serial_connection_text(device)
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
        serial_endpoint = self.device_serial_connection_text(device)
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
            if self.is_my_occupied_device(device) and not device.serial_ip.strip():
                self.show_warning("当前设备无串口 IP。")
            else:
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

    def should_show_serial_connection_text(self, device: Device) -> bool:
        return self.can_view_serial_connection(device) or (
            self.is_my_occupied_device(device) and not device.serial_ip.strip()
        )

    def device_serial_connection_text(self, device: Device) -> str:
        if self.can_view_serial_connection(device):
            return f"{device.serial_ip}:{device.serial_port}"
        if self.is_temporary_device(device):
            return ""
        if self.is_my_occupied_device(device) and not device.serial_ip.strip():
            return "设备无串口 IP"
        return "占用后可见"

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
        self.selected_device_id = device_id
        self._mark_recent_device(device_id)
        self.sync_auth_fields_from_selected()
        self.refresh_device_context()
        self.refresh_workspace_context()
        self.update_controls()
        self.refresh_device_navigation_web()

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
        self.refresh_device_navigation_web()

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

    def has_active_device_filters(self) -> bool:
        return bool(
            self.search_input.text().strip()
            or self.my_occupancy_filter_enabled
            or self.domain_combo.currentText().strip() != ALL_DOMAINS
            or self.status_combo.currentText().strip() != ALL_STATUS
            or self.cpu_input.text().strip()
        )

    def filter_summary_plain_text(self) -> str:
        active_filters: list[str] = []
        search_text = self.search_input.text().strip()
        domain_filter = self.domain_combo.currentText().strip()
        status_filter = self.status_combo.currentText().strip()
        cpu_filter = self.cpu_input.text().strip()
        if search_text:
            active_filters.append(f"关键词 {search_text}")
        if self.my_occupancy_filter_enabled:
            label = self.current_user or "我的占用"
            active_filters.append(f"占用 {label}")
        if domain_filter and domain_filter != ALL_DOMAINS:
            active_filters.append(f"领域 {domain_filter}")
        if status_filter and status_filter != ALL_STATUS:
            active_filters.append(f"状态 {status_filter}")
        if cpu_filter:
            active_filters.append(f"CPU {cpu_filter}")
        return " / ".join(active_filters) if active_filters else "当前显示全部设备"

    def filter_chip_html(self, label: str, value: str) -> str:
        return html_chip(label, value, class_name="filter-chip")

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

        menu = self.new_workspace_menu(table, self.temporary_device_display_name(device), "device")
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
        simulated = self.is_simulated_device(device)
        serial_available = self.can_view_serial_connection(device)
        copy_ssh_ip_action.setEnabled(not simulated)
        copy_telnet_ip_action.setEnabled(not simulated)
        copy_connection_action.setEnabled(not simulated)
        toggle_action.setEnabled(not simulated)
        copy_serial_ip_action.setEnabled(serial_available)
        open_linux_action.setEnabled(not simulated)
        open_serial_action.setEnabled(serial_available and not simulated)
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
        menu = self.new_workspace_menu(widget, self.temporary_device_display_name(device), "device")
        actions = self._add_device_quick_actions(menu)
        self.update_device_quick_actions_for_device(actions, device)
        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen is None:
            return
        self._handle_device_quick_action(chosen, actions, device)

    def show_web_device_context_menu(self, device_id: str, global_x: int, global_y: int) -> None:
        device = self.get_device_by_id(device_id)
        if device is None or QMenu is None or QPoint is None:
            return
        self.activate_device(device_id)
        menu = self.new_workspace_menu(self, self.temporary_device_display_name(device), "device")
        actions = self._add_device_quick_actions(menu)
        self.update_device_quick_actions_for_device(actions, device)
        chosen = menu.exec(QPoint(global_x, global_y))
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
        device = self.get_selected_device()
        if device is None:
            return
        telnet_username, telnet_password = self.local_session_credentials(device, "device") or (
            device.username,
            device.password,
        )
        ssh_username, ssh_password = self.local_session_credentials(device, "linux") or (
            self.device_ssh_username(device),
            self.device_ssh_password(device),
        )
        serial_username, serial_password = self.local_session_credentials(device, "serial") or (
            self.device_serial_username(device),
            self.device_serial_password(device),
        )
        self.device_telnet_ip_value.setText(device.telnet_ip)
        self.device_username_input.setText(telnet_username)
        self.device_password_input.setText(telnet_password)
        self.device_ssh_ip_value.setText(device.ssh_ip)
        self.device_serial_ip_value.setText(
            self.device_serial_connection_text(device) if self.should_show_serial_connection_text(device) else ""
        )
        if hasattr(self, "serial_username_input"):
            self.serial_username_input.setText(serial_username)
            self.serial_password_input.setText(serial_password)
        self.linux_username_input.setText(ssh_username)
        self.linux_password_input.setText(ssh_password)

    def refresh_device_context(self) -> None:
        device = self.get_selected_device()
        if device is None:
            self.device_summary_card.setText("请选择一台设备。")
            self.device_ssh_ip_value.clear()
            self.device_telnet_ip_value.clear()
            self.device_serial_ip_value.clear()
            if hasattr(self, "serial_username_input"):
                self.serial_username_input.clear()
                self.serial_password_input.clear()
            return

        self.device_ssh_ip_value.setText(device.ssh_ip)
        self.device_telnet_ip_value.setText(device.telnet_ip)
        self.device_serial_ip_value.setText(
            self.device_serial_connection_text(device) if self.should_show_serial_connection_text(device) else ""
        )
        if hasattr(self, "serial_username_input"):
            serial_username, serial_password = self.local_session_credentials(device, "serial") or (
                self.device_serial_username(device),
                self.device_serial_password(device),
            )
            self.serial_username_input.setText(serial_username)
            self.serial_password_input.setText(serial_password)
        owner_text = device.owner or "未占用"
        self.device_summary_card.setText(
            html_device_summary(
                self.temporary_device_display_name(device),
                device.id,
                device.domain,
                device.status,
                status_color(device.status),
                owner_text,
                owner_muted=not bool(device.owner),
                detail_html=self.temporary_device_detail_badge(device),
            )
        )
        return
