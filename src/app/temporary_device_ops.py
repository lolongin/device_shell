"""Temporary device management mixin for DeviceDesktopApp."""

from __future__ import annotations

from typing import Any

try:
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMenu,
        QMessageBox,
        QSpinBox,
        QVBoxLayout,
    )
except ModuleNotFoundError:  # pragma: no cover - only used when launching the GUI
    QComboBox = None
    QDialog = None
    QDialogButtonBox = None
    QFormLayout = None
    QFrame = None
    QHBoxLayout = None
    QLabel = None
    QLineEdit = None
    QMenu = None
    QMessageBox = None
    QSpinBox = None
    QVBoxLayout = None

from ..data import Device
from ..helpers import build_search_text, html_badge
from ..temporary_devices import (
    is_temporary_device,
    make_temporary_device,
    next_temporary_device_id,
)
from ..widgets.password_field import configure_password_visibility


if QDialog is not None:

    class TemporaryDeviceDialog(QDialog):
        """Small editor for a local-only temporary connection."""

        def __init__(self, parent: Any = None, device: Device | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("workspaceDialog")
            self.setWindowTitle("编辑临时连接" if device is not None else "新增临时连接")
            self.setMinimumWidth(420)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(16, 16, 16, 14)
            layout.setSpacing(12)
            hint = QLabel("临时连接只保存在本机，不会写入资产库或设备表。")
            hint.setObjectName("sectionCopy")
            layout.addWidget(hint)

            form_card = QFrame()
            form_card.setObjectName("dialogFormCard")
            form = QFormLayout(form_card)
            form.setContentsMargins(12, 12, 12, 12)
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(8)
            layout.addWidget(form_card)

            self.name_input = QLineEdit()
            self.name_input.setPlaceholderText("例如 Temp-10.1.2.3")
            form.addRow("名称", self.name_input)

            self.open_kind_combo = QComboBox()
            self.open_kind_combo.addItem("Telnet", "device")
            self.open_kind_combo.addItem("SSH", "linux")
            form.addRow("打开方式", self.open_kind_combo)

            telnet_row = QHBoxLayout()
            self.telnet_ip_input = QLineEdit()
            self.telnet_ip_input.setPlaceholderText("Telnet IP")
            self.telnet_port_input = QSpinBox()
            self.telnet_port_input.setRange(1, 65535)
            self.telnet_port_input.setValue(23)
            telnet_row.addWidget(self.telnet_ip_input, 1)
            telnet_row.addWidget(self.telnet_port_input, 0)
            form.addRow("Telnet", telnet_row)

            ssh_row = QHBoxLayout()
            self.ssh_ip_input = QLineEdit()
            self.ssh_ip_input.setPlaceholderText("SSH IP")
            self.ssh_port_input = QSpinBox()
            self.ssh_port_input.setRange(1, 65535)
            self.ssh_port_input.setValue(22)
            ssh_row.addWidget(self.ssh_ip_input, 1)
            ssh_row.addWidget(self.ssh_port_input, 0)
            form.addRow("SSH", ssh_row)

            self.username_input = QLineEdit()
            self.password_input = QLineEdit()
            configure_password_visibility(self.password_input)
            self.notes_input = QLineEdit()
            form.addRow("用户名", self.username_input)
            form.addRow("密码", self.password_input)
            form.addRow("备注", self.notes_input)

            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.setObjectName("workspaceDialogButtons")
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

            if device is not None:
                self.name_input.setText(device.name)
                self.telnet_ip_input.setText(device.telnet_ip)
                self.telnet_port_input.setValue(device.telnet_port)
                self.ssh_ip_input.setText(device.ssh_ip)
                self.ssh_port_input.setValue(device.ssh_port)
                self.username_input.setText(device.username)
                self.password_input.setText(device.password)
                self.notes_input.setText(device.notes)
                preferred_kind = str(device.extra.get("preferred_kind", "device"))
                index = self.open_kind_combo.findData(preferred_kind)
                self.open_kind_combo.setCurrentIndex(max(0, index))

        def values(self) -> dict[str, object]:
            return {
                "name": self.name_input.text().strip(),
                "open_kind": str(self.open_kind_combo.currentData() or "device"),
                "telnet_ip": self.telnet_ip_input.text().strip(),
                "telnet_port": self.telnet_port_input.value(),
                "ssh_ip": self.ssh_ip_input.text().strip(),
                "ssh_port": self.ssh_port_input.value(),
                "username": self.username_input.text().strip(),
                "password": self.password_input.text(),
                "notes": self.notes_input.text().strip(),
            }

else:

    class TemporaryDeviceDialog:  # pragma: no cover - placeholder without PySide6
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("PySide6 is required to edit temporary devices.")


class TemporaryDeviceOpsMixin:
    """Mixin providing local temporary connection CRUD."""

    @staticmethod
    def is_temporary_device(device: Device | None) -> bool:
        return bool(device is not None and is_temporary_device(device))

    @staticmethod
    def is_simulated_device(device: Device | None) -> bool:
        return bool(device is not None and device.id == "SIM-TERMINAL")

    def add_temporary_device(self) -> None:
        self.save_temporary_device_from_form()

    def show_temporary_device_menu(self) -> None:
        if not self.temporary_devices:
            self.save_temporary_device_from_form()
            return
        anchor = getattr(self, "temporary_save_button", self)
        menu = self.new_workspace_menu(anchor, "临时连接", "temporary-list")
        add_action = menu.addAction("新增临时连接...")
        menu.addSeparator()
        open_actions: dict[Any, Device] = {}
        edit_actions: dict[Any, Device] = {}
        delete_actions: dict[Any, Device] = {}
        for device in self.temporary_devices:
            device_menu = menu.addMenu(self.temporary_device_display_name(device))
            device_menu.setObjectName("workspaceContextMenu")
            device_menu.setProperty("menuKind", "temporary-list-device")
            open_action = device_menu.addAction("打开")
            edit_action = device_menu.addAction("编辑...")
            delete_action = device_menu.addAction("删除")
            open_actions[open_action] = device
            edit_actions[edit_action] = device
            delete_actions[delete_action] = device
        menu_pos = anchor.rect().bottomLeft() if hasattr(anchor, "rect") else None
        chosen = menu.exec(anchor.mapToGlobal(menu_pos)) if menu_pos is not None else menu.exec()
        if chosen is None:
            return
        if chosen == add_action:
            self.clear_temporary_form()
            return
        if chosen in open_actions:
            self.open_temporary_device(open_actions[chosen])
            return
        if chosen in edit_actions:
            self.edit_temporary_device(edit_actions[chosen])
            return
        if chosen in delete_actions:
            self.delete_temporary_device(delete_actions[chosen])

    def add_and_open_temporary_device(self) -> None:
        self.save_temporary_device_from_form()

    def save_temporary_device_from_form(self) -> None:
        values = self.temporary_form_values()
        if not self.validate_temporary_device_values(values):
            return
        host = str(values["telnet_ip"] or values["ssh_ip"] or values["serial_ip"])
        existing_ids = {device.id for device in self.devices} | {device.id for device in self.temporary_devices}
        editing_id = self.editing_temporary_device_id
        device_id = editing_id or next_temporary_device_id(existing_ids, host)
        name = str(values["name"] or f"Temp-{host}")
        existing = self.get_device_by_id(editing_id) if editing_id else None
        preferred_kind = self.infer_temporary_open_kind(values, existing)
        device = make_temporary_device(
            device_id=device_id,
            name=name,
            telnet_ip=str(values["telnet_ip"]),
            telnet_port=int(values["telnet_port"]),
            ssh_ip=str(values["ssh_ip"]),
            ssh_port=int(values["ssh_port"]),
            telnet_username=str(values["telnet_username"]),
            telnet_password=str(values["telnet_password"]),
            ssh_username=str(values["ssh_username"]),
            ssh_password=str(values["ssh_password"]),
            serial_ip=str(values["serial_ip"]),
            serial_port=int(values["serial_port"]),
            serial_password=str(values["serial_password"]),
            notes=str(values["notes"]),
            created_at=str(existing.extra.get("created_at", "")) if existing is not None else "",
            preferred_kind=preferred_kind,
        )
        self.upsert_temporary_device(device)
        self.refresh_device_tab_title(device)
        if not editing_id:
            self.open_temporary_device(device)
        self.clear_temporary_form()
        action = "已更新" if editing_id else "已添加"
        self.set_status_message(f"{action}临时连接: {device.name}")

    def edit_temporary_device(self, device: Device | None = None) -> None:
        device = device if isinstance(device, Device) else self.get_selected_device()
        if device is None or not self.is_temporary_device(device):
            self.show_warning("请选择一条临时连接。")
            return
        self.populate_temporary_form(device)
        self.set_status_message(f"已载入临时连接，可直接修改: {device.name}")

    def delete_temporary_device(self, device: Device | None = None) -> None:
        device = device if isinstance(device, Device) else self.get_selected_device()
        if device is None or not self.is_temporary_device(device):
            self.show_warning("请选择一条临时连接。")
            return
        if any(state.device_id == device.id for state in self.session_tabs_by_id.values()):
            self.show_warning("请先关闭这条临时连接的终端会话，再删除它。")
            return
        confirmed = QMessageBox.question(
            self,
            "删除临时连接",
            f"确认删除临时连接 {device.name}？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed != QMessageBox.Yes:
            return
        self.temporary_devices = [item for item in self.temporary_devices if item.id != device.id]
        self.rebuild_device_indexes()
        self.refresh_temporary_panel()
        if self.editing_temporary_device_id == device.id:
            self.clear_temporary_form()
        if self.selected_device_id == device.id:
            self.selected_device_id = ""
        self.schedule_desktop_state_save()
        self.set_status_message(f"已删除临时连接: {device.name}")

    def validate_temporary_device_values(self, values: dict[str, object]) -> bool:
        has_telnet = bool(str(values.get("telnet_ip") or "").strip())
        has_ssh = bool(str(values.get("ssh_ip") or "").strip())
        has_serial = bool(str(values.get("serial_ip") or "").strip())
        if not has_telnet and not has_ssh and not has_serial:
            self.show_warning("临时连接至少需要 Telnet、SSH 或串口地址。")
            return False
        if has_telnet and (
            not str(values.get("telnet_username") or "").strip()
            or not str(values.get("telnet_password") or "")
        ):
            self.show_warning("填写 Telnet 地址时需要 Telnet 账号和密码。")
            return False
        if has_ssh and (
            not str(values.get("ssh_username") or "").strip()
            or not str(values.get("ssh_password") or "")
        ):
            self.show_warning("填写 SSH 地址时需要 SSH 账号和密码。")
            return False
        if has_serial and not str(values.get("serial_password") or ""):
            self.show_warning("填写串口地址时需要串口密码。")
            return False
        return True

    def temporary_form_values(self) -> dict[str, object]:
        return {
            "name": self.temporary_name_input.text().strip(),
            "telnet_ip": self.temporary_telnet_ip_input.text().strip(),
            "telnet_port": self.temporary_port_value(self.temporary_telnet_port_input.text(), 23),
            "ssh_ip": self.temporary_ssh_ip_input.text().strip(),
            "ssh_port": self.temporary_port_value(self.temporary_ssh_port_input.text(), 22),
            "serial_ip": self.temporary_serial_ip_input.text().strip(),
            "serial_port": self.temporary_port_value(self.temporary_serial_port_input.text(), 23),
            "serial_password": self.temporary_serial_password_input.text(),
            "telnet_username": self.temporary_telnet_username_input.text().strip(),
            "telnet_password": self.temporary_telnet_password_input.text(),
            "ssh_username": self.temporary_ssh_username_input.text().strip(),
            "ssh_password": self.temporary_ssh_password_input.text(),
            "notes": self.temporary_notes_input.text().strip(),
        }

    @staticmethod
    def temporary_port_value(value: str, default: int) -> int:
        try:
            port = int(value.strip() or default)
        except ValueError:
            return default
        return port if 1 <= port <= 65535 else default

    @staticmethod
    def infer_temporary_open_kind(values: dict[str, object], existing: Device | None = None) -> str:
        available = {
            "linux": bool(str(values.get("ssh_ip") or "").strip()),
            "device": bool(str(values.get("telnet_ip") or "").strip()),
            "serial": bool(str(values.get("serial_ip") or "").strip()),
        }
        if existing is not None:
            existing_kind = str(existing.extra.get("preferred_kind", ""))
            if available.get(existing_kind):
                return existing_kind
        if available["linux"]:
            return "linux"
        if available["device"]:
            return "device"
        if available["serial"]:
            return "serial"
        return "device"

    def populate_temporary_form(self, device: Device) -> None:
        self.editing_temporary_device_id = device.id
        self.temporary_name_input.setText(device.name)
        self.temporary_telnet_ip_input.setText(device.telnet_ip)
        self.temporary_telnet_port_input.setText(str(device.telnet_port))
        self.temporary_ssh_ip_input.setText(device.ssh_ip)
        self.temporary_ssh_port_input.setText(str(device.ssh_port))
        self.temporary_serial_ip_input.setText(device.serial_ip)
        self.temporary_serial_port_input.setText(str(device.serial_port))
        self.temporary_serial_password_input.setText(device.serial_password)
        self.temporary_telnet_username_input.setText(device.username)
        self.temporary_telnet_password_input.setText(device.password)
        self.temporary_ssh_username_input.setText(device.ssh_username)
        self.temporary_ssh_password_input.setText(device.ssh_password)
        self.temporary_notes_input.setText(device.notes)
        self.temporary_save_button.setText("更新")

    def clear_temporary_form(self) -> None:
        self.editing_temporary_device_id = ""
        self.temporary_name_input.clear()
        self.temporary_telnet_ip_input.clear()
        self.temporary_telnet_port_input.clear()
        self.temporary_ssh_ip_input.clear()
        self.temporary_ssh_port_input.clear()
        self.temporary_serial_ip_input.clear()
        self.temporary_serial_port_input.clear()
        self.temporary_serial_password_input.clear()
        self.temporary_telnet_username_input.clear()
        self.temporary_telnet_password_input.clear()
        self.temporary_ssh_username_input.clear()
        self.temporary_ssh_password_input.clear()
        self.temporary_notes_input.clear()
        self.temporary_save_button.setText("保存并打开")

    def upsert_temporary_device(self, device: Device) -> None:
        self.temporary_devices = [item for item in self.temporary_devices if item.id != device.id]
        self.temporary_devices.append(device)
        self.rebuild_device_indexes()
        self.refresh_temporary_panel()
        self.schedule_desktop_state_save()

    def rebuild_device_indexes(self) -> None:
        simulated_devices = [self.simulated_device()] if hasattr(self, "simulated_device") else []
        self.device_by_id = {}
        for device in [*self.devices, *self.temporary_devices, *simulated_devices]:
            self.device_by_id.setdefault(device.id, device)
        self.search_index = {}
        for device in [*self.devices, *simulated_devices]:
            current = self.search_index.get(device.id, "")
            text = build_search_text(device)
            self.search_index[device.id] = f"{current} {text}".strip() if current else text
        self._last_device_table_signature = ()
        self._last_owned_table_signature = ()

    def open_temporary_device(self, device: Device, kind: str | None = None) -> None:
        if kind == "device" and device.telnet_ip.strip():
            self.open_device_session(device)
            return
        if kind == "linux" and device.ssh_ip.strip():
            self.open_linux_session(device)
            return
        if kind == "serial" and device.serial_ip.strip():
            self.open_serial_session(device)
            return
        if kind is not None:
            self.show_warning("临时连接缺少对应类型的连接地址。")
            return

        opened = False
        if device.telnet_ip.strip():
            self.open_device_session(device)
            opened = True
        if device.ssh_ip.strip():
            self.open_linux_session(device)
            opened = True
        if device.serial_ip.strip():
            self.open_serial_session(device)
            opened = True
        if opened:
            return
        self.show_warning("临时连接缺少可用的 Telnet/SSH/串口地址。")

    def show_temporary_device_context_menu(self, device: Device, widget: Any, pos: Any) -> None:
        menu = self.new_workspace_menu(widget, self.temporary_device_display_name(device), "temporary-device")
        copy_connection_action = menu.addAction("复制连接信息")
        menu.addSeparator()
        open_device_action = menu.addAction("打开设备管理口")
        open_linux_action = menu.addAction("打开 Linux 后台")
        open_serial_action = menu.addAction("打开串口")
        menu.addSeparator()
        edit_action = menu.addAction("编辑")
        delete_action = menu.addAction("删除")
        open_device_action.setEnabled(bool(device.telnet_ip.strip()))
        open_linux_action.setEnabled(bool(device.ssh_ip.strip()))
        open_serial_action.setEnabled(bool(device.serial_ip.strip()))

        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == copy_connection_action:
            self.copy_text_to_clipboard(
                self.device_connection_copy_text(device),
                f"已复制连接信息: {device.name}",
            )
            return
        if chosen == open_device_action:
            self.open_device_session(device)
            return
        if chosen == open_linux_action:
            self.open_linux_session(device)
            return
        if chosen == open_serial_action:
            self.open_serial_session(device)
            return
        if chosen == edit_action:
            self.edit_temporary_device(device)
            return
        if chosen == delete_action:
            self.delete_temporary_device(device)

    def temporary_device_search_text(self, device: Device) -> str:
        search_text = build_search_text(device)
        if self.is_temporary_device(device):
            search_text = f"{search_text} temporary 临时"
        if self.is_simulated_device(device):
            search_text = f"{search_text} simulated simulator mock terminal 模拟 终端 测试"
        return search_text

    def temporary_device_display_name(self, device: Device) -> str:
        if self.is_simulated_device(device):
            return device.name
        return f"[临时] {device.name}" if self.is_temporary_device(device) else device.name

    @staticmethod
    def temporary_device_endpoint_text(device: Device) -> str:
        endpoints: list[str] = []
        if device.telnet_ip.strip():
            endpoints.append(f"Telnet {device.telnet_ip}:{device.telnet_port}")
        if device.ssh_ip.strip():
            endpoints.append(f"SSH {device.ssh_ip}:{device.ssh_port}")
        if device.serial_ip.strip():
            endpoints.append(f"串口 {device.serial_ip}:{device.serial_port}")
        return " / ".join(endpoints) or "未配置地址"

    def temporary_device_detail_badge(self, device: Device) -> str:
        if not self.is_temporary_device(device):
            return ""
        return html_badge(
            "临时连接",
            "仅保存在本机，不会同步到资产库或设备表",
            variant="warning",
            class_name="temporary-detail-badge",
        )

    def refresh_device_tab_title(self, device: Device) -> None:
        device_tab = self.device_tabs_by_id.get(device.id)
        if device_tab is None:
            return
        title = self.temporary_device_display_name(device)
        device_tab.title = title
        if device_tab.tab_title_label is not None:
            device_tab.tab_title_label.setText(title)
        index = self.session_tab_widget.indexOf(device_tab.page)
        if index >= 0:
            self.session_tab_widget.setTabText(index, "")

    def update_device_quick_actions_for_device(self, actions: dict[str, Any], device: Device) -> None:
        if self.is_simulated_device(device):
            for name, action in actions.items():
                action.setEnabled(name in {"locate", "clone_telnet"})
            if "clone_telnet" in actions:
                actions["clone_telnet"].setText("打开设备管理口")
            return
        if "clone_serial" in actions:
            actions["clone_serial"].setEnabled(self.can_view_serial_connection(device))
        if "copy_serial_ip" in actions:
            actions["copy_serial_ip"].setEnabled(self.can_view_serial_connection(device))
        if "power_off" in actions:
            actions["power_off"].setEnabled(self.can_power_off_device(device))
