"""Session management mixin for DeviceDesktopApp."""
from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

try:
    from PySide6.QtCore import QEvent, QMimeData, Qt, QTimer
    from PySide6.QtGui import QAction, QColor, QDrag, QFont, QIcon, QKeySequence, QPixmap, QTextBlockFormat
    from PySide6.QtWidgets import (
        QApplication,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QMenu,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSplitter,
        QTabBar,
        QTabWidget,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:
    QEvent = None
    QMimeData = None
    Qt = None
    QTimer = None
    QAction = None
    QColor = None
    QDrag = None
    QFont = None
    QIcon = None
    QKeySequence = None
    QPixmap = None
    QTextBlockFormat = None
    QApplication = None
    QFrame = None
    QGroupBox = None
    QHBoxLayout = None
    QLabel = None
    QMenu = None
    QMessageBox = None
    QPushButton = None
    QScrollArea = None
    QSizePolicy = None
    QSplitter = None
    QTabBar = None
    QTabWidget = None
    QToolButton = None
    QVBoxLayout = None
    QWidget = None

from ..app_state import DeviceTabState, SessionTabState
from ..data import Device
from ..helpers import mask_password
from ..linux_session import LinuxSshSession
from ..session_protocol import SessionCallbacks, SessionUnavailableError
from ..styles import STATUS_COLORS
from ..telnet_session import HuaweiTelnetSession, TelnetSessionError
from ..widgets.terminal_canvas import TerminalCanvasWidget
from ..widgets.terminal_widget import InteractiveTerminal

SESSION_TAB_MIME = "application/x-device-tui-session-tab"


class SessionOpsMixin:
    """Mixin providing session connection, tab management, and terminal operations."""

    # ---- Session cloning ----

    def base_session_credentials(self, device: Device, kind: str) -> tuple[str, str]:
        if kind == "device":
            return device.username.strip(), device.password
        if kind == "linux":
            return self.device_ssh_username(device).strip(), self.device_ssh_password(device)
        if kind == "serial":
            return self.device_serial_username(device).strip(), self.device_serial_password(device)
        return "", ""

    def local_session_credentials(self, device: Device, kind: str) -> tuple[str, str] | None:
        if self.is_temporary_device(device):
            return None
        overrides = getattr(self, "local_credential_overrides", {})
        per_device = overrides.get(device.id, {})
        credentials = per_device.get(kind, {})
        if not isinstance(credentials, dict):
            return None
        if "username" not in credentials and "password" not in credentials:
            return None
        return str(credentials.get("username") or "").strip(), str(credentials.get("password") or "")

    def remember_session_credentials_override(
        self,
        device: Device,
        kind: str,
        username: str,
        password: str,
    ) -> None:
        if self.is_temporary_device(device):
            return
        base_username, base_password = self.base_session_credentials(device, kind)
        overrides = getattr(self, "local_credential_overrides", {})
        if username.strip() == base_username and password == base_password:
            per_device = overrides.get(device.id)
            if per_device is not None:
                per_device.pop(kind, None)
                if not per_device:
                    overrides.pop(device.id, None)
                self.schedule_desktop_state_save()
            return
        per_device = overrides.setdefault(device.id, {})
        per_device[kind] = {"username": username.strip(), "password": password}
        self.schedule_desktop_state_save()

    def linux_ssh_credential_candidates(
        self,
        device: Device,
        username: str,
        password: str,
    ) -> list[tuple[str, str]]:
        if self.is_temporary_device(device) or self.local_session_credentials(device, "linux") is not None:
            return [(username.strip(), password)]

        candidates: list[tuple[str, str]] = []
        for candidate in (
            ("root", "root"),
            ("root", "huawei"),
            (username.strip(), password),
        ):
            candidate_username, candidate_password = candidate
            if not candidate_username or not candidate_password:
                continue
            if candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def session_telnet_credentials(self, device: Device) -> tuple[str, str]:
        selected_device = self.get_selected_device()
        if selected_device is not None and selected_device.id == device.id and hasattr(self, "device_username_input"):
            return self.device_username_input.text().strip(), self.device_password_input.text()
        return self.local_session_credentials(device, "device") or self.base_session_credentials(device, "device")

    def session_ssh_credentials(self, device: Device) -> tuple[str, str]:
        selected_device = self.get_selected_device()
        if selected_device is not None and selected_device.id == device.id and hasattr(self, "linux_username_input"):
            return self.linux_username_input.text().strip(), self.linux_password_input.text()
        return self.local_session_credentials(device, "linux") or self.base_session_credentials(device, "linux")

    def session_serial_credentials(self, device: Device) -> tuple[str, str]:
        selected_device = self.get_selected_device()
        if selected_device is not None and selected_device.id == device.id and hasattr(self, "serial_password_input"):
            return self.serial_username_input.text().strip(), self.serial_password_input.text()
        return self.local_session_credentials(device, "serial") or self.base_session_credentials(device, "serial")

    def refresh_session_credentials_from_panel(self, state: SessionTabState) -> None:
        device = self.get_device_by_id(state.device_id)
        if device is None:
            return
        if state.kind == "device":
            state.username, state.password = self.session_telnet_credentials(device)
            self.remember_session_credentials_override(device, state.kind, state.username, state.password)
        elif state.kind == "linux":
            state.username, state.password = self.session_ssh_credentials(device)
            self.remember_session_credentials_override(device, state.kind, state.username, state.password)
            state.credential_candidates = self.linux_ssh_credential_candidates(device, state.username, state.password)
        elif state.kind == "serial":
            state.username, state.password = self.session_serial_credentials(device)
            self.remember_session_credentials_override(device, state.kind, state.username, state.password)

    def clone_telnet_session(self, device: Device) -> None:
        username, password = self.session_telnet_credentials(device)
        if not device.telnet_ip.strip() or not username or not password:
            self.show_warning("设备 Telnet 地址、用户名和密码不完整。")
            return
        self.remember_session_credentials_override(device, "device", username, password)
        self.ensure_session_tab(
            kind="device",
            device=device,
            host=device.telnet_ip.strip(),
            port=device.telnet_port,
            username=username,
            password=password,
        )

    def clone_ssh_session(self, device: Device) -> None:
        username, password = self.session_ssh_credentials(device)
        if not device.ssh_ip.strip() or not username or not password:
            self.show_warning("设备 SSH 地址、用户名和密码不完整。")
            return
        self.remember_session_credentials_override(device, "linux", username, password)
        self.ensure_session_tab(
            kind="linux",
            device=device,
            host=device.ssh_ip.strip(),
            port=device.ssh_port,
            username=username,
            password=password,
            credential_candidates=self.linux_ssh_credential_candidates(device, username, password),
        )

    def clone_serial_session(self, device: Device) -> None:
        if not self.is_temporary_device(device) and not self.is_my_occupied_device(device):
            self.show_warning("请先占用设备后再连接串口。")
            self.set_status_message("串口连接需要先占用当前设备。")
            return
        if not device.serial_ip.strip():
            self.show_warning("当前设备无串口 IP。")
            self.set_status_message("串口地址不可用。")
            return
        username, password = self.session_serial_credentials(device)
        if self.is_temporary_device(device):
            if not password:
                self.show_warning("临时串口需要填写串口密码。")
                return
        elif not username or not password:
            self.show_warning("设备串口地址、用户名和密码不完整。")
            return
        self.remember_session_credentials_override(device, "serial", username, password)
        self.ensure_session_tab(
            kind="serial",
            device=device,
            host=device.serial_ip.strip(),
            port=device.serial_port,
            username=username,
            password=password,
        )

    # ---- Session tab dragging ----

    @staticmethod
    def event_has_session_tab(event: Any) -> bool:
        mime = event.mimeData()
        return bool(mime is not None and mime.hasFormat(SESSION_TAB_MIME))

    def start_session_tab_drag(self, source: QWidget, tab_id: str) -> None:
        if QDrag is None or QMimeData is None:
            return
        self._drag_session_tab_id = tab_id
        mime = QMimeData()
        mime.setData(SESSION_TAB_MIME, tab_id.encode("utf-8"))
        drag = QDrag(source)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)
        self._drag_session_tab_id = ""

    def handle_session_tab_drop(self, target: Any, event: Any) -> bool:
        if not self.event_has_session_tab(event):
            return False
        tab_id = bytes(event.mimeData().data(SESSION_TAB_MIME)).decode("utf-8")
        if tab_id not in self.session_tabs_by_id:
            return False
        direction = self.split_direction_for_drop(target, event)
        self.split_session(tab_id, direction)
        event.acceptProposedAction()
        return True

    @staticmethod
    def split_direction_for_drop(target: QWidget, event: Any) -> str:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        rect = target.rect()
        distances = {
            "left": max(0, pos.x() - rect.left()),
            "right": max(0, rect.right() - pos.x()),
            "top": max(0, pos.y() - rect.top()),
            "bottom": max(0, rect.bottom() - pos.y()),
        }
        return min(distances, key=distances.get)

    def split_session_to_right(self, tab_id: str) -> None:
        self.split_session(tab_id, "right")

    def split_session(self, tab_id: str, direction: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return
        device_tab = self.device_tabs_by_id.get(state.device_id)
        if device_tab is None or device_tab.session_splitter is None:
            return
        source_tabs = self.find_session_tab_widget(device_tab, state.page)
        if source_tabs is None:
            return
        horizontal = direction in {"left", "right"}
        device_tab.session_splitter.setOrientation(Qt.Horizontal if horizontal else Qt.Vertical)
        if len(self.session_tab_widgets_for_device(device_tab)) < 2:
            target_tabs = self.create_session_tab_widget(device_tab.device_id, device_tab.session_splitter)
            if direction in {"left", "top"}:
                device_tab.session_splitter.insertWidget(0, target_tabs)
                device_tab.session_tab_widgets.insert(0, target_tabs)
            else:
                device_tab.session_splitter.addWidget(target_tabs)
                device_tab.session_tab_widgets.append(target_tabs)
            device_tab.session_splitter.setSizes([1, 1])
        else:
            target_tabs = self.session_tab_widgets_for_device(device_tab)[0 if direction in {"left", "top"} else -1]
        if source_tabs is target_tabs:
            self.set_status_message("当前会话已经在目标分屏。")
            return
        source_index = source_tabs.indexOf(state.page)
        if source_index < 0:
            return
        source_tabs.removeTab(source_index)
        target_index = target_tabs.addTab(state.page, state.title)
        self._install_session_tab_header(target_tabs, target_index, state)
        target_tabs.setCurrentIndex(target_index)
        device_tab.active_session_tab_widget = target_tabs
        self.session_tab_widget.setCurrentWidget(device_tab.page)
        self._refresh_tab_header_styles()
        self.refresh_workspace_context()
        self.update_controls()
        state.terminal.setFocus()
        direction_label = {"left": "左侧", "right": "右侧", "top": "上方", "bottom": "下方"}.get(direction, "目标")
        self.set_status_message(f"已将会话移动到{direction_label}分屏: {state.title}")

    # ---- Session context menus ----

    def show_terminal_context_menu(self, tab_id: str, terminal: Any, pos: Any) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return
        device = self.get_device_by_id(state.device_id)
        if device is None:
            return

        menu = QMenu(terminal)
        copy_selection_action = None
        if terminal.textCursor().hasSelection():
            copy_selection_action = menu.addAction("复制选中文本")
        copy_all_action = menu.addAction("复制全部")
        clear_terminal_action = menu.addAction("清屏")
        menu.addSeparator()
        actions = self._add_device_quick_actions(menu)
        self.update_device_quick_actions_for_device(actions, device)

        chosen = menu.exec(terminal.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if copy_selection_action is not None and chosen == copy_selection_action:
            terminal.copy()
            return
        if chosen == copy_all_action:
            if hasattr(terminal, "copy_all"):
                terminal.copy_all()
            else:
                terminal.selectAll()
                terminal.copy()
            return
        if chosen == clear_terminal_action:
            if hasattr(terminal, "clear_terminal"):
                terminal.clear_terminal()
            else:
                terminal.clear()
            return
        self._handle_device_quick_action(chosen, actions, device)

    def show_session_quick_context_menu(self, tab_id: str, widget: QWidget, pos: Any) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return
        device = self.get_device_by_id(state.device_id)
        if device is None:
            return
        menu = QMenu(widget)
        actions = self._add_device_quick_actions(menu)
        self.update_device_quick_actions_for_device(actions, device)
        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen is None:
            return
        self._handle_device_quick_action(chosen, actions, device)

    def _handle_device_quick_action(
        self,
        chosen: Any,
        actions: dict[str, Any],
        device: Device,
    ) -> None:
        if chosen == actions["locate"]:
            self.locate_device_in_list(device.id)
            return
        if chosen == actions["clone_telnet"]:
            self.clone_telnet_session(device)
            return
        if chosen == actions["clone_ssh"]:
            self.clone_ssh_session(device)
            return
        if chosen == actions["clone_serial"]:
            self.clone_serial_session(device)
            return
        if chosen == actions["copy_telnet_ip"]:
            self.copy_device_field(device, "telnet_ip")
            return
        if chosen == actions["copy_ssh_ip"]:
            self.copy_device_field(device, "ssh_ip")
            return
        if chosen == actions["copy_serial_ip"]:
            self.copy_device_field(device, "serial_ip")
            return
        if chosen == actions["copy_connection"]:
            self.copy_text_to_clipboard(
                self.device_connection_copy_text(device),
                f"已复制连接信息: {device.name}",
            )

        if chosen == actions["power_off"]:
            self.power_off_device(device)

    # ---- Session jump/refresh ----

    def refresh_workspace_context(self) -> None:
        self.refresh_session_jump_combo()

    def refresh_session_jump_combo(self) -> None:
        if not hasattr(self, "session_jump_combo"):
            return
        current_tab_id = self.current_session_key()
        combo = self.session_jump_combo
        combo.blockSignals(True)
        combo.clear()
        states = self.ordered_session_states()
        if not states:
            combo.addItem("无打开会话", "")
            combo.setCurrentIndex(0)
            combo.setEnabled(False)
            combo.blockSignals(False)
            return
        combo.setEnabled(True)
        current_index = 0
        for index, state in enumerate(states):
            combo.addItem(self.session_jump_text(state), state.tab_id)
            if state.tab_id == current_tab_id:
                current_index = index
        combo.setCurrentIndex(current_index)
        combo.blockSignals(False)

    # ---- Session tab helpers ----

    def ordered_session_states(self) -> list[SessionTabState]:
        states: list[SessionTabState] = []
        for device_index in range(self.session_tab_widget.count()):
            device_tab = self._device_tab_for_page(self.session_tab_widget.widget(device_index))
            if device_tab is None:
                continue
            for tabs in self.session_tab_widgets_for_device(device_tab):
                for session_index in range(tabs.count()):
                    state = self._session_state_for_page(tabs.widget(session_index))
                    if state is not None:
                        states.append(state)
        return states

    def session_jump_text(self, state: SessionTabState) -> str:
        device = self.get_device_by_id(state.device_id)
        device_name = self.temporary_device_display_name(device) if device is not None else state.device_id
        kind = self.session_kind_label(state.kind)
        return f"{device_name} · {self.session_display_title(state, kind)} · {self.session_status_label(state.status_text)}"

    @staticmethod
    def session_kind_label(kind: str) -> str:
        if kind == "device":
            return "Telnet"
        if kind == "serial":
            return "串口"
        return "SSH"

    @staticmethod
    def session_display_title(state: SessionTabState, kind: str) -> str:
        title = state.title.strip()
        if title.lower().startswith(kind.lower()):
            return title
        return f"{kind} {title}" if title else kind

    @staticmethod
    def session_status_label(status: str) -> str:
        normalized = status.strip().lower()
        if normalized == "connected":
            return "已连接"
        if normalized == "connecting":
            return "连接中"
        if normalized == "disconnected":
            return "未连接"
        return status or "未知"

    def handle_session_jump_activated(self, index: int) -> None:
        tab_id = str(self.session_jump_combo.itemData(index) or "")
        if tab_id:
            self.jump_to_session(tab_id)

    def jump_to_session(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            self.refresh_session_jump_combo()
            return
        device_tab = self.device_tabs_by_id.get(state.device_id)
        if device_tab is None:
            self.refresh_session_jump_combo()
            return
        device_index = self.session_tab_widget.indexOf(device_tab.page)
        session_tabs = self.find_session_tab_widget(device_tab, state.page)
        session_index = session_tabs.indexOf(state.page) if session_tabs is not None else -1
        if device_index >= 0:
            self.session_tab_widget.setCurrentIndex(device_index)
        if session_tabs is not None and session_index >= 0:
            device_tab.active_session_tab_widget = session_tabs
            session_tabs.setCurrentIndex(session_index)
        device = self.get_device_by_id(state.device_id)
        if device is not None:
            self.activate_device(device.id)
        state.terminal.setFocus()
        self.refresh_session_jump_combo()
        self.set_status_message(f"已跳转到会话: {self.session_jump_text(state)}")

    def handle_session_tab_changed(self, _index: int) -> None:
        self.refresh_workspace_context()
        self._refresh_tab_header_styles()
        self.update_controls()
        state = self.current_session_state()
        if state is not None:
            state.terminal.setFocus()

    def handle_split_session_tab_changed(self, device_id: str, tabs: QTabWidget) -> None:
        self.mark_active_session_tab_widget(device_id, tabs)
        self.handle_session_tab_changed(tabs.currentIndex())

    def handle_split_session_tab_clicked(self, device_id: str, tabs: QTabWidget, index: int) -> None:
        if index < 0:
            return
        self.mark_active_session_tab_widget(device_id, tabs)
        if tabs.currentIndex() != index:
            tabs.setCurrentIndex(index)
        self.refresh_workspace_context()
        self._refresh_tab_header_styles()
        self.update_controls()
        state = self._session_state_for_page(tabs.widget(index))
        if state is not None:
            state.terminal.setFocus()

    def update_center_stage_state(self) -> None:
        if not hasattr(self, "center_stage_stack"):
            return
        self.center_stage_stack.setCurrentIndex(1 if self.session_tab_widget.count() > 0 else 0)

    def current_session_key(self) -> str | None:
        state = self.current_session_state()
        return state.tab_id if state else None

    def current_device_tab_state(self) -> DeviceTabState | None:
        current_page = self.session_tab_widget.currentWidget()
        if current_page is None:
            return None
        return next((state for state in self.device_tabs_by_id.values() if state.page is current_page), None)

    def _device_tab_for_page(self, page: QWidget | None) -> DeviceTabState | None:
        if page is None:
            return None
        return next((state for state in self.device_tabs_by_id.values() if state.page is page), None)

    def _session_state_for_page(self, page: QWidget | None) -> SessionTabState | None:
        if page is None:
            return None
        return next((state for state in self.session_tabs_by_id.values() if state.page is page), None)

    def _session_states_for_device(self, device_id: str) -> list[SessionTabState]:
        return [state for state in self.session_tabs_by_id.values() if state.device_id == device_id]

    def session_tab_widgets_for_device(self, device_tab: DeviceTabState) -> list[QTabWidget]:
        return device_tab.session_tab_widgets or [device_tab.session_tab_widget]

    def active_session_tabs_for_device(self, device_tab: DeviceTabState) -> QTabWidget:
        tabs = device_tab.active_session_tab_widget or device_tab.session_tab_widget
        if tabs in self.session_tab_widgets_for_device(device_tab):
            return tabs
        return device_tab.session_tab_widget

    def find_session_tab_widget(self, device_tab: DeviceTabState, page: QWidget) -> QTabWidget | None:
        for tabs in self.session_tab_widgets_for_device(device_tab):
            if tabs.indexOf(page) >= 0:
                return tabs
        return None

    def mark_active_session_tab_widget(self, device_id: str, tabs: QTabWidget) -> None:
        device_tab = self.device_tabs_by_id.get(device_id)
        if device_tab is not None:
            device_tab.active_session_tab_widget = tabs

    # ---- Session opening ----

    def open_device_session(self, device: Device | None = None) -> None:
        device = device if isinstance(device, Device) else None
        device = device or self.get_selected_device()
        if device is None:
            self.show_warning("请先选择设备。")
            return

        username, password = self.session_telnet_credentials(device)
        if not username or not password:
            self.show_warning("设备终端需要用户名和密码。")
            return

        self.remember_session_credentials_override(device, "device", username, password)
        self.ensure_session_tab(
            kind="device",
            device=device,
            host=device.telnet_ip.strip(),
            port=device.telnet_port,
            username=username,
            password=password,
        )

    def open_linux_session(self, device: Device | None = None) -> None:
        device = device if isinstance(device, Device) else None
        device = device or self.get_quick_action_device()
        if device is None:
            self.show_warning("请先选择设备。")
            return

        host = device.ssh_ip.strip()
        username, password = self.session_ssh_credentials(device)
        port = device.ssh_port
        if not host or not username or not password:
            self.show_warning("Linux 后台需要设备 SSH 地址、用户名和密码。")
            return

        self.remember_session_credentials_override(device, "linux", username, password)
        self.ensure_session_tab(
            kind="linux",
            device=device,
            host=host,
            port=port,
            username=username,
            password=password,
            credential_candidates=self.linux_ssh_credential_candidates(device, username, password),
        )

    def open_serial_session(self, device: Device | None = None) -> None:
        device = device if isinstance(device, Device) else None
        device = device or self.get_quick_action_device()
        if device is None:
            self.show_warning("请先选择设备。")
            return
        self.clone_serial_session(device)

    def open_selected_device_session(self) -> None:
        device = self.get_selected_device()
        if device is None:
            self.show_warning("请先选择设备。")
            return
        self.open_device_session(device)

    def open_selected_linux_session(self) -> None:
        device = self.get_selected_device()
        if device is None:
            self.show_warning("请先选择设备。")
            return
        self.open_linux_session(device)

    def open_selected_serial_session(self) -> None:
        device = self.get_selected_device()
        if device is None:
            self.show_warning("请先选择设备。")
            return
        self.open_serial_session(device)

    # ---- Session tab management ----

    def ensure_session_tab(
        self,
        kind: str,
        device: Device,
        host: str,
        port: int,
        username: str,
        password: str,
        credential_candidates: list[tuple[str, str]] | None = None,
    ) -> None:
        if not host:
            self.show_warning("目标地址不能为空。")
            return

        device_tab = self.ensure_device_tab(device)
        title = self.next_session_title(device_tab, kind)
        tab_id = self.next_session_tab_id(device.id, kind)
        state = self._create_session_tab(
            tab_id=tab_id,
            kind=kind,
            device=device,
            title=title,
            host=host,
            port=port,
            username=username,
            password=password,
            credential_candidates=credential_candidates,
        )
        self.session_tabs_by_id[tab_id] = state
        target_tabs = self.active_session_tabs_for_device(device_tab)
        index = target_tabs.addTab(state.page, title)
        self._install_session_tab_header(target_tabs, index, state)
        self.session_tab_widget.setCurrentWidget(device_tab.page)
        target_tabs.setCurrentIndex(index)
        device_tab.active_session_tab_widget = target_tabs
        self.set_status_message(f"正在打开会话: {title}")
        self.refresh_workspace_context()
        self.update_center_stage_state()
        self.update_controls()
        self.connect_session_tab(tab_id)

    def ensure_device_tab(self, device: Device) -> DeviceTabState:
        display_name = self.temporary_device_display_name(device)
        existing = self.device_tabs_by_id.get(device.id)
        if existing is not None:
            existing.title = display_name
            if existing.tab_title_label is not None:
                existing.tab_title_label.setText(display_name)
            index = self.session_tab_widget.indexOf(existing.page)
            if index >= 0:
                self.session_tab_widget.setCurrentIndex(index)
                return existing
            self.device_tabs_by_id.pop(device.id, None)

        page = QWidget()
        page.setObjectName("deviceSessionPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        session_splitter = QSplitter(Qt.Horizontal, page)
        session_splitter.setObjectName("sessionSplitPane")
        session_splitter.setAcceptDrops(True)
        session_splitter.setProperty("sessionDropDeviceId", device.id)
        session_splitter.installEventFilter(self)
        page.setAcceptDrops(True)
        page.setProperty("sessionDropDeviceId", device.id)
        page.installEventFilter(self)
        layout.addWidget(session_splitter, 1)
        child_tabs = self.create_session_tab_widget(device.id, session_splitter)
        session_splitter.addWidget(child_tabs)

        state = DeviceTabState(
            device_id=device.id,
            title=display_name,
            page=page,
            session_tab_widget=child_tabs,
            session_splitter=session_splitter,
            session_tab_widgets=[child_tabs],
            active_session_tab_widget=child_tabs,
        )
        self.device_tabs_by_id[device.id] = state
        index = self.session_tab_widget.addTab(page, display_name)
        self._install_device_tab_header(index, state)
        self.session_tab_widget.setCurrentIndex(index)
        self.update_center_stage_state()
        return state

    def create_session_tab_widget(self, device_id: str, parent: QWidget) -> QTabWidget:
        child_tabs = QTabWidget(parent)
        child_tabs.setObjectName("deviceSessionTabs")
        child_tabs.setAcceptDrops(True)
        child_tabs.setProperty("sessionDropDeviceId", device_id)
        child_tabs.installEventFilter(self)
        child_tabs.setDocumentMode(True)
        child_tabs.setTabsClosable(False)
        child_tabs.setMovable(True)
        child_tabs.tabBar().setExpanding(False)
        child_tabs.tabBar().setUsesScrollButtons(True)
        child_tabs.currentChanged.connect(
            lambda _index, device_id=device_id, tabs=child_tabs: self.handle_split_session_tab_changed(
                device_id,
                tabs,
            )
        )
        child_tabs.tabBarClicked.connect(
            lambda index, device_id=device_id, tabs=child_tabs: self.handle_split_session_tab_clicked(
                device_id,
                tabs,
                index,
            )
        )
        child_tabs.tabCloseRequested.connect(
            lambda index, device_id=device_id, tabs=child_tabs: self.close_child_session_tab_at_index(
                device_id,
                index,
                tabs,
            )
        )
        return child_tabs

    def next_session_title(self, device_tab: DeviceTabState, kind: str) -> str:
        if kind == "device":
            number = device_tab.next_telnet_index
            device_tab.next_telnet_index += 1
            return f"Telnet #{number}"
        if kind == "serial":
            number = device_tab.next_serial_index
            device_tab.next_serial_index += 1
            return f"串口 #{number}"
        number = device_tab.next_ssh_index
        device_tab.next_ssh_index += 1
        return f"SSH #{number}"

    def next_session_tab_id(self, device_id: str, kind: str) -> str:
        tab_id = f"{device_id}:{kind}:{self.next_session_sequence}"
        self.next_session_sequence += 1
        return tab_id

    def _create_session_tab(
        self,
        tab_id: str,
        kind: str,
        device: Device,
        title: str,
        host: str,
        port: int,
        username: str,
        password: str,
        credential_candidates: list[tuple[str, str]] | None = None,
    ) -> SessionTabState:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        terminal = (
            InteractiveTerminal()
            if os.getenv("DEVICE_TUI_TERMINAL_WIDGET", "").lower() == "legacy"
            else TerminalCanvasWidget()
        )
        terminal.setContextMenuPolicy(Qt.CustomContextMenu)
        terminal.customContextMenuRequested.connect(
            lambda pos, tab_id=tab_id, terminal=terminal: self.show_terminal_context_menu(tab_id, terminal, pos)
        )
        layout.addWidget(terminal, 1)

        if kind in {"device", "serial"}:
            session = HuaweiTelnetSession(
                on_output=lambda message, tab_id=tab_id: self.dispatch_ui(self.append_session_output, tab_id, message),
                on_status=lambda status, tab_id=tab_id: self.dispatch_ui(self.set_session_status, tab_id, status),
            )
        else:
            session = LinuxSshSession(
                SessionCallbacks(
                    on_output=lambda message, tab_id=tab_id: self.dispatch_ui(self.append_session_output, tab_id, message),
                    on_status=lambda status, tab_id=tab_id: self.dispatch_ui(self.set_session_status, tab_id, status),
                )
            )

        state = SessionTabState(
            tab_id=tab_id,
            kind=kind,
            device_id=device.id,
            title=title,
            host=host,
            port=port,
            username=username,
            password=password,
            credential_candidates=credential_candidates or [],
            page=page,
            terminal=terminal,
            session=session,
            log_path=self.session_log_path(device, title, kind),
            connecting=True,
            status_text="Connecting",
        )

        terminal.set_raw_sender(lambda text, tab_id=tab_id: self.send_session_text(tab_id, text))
        terminal.set_enter_reconnect_handler(lambda tab_id=tab_id: self.reconnect_session_from_enter(tab_id))
        terminal.set_terminal_resize_handler(
            lambda columns, lines, tab_id=tab_id: self.resize_session_pty(tab_id, columns, lines)
        )
        kind_label = self.session_kind_label(kind)
        self.write_session_log_line(
            state,
            "SYS",
            f"Session created: {kind_label} {host}:{port} user={username} device={device.name} ({device.id})",
        )
        return state

    # ---- Tab header style ----

    def _install_device_tab_header(self, index: int, state: DeviceTabState) -> None:
        self._install_tab_header(
            self.session_tab_widget,
            index,
            state,
            close_callback=lambda page=state.page: self.close_device_tab_for_page(page),
            close_tooltip="关闭设备会话",
            min_label_width=112,
            header_height=23,
            dot_size=8,
            close_slot_size=(21, 19),
            close_button_size=15,
        )
        self._install_device_context_menu_on_tab_header(state.device_id, state)

    def _install_session_tab_header(self, tab_widget: QTabWidget, index: int, state: SessionTabState) -> None:
        self._install_tab_header(
            tab_widget,
            index,
            state,
            close_callback=lambda page=state.page: self.close_session_tab_for_page(page),
            close_tooltip="关闭会话",
            min_label_width=44,
            header_height=20,
            dot_size=6,
            close_slot_size=(17, 16),
            close_button_size=13,
        )
        self._install_device_context_menu_on_tab_header(state.device_id, state)

    def _install_device_context_menu_on_tab_header(
        self,
        device_id: str,
        state: DeviceTabState | SessionTabState,
    ) -> None:
        for widget in (state.tab_header, state.tab_title_label, state.tab_status_dot):
            if widget is None:
                continue
            widget.setContextMenuPolicy(Qt.CustomContextMenu)
            if isinstance(state, SessionTabState):
                widget.setProperty("sessionDragTabId", state.tab_id)
                widget.setToolTip("拖动到终端区边缘分屏")
                widget.installEventFilter(self)
                widget.customContextMenuRequested.connect(
                    lambda pos, widget=widget, tab_id=state.tab_id: self.show_session_quick_context_menu(
                        tab_id,
                        widget,
                        pos,
                    )
                )
            else:
                widget.customContextMenuRequested.connect(
                    lambda pos, widget=widget, device_id=device_id: self.show_device_quick_context_menu(
                        device_id,
                        widget,
                        pos,
                    )
                )

    def _install_tab_header(
        self,
        tab_widget: QTabWidget,
        index: int,
        state: DeviceTabState | SessionTabState,
        close_callback: Callable[[], None],
        close_tooltip: str,
        min_label_width: int,
        header_height: int,
        dot_size: int,
        close_slot_size: tuple[int, int],
        close_button_size: int,
    ) -> None:
        if QToolButton is None:
            return
        header = QWidget(tab_widget)
        header.setObjectName("tabHeader")
        header.setFixedHeight(header_height)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(7, 2, 0, 2)
        layout.setSpacing(5)

        dot = QLabel(header)
        dot.setObjectName("tabStatusDot")
        dot.setFixedSize(dot_size, dot_size)
        layout.addWidget(dot, 0, Qt.AlignVCenter)

        label = QLabel(state.title, header)
        label.setObjectName("tabHeaderLabel")
        label.setMinimumWidth(min_label_width)
        layout.addWidget(label, 1)

        close_slot = QWidget(tab_widget.tabBar())
        close_slot.setObjectName("tabHeader")
        close_slot.setFixedSize(*close_slot_size)
        close_layout = QHBoxLayout(close_slot)
        close_layout.setContentsMargins(0, 1, 4, 1)
        close_layout.setSpacing(0)

        button = QToolButton(close_slot)
        button.setObjectName("tabCloseButton")
        button.setText("×")
        button.setAutoRaise(True)
        button.setFixedSize(close_button_size, close_button_size)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setFocusPolicy(Qt.NoFocus)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(close_tooltip)
        button.clicked.connect(lambda _checked=False, callback=close_callback: callback())
        close_layout.addWidget(button)

        state.tab_title_label = label
        state.tab_header = header
        state.tab_status_dot = dot
        state.tab_close_button = button
        tab_widget.setTabText(index, "")
        tab_widget.tabBar().setTabButton(index, QTabBar.LeftSide, header)
        tab_widget.tabBar().setTabButton(index, QTabBar.RightSide, close_slot)
        self._refresh_tab_header_styles()

    def _tab_connection_state(self, state: SessionTabState) -> str:
        if state.connecting:
            return "connecting"
        if state.session.is_connected:
            return "connected"
        if state.status_text.lower() == "disconnected":
            return "idle"
        return "error"

    def refresh_session_header(self, state: SessionTabState) -> None:
        del state

    def _device_connection_state(self, state: DeviceTabState) -> str:
        child_states = self._session_states_for_device(state.device_id)
        if any(child.connecting for child in child_states):
            return "connecting"
        if any(child.session.is_connected for child in child_states):
            return "connected"
        if any(self._tab_connection_state(child) == "error" for child in child_states):
            return "error"
        return "idle"

    def _apply_tab_header_style(
        self,
        state: DeviceTabState | SessionTabState,
        selected: bool,
        connection_state: str,
    ) -> None:
        if state.tab_header is not None:
            state.tab_header.setProperty("selected", selected)
            state.tab_header.style().unpolish(state.tab_header)
            state.tab_header.style().polish(state.tab_header)
            state.tab_header.update()
        if state.tab_title_label is not None:
            state.tab_title_label.setProperty("selected", selected)
            state.tab_title_label.style().unpolish(state.tab_title_label)
            state.tab_title_label.style().polish(state.tab_title_label)
            state.tab_title_label.update()
        if state.tab_status_dot is not None:
            state.tab_status_dot.setProperty("connectionState", connection_state)
            state.tab_status_dot.style().unpolish(state.tab_status_dot)
            state.tab_status_dot.style().polish(state.tab_status_dot)
            state.tab_status_dot.update()
        if state.tab_close_button is not None:
            state.tab_close_button.setProperty("selected", selected)
            state.tab_close_button.style().unpolish(state.tab_close_button)
            state.tab_close_button.style().polish(state.tab_close_button)
            state.tab_close_button.update()

    def _refresh_tab_header_styles(self) -> None:
        current_device = self.current_device_tab_state()
        current_device_index = self.session_tab_widget.currentIndex()
        for state in self.device_tabs_by_id.values():
            index = self.session_tab_widget.indexOf(state.page)
            selected = index == current_device_index
            self._apply_tab_header_style(state, selected, self._device_connection_state(state))

        for state in self.session_tabs_by_id.values():
            self.refresh_session_header(state)
            device_tab = self.device_tabs_by_id.get(state.device_id)
            if device_tab is None:
                continue
            tabs = self.find_session_tab_widget(device_tab, state.page)
            index = tabs.indexOf(state.page) if tabs is not None else -1
            selected = (
                device_tab is current_device
                and tabs is not None
                and tabs is device_tab.active_session_tab_widget
                and index == tabs.currentIndex()
            )
            self._apply_tab_header_style(state, selected, self._tab_connection_state(state))

    # ---- Session connect/disconnect ----

    def close_session_tab_for_page(self, page: QWidget) -> None:
        state = self._session_state_for_page(page)
        if state is None:
            return
        device_tab = self.device_tabs_by_id.get(state.device_id)
        if device_tab is None:
            return
        tabs = self.find_session_tab_widget(device_tab, page)
        if tabs is not None:
            index = tabs.indexOf(page)
            if index >= 0:
                self.close_child_session_tab_at_index(device_tab.device_id, index, tabs)

    def connect_session_tab(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return

        state.connecting = True
        self.set_session_status(tab_id, "Connecting")
        self.write_session_log_line(state, "SYS", f"Connecting to {state.host}:{state.port}")
        self.update_controls()

        async def connect() -> tuple[str, str] | None:
            if isinstance(state.session, LinuxSshSession):
                candidates = state.credential_candidates or [(state.username, state.password)]
                last_error: Exception | None = None
                for index, (username, password) in enumerate(candidates, start=1):
                    try:
                        if len(candidates) > 1:
                            state.session.callbacks.on_output(
                                f"\n=== Trying SSH credential {index}/{len(candidates)}: {username} ===\n"
                            )
                        await state.session.connect(
                            state.host,
                            state.port,
                            username,
                            password,
                            term_size=state.terminal.terminal_dimensions(),
                        )
                        return username, password
                    except SessionUnavailableError as exc:
                        last_error = exc
                        state.session.callbacks.on_output(f"=== SSH credential failed: {username} ===\n")
                if last_error is not None:
                    raise last_error
                return None
            await state.session.connect(
                state.host,
                state.port,
                state.username,
                state.password,
            )
            return None

        def success(result: object) -> None:
            current_state = self.session_tabs_by_id.get(tab_id)
            if current_state is None:
                return
            if isinstance(result, tuple) and len(result) == 2:
                current_state.username, current_state.password = result
                device = self.get_device_by_id(current_state.device_id)
                if device is not None:
                    self.remember_session_credentials_override(
                        device,
                        current_state.kind,
                        current_state.username,
                        current_state.password,
                    )
            current_state.connecting = False
            self.set_session_status(tab_id, "Connected")
            self.write_session_log_line(current_state, "SYS", "Connected")
            self.set_status_message(f"会话已连接: {current_state.title}")
            current_state.terminal.setFocus()

        def failure(exc: Exception) -> None:
            current_state = self.session_tabs_by_id.get(tab_id)
            if current_state is None:
                return
            current_state.connecting = False
            self.set_session_status(tab_id, "Disconnected")
            self.write_session_log_line(current_state, "SYS", f"Connection failed: {exc}")
            if isinstance(exc, (OSError, asyncio.TimeoutError, TelnetSessionError, SessionUnavailableError)):
                self.append_session_output(tab_id, f"\n连接失败: {exc}\n")
                self.append_reconnect_hint(tab_id)
                if self.is_connection_timeout(exc):
                    self.set_status_message(f"连接超时: {current_state.title}")
                    self.update_controls()
                    return
                self.show_error(str(exc))
                self.set_status_message(f"连接失败: {exc}")
                self.update_controls()
                return
            self.handle_background_error(exc)

        self.run_coro(connect(), on_success=success, on_error=failure)

    def resize_session_pty(self, tab_id: str, columns: int, lines: int) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None or not isinstance(state.session, LinuxSshSession):
            return

        async def resize() -> None:
            await state.session.resize_terminal(columns, lines)

        self.run_coro(resize(), on_error=lambda _exc: None)

    def set_session_status(self, tab_id: str, status: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return
        previous_status = state.status_text
        state.status_text = status
        if status != "Connecting":
            state.connecting = False
        if (
            status.lower() == "disconnected"
            and previous_status.lower() not in {"connecting", "disconnected"}
            and not state.connecting
        ):
            self.append_reconnect_hint(tab_id)
        device_tab = self.device_tabs_by_id.get(state.device_id)
        if device_tab is not None:
            tabs = self.find_session_tab_widget(device_tab, state.page)
            if tabs is not None:
                index = tabs.indexOf(state.page)
                if index >= 0:
                    tabs.setTabText(index, "")
        if state.tab_title_label is not None:
            state.tab_title_label.setText(state.title)
        self._refresh_tab_header_styles()
        self.refresh_workspace_context()
        self.update_center_stage_state()
        self.update_controls()

    def append_reconnect_hint(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return
        state.terminal.append_output("\n=== 会话已断开，按 Enter 重连 ===\n")

    def append_session_output(self, tab_id: str, message: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None or not message:
            return

        state.terminal.append_output(message)
        self.write_session_log(state, "OUT", message)

    def send_session_text(self, tab_id: str, text: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return

        if text == "\x7f":
            text = "\x08" if state.kind in {"device", "serial"} else "\x7f"
        self.log_session_input(state, text)
        state.pending_input_text += text
        if state.input_flush_scheduled:
            return
        state.input_flush_scheduled = True
        if QTimer is None:
            self.flush_session_input(tab_id)
            return
        QTimer.singleShot(0, lambda tab_id=tab_id: self.flush_session_input(tab_id))

    def flush_session_input(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return
        text = state.pending_input_text
        state.pending_input_text = ""
        state.input_flush_scheduled = False
        if not text:
            return

        async def send() -> None:
            await state.session.send_text(text)

        def failure(exc: Exception) -> None:
            current_state = self.session_tabs_by_id.get(tab_id)
            if current_state is not None:
                self.write_session_log_line(current_state, "SYS", f"Send failed: {exc}")
            if isinstance(exc, (TelnetSessionError, SessionUnavailableError)):
                self.show_error(str(exc))
                return
            self.handle_background_error(exc)

        self.run_coro(send(), on_error=failure)

    def reconnect_session_from_enter(self, tab_id: str) -> bool:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return False
        if state.connecting:
            self.set_status_message(f"Session is connecting: {state.title}")
            return True
        if state.session.is_connected:
            return False
        self.refresh_session_credentials_from_panel(state)
        self.reconnect_session_tab(tab_id)
        return True

    def disconnect_session_tab(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return

        async def disconnect() -> None:
            await state.session.disconnect("Disconnected.")

        def success(_result: object) -> None:
            self.set_session_status(tab_id, "Disconnected")
            self.write_session_log_line(state, "SYS", "Disconnected")
            self.set_status_message(f"会话已断开: {state.title}")

        self.run_coro(disconnect(), on_success=success)

    def reconnect_session_tab(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None or state.connecting:
            return

        state.connecting = True
        self.set_session_status(tab_id, "Connecting")
        self.write_session_log_line(state, "SYS", f"Reconnecting to {state.host}:{state.port}")
        self.set_status_message(f"正在重连会话: {state.title}")

        async def reconnect() -> tuple[str, str] | None:
            await state.session.disconnect("")
            if isinstance(state.session, LinuxSshSession):
                candidates = state.credential_candidates or [(state.username, state.password)]
                last_error: Exception | None = None
                for index, (username, password) in enumerate(candidates, start=1):
                    try:
                        if len(candidates) > 1:
                            state.session.callbacks.on_output(
                                f"\n=== Trying SSH credential {index}/{len(candidates)}: {username} ===\n"
                            )
                        await state.session.connect(
                            state.host,
                            state.port,
                            username,
                            password,
                            term_size=state.terminal.terminal_dimensions(),
                        )
                        return username, password
                    except SessionUnavailableError as exc:
                        last_error = exc
                        state.session.callbacks.on_output(f"=== SSH credential failed: {username} ===\n")
                if last_error is not None:
                    raise last_error
                return None
            await state.session.connect(
                state.host,
                state.port,
                state.username,
                state.password,
            )
            return None

        def success(result: object) -> None:
            current_state = self.session_tabs_by_id.get(tab_id)
            if current_state is None:
                return
            if isinstance(result, tuple) and len(result) == 2:
                current_state.username, current_state.password = result
                device = self.get_device_by_id(current_state.device_id)
                if device is not None:
                    self.remember_session_credentials_override(
                        device,
                        current_state.kind,
                        current_state.username,
                        current_state.password,
                    )
            current_state.connecting = False
            self.set_session_status(tab_id, "Connected")
            self.write_session_log_line(current_state, "SYS", "Reconnected")
            current_state.terminal.setFocus()
            self.set_status_message(f"会话已重连: {current_state.title}")

        def failure(exc: Exception) -> None:
            current_state = self.session_tabs_by_id.get(tab_id)
            if current_state is not None:
                current_state.connecting = False
                self.set_session_status(tab_id, "Disconnected")
                self.write_session_log_line(current_state, "SYS", f"Reconnect failed: {exc}")
            if isinstance(exc, (OSError, asyncio.TimeoutError, TelnetSessionError, SessionUnavailableError)):
                self.append_session_output(tab_id, f"\n重连失败: {exc}\n")
                self.append_reconnect_hint(tab_id)
                if self.is_connection_timeout(exc):
                    title = current_state.title if current_state is not None else tab_id
                    self.set_status_message(f"重连超时: {title}")
                    return
                self.show_error(str(exc))
                self.set_status_message(f"重连失败: {exc}")
                return
            self.handle_background_error(exc)

        self.run_coro(reconnect(), on_success=success, on_error=failure)

    def is_connection_timeout(self, exc: Exception) -> bool:
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return True
        if getattr(exc, "winerror", None) in {121, 10060}:
            return True
        if getattr(exc, "errno", None) in {110, 121, 10060}:
            return True
        message = str(exc).lower()
        return "timed out" in message or "timeout" in message or "超时" in message

    # ---- Session closing ----

    def close_child_session_tab_at_index(
        self,
        device_id: str,
        index: int,
        tab_widget: QTabWidget | None = None,
    ) -> None:
        device_tab = self.device_tabs_by_id.get(device_id)
        if device_tab is None:
            return
        tabs = tab_widget or self.active_session_tabs_for_device(device_tab)
        page = tabs.widget(index)
        state = self._session_state_for_page(page)
        if state is None:
            if index >= 0:
                tabs.removeTab(index)
            self.normalize_session_splitters(device_tab)
            self._remove_device_tab_if_empty(device_tab)
            return

        async def disconnect() -> None:
            await state.session.disconnect("")

        def finalize_close(_result: object | None = None) -> None:
            current_device_tab = self.device_tabs_by_id.get(device_id)
            if current_device_tab is not None:
                close_tabs = self.find_session_tab_widget(current_device_tab, state.page)
                if close_tabs is not None:
                    close_index = close_tabs.indexOf(state.page)
                    if close_index >= 0:
                        close_tabs.removeTab(close_index)
            self.write_session_log_line(state, "SYS", "Session closed")
            self.session_tabs_by_id.pop(state.tab_id, None)
            state.page.deleteLater()
            if current_device_tab is not None:
                self.normalize_session_splitters(current_device_tab)
                self._remove_device_tab_if_empty(current_device_tab)
            self.refresh_workspace_context()
            self._refresh_tab_header_styles()
            self.update_controls()

        self.run_coro(disconnect(), on_success=finalize_close, on_error=lambda _exc: finalize_close())

    def close_session_tab_at_index(self, index: int) -> None:
        device_tab = self.current_device_tab_state()
        if device_tab is None:
            return
        self.close_child_session_tab_at_index(
            device_tab.device_id,
            index,
            self.active_session_tabs_for_device(device_tab),
        )

    def close_device_tab_for_page(self, page: QWidget) -> None:
        state = self._device_tab_for_page(page)
        if state is not None:
            self.close_device_tab_state(state)

    def close_device_tab_at_index(self, index: int) -> None:
        state = self._device_tab_for_page(self.session_tab_widget.widget(index))
        if state is None:
            if index >= 0:
                self.session_tab_widget.removeTab(index)
            return
        self.close_device_tab_state(state)

    def close_device_tab_state(self, device_tab: DeviceTabState) -> None:
        child_states = list(self._session_states_for_device(device_tab.device_id))

        async def disconnect_all() -> None:
            await asyncio.gather(
                *[state.session.disconnect("") for state in child_states],
                return_exceptions=True,
            )

        def finalize_close(_result: object | None = None) -> None:
            current_device_tab = self.device_tabs_by_id.get(device_tab.device_id)
            if current_device_tab is None:
                return
            for state in child_states:
                self.write_session_log_line(state, "SYS", "Session closed")
                self.session_tabs_by_id.pop(state.tab_id, None)
                state.page.deleteLater()
            self._remove_device_tab(current_device_tab)
            self.refresh_workspace_context()
            self._refresh_tab_header_styles()
            self.update_controls()

        if not child_states:
            finalize_close()
            return
        self.run_coro(disconnect_all(), on_success=finalize_close, on_error=lambda _exc: finalize_close())

    def _remove_device_tab_if_empty(self, device_tab: DeviceTabState) -> None:
        if any(tabs.count() > 0 for tabs in self.session_tab_widgets_for_device(device_tab)):
            return
        self._remove_device_tab(device_tab)

    def normalize_session_splitters(self, device_tab: DeviceTabState) -> None:
        splitter = device_tab.session_splitter
        if splitter is None:
            return
        primary_tabs = device_tab.session_tab_widget
        all_tabs = self.session_tab_widgets_for_device(device_tab)
        nonempty_tabs = [tabs for tabs in all_tabs if tabs.count() > 0]

        if not nonempty_tabs:
            for tabs in list(all_tabs):
                if tabs is not primary_tabs:
                    device_tab.session_tab_widgets.remove(tabs)
                    tabs.setParent(None)
                    tabs.deleteLater()
            device_tab.active_session_tab_widget = primary_tabs
            return

        if len(nonempty_tabs) == 1:
            survivor = nonempty_tabs[0]
            if survivor is not primary_tabs:
                while survivor.count() > 0:
                    page = survivor.widget(0)
                    state = self._session_state_for_page(page)
                    survivor.removeTab(0)
                    title = state.title if state is not None else ""
                    index = primary_tabs.addTab(page, title)
                    if state is not None:
                        self._install_session_tab_header(primary_tabs, index, state)
                survivor.setParent(None)
                survivor.deleteLater()
            for tabs in list(device_tab.session_tab_widgets):
                if tabs is not primary_tabs and tabs.count() == 0:
                    device_tab.session_tab_widgets.remove(tabs)
                    tabs.setParent(None)
                    tabs.deleteLater()
            device_tab.session_tab_widgets = [primary_tabs]
            device_tab.active_session_tab_widget = primary_tabs
            splitter.setSizes([1])
            return

        for tabs in list(device_tab.session_tab_widgets):
            if tabs is not primary_tabs and tabs.count() == 0:
                device_tab.session_tab_widgets.remove(tabs)
                tabs.setParent(None)
                tabs.deleteLater()
        if device_tab.active_session_tab_widget not in device_tab.session_tab_widgets:
            device_tab.active_session_tab_widget = device_tab.session_tab_widgets[0]

    def _remove_device_tab(self, device_tab: DeviceTabState) -> None:
        close_index = self.session_tab_widget.indexOf(device_tab.page)
        if close_index >= 0:
            self.session_tab_widget.removeTab(close_index)
        self.device_tabs_by_id.pop(device_tab.device_id, None)
        device_tab.page.deleteLater()
        self.update_center_stage_state()

    # ---- Current session operations ----

    def current_session_state(self) -> SessionTabState | None:
        device_tab = self.current_device_tab_state()
        if device_tab is None:
            return None
        tabs = self.active_session_tabs_for_device(device_tab)
        return self._session_state_for_page(tabs.currentWidget())

    def reconnect_current_session(self) -> None:
        state = self.current_session_state()
        if state is None:
            self.set_status_message("当前没有可重连的终端会话。")
            return
        self.reconnect_session_tab(state.tab_id)

    def open_current_session_log(self) -> None:
        state = self.current_session_state()
        if state is None:
            self.set_status_message("当前没有可打开日志的终端会话。")
            return
        self.open_session_log(state)

    def open_current_session_log_directory(self) -> None:
        state = self.current_session_state()
        if state is None:
            self.set_status_message("当前没有可打开日志目录的终端会话。")
            return
        self.open_session_log_directory(state)

    def disconnect_current_session(self) -> None:
        state = self.current_session_state()
        if state is None:
            self.set_status_message("当前没有可断开的终端会话。")
            return
        self.disconnect_session_tab(state.tab_id)
