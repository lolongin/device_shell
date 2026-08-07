"""Desktop state persistence mixin for DeviceDesktopApp."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QFileDialog, QInputDialog
except ModuleNotFoundError:
    QUrl = None
    QDesktopServices = None
    QFileDialog = None
    QInputDialog = None

from ..app_state import SessionTabState
from ..auto_response import (
    deserialize_auto_response_rule,
    deserialize_quick_send_button,
    serialize_auto_response_rule,
    serialize_quick_send_button,
)
from ..command_suggestions import (
    deserialize_command_history_item,
    serialize_command_history_item,
)
from ..data import Device, SavedServer
from ..temporary_devices import deserialize_temporary_device, serialize_temporary_device
from ..widgets.terminal_widget import ANSI_ESCAPE_RE

DESKTOP_STATE_VERSION = 15


def _clamp_int(value: object, low: int, high: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(max(parsed, low), high)


class DesktopStateMixin:
    """Mixin providing desktop state load/save and session logging."""

    @staticmethod
    def desktop_state_path() -> Path:
        configured = os.getenv("DEVICE_TUI_DESKTOP_STATE_PATH", "").strip()
        if configured:
            return Path(configured).expanduser()
        pytest_test = os.getenv("PYTEST_CURRENT_TEST", "").strip()
        if pytest_test:
            digest = hashlib.sha1(pytest_test.encode("utf-8", errors="ignore")).hexdigest()[:12]
            return Path(tempfile.gettempdir()) / "device_tui_pytest" / digest / "desktop_state.json"
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
        command_history = []
        raw_command_history = payload.get("command_history", [])
        if isinstance(raw_command_history, list):
            for item in raw_command_history:
                history_item = deserialize_command_history_item(item)
                if history_item is not None:
                    command_history.append(history_item)
        self.command_history = command_history
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
        terminal_navigation = payload.get("terminal_navigation", {})
        if isinstance(terminal_navigation, dict):
            active_tab = str(terminal_navigation.get("active_tab") or "").strip().lower()
            if active_tab in {"sessions", "devices"}:
                self.terminal_navigation_active_tab = active_tab
            query = str(terminal_navigation.get("device_query") or "")
            if len(query) <= 120:
                self.terminal_navigation_device_query = query
            self.terminal_navigation_expanded_device_id = str(
                terminal_navigation.get("expanded_device_id") or ""
            )
            try:
                loaded_navigation_height = int(
                    terminal_navigation.get("web_height", self.terminal_navigation_web_height)
                )
            except (TypeError, ValueError):
                loaded_navigation_height = self.terminal_navigation_web_height
            self.terminal_navigation_web_height = self.clamp_terminal_navigation_web_height(
                loaded_navigation_height
            )
            self.terminal_sidebar_collapsed = bool(
                terminal_navigation.get("sidebar_collapsed", self.terminal_sidebar_collapsed)
            )
            try:
                loaded_width = int(
                    terminal_navigation.get("sidebar_width", self.terminal_sidebar_width)
                )
            except (TypeError, ValueError):
                loaded_width = self.terminal_sidebar_width
            self.terminal_sidebar_width = max(
                self.TERMINAL_SIDEBAR_MIN_WIDTH, loaded_width
            )
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
        transfer_config = payload.get("file_transfer_service", {})
        if isinstance(transfer_config, dict):
            protocol = str(transfer_config.get("protocol") or self.transfer_protocol).lower()
            if protocol in {"ftp", "sftp"}:
                self.transfer_protocol = protocol
            self.transfer_host = str(transfer_config.get("host") or self.transfer_host)
            try:
                self.transfer_port = int(transfer_config.get("port", self.transfer_port))
            except (TypeError, ValueError):
                pass
            if state_version < 9:
                if self.transfer_protocol == "ftp" and self.transfer_port == 21:
                    self.transfer_port = 2121
                elif self.transfer_protocol == "sftp" and self.transfer_port == 22:
                    self.transfer_port = 2222
            root = str(transfer_config.get("root") or "").strip()
            if root:
                self.transfer_root_directory = Path(root).expanduser()
            self.transfer_username = str(transfer_config.get("username") or self.transfer_username)
            self.transfer_password = str(transfer_config.get("password") or self.transfer_password)
            self.transfer_writable = bool(transfer_config.get("writable", self.transfer_writable))
        loaded_log_directory = str(payload.get("log_directory") or "").strip()
        if loaded_log_directory:
            self.log_directory = Path(loaded_log_directory).expanduser()
        try:
            rotate_size_mb = int(payload.get("log_rotate_size_mb", self.DEFAULT_LOG_ROTATE_SIZE_MB))
        except (TypeError, ValueError):
            rotate_size_mb = self.DEFAULT_LOG_ROTATE_SIZE_MB
        self.log_rotate_size_bytes = min(max(rotate_size_mb, 1), 1024) * 1024 * 1024
        temporary_devices: list[Device] = []
        raw_temporary_devices = payload.get("temporary_devices", [])
        if isinstance(raw_temporary_devices, list):
            for item in raw_temporary_devices:
                device = deserialize_temporary_device(item)
                if device is not None:
                    temporary_devices.append(device)
        self.temporary_devices = temporary_devices

        saved_server_groups: list[str] = []
        raw_server_groups = payload.get("saved_server_groups", [])
        if isinstance(raw_server_groups, list):
            for item in raw_server_groups:
                group_name = str(item or "").strip()
                if group_name and group_name != "未分组" and group_name not in saved_server_groups:
                    saved_server_groups.append(group_name)
        self.saved_server_groups = saved_server_groups

        saved_servers: list[SavedServer] = []
        raw_servers = payload.get("saved_servers", [])
        if isinstance(raw_servers, list):
            for item in raw_servers:
                if not isinstance(item, dict):
                    continue
                server_id = str(item.get("id") or "").strip()
                if not server_id:
                    continue
                saved_servers.append(SavedServer(
                    id=server_id,
                    name=str(item.get("name") or "").strip() or server_id,
                    host=str(item.get("host") or "").strip(),
                    port=int(item.get("port", 22) or 22),
                    username=str(item.get("username") or "").strip(),
                    password=str(item.get("password") or ""),
                    group=str(item.get("group") or "").strip(),
                    notes=str(item.get("notes") or "").strip(),
                ))
        self.saved_servers = saved_servers
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
        remembered_terminal_sessions: list[dict[str, object]] = []
        raw_terminal_sessions = payload.get("terminal_sessions", [])
        if isinstance(raw_terminal_sessions, list):
            for item in raw_terminal_sessions:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("kind") or "").strip()
                if kind not in {"device", "linux", "serial", "simulated"}:
                    continue
                device_id = str(item.get("device_id") or "").strip()
                if not device_id:
                    continue
                try:
                    port = int(item.get("port", 0))
                except (TypeError, ValueError):
                    port = 0
                remembered_terminal_sessions.append({
                    "device_id": device_id,
                    "kind": kind,
                    "title": str(item.get("title") or "").strip(),
                    "host": str(item.get("host") or "").strip(),
                    "port": max(0, port),
                    "active": bool(item.get("active", False)),
                })
                if len(remembered_terminal_sessions) >= 20:
                    break
        self.remembered_terminal_sessions = remembered_terminal_sessions
        session_layout = payload.get("session_layout", {})
        if isinstance(session_layout, dict):
            raw_layout = str(session_layout.get("session_tab_layout") or "top").strip().lower()
            if raw_layout in {"top", "side"}:
                self.session_tab_layout = raw_layout
            try:
                loaded_font = int(session_layout.get("terminal_font_size", self.terminal_font_size))
            except (TypeError, ValueError):
                loaded_font = self.terminal_font_size
            self.terminal_font_size = max(9, min(28, loaded_font))
            self.session_manager_default_collapsed = bool(
                session_layout.get("session_manager_default_collapsed", False)
            )
            try:
                loaded_width = int(session_layout.get("session_manager_width", self.session_manager_width))
            except (TypeError, ValueError):
                loaded_width = self.session_manager_width
            self.session_manager_width = max(200, min(480, loaded_width))
            if "session_manager_collapsed" in session_layout:
                self.session_manager_collapsed = bool(
                    session_layout["session_manager_collapsed"]
                )
            else:
                # No memorized collapse history yet — the default-collapse
                # setting governs the first entry into `side`. Afterwards the
                # memorized toggle value wins.
                self.session_manager_collapsed = bool(self.session_manager_default_collapsed)
            raw_collapsed = session_layout.get("collapsed_device_groups", [])
            if isinstance(raw_collapsed, list):
                self.collapsed_device_groups = [
                    str(item or "").strip() for item in raw_collapsed if str(item or "").strip()
                ]
        raw_theme = str(payload.get("theme_mode") or "dark").strip().lower()
        if raw_theme in {"light", "dark"}:
            self.theme_mode = raw_theme
        if state_version >= 15:
            ai_gateway = payload.get("ai_gateway")
            if not isinstance(ai_gateway, dict):
                ai_gateway = {}
        else:
            # Pre-v15 states have no AI gateway config — use defaults.
            ai_gateway = {}
        result_store = ai_gateway.get("result_store")
        if not isinstance(result_store, dict):
            result_store = {}
        self.ai_gateway_result_store_config = {
            "max_entries": _clamp_int(result_store.get("max_entries", 500), 50, 5000, 500),
            "ttl_hours": _clamp_int(result_store.get("ttl_hours", 24), 1, 168, 24),
        }
        if hasattr(self, "apply_session_layout_state"):
            self.apply_session_layout_state()
        if hasattr(self, "apply_theme"):
            self.apply_theme(getattr(self, "theme_mode", "dark"))
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
                "command_history": [
                    serialize_command_history_item(item)
                    for item in self.command_history
                ],
                "command_record_height": self.command_record_height,
                "connection_params_collapsed": self.connection_params_collapsed,
                "device_navigation_collapsed": self.device_navigation_collapsed,
                "terminal_navigation": {
                    "active_tab": self.terminal_navigation_active_tab,
                    "device_query": self.terminal_navigation_device_query,
                    "expanded_device_id": self.terminal_navigation_expanded_device_id,
                    "web_height": self.terminal_navigation_web_height,
                    "sidebar_collapsed": self.terminal_sidebar_collapsed,
                    "sidebar_width": self.terminal_sidebar_width,
                },
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
                "file_transfer_service": {
                    "protocol": self.transfer_protocol,
                    "host": self.transfer_host,
                    "port": self.transfer_port,
                    "root": str(self.transfer_root_directory),
                    "username": self.transfer_username,
                    "password": self.transfer_password,
                    "writable": self.transfer_writable,
                },
                "log_directory": str(self.log_directory),
                "log_rotate_size_mb": max(1, self.log_rotate_size_bytes // (1024 * 1024)),
                "temporary_devices": [
                    serialize_temporary_device(device)
                    for device in self.temporary_devices
                ],
                "saved_server_groups": list(getattr(self, "saved_server_groups", [])),
                "saved_servers": [
                    {
                        "id": server.id,
                        "name": server.name,
                        "host": server.host,
                        "port": server.port,
                        "username": server.username,
                        "password": server.password,
                        "group": server.group,
                        "notes": server.notes,
                    }
                    for server in self.saved_servers
                ],
                "local_credential_overrides": self.local_credential_overrides,
                "session_layout": {
                    "session_tab_layout": self.session_tab_layout,
                    "terminal_font_size": self.terminal_font_size,
                    "session_manager_default_collapsed": self.session_manager_default_collapsed,
                    "session_manager_width": self.session_manager_width,
                    "session_manager_collapsed": self.session_manager_collapsed,
                    "collapsed_device_groups": list(self.collapsed_device_groups),
                },
                "theme_mode": getattr(self, "theme_mode", "dark"),
                "terminal_sessions": self.serialize_terminal_sessions()
                if hasattr(self, "serialize_terminal_sessions")
                else [],
                "ai_gateway": {
                    "result_store": {
                        "max_entries": self.ai_gateway_service.result_store.max_entries
                        if hasattr(self, "ai_gateway_service")
                        and hasattr(self.ai_gateway_service, "result_store")
                        else 500,
                        "ttl_hours": self.ai_gateway_service.result_store.ttl_seconds // 3600
                        if hasattr(self, "ai_gateway_service")
                        and hasattr(self.ai_gateway_service, "result_store")
                        else 24,
                    },
                },
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
        return self.unique_log_path(self.device_log_directory(device) / filename)

    def device_log_directory(self, device: Device, root: Path | None = None) -> Path:
        device_label = "_".join(part for part in (device.id, device.name) if part)
        directory_name = self.safe_log_component(device_label, "device")
        return (root or self.log_directory).expanduser() / directory_name

    def session_device_log_directory(
        self,
        state: SessionTabState,
        root: Path | None = None,
    ) -> Path:
        device = self.get_device_by_id(state.device_id) if hasattr(self, "get_device_by_id") else None
        if device is not None:
            return self.device_log_directory(device, root)
        directory_name = self.safe_log_component(state.device_id, "device")
        return (root or self.log_directory).expanduser() / directory_name

    def session_log_path_for_state(self, state: SessionTabState) -> Path:
        device = self.get_device_by_id(state.device_id) if hasattr(self, "get_device_by_id") else None
        if device is not None:
            return self.session_log_path(device, state.title, state.kind)
        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        device_name = self.safe_log_component(state.device_id, "device")
        session_name = self.safe_log_component(state.title, "session")
        kind_name = (
            "serial"
            if state.kind == "serial"
            else ("telnet" if state.kind == "device" else ("simulated" if state.kind == "simulated" else "ssh"))
        )
        filename = f"{timestamp}_{device_name}_{kind_name}_{session_name}.log"
        return self.unique_log_path(self.session_device_log_directory(state) / filename)

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
            records = list(state.log_pending_records)
            payload, next_line_start = self.render_session_log_records(
                records,
                state.log_at_line_start,
            )
            current_size = state.log_path.stat().st_size if state.log_path.exists() else 0
            if (
                current_size > 0
                and current_size + len(payload.encode("utf-8")) > self.log_rotate_size_bytes
            ):
                previous_path = state.log_path
                state.log_path = self.session_log_path_for_state(state)
                rotation_record = (
                    "SYS",
                    f"# Log rotated automatically; previous log: {previous_path}\n",
                    True,
                )
                payload, next_line_start = self.render_session_log_records(
                    [rotation_record, *records],
                    True,
                )
            state.log_path.parent.mkdir(parents=True, exist_ok=True)
            with state.log_path.open("a", encoding="utf-8", newline="") as log_file:
                log_file.write(payload)
            state.log_at_line_start = next_line_start
            state.log_pending_records.clear()
        except OSError as exc:
            self.set_status_message(f"Log write failed: {exc}")

    def render_session_log_records(
        self,
        records: list[tuple[str, str, bool]],
        at_line_start: bool,
    ) -> tuple[str, bool]:
        output: list[str] = []
        for channel, sanitized, separate_record in records:
            if separate_record and not at_line_start:
                output.append("\n")
                at_line_start = True
            for segment in sanitized.splitlines(keepends=True):
                if channel != "SYS" and at_line_start and not segment.strip():
                    continue
                if at_line_start:
                    output.append(f"[{self.log_timestamp()}] ")
                output.append(segment)
                at_line_start = segment.endswith("\n")
        return "".join(output), at_line_start

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
        new_path = self.session_log_path_for_state(state)
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

    def change_log_rotate_size(self) -> None:
        current_mb = max(1, self.log_rotate_size_bytes // (1024 * 1024))
        selected_mb, accepted = QInputDialog.getInt(
            self,
            "设置日志分卷大小",
            "单个日志达到该大小后自动新建分卷（MB）：",
            current_mb,
            1,
            1024,
            1,
        )
        if not accepted:
            return
        self.log_rotate_size_bytes = selected_mb * 1024 * 1024
        self.schedule_desktop_state_save()
        self.set_status_message(f"日志分卷大小已设置为 {selected_mb} MB")

    def move_active_session_logs(self, new_directory: Path) -> int:
        moved_count = 0
        for state in self.session_tabs_by_id.values():
            old_path = state.log_path
            target_path = self.session_device_log_directory(state, new_directory) / old_path.name
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
