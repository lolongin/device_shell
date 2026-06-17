"""System package upgrade panel and actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QFileDialog,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QPlainTextEdit,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:
    Qt = None
    QTimer = None
    QFileDialog = None
    QCheckBox = None
    QComboBox = None
    QFormLayout = None
    QFrame = None
    QGroupBox = None
    QHBoxLayout = None
    QLabel = None
    QLineEdit = None
    QPushButton = None
    QPlainTextEdit = None
    QSizePolicy = None
    QVBoxLayout = None
    QWidget = None

from ..file_transfer_service import TransferServiceConfig, TransferServiceController
from ..package_upgrade import (
    DEFAULT_MASTER_STORAGE,
    DEFAULT_SLAVE_STORAGE,
    PackageFileEntry,
    PackageUpgradeConfig,
    StartupInfo,
    build_cleanup_plan,
    generate_huawei_upgrade_plan,
    parse_dir_entries,
    parse_display_startup,
    parse_free_space_bytes,
)


class PackageUpgradeOpsMixin:
    """Mixin providing package upgrade planning and command sending."""

    def _build_package_upgrade_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("leftRail")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)

        group = QGroupBox("大包更换")
        group.setObjectName("navShell")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)

        title = QLabel("一键大包更换")
        title.setObjectName("railTitle")
        group_layout.addWidget(title)
        copy = QLabel("选择系统包后，对当前选中设备执行自动更换。")
        copy.setObjectName("railCopy")
        copy.setWordWrap(True)
        if QSizePolicy is not None:
            copy.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        group_layout.addWidget(copy)

        form_frame = QFrame()
        form_frame.setObjectName("transferConfigCard")
        form_layout = QFormLayout(form_frame)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setVerticalSpacing(7)
        form_layout.setHorizontalSpacing(8)
        if Qt is not None:
            form_layout.setLabelAlignment(Qt.AlignRight)

        package_row = QHBoxLayout()
        package_row.setSpacing(6)
        self.package_upgrade_file_input = QLineEdit()
        self.package_upgrade_file_input.setPlaceholderText("选择 .cc 系统包")
        self.package_upgrade_browse_button = QPushButton("选择")
        self.package_upgrade_browse_button.setObjectName("compactGhostButton")
        self.package_upgrade_browse_button.setFixedWidth(58)
        package_row.addWidget(self.package_upgrade_file_input, 1)
        package_row.addWidget(self.package_upgrade_browse_button)
        form_layout.addRow("系统包", package_row)

        self.package_upgrade_server_host_input = QLineEdit("192.168.1.10")
        self.package_upgrade_server_host_input.setPlaceholderText("设备可访问的本机 IP")
        form_layout.addRow("本机地址", self.package_upgrade_server_host_input)

        group_layout.addWidget(form_frame)

        protocol_row = QHBoxLayout()
        protocol_row.setSpacing(6)
        self.package_upgrade_protocol_combo = QComboBox()
        self.package_upgrade_protocol_combo.addItems(["FTP", "SFTP"])
        self.package_upgrade_protocol_combo.setCurrentText(str(getattr(self, "transfer_protocol", "ftp")).upper())
        self.package_upgrade_port_input = QLineEdit(str(getattr(self, "transfer_port", 2121)))
        self.package_upgrade_port_input.setMaximumWidth(76)
        protocol_row.addWidget(self.package_upgrade_protocol_combo, 1)
        protocol_row.addWidget(self.package_upgrade_port_input)
        form_layout.addRow("传输", protocol_row)

        self.package_upgrade_username_input = QLineEdit(str(getattr(self, "transfer_username", "device")))
        self.package_upgrade_password_input = QLineEdit(str(getattr(self, "transfer_password", "device")))
        form_layout.addRow("账号", self.package_upgrade_username_input)
        form_layout.addRow("密码", self.package_upgrade_password_input)

        self.package_upgrade_master_storage_input = QLineEdit(DEFAULT_MASTER_STORAGE)
        self.package_upgrade_slave_storage_input = QLineEdit(DEFAULT_SLAVE_STORAGE)
        form_layout.addRow("主控路径", self.package_upgrade_master_storage_input)
        form_layout.addRow("备控路径", self.package_upgrade_slave_storage_input)

        self.package_upgrade_include_slave_checkbox = QCheckBox("双主控：同步备控并设置 all / slave-board")
        self.package_upgrade_include_slave_checkbox.setChecked(True)
        form_layout.addRow("", self.package_upgrade_include_slave_checkbox)
        self.package_upgrade_auto_delete_checkbox = QCheckBox("空间不足时自动删除未使用旧 .cc 包")
        self.package_upgrade_auto_delete_checkbox.setChecked(True)
        form_layout.addRow("", self.package_upgrade_auto_delete_checkbox)
        self.package_upgrade_reboot_checkbox = QCheckBox("包含 reboot 命令")
        self.package_upgrade_reboot_checkbox.setChecked(False)

        if hasattr(form_layout, "setRowVisible"):
            for row_index in range(2, form_layout.rowCount()):
                form_layout.setRowVisible(row_index, False)

        self.package_upgrade_startup_output = self._new_package_upgrade_textarea(
            "粘贴 display startup 输出，用于保护当前/下次启动包"
        )

        self.package_upgrade_master_dir_output = self._new_package_upgrade_textarea(
            "粘贴 dir flash:/ 输出，用于计算主控可删除旧包"
        )

        self.package_upgrade_slave_dir_output = self._new_package_upgrade_textarea(
            "粘贴 dir slave#flash:/ 输出，用于计算备控可删除旧包"
        )

        one_click_row = QHBoxLayout()
        one_click_row.setSpacing(6)
        self.package_upgrade_one_click_button = QPushButton("一键更换选中设备")
        self.package_upgrade_one_click_button.setObjectName("primaryButton")
        one_click_row.addWidget(self.package_upgrade_one_click_button, 1)
        group_layout.addLayout(one_click_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.package_upgrade_read_terminal_button = QPushButton("读取终端")
        self.package_upgrade_read_terminal_button.setObjectName("compactGhostButton")
        self.package_upgrade_start_transfer_button = QPushButton("启动传输")
        self.package_upgrade_start_transfer_button.setObjectName("compactGhostButton")
        self.package_upgrade_generate_button = QPushButton("生成脚本")
        self.package_upgrade_generate_button.setObjectName("primaryButton")

        send_row = QHBoxLayout()
        send_row.setSpacing(6)
        self.package_upgrade_send_button = QPushButton("发送脚本")
        self.package_upgrade_send_button.setObjectName("primaryButton")
        self.package_upgrade_copy_button = QPushButton("复制脚本")
        self.package_upgrade_copy_button.setObjectName("compactGhostButton")

        self.package_upgrade_status_label = QLabel("选择设备和 .cc 系统包后可一键更换。")
        self.package_upgrade_status_label.setObjectName("activeFilterText")
        self.package_upgrade_status_label.setWordWrap(True)
        group_layout.addWidget(self.package_upgrade_status_label)

        self.package_upgrade_script_output = QPlainTextEdit()
        self.package_upgrade_script_output.setObjectName("transferLogOutput")
        self.package_upgrade_script_output.setReadOnly(False)
        self.package_upgrade_script_output.setMinimumHeight(220)

        layout.addWidget(group)
        layout.addStretch(1)
        return panel

    def _new_package_upgrade_textarea(self, placeholder: str) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setObjectName("transferLogOutput")
        editor.setPlaceholderText(placeholder)
        editor.setMaximumBlockCount(500)
        editor.setMinimumHeight(74)
        editor.setMaximumHeight(108)
        return editor

    def wire_package_upgrade_events(self) -> None:
        self.package_upgrade_browse_button.clicked.connect(self.choose_package_upgrade_file)
        self.package_upgrade_one_click_button.clicked.connect(self.run_package_upgrade_one_click)
        self.package_upgrade_generate_button.clicked.connect(self.generate_package_upgrade_script)
        self.package_upgrade_send_button.clicked.connect(self.send_package_upgrade_script)
        self.package_upgrade_copy_button.clicked.connect(self.copy_package_upgrade_script)
        self.package_upgrade_read_terminal_button.clicked.connect(self.read_package_upgrade_precheck_from_terminal)
        self.package_upgrade_start_transfer_button.clicked.connect(self.start_package_upgrade_transfer_service)
        self.package_upgrade_protocol_combo.currentTextChanged.connect(self.update_package_upgrade_default_port)

    def choose_package_upgrade_file(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "选择系统包",
            str(Path.home()),
            "System package (*.cc);;All files (*.*)",
        )
        if selected:
            self.package_upgrade_file_input.setText(selected)
            self.generate_package_upgrade_script()

    def update_package_upgrade_default_port(self, protocol: str) -> None:
        current = self.package_upgrade_port_input.text().strip()
        if current in {"21", "22", "2121", "2222", ""}:
            self.package_upgrade_port_input.setText("2121" if protocol.upper() == "FTP" else "2222")

    def read_package_upgrade_precheck_from_terminal(self) -> None:
        state = self.current_session_state()
        if state is None:
            self.set_status_message("当前没有可读取的终端会话。")
            return
        terminal = state.terminal
        text = ""
        if hasattr(terminal, "all_text"):
            text = terminal.all_text()
        elif hasattr(terminal, "toPlainText"):
            text = terminal.toPlainText()
        if not text:
            self.set_status_message("当前终端没有可读取的文本。")
            return
        self.package_upgrade_startup_output.setPlainText(text)
        self.package_upgrade_master_dir_output.setPlainText(text)
        if self.package_upgrade_include_slave_checkbox.isChecked():
            self.package_upgrade_slave_dir_output.setPlainText(text)
        self.generate_package_upgrade_script()

    def run_package_upgrade_one_click(self, _checked: bool = False) -> None:
        device = self.get_selected_device()
        if device is None:
            self.show_warning("请先在设备列表中选择要更换大包的设备。")
            return
        if self.package_upgrade_config() is None:
            return
        if not self.ensure_package_upgrade_transfer_service():
            return
        self.activate_device(device.id)
        state = self.package_upgrade_session_for_device(device.id)
        if state is None:
            self.open_device_session(device)
            self.set_status_message(f"正在打开设备会话，准备一键更换: {device.name}")
            self._schedule_package_upgrade_precheck(device.id, delay_ms=6500)
            return
        self.jump_to_session(state.tab_id)
        self._start_package_upgrade_precheck(state.tab_id)

    def package_upgrade_session_for_device(self, device_id: str) -> Any | None:
        states = self._session_states_for_device(device_id)
        if not states:
            return None
        connected = [state for state in states if state.session.is_connected]
        current = self.current_session_state()
        if current in connected:
            return current
        if connected:
            return connected[0]
        return states[0]

    def _schedule_package_upgrade_precheck(self, device_id: str, *, delay_ms: int) -> None:
        if QTimer is None:
            state = self.package_upgrade_session_for_device(device_id)
            if state is not None:
                self._start_package_upgrade_precheck(state.tab_id)
            return
        QTimer.singleShot(
            delay_ms,
            lambda device_id=device_id: self._start_package_upgrade_for_device(device_id),
        )

    def _start_package_upgrade_for_device(self, device_id: str) -> None:
        state = self.package_upgrade_session_for_device(device_id)
        if state is None:
            self.set_status_message("未找到设备会话，无法继续一键更换。")
            return
        self.jump_to_session(state.tab_id)
        self._start_package_upgrade_precheck(state.tab_id)

    def _start_package_upgrade_precheck(self, tab_id: str) -> None:
        config = self.package_upgrade_config()
        if config is None:
            return
        commands = [
            "screen-length 0 temporary",
            "display startup",
            f"dir {config.master_storage}",
        ]
        if config.include_slave:
            commands.append(f"dir {config.slave_storage}")
        self.set_status_message("正在预检查启动包和存储空间...")
        self._send_package_upgrade_commands(tab_id, commands, index=0)
        delay_ms = len(commands) * int(getattr(self, "package_upgrade_send_interval_ms", 900)) + 5500
        if QTimer is None:
            self._finish_package_upgrade_one_click(tab_id)
            return
        QTimer.singleShot(
            delay_ms,
            lambda tab_id=tab_id: self._finish_package_upgrade_one_click(tab_id),
        )

    def _finish_package_upgrade_one_click(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            self.set_status_message("目标会话已关闭，停止一键更换。")
            return
        text = self.package_upgrade_terminal_text(state)
        if text:
            self.package_upgrade_startup_output.setPlainText(text)
            self.package_upgrade_master_dir_output.setPlainText(text)
            if self.package_upgrade_include_slave_checkbox.isChecked():
                self.package_upgrade_slave_dir_output.setPlainText(text)
        self.generate_package_upgrade_script()
        self.send_package_upgrade_script(tab_id=tab_id)

    @staticmethod
    def package_upgrade_terminal_text(state: Any) -> str:
        terminal = state.terminal
        if hasattr(terminal, "all_text"):
            return str(terminal.all_text() or "")
        if hasattr(terminal, "toPlainText"):
            return str(terminal.toPlainText() or "")
        return ""

    def start_package_upgrade_transfer_service(self) -> None:
        self.ensure_package_upgrade_transfer_service(show_running_message=True)

    def ensure_package_upgrade_transfer_service(self, *, show_running_message: bool = False) -> bool:
        config = self.package_upgrade_transfer_config()
        if config is None:
            return False
        try:
            config.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.show_error(f"共享目录不可用: {exc}")
            return False
        if self.transfer_service is None:
            self.transfer_service = TransferServiceController(
                lambda message: self.dispatch_ui(self.append_transfer_log, message)
            )
        if self.transfer_service.is_running:
            if show_running_message:
                self.set_status_message("文件传输服务已在运行。")
            return True
        try:
            self.transfer_service.start(config)
        except RuntimeError as exc:
            self.show_error(str(exc))
            self.set_status_message(str(exc))
            return False
        self.remember_transfer_panel_config(config)
        if hasattr(self, "refresh_transfer_panel_state"):
            self.refresh_transfer_panel_state()
        self.set_status_message(f"{config.protocol.upper()} 服务已启动，根目录: {config.root}")
        return True

    def package_upgrade_transfer_config(self) -> TransferServiceConfig | None:
        package_path = Path(self.package_upgrade_file_input.text().strip()).expanduser()
        if not package_path.exists() or not package_path.is_file():
            self.show_warning("请先选择存在的 .cc 系统包。")
            return None
        protocol = self.package_upgrade_protocol_combo.currentText().strip().lower() or "ftp"
        try:
            port = int(self.package_upgrade_port_input.text().strip())
        except ValueError:
            self.show_warning("传输端口必须是数字。")
            return None
        username = self.package_upgrade_username_input.text().strip()
        password = self.package_upgrade_password_input.text()
        if not username or not password:
            self.show_warning("FTP/SFTP 账号和密码不能为空。")
            return None
        return TransferServiceConfig(
            protocol=protocol,
            host="0.0.0.0",
            port=port,
            root=package_path.parent,
            username=username,
            password=password,
            writable=False,
        )

    def generate_package_upgrade_script(self) -> None:
        config = self.package_upgrade_config()
        if config is None:
            return
        cleanup_entries, status_lines = self.package_upgrade_cleanup_entries(config)
        config.cleanup_entries = cleanup_entries
        plan = generate_huawei_upgrade_plan(config)
        self.package_upgrade_script_output.setPlainText("\n".join(plan.commands))
        if status_lines:
            self.package_upgrade_status_label.setText("；".join(status_lines))
        else:
            self.package_upgrade_status_label.setText("脚本已生成。")

    def package_upgrade_config(self) -> PackageUpgradeConfig | None:
        package_path = Path(self.package_upgrade_file_input.text().strip()).expanduser()
        if not package_path.exists() or not package_path.is_file():
            self.set_status_message("请先选择存在的 .cc 系统包。")
            return None
        if package_path.suffix.lower() != ".cc":
            self.show_warning("系统包通常应为 .cc 文件。")
        server_host = self.package_upgrade_server_host_input.text().strip()
        if not server_host:
            self.show_warning("请填写设备可访问的本机 IP。")
            return None
        try:
            port = int(self.package_upgrade_port_input.text().strip())
        except ValueError:
            self.show_warning("传输端口必须是数字。")
            return None
        return PackageUpgradeConfig(
            package_path=package_path,
            server_host=server_host,
            protocol=self.package_upgrade_protocol_combo.currentText().strip().lower() or "ftp",
            port=port,
            username=self.package_upgrade_username_input.text().strip(),
            password=self.package_upgrade_password_input.text(),
            master_storage=self.package_upgrade_master_storage_input.text().strip() or DEFAULT_MASTER_STORAGE,
            slave_storage=self.package_upgrade_slave_storage_input.text().strip() or DEFAULT_SLAVE_STORAGE,
            include_slave=self.package_upgrade_include_slave_checkbox.isChecked(),
            auto_delete_old_packages=self.package_upgrade_auto_delete_checkbox.isChecked(),
            reboot_after_setting=self.package_upgrade_reboot_checkbox.isChecked(),
        )

    def package_upgrade_cleanup_entries(
        self,
        config: PackageUpgradeConfig,
    ) -> tuple[list[PackageFileEntry], list[str]]:
        if not config.auto_delete_old_packages:
            return [], ["自动删除已关闭"]
        package_size = config.package_path.stat().st_size
        startup = parse_display_startup(self.package_upgrade_startup_output.toPlainText())
        status_lines: list[str] = []
        entries: list[PackageFileEntry] = []
        master_text = self.package_upgrade_master_dir_output.toPlainText()
        if master_text:
            master_plan = build_cleanup_plan(
                storage=config.master_storage,
                free_bytes=parse_free_space_bytes(master_text),
                target_bytes=package_size,
                entries=parse_dir_entries(master_text, config.master_storage),
                startup=startup,
                target_package_name=config.package_path.name,
            )
            entries.extend(master_plan.delete_entries)
            status_lines.append(
                f"主控删除 {len(master_plan.delete_entries)} 个旧包，释放 {master_plan.reclaim_bytes // (1024 * 1024)} MB"
            )
            if not master_plan.has_enough_space:
                status_lines.append("主控空间仍可能不足")
        else:
            status_lines.append("未提供主控目录输出，跳过主控自动删除")
        if config.include_slave:
            slave_text = self.package_upgrade_slave_dir_output.toPlainText()
            if slave_text:
                slave_plan = build_cleanup_plan(
                    storage=config.slave_storage,
                    free_bytes=parse_free_space_bytes(slave_text),
                    target_bytes=package_size,
                    entries=parse_dir_entries(slave_text, config.slave_storage),
                    startup=startup,
                    target_package_name=config.package_path.name,
                )
                entries.extend(slave_plan.delete_entries)
                status_lines.append(
                    f"备控删除 {len(slave_plan.delete_entries)} 个旧包，释放 {slave_plan.reclaim_bytes // (1024 * 1024)} MB"
                )
                if not slave_plan.has_enough_space:
                    status_lines.append("备控空间仍可能不足")
            else:
                status_lines.append("未提供备控目录输出，跳过备控自动删除")
        return entries, status_lines

    def copy_package_upgrade_script(self) -> None:
        text = self.package_upgrade_script_output.toPlainText()
        if not text:
            self.generate_package_upgrade_script()
            text = self.package_upgrade_script_output.toPlainText()
        if not text:
            return
        self.copy_text_to_clipboard(text, "已复制自动换大包脚本")

    def send_package_upgrade_script(self, _checked: bool = False, *, tab_id: str = "") -> None:
        state = self.session_tabs_by_id.get(tab_id) if tab_id else self.current_session_state()
        if state is None:
            self.set_status_message("当前没有打开的终端会话。")
            return
        text = self.package_upgrade_script_output.toPlainText().strip()
        if not text:
            self.generate_package_upgrade_script()
            text = self.package_upgrade_script_output.toPlainText().strip()
        commands = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not commands:
            self.set_status_message("没有可发送的换包命令。")
            return
        self.set_status_message(f"开始发送自动换大包命令，共 {len(commands)} 条。")
        self._send_package_upgrade_commands(state.tab_id, commands, index=0)

    def _send_package_upgrade_commands(self, tab_id: str, commands: list[str], index: int) -> None:
        if index >= len(commands):
            self.set_status_message("自动换大包命令已全部发送。")
            return
        if tab_id not in self.session_tabs_by_id:
            self.set_status_message("目标终端会话已关闭，停止发送换包命令。")
            return
        command = commands[index]
        self.send_session_text(tab_id, f"{command}\r")
        if QTimer is None:
            self._send_package_upgrade_commands(tab_id, commands, index + 1)
            return
        QTimer.singleShot(
            int(getattr(self, "package_upgrade_send_interval_ms", 900)),
            lambda tab_id=tab_id, commands=commands, index=index + 1: self._send_package_upgrade_commands(
                tab_id,
                commands,
                index,
            ),
        )
