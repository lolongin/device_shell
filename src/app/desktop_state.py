"""Desktop state persistence mixin for DeviceDesktopApp."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from pathlib import Path

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QFileDialog
except ModuleNotFoundError:
    QUrl = None
    QDesktopServices = None
    QFileDialog = None

from ..app_state import SessionTabState
from ..auto_response import (
    deserialize_auto_response_rule,
    deserialize_quick_send_button,
    serialize_auto_response_rule,
    serialize_quick_send_button,
)
from ..data import Device
from ..temporary_devices import deserialize_temporary_device, serialize_temporary_device
from ..widgets.terminal_widget import ANSI_ESCAPE_RE

DESKTOP_STATE_VERSION = 8


class DesktopStateMixin:
    """Mixin providing desktop state load/save and session logging."""

    @staticmethod
    def desktop_state_path() -> Path:
        configured = os.getenv("DEVICE_TUI_DESKTOP_STATE_PATH", "").strip()
        if configured:
            return Path(configured).expanduser()
        appdata = os.getenv("APPDATA", "").strip()
        if appdata:
            return Path(appdata) / "device_tui" / "desktop_state.json"
        return Path.home() / ".device_tui" / "desktop_state.json"

    def default_log_directory(self) -> Path:
        return self.state_path.parent / "logs"

    @staticmethod
    def default_command_record_groups() -> list[dict[str, object]]:
        return [{"name": "终端", "content": ""}]

    def load_desktop_state(self) -> None:
        try:
            if not self.state_path.exists():
                return
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        try:
            state_version = int(payload.get("version", 0))
        except (TypeError, ValueError):
            state_version = 0

        groups: list[dict[str, object]] = []
        raw_groups = payload.get("command_record_groups", [])
        if isinstance(raw_groups, list):
            for index, item in enumerate(raw_groups, start=1):
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or f"分组 {index}").strip()
                content = str(item.get("content") or "")
                groups.append({"name": name or f"分组 {index}", "content": content})
        self.command_record_groups = groups or self.default_command_record_groups()

        try:
            loaded_index = int(payload.get("current_command_group", 0))
        except (TypeError, ValueError):
            loaded_index = 0
        self.current_command_group = min(max(loaded_index, 0), len(self.command_record_groups) - 1)
        self.command_record_collapsed = bool(payload.get("command_record_collapsed", True))
        if state_version < 3:
            self.command_record_collapsed = True
        self.command_enter_sends = bool(payload.get("command_enter_sends", False))
        try:
            loaded_command_height = int(
                payload.get("command_record_height", self.COMMAND_RECORD_DEFAULT_HEIGHT)
            )
        except (TypeError, ValueError):
            loaded_command_height = self.COMMAND_RECORD_DEFAULT_HEIGHT
        self.command_record_height = self.clamp_command_record_height(loaded_command_height)
        self.connection_params_collapsed = bool(payload.get("connection_params_collapsed", False))
        if state_version < 5:
            self.connection_params_collapsed = False
        self.device_navigation_collapsed = bool(payload.get("device_navigation_collapsed", False))
        self.left_sidebar_collapsed = bool(payload.get("left_sidebar_collapsed", False))
        self.always_on_top = bool(payload.get("always_on_top", False))
        remembered_rules = []
        raw_auto_response_rules = payload.get("auto_response_rules", [])
        if isinstance(raw_auto_response_rules, list):
            for item in raw_auto_response_rules:
                rule = deserialize_auto_response_rule(item)
                if rule is not None:
                    remembered_rules.append(rule)
        self.remembered_auto_response_rules = remembered_rules
        raw_quick_buttons = payload.get("quick_send_buttons")
        if isinstance(raw_quick_buttons, list):
            quick_buttons = []
            for item in raw_quick_buttons:
                button = deserialize_quick_send_button(item)
                if button is not None:
                    quick_buttons.append(button)
            self.remembered_quick_send_buttons = quick_buttons
        loaded_log_directory = str(payload.get("log_directory") or "").strip()
        if loaded_log_directory:
            self.log_directory = Path(loaded_log_directory).expanduser()
        temporary_devices: list[Device] = []
        raw_temporary_devices = payload.get("temporary_devices", [])
        if isinstance(raw_temporary_devices, list):
            for item in raw_temporary_devices:
                device = deserialize_temporary_device(item)
                if device is not None:
                    temporary_devices.append(device)
        self.temporary_devices = temporary_devices
        credential_overrides: dict[str, dict[str, dict[str, str]]] = {}
        raw_credential_overrides = payload.get("local_credential_overrides", {})
        if isinstance(raw_credential_overrides, dict):
            for device_id, per_device in raw_credential_overrides.items():
                if not isinstance(per_device, dict):
                    continue
                device_key = str(device_id)
                protocol_overrides: dict[str, dict[str, str]] = {}
                for kind, credentials in per_device.items():
                    if kind not in {"device", "linux", "serial"} or not isinstance(credentials, dict):
                        continue
                    protocol_overrides[str(kind)] = {
                        "username": str(credentials.get("username") or ""),
                        "password": str(credentials.get("password") or ""),
                    }
                if protocol_overrides:
                    credential_overrides[device_key] = protocol_overrides
        self.local_credential_overrides = credential_overrides
        if hasattr(self, "rebuild_device_indexes"):
            self.rebuild_device_indexes()

    def schedule_desktop_state_save(self) -> None:
        if hasattr(self, "state_save_timer"):
            self.state_save_timer.start(1200)

    def save_desktop_state(self) -> None:
        try:
            self._save_current_command_content()
            payload = {
                "version": DESKTOP_STATE_VERSION,
                "command_record_groups": self.command_record_groups,
                "current_command_group": self.current_command_group_index(),
                "command_record_collapsed": self.command_record_collapsed,
                "command_enter_sends": self.command_enter_sends,
                "command_record_height": self.command_record_height,
                "connection_params_collapsed": self.connection_params_collapsed,
                "device_navigation_collapsed": self.device_navigation_collapsed,
                "left_sidebar_collapsed": self.left_sidebar_collapsed,
                "always_on_top": self.always_on_top,
                "auto_response_rules": [
                    serialize_auto_response_rule(rule)
                    for rule in self.remembered_auto_response_rules
                ],
                "quick_send_buttons": [
                    serialize_quick_send_button(button)
                    for button in self.remembered_quick_send_buttons
                ],
                "log_directory": str(self.log_directory),
                "temporary_devices": [
                    serialize_temporary_device(device)
                    for device in self.temporary_devices
                ],
                "local_credential_overrides": self.local_credential_overrides,
            }
            serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if serialized == self._last_desktop_state_payload:
                return
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(self.state_path)
            self._last_desktop_state_payload = serialized
        except OSError as exc:
            if self.statusBar() is not None:
                self.statusBar().showMessage(f"桌面状态保存失败: {exc}")

    def session_log_path(self, device: Device, title: str, kind: str) -> Path:
        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        device_name = self.safe_log_component(device.name or device.id, "device")
        session_name = self.safe_log_component(title, "session")
        kind_name = (
            "serial"
            if kind == "serial"
            else ("telnet" if kind == "device" else ("simulated" if kind == "simulated" else "ssh"))
        )
        filename = f"{timestamp}_{device_name}_{kind_name}_{session_name}.log"
        return self.unique_log_path(self.log_directory.expanduser() / filename)

    def unique_log_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def safe_log_component(self, value: str, fallback: str) -> str:
        safe_chars: list[str] = []
        for char in value.strip():
            if char.isalnum() or char in {"-", "_", "."}:
                safe_chars.append(char)
            elif safe_chars and safe_chars[-1] != "-":
                safe_chars.append("-")
        safe = "".join(safe_chars).strip("-._")
        return (safe or fallback)[:80]

    def write_session_log_line(self, state: SessionTabState, channel: str, text: str) -> None:
        self.write_session_log(state, channel, f"{text}\n", separate_record=True)

    def write_session_log(
        self,
        state: SessionTabState,
        channel: str,
        text: str,
        *,
        separate_record: bool = False,
    ) -> None:
        if channel == "IN":
            return
        sanitized = self.sanitize_log_text(text)
        if not sanitized:
            return
        if channel == "SYS":
            sanitized = f"# {sanitized}"
        state.log_pending_records.append((channel, sanitized, separate_record))
        if separate_record or len(sanitized) >= self.LOG_FLUSH_IMMEDIATE_CHARS:
            self.flush_session_log_state(state)
        else:
            self.schedule_session_log_flush()

    def schedule_session_log_flush(self) -> None:
        if not self.log_flush_timer.isActive():
            self.log_flush_timer.start(self.LOG_FLUSH_INTERVAL_MS)

    def flush_pending_session_logs(self) -> None:
        for state in list(self.session_tabs_by_id.values()):
            self.flush_session_log_state(state)

    def flush_session_log_state(self, state: SessionTabState) -> None:
        if not state.log_pending_records:
            return
        try:
            state.log_path.parent.mkdir(parents=True, exist_ok=True)
            with state.log_path.open("a", encoding="utf-8", newline="") as log_file:
                for channel, sanitized, separate_record in state.log_pending_records:
                    if separate_record and not state.log_at_line_start:
                        log_file.write("\n")
                        state.log_at_line_start = True
                    for segment in sanitized.splitlines(keepends=True):
                        if channel != "SYS" and state.log_at_line_start and not segment.strip():
                            continue
                        if state.log_at_line_start:
                            log_file.write(f"[{self.log_timestamp()}] ")
                        log_file.write(segment)
                        state.log_at_line_start = segment.endswith("\n")
            state.log_pending_records.clear()
        except OSError as exc:
            self.set_status_message(f"Log write failed: {exc}")

    def finish_session_log_record(self, state: SessionTabState) -> None:
        self.flush_session_log_state(state)
        if state.log_at_line_start:
            return
        try:
            state.log_path.parent.mkdir(parents=True, exist_ok=True)
            with state.log_path.open("a", encoding="utf-8", newline="") as log_file:
                log_file.write("\n")
            state.log_at_line_start = True
        except OSError as exc:
            self.set_status_message(f"日志写入失败: {exc}")

    @staticmethod
    def sanitize_log_text(text: str) -> str:
        sanitized = ANSI_ESCAPE_RE.sub("", text)
        sanitized = sanitized.replace("\r\n", "\n").replace("\r", "\n")
        return "".join(char if char == "\n" or char == "\t" or char >= " " else "" for char in sanitized)

    @staticmethod
    def log_timestamp() -> str:
        return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log_session_input(self, state: SessionTabState, text: str) -> None:
        del state, text

    @staticmethod
    def skip_escape_sequence(text: str, index: int) -> int:
        if index + 1 >= len(text) or text[index + 1] != "[":
            return index + 1
        end = index + 2
        while end < len(text) and not ("@" <= text[end] <= "~"):
            end += 1
        return min(end + 1, len(text))

    def flush_session_input_log(self, state: SessionTabState) -> None:
        command = state.log_input_buffer.rstrip()
        state.log_input_buffer = ""
        if command:
            self.write_session_log_line(state, "IN", command)

    def open_session_log(self, state: SessionTabState) -> None:
        self.finish_session_log_record(state)
        self.open_local_path(state.log_path, "日志文件", is_directory=False)

    def create_session_log(self, state: SessionTabState) -> Path:
        old_path = state.log_path
        self.finish_session_log_record(state)
        device = self.get_device_by_id(state.device_id) if hasattr(self, "get_device_by_id") else None
        if device is not None:
            new_path = self.session_log_path(device, state.title, state.kind)
        else:
            timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            device_name = self.safe_log_component(state.device_id, "device")
            session_name = self.safe_log_component(state.title, "session")
            kind_name = "serial" if state.kind == "serial" else ("telnet" if state.kind == "device" else "ssh")
            filename = f"{timestamp}_{device_name}_{kind_name}_{session_name}.log"
            new_path = self.unique_log_path(self.log_directory.expanduser() / filename)
        state.log_path = new_path
        state.log_at_line_start = True
        self.write_session_log_line(state, "SYS", f"New log created; previous log: {old_path}")
        return new_path

    def open_session_log_directory(self, state: SessionTabState) -> None:
        self.finish_session_log_record(state)
        self.open_local_path(state.log_path.parent, "日志目录", is_directory=True)

    def open_log_directory(self) -> None:
        self.open_local_path(self.log_directory.expanduser(), "日志目录", is_directory=True)

    def open_local_path(self, path: Path, label: str, *, is_directory: bool) -> None:
        try:
            if is_directory:
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
            if not is_directory and not path.exists():
                path.touch()
        except OSError as exc:
            self.show_error(f"{label}准备失败: {exc}")
            return
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.set_status_message(f"已打开{label}: {path}")
            return
        self.show_warning(f"无法打开{label}: {path}")

    def change_log_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择日志保存位置",
            str(self.log_directory.expanduser()),
        )
        if not selected:
            return
        new_directory = Path(selected).expanduser()
        try:
            new_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.show_error(f"日志目录不可用: {exc}")
            return
        moved_count = self.move_active_session_logs(new_directory)
        self.log_directory = new_directory
        self.schedule_desktop_state_save()
        suffix = f"，已迁移 {moved_count} 个当前会话日志" if moved_count else ""
        self.set_status_message(f"日志位置已更改: {new_directory}{suffix}")

    def move_active_session_logs(self, new_directory: Path) -> int:
        moved_count = 0
        for state in self.session_tabs_by_id.values():
            old_path = state.log_path
            target_path = new_directory / old_path.name
            try:
                same_path = old_path.resolve() == target_path.resolve()
            except OSError:
                same_path = old_path == target_path
            if same_path:
                continue
            new_path = self.unique_log_path(target_path)
            self.finish_session_log_record(state)
            try:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                if old_path.exists():
                    shutil.move(str(old_path), str(new_path))
                    moved_count += 1
                state.log_path = new_path
                state.log_at_line_start = True
                self.write_session_log_line(state, "SYS", f"Log location changed from {old_path}")
            except (OSError, shutil.Error) as exc:
                self.set_status_message(f"日志迁移失败: {exc}")
        return moved_count
