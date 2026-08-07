"""System package upgrade panel and actions."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import socket
import time
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
    STANDBY_STORAGE_ABSENT,
    STANDBY_STORAGE_AVAILABLE,
    PackageFileEntry,
    PackageUpgradeConfig,
    StartupInfo,
    build_cleanup_plan,
    classify_standby_storage,
    dir_contains_package,
    find_upgrade_failure,
    generate_huawei_upgrade_plan,
    parse_dir_entries,
    parse_display_startup,
    parse_free_space_bytes,
    startup_uses_package,
)
from ..terminal_orchestration import TerminalPlanError, parse_terminal_plan


class PackageUpgradeOpsMixin:
    """Mixin providing package upgrade planning and command sending."""

    PACKAGE_UPGRADE_PIPELINE = (
        ("precheck", "1 预检启动项和空间"),
        ("cleanup", "2 安全清理旧包"),
        ("download", "3 下载目标系统包"),
        ("verify", "4 校验主备包"),
        ("startup", "5 设置下次启动项"),
        ("confirm", "6 最终确认"),
    )
    PACKAGE_UPGRADE_MAX_RETRIES = 2
    PACKAGE_UPGRADE_COMMAND_TIMEOUT_MS = 45_000
    PACKAGE_UPGRADE_QUIET_MS = 1_100

    @staticmethod
    def _list_local_ipv4() -> list[str]:
        """Enumerate this host's IPv4 addresses (including VPN interfaces).

        ``socket.gethostbyname_ex`` lists the addresses the OS binds for the
        hostname, which covers wired/LAN and VPN adapters. Dedupe and drop
        loopback; fall back gracefully when the OS cannot resolve the hostname.
        """
        try:
            addrs = socket.gethostbyname_ex(socket.gethostname())[2]
        except (OSError, socket.gaierror):
            return []
        seen: list[str] = []
        for addr in addrs:
            addr = addr.strip()
            if not addr or addr.startswith("127."):
                continue
            if addr not in seen:
                seen.append(addr)
        return seen

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

        package_dir_row = QHBoxLayout()
        package_dir_row.setSpacing(6)
        self.package_upgrade_dir_input = QLineEdit()
        self.package_upgrade_dir_input.setPlaceholderText("包所在目录")
        self.package_upgrade_dir_input.setText(getattr(self, "package_upgrade_package_dir", ""))
        self.package_upgrade_dir_browse_button = QPushButton("浏览")
        self.package_upgrade_dir_browse_button.setObjectName("compactGhostButton")
        self.package_upgrade_dir_browse_button.setFixedWidth(58)
        package_dir_row.addWidget(self.package_upgrade_dir_input, 1)
        package_dir_row.addWidget(self.package_upgrade_dir_browse_button)
        form_layout.addRow("包目录", package_dir_row)

        package_row = QHBoxLayout()
        package_row.setSpacing(6)
        self.package_upgrade_file_input = QLineEdit()
        self.package_upgrade_file_input.setPlaceholderText("选择 .cc 系统包")
        self.package_upgrade_file_input.setText(getattr(self, "package_upgrade_package_file", ""))
        self.package_upgrade_browse_button = QPushButton("选择")
        self.package_upgrade_browse_button.setObjectName("compactGhostButton")
        self.package_upgrade_browse_button.setFixedWidth(58)
        package_row.addWidget(self.package_upgrade_file_input, 1)
        package_row.addWidget(self.package_upgrade_browse_button)
        form_layout.addRow("系统包", package_row)

        self.package_upgrade_server_host_combo = QComboBox()
        self.package_upgrade_server_host_combo.setEditable(True)
        remembered_host = str(getattr(self, "package_upgrade_server_host", "")).strip()
        local_addrs = self._list_local_ipv4()
        for addr in local_addrs:
            self.package_upgrade_server_host_combo.addItem(addr)
        if remembered_host and remembered_host not in local_addrs:
            self.package_upgrade_server_host_combo.addItem(remembered_host)
        self.package_upgrade_server_host_combo.setCurrentText(
            remembered_host or (local_addrs[0] if local_addrs else "")
        )
        self.package_upgrade_server_host_combo.setPlaceholderText("设备可访问的本机 IP")
        form_layout.addRow("本机地址", self.package_upgrade_server_host_combo)
        if hasattr(self, "schedule_desktop_state_save"):
            self.package_upgrade_server_host_combo.currentTextChanged.connect(
                lambda text: self._remember_package_upgrade_values()
            )
            self.package_upgrade_dir_input.textChanged.connect(
                lambda text: self._remember_package_upgrade_values()
            )
            self.package_upgrade_file_input.textChanged.connect(
                lambda text: self._remember_package_upgrade_values()
            )

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

        self.package_upgrade_include_slave_checkbox = QCheckBox("自动探测双主控并同步备控")
        self.package_upgrade_include_slave_checkbox.setChecked(True)
        form_layout.addRow("", self.package_upgrade_include_slave_checkbox)
        self.package_upgrade_auto_delete_checkbox = QCheckBox("空间不足时自动删除未使用旧 .cc 包")
        self.package_upgrade_auto_delete_checkbox.setChecked(True)
        form_layout.addRow("", self.package_upgrade_auto_delete_checkbox)
        self.package_upgrade_reboot_checkbox = QCheckBox("包含 reboot 命令")
        self.package_upgrade_reboot_checkbox.setChecked(True)
        form_layout.addRow("", self.package_upgrade_reboot_checkbox)

        if hasattr(form_layout, "setRowVisible"):
            for row_index in range(2, form_layout.rowCount()):
                form_layout.setRowVisible(row_index, False)
            form_layout.setRowVisible(form_layout.rowCount() - 1, True)

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

        self.package_upgrade_pipeline_labels: dict[str, QLabel] = {}
        pipeline_frame = QFrame()
        pipeline_frame.setObjectName("transferConfigCard")
        pipeline_layout = QVBoxLayout(pipeline_frame)
        pipeline_layout.setContentsMargins(10, 8, 10, 8)
        pipeline_layout.setSpacing(4)
        pipeline_title = QLabel("安全流水线")
        pipeline_title.setObjectName("sectionCaption")
        pipeline_layout.addWidget(pipeline_title)
        for key, label_text in self.PACKAGE_UPGRADE_PIPELINE:
            step_label = QLabel(f"待开始  {label_text}")
            step_label.setObjectName("activeFilterText")
            step_label.setWordWrap(True)
            self.package_upgrade_pipeline_labels[key] = step_label
            pipeline_layout.addWidget(step_label)
        group_layout.addWidget(pipeline_frame)

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
        self.package_upgrade_dir_browse_button.clicked.connect(self.choose_package_upgrade_dir)
        self.package_upgrade_browse_button.clicked.connect(self.choose_package_upgrade_file)
        self.package_upgrade_one_click_button.clicked.connect(self.run_package_upgrade_one_click)
        self.package_upgrade_generate_button.clicked.connect(self.generate_package_upgrade_script)
        self.package_upgrade_send_button.clicked.connect(self.send_package_upgrade_script)
        self.package_upgrade_copy_button.clicked.connect(self.copy_package_upgrade_script)
        self.package_upgrade_read_terminal_button.clicked.connect(self.read_package_upgrade_precheck_from_terminal)
        self.package_upgrade_start_transfer_button.clicked.connect(self.start_package_upgrade_transfer_service)
        self.package_upgrade_protocol_combo.currentTextChanged.connect(self.update_package_upgrade_default_port)

    def reset_package_upgrade_pipeline(self) -> None:
        if not hasattr(self, "package_upgrade_pipeline_labels"):
            return
        for key, label_text in self.PACKAGE_UPGRADE_PIPELINE:
            self.package_upgrade_pipeline_labels[key].setText(f"待开始  {label_text}")

    def set_package_upgrade_step_status(self, key: str, status: str, detail: str = "") -> None:
        if not hasattr(self, "package_upgrade_pipeline_labels"):
            return
        labels = dict(self.PACKAGE_UPGRADE_PIPELINE)
        label = self.package_upgrade_pipeline_labels.get(key)
        if label is None:
            return
        suffix = f" - {detail}" if detail else ""
        label.setText(f"{status}  {labels.get(key, key)}{suffix}")
        operation = getattr(self, "package_upgrade_operation_state", None)
        if isinstance(operation, dict):
            operation["stage"] = key
            operation["message"] = label.text()

    def fail_package_upgrade_run(self, key: str, message: str) -> None:
        run = getattr(self, "package_upgrade_run", None)
        if isinstance(run, dict):
            run["cancelled"] = True
        self.release_package_upgrade_lease()
        self.set_package_upgrade_step_status(key, "停住", message)
        self.package_upgrade_status_label.setText(message)
        self.set_status_message(message)
        self.package_upgrade_one_click_button.setEnabled(True)
        operation = getattr(self, "package_upgrade_operation_state", None)
        if isinstance(operation, dict):
            operation.update({"status": "failed", "stage": key, "message": message})

    def finish_package_upgrade_run(self, message: str) -> None:
        self.release_package_upgrade_lease()
        self.set_package_upgrade_step_status("confirm", "完成", message)
        self.package_upgrade_status_label.setText(message)
        self.set_status_message(message)
        self.package_upgrade_one_click_button.setEnabled(True)
        operation = getattr(self, "package_upgrade_operation_state", None)
        if isinstance(operation, dict):
            operation.update({"status": "completed", "stage": "confirm", "message": message})

    def release_package_upgrade_lease(self) -> None:
        run = getattr(self, "package_upgrade_run", None)
        if not isinstance(run, dict):
            return
        tab_id = str(run.get("tab_id") or "")
        owner_id = str(run.get("lease_owner_id") or "")
        coordinator = getattr(self, "terminal_execution_coordinator", None)
        if coordinator is not None and tab_id and owner_id:
            coordinator.release_external_lease(tab_id, owner_id)

    def cancel_package_upgrade_for_user_input(
        self,
        tab_id: str,
        owner_id: str,
    ) -> None:
        run = getattr(self, "package_upgrade_run", None)
        if not isinstance(run, dict):
            return
        if (
            str(run.get("tab_id") or "") != tab_id
            or str(run.get("lease_owner_id") or "") != owner_id
        ):
            return
        self.fail_package_upgrade_run(
            str(getattr(self, "package_upgrade_operation_state", {}).get("stage") or "precheck"),
            "检测到人工终端输入，自动换包已停止。",
        )

    def package_upgrade_run_is_active(self) -> bool:
        run = getattr(self, "package_upgrade_run", None)
        operation = getattr(self, "package_upgrade_operation_state", None)
        return bool(
            isinstance(run, dict)
            and not run.get("cancelled")
            and isinstance(operation, dict)
            and operation.get("status") == "running"
        )

    def package_upgrade_status_snapshot(self) -> dict[str, Any]:
        operation = dict(
            getattr(
                self,
                "package_upgrade_operation_state",
                {
                    "status": "idle",
                    "stage": "",
                    "message": "当前没有自动换包操作。",
                    "device_id": "",
                },
            )
        )
        labels = getattr(self, "package_upgrade_pipeline_labels", {})
        operation["steps"] = {
            key: label.text()
            for key, label in labels.items()
        }
        return operation

    def choose_package_upgrade_dir(self) -> None:
        """Pick the local directory that holds the .cc packages."""
        current_dir = self.package_upgrade_dir_input.text().strip()
        start = current_dir if current_dir and Path(current_dir).is_dir() else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择包目录", start)
        if selected:
            self.package_upgrade_dir_input.setText(selected)
            self._remember_package_upgrade_values()

    def _remember_package_upgrade_values(self) -> None:
        """Persist the package-upgrade host / dir / file selections."""
        combo = getattr(self, "package_upgrade_server_host_combo", None)
        if combo is not None:
            self.package_upgrade_server_host = combo.currentText().strip()
        dir_input = getattr(self, "package_upgrade_dir_input", None)
        if dir_input is not None:
            self.package_upgrade_package_dir = dir_input.text().strip()
        file_input = getattr(self, "package_upgrade_file_input", None)
        if file_input is not None:
            self.package_upgrade_package_file = file_input.text().strip()
        if hasattr(self, "schedule_desktop_state_save"):
            self.schedule_desktop_state_save()

    def choose_package_upgrade_file(self) -> None:
        start_dir = self.package_upgrade_dir_input.text().strip()
        if not start_dir or not Path(start_dir).is_dir():
            start_dir = str(Path.home())
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "选择系统包",
            start_dir,
            "System package (*.cc);;All files (*.*)",
        )
        if selected:
            self.package_upgrade_file_input.setText(selected)
            parent = str(Path(selected).parent)
            self.package_upgrade_dir_input.setText(parent)
            self.schedule_desktop_state_save()
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

    def run_package_upgrade_one_click(self, _checked: bool = False) -> bool:
        device = self.get_selected_device()
        if device is None:
            self.show_warning("请先在设备列表中选择要更换大包的设备。")
            return False
        if self.package_upgrade_config() is None:
            return False
        if not self.ensure_package_upgrade_transfer_service():
            return False
        self.package_upgrade_operation_state = {
            "status": "running",
            "stage": "precheck",
            "message": "正在准备自动换包预检。",
            "device_id": device.id,
        }
        self.activate_device(device.id)
        self.show_left_sidebar_panel("package_upgrade")
        state = self.package_upgrade_session_for_device(device.id)
        if state is None:
            self.open_device_session(device)
            self.show_left_sidebar_panel("package_upgrade")
            self.set_status_message(f"正在打开设备会话，准备一键更换: {device.name}")
            self._schedule_package_upgrade_precheck(device.id, delay_ms=6500)
            return True
        self.jump_to_package_upgrade_session(state.tab_id)
        self._start_package_upgrade_precheck(state.tab_id)
        return True

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
        self.jump_to_package_upgrade_session(state.tab_id)
        self._start_package_upgrade_precheck(state.tab_id)

    def jump_to_package_upgrade_session(self, tab_id: str) -> None:
        self.jump_to_session(tab_id)
        self.show_left_sidebar_panel("package_upgrade")

    def _start_package_upgrade_precheck(self, tab_id: str) -> None:
        config = self.package_upgrade_config()
        if config is None:
            return
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            self.set_status_message("目标会话已关闭，停止一键更换。")
            return
        lease_owner_id = f"package-upgrade:{time.monotonic_ns()}"
        try:
            self.terminal_execution_coordinator.acquire_external_lease(
                tab_id,
                lease_owner_id,
                on_cancel=lambda tab_id=tab_id, owner_id=lease_owner_id: (
                    self.cancel_package_upgrade_for_user_input(tab_id, owner_id)
                ),
            )
        except TerminalPlanError as exc:
            self.fail_package_upgrade_run(
                "precheck",
                f"终端正在执行其他任务，无法开始换包: {exc}",
            )
            return
        if hasattr(state.session, "configure_package_upgrade"):
            state.session.configure_package_upgrade(
                config.package_path.name,
                config.package_path.stat().st_size,
                config.username,
                config.password,
            )
        self.package_upgrade_one_click_button.setEnabled(False)
        self.reset_package_upgrade_pipeline()
        commands = [
            "screen-length 0 temporary",
            "display startup",
            f"dir {config.master_storage}",
        ]
        if config.include_slave:
            commands.append(f"dir {config.slave_storage}")
        self.package_upgrade_run = {
            "tab_id": tab_id,
            "config": config,
            "precheck_offset": self.package_upgrade_output_offset(state),
            "precheck_commands": commands,
            "precheck_outputs": {},
            "lease_owner_id": lease_owner_id,
            "cancelled": False,
        }
        self.package_upgrade_status_label.setText("正在预检设备，请保持终端会话在当前设备。")
        self.set_status_message("正在预检查启动包和存储空间...")
        self._run_package_upgrade_precheck_command(tab_id, 0)

    def _run_package_upgrade_precheck_command(self, tab_id: str, index: int) -> None:
        if not self.package_upgrade_run_is_active():
            return
        run = getattr(self, "package_upgrade_run", {})
        commands = list(run.get("precheck_commands") or [])
        if index >= len(commands):
            self._finish_package_upgrade_one_click(tab_id)
            return
        command = commands[index]
        config = run.get("config")
        is_standby_probe = bool(
            isinstance(config, PackageUpgradeConfig)
            and config.include_slave
            and command == f"dir {config.slave_storage}"
        )

        def done(output: str, tab_id: str = tab_id, index: int = index, command: str = command) -> None:
            run = getattr(self, "package_upgrade_run", {})
            outputs = run.get("precheck_outputs")
            if isinstance(outputs, dict):
                outputs[command] = output
            self._run_package_upgrade_precheck_command(tab_id, index + 1)

        self.send_package_upgrade_command_and_wait(
            tab_id,
            command,
            step_key="precheck",
            detail=f"{index + 1}/{len(commands)} {command}",
            on_done=done,
            timeout_ms=25_000,
            stop_on_failure=not is_standby_probe,
        )

    def _finish_package_upgrade_one_click(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            self.set_status_message("目标会话已关闭，停止一键更换。")
            self.package_upgrade_one_click_button.setEnabled(True)
            return
        text = self.package_upgrade_terminal_text(state)
        run = getattr(self, "package_upgrade_run", {})
        precheck_offset = int(run.get("precheck_offset", 0) or 0)
        recent_precheck_text = self.package_upgrade_output_since(state, precheck_offset)
        if recent_precheck_text:
            text = recent_precheck_text
        config = run.get("config")
        if not isinstance(config, PackageUpgradeConfig):
            self.package_upgrade_one_click_button.setEnabled(True)
            return
        precheck_outputs = run.get("precheck_outputs")
        if isinstance(precheck_outputs, dict) and precheck_outputs:
            self.package_upgrade_startup_output.setPlainText(str(precheck_outputs.get("display startup") or text))
            self.package_upgrade_master_dir_output.setPlainText(
                str(precheck_outputs.get(f"dir {config.master_storage}") or text)
            )
            if self.package_upgrade_include_slave_checkbox.isChecked():
                self.package_upgrade_slave_dir_output.setPlainText(
                    str(precheck_outputs.get(f"dir {config.slave_storage}") or text)
                )
        elif text:
            self.package_upgrade_startup_output.setPlainText(text)
            self.package_upgrade_master_dir_output.setPlainText(text)
            if self.package_upgrade_include_slave_checkbox.isChecked():
                self.package_upgrade_slave_dir_output.setPlainText(text)
        mode_status = ""
        if config.include_slave:
            slave_output = ""
            if isinstance(precheck_outputs, dict):
                slave_output = str(precheck_outputs.get(f"dir {config.slave_storage}") or "")
            standby_state = classify_standby_storage(slave_output, config.slave_storage)
            if standby_state == STANDBY_STORAGE_ABSENT:
                config = replace(config, include_slave=False)
                run["config"] = config
                mode_status = "未检测到备控，按单主控执行"
            elif standby_state == STANDBY_STORAGE_AVAILABLE:
                mode_status = "已检测到备控，按双主控执行"
            else:
                self.fail_package_upgrade_run(
                    "precheck",
                    "无法确认备控存储是否存在，未自动降级；请检查设备返回或手动关闭自动探测。",
                )
                return
        cleanup_entries, blockers, status_lines = self.package_upgrade_safety_report(config)
        plan_config = replace(config, cleanup_entries=cleanup_entries)
        self.package_upgrade_script_output.setPlainText(
            "\n".join(generate_huawei_upgrade_plan(plan_config).commands)
        )
        if mode_status:
            status_lines.insert(0, mode_status)
        if status_lines:
            self.package_upgrade_status_label.setText("；".join(status_lines))
        if blockers:
            self.fail_package_upgrade_run("precheck", "；".join(blockers))
            return
        self.set_package_upgrade_step_status(
            "precheck",
            "完成",
            mode_status or "空间和启动项已读取",
        )
        self._run_package_upgrade_execution(tab_id, config, cleanup_entries)

    @staticmethod
    def package_upgrade_terminal_text(state: Any) -> str:
        recent = str(getattr(state, "recent_output_buffer", "") or "")
        if recent:
            return recent
        terminal = state.terminal
        if hasattr(terminal, "all_text"):
            return str(terminal.all_text() or "")
        if hasattr(terminal, "toPlainText"):
            return str(terminal.toPlainText() or "")
        return ""

    def package_upgrade_output_offset(self, state: Any) -> int:
        return len(str(getattr(state, "recent_output_buffer", "") or ""))

    def package_upgrade_output_since(self, state: Any, offset: int) -> str:
        text = str(getattr(state, "recent_output_buffer", "") or "")
        if offset < 0 or offset > len(text):
            return text
        return text[offset:]

    def send_package_upgrade_command_and_wait(
        self,
        tab_id: str,
        command: str,
        *,
        step_key: str,
        detail: str,
        on_done: Any,
        validate: Any | None = None,
        timeout_ms: int | None = None,
        retries_left: int | None = None,
        stop_on_failure: bool = True,
    ) -> None:
        if not self.package_upgrade_run_is_active():
            return
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            self.fail_package_upgrade_run(step_key, "目标终端会话已关闭，自动换包停止。")
            return
        if not state.session.is_connected:
            self.fail_package_upgrade_run(step_key, "目标终端未连接，自动换包停止。")
            return
        retries = self.PACKAGE_UPGRADE_MAX_RETRIES if retries_left is None else retries_left
        timeout = self.PACKAGE_UPGRADE_COMMAND_TIMEOUT_MS if timeout_ms is None else timeout_ms
        self.set_package_upgrade_step_status(step_key, "进行中", detail)
        offset = self.package_upgrade_output_offset(state)
        started = time.monotonic()
        last_change = started
        last_size = 0
        run = getattr(self, "package_upgrade_run", {})
        self.send_session_text(
            tab_id,
            f"{command}\r",
            origin="package_upgrade",
            execution_id=str(run.get("lease_owner_id") or ""),
        )

        def poll() -> None:
            nonlocal last_change, last_size
            if not self.package_upgrade_run_is_active():
                return
            current_state = self.session_tabs_by_id.get(tab_id)
            if current_state is None:
                self.fail_package_upgrade_run(step_key, "目标终端会话已关闭，自动换包停止。")
                return
            output = self.package_upgrade_output_since(current_state, offset)
            now = time.monotonic()
            if len(output) != last_size:
                last_size = len(output)
                last_change = now
            elapsed_ms = int((now - started) * 1000)
            quiet_ms = int((now - last_change) * 1000)
            if output and quiet_ms >= self.PACKAGE_UPGRADE_QUIET_MS:
                failure = find_upgrade_failure(output)
                if failure and stop_on_failure:
                    self.fail_package_upgrade_run(step_key, f"{detail} 失败，设备输出包含: {failure}")
                    return
                if validate is not None:
                    validation_error = validate(output)
                    if validation_error:
                        self.fail_package_upgrade_run(step_key, validation_error)
                        return
                on_done(output)
                return
            if elapsed_ms >= timeout:
                if retries > 0:
                    self.set_package_upgrade_step_status(
                        step_key,
                        "重试",
                        f"{detail} 超时，剩余 {retries} 次",
                    )
                    self.send_package_upgrade_command_and_wait(
                        tab_id,
                        command,
                        step_key=step_key,
                        detail=detail,
                        on_done=on_done,
                        validate=validate,
                        timeout_ms=timeout,
                        retries_left=retries - 1,
                        stop_on_failure=stop_on_failure,
                    )
                    return
                self.fail_package_upgrade_run(step_key, f"{detail} 超时，未确认设备响应。")
                return
            if QTimer is None:
                self.fail_package_upgrade_run(step_key, f"{detail} 未确认完成。")
                return
            QTimer.singleShot(300, poll)

        if QTimer is None:
            poll()
            return
        QTimer.singleShot(300, poll)

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
        server_host = self.package_upgrade_server_host_combo.currentText().strip()
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

    def package_upgrade_safety_report(
        self,
        config: PackageUpgradeConfig,
    ) -> tuple[list[PackageFileEntry], list[str], list[str]]:
        if not config.auto_delete_old_packages:
            return [], [], ["自动删除已关闭"]
        package_size = config.package_path.stat().st_size
        startup = parse_display_startup(self.package_upgrade_startup_output.toPlainText())
        status_lines: list[str] = []
        blockers: list[str] = []
        entries: list[PackageFileEntry] = []

        def evaluate_storage(label: str, storage: str, text: str) -> None:
            if not text:
                blockers.append(f"未读取到{label}目录输出")
                return
            free_bytes = parse_free_space_bytes(text)
            if free_bytes <= 0:
                blockers.append(f"无法确认{label}剩余空间")
            plan = build_cleanup_plan(
                storage=storage,
                free_bytes=free_bytes,
                target_bytes=package_size,
                entries=parse_dir_entries(text, storage),
                startup=startup,
                target_package_name=config.package_path.name,
            )
            entries.extend(plan.delete_entries)
            status_lines.append(
                f"{label}删除 {len(plan.delete_entries)} 个旧包，释放 {plan.reclaim_bytes // (1024 * 1024)} MB"
            )
            if not plan.has_enough_space:
                blockers.append(f"{label}清理后空间仍不足")

        evaluate_storage("主控", config.master_storage, self.package_upgrade_master_dir_output.toPlainText())
        if config.include_slave:
            evaluate_storage("备控", config.slave_storage, self.package_upgrade_slave_dir_output.toPlainText())
        return entries, blockers, status_lines

    def _run_package_upgrade_execution(
        self,
        tab_id: str,
        config: PackageUpgradeConfig,
        cleanup_entries: list[PackageFileEntry],
    ) -> None:
        cleanup_commands = [f"delete /unreserved /quiet {entry.path}" for entry in cleanup_entries]
        if cleanup_commands:
            self._run_package_upgrade_command_sequence(
                tab_id,
                cleanup_commands,
                step_key="cleanup",
                detail="安全删除未使用旧包",
                on_done=lambda: self._run_package_upgrade_download(tab_id, config),
            )
            return
        self.set_package_upgrade_step_status("cleanup", "完成", "无需删除旧包")
        self._run_package_upgrade_download(tab_id, config)

    def _run_package_upgrade_command_sequence(
        self,
        tab_id: str,
        commands: list[str],
        *,
        step_key: str,
        detail: str,
        on_done: Any,
        index: int = 0,
    ) -> None:
        if index >= len(commands):
            self.set_package_upgrade_step_status(step_key, "完成", detail)
            on_done()
            return
        command = commands[index]
        self.send_package_upgrade_command_and_wait(
            tab_id,
            command,
            step_key=step_key,
            detail=f"{detail} {index + 1}/{len(commands)}",
            on_done=lambda _output, tab_id=tab_id, commands=commands, index=index: (
                self._run_package_upgrade_command_sequence(
                    tab_id,
                    commands,
                    step_key=step_key,
                    detail=detail,
                    on_done=on_done,
                    index=index + 1,
                )
            ),
        )

    def _run_package_upgrade_download(self, tab_id: str, config: PackageUpgradeConfig) -> None:
        package_size = config.package_path.stat().st_size
        if dir_contains_package(
            self.package_upgrade_master_dir_output.toPlainText(),
            storage=config.master_storage,
            package_name=config.package_path.name,
            expected_size=package_size,
        ):
            self.set_package_upgrade_step_status("download", "完成", "主控目标包已存在且大小匹配")
            self._run_package_upgrade_verify_master(tab_id, config)
            return
        package_name = config.package_path.name
        master_package = f"{config.master_storage.rstrip('/')}/{package_name}"
        transfer_timeout = min(
            3500,
            max(120, int(package_size / (1024 * 1024)) * 2),
        )
        if config.protocol.lower() == "sftp":
            login_success = ["sftp_prompt", "ftp_prompt"]
            login_responses = [
                {
                    "match": "host_key_prompt",
                    "text": "yes",
                    "max_matches": 1,
                },
                {
                    "match": "username_prompt",
                    "secret_ref": "transfer.username",
                    "max_matches": 1,
                },
                {
                    "match": "password_prompt",
                    "secret_ref": "transfer.password",
                    "max_matches": 2,
                },
            ]
            protocol_steps: list[dict[str, Any]] = []
        else:
            login_success = ["ftp_prompt"]
            login_responses = [
                {
                    "match": "username_prompt",
                    "secret_ref": "transfer.username",
                    "max_matches": 1,
                },
                {
                    "match": "password_prompt",
                    "secret_ref": "transfer.password",
                    "max_matches": 1,
                },
            ]
            protocol_steps = [
                {"type": "send", "text": "binary", "label": "切换二进制模式"},
                {
                    "type": "expect",
                    "success": ["ftp_prompt"],
                    "failures": ["Error:", "Unknown command"],
                    "timeout_seconds": 30,
                    "label": "确认二进制模式",
                },
            ]
        transfer_prompt = "sftp_prompt" if config.protocol.lower() == "sftp" else "ftp_prompt"
        steps = [
            {
                "type": "send",
                "text": f"{config.protocol.lower()} {config.server_host} {config.port}",
                "label": f"连接 {config.protocol.upper()} 服务",
            },
            {
                "type": "expect",
                "success": login_success,
                "responses": login_responses,
                "failures": [
                    "Login incorrect",
                    "Authentication failed",
                    "Permission denied",
                    "Host key verification failed",
                    "530 ",
                ],
                "timeout_seconds": 45,
                "label": "本地自动登录文件服务",
            },
            *protocol_steps,
            {
                "type": "send",
                "text": f"get {package_name} {master_package}",
                "label": f"下载 {package_name}",
            },
            {
                "type": "expect",
                "success": [transfer_prompt, "ftp_prompt"],
                "failures": [
                    "Error:",
                    "failed",
                    "No such file",
                    "not found",
                    "timed out",
                    "Connection closed",
                ],
                "timeout_seconds": transfer_timeout,
                "label": "等待系统包下载完成",
                "max_output_chars": 32_768,
            },
            {"type": "send", "text": "quit", "label": "退出文件客户端"},
            {
                "type": "expect",
                "success": ["device_prompt"],
                "failures": ["Error:"],
                "timeout_seconds": 30,
                "label": "返回设备命令行",
            },
        ]
        try:
            plan = parse_terminal_plan(
                steps,
                total_timeout_seconds=min(3600, transfer_timeout + 120),
            )
            runner = self.terminal_execution_coordinator.start(
                session_id=tab_id,
                device_id=str(getattr(self.session_tabs_by_id.get(tab_id), "device_id", "")),
                plan=plan,
                lease_owner_id=str(
                    getattr(self, "package_upgrade_run", {}).get("lease_owner_id")
                    or ""
                ),
            )
        except TerminalPlanError as exc:
            self.fail_package_upgrade_run(
                "download",
                f"下载流程无法启动: {exc}",
            )
            return
        run = getattr(self, "package_upgrade_run", None)
        if isinstance(run, dict):
            run["download_execution_id"] = runner.execution_id
        operation = getattr(self, "package_upgrade_operation_state", None)
        if isinstance(operation, dict):
            operation["execution_id"] = runner.execution_id
        self.set_package_upgrade_step_status(
            "download",
            "进行中",
            f"本地自动登录并下载 {package_name}",
        )
        runner.add_done_callback(
            lambda completed, tab_id=tab_id, config=config: (
                self._finish_package_upgrade_download_execution(
                    tab_id,
                    config,
                    completed.public_dict(),
                )
            )
        )

    def _finish_package_upgrade_download_execution(
        self,
        tab_id: str,
        config: PackageUpgradeConfig,
        result: dict[str, Any],
    ) -> None:
        if result.get("status") != "completed":
            failed_step = int(result.get("current_step", 0))
            message = str(result.get("message") or "文件下载交互未完成。")
            self.fail_package_upgrade_run(
                "download",
                f"下载步骤 {failed_step} 失败: {message}",
            )
            return
        self.set_package_upgrade_step_status(
            "download",
            "完成",
            "文件服务登录和系统包下载完成",
        )
        self._run_package_upgrade_verify_master(tab_id, config)

    def _run_package_upgrade_verify_master(self, tab_id: str, config: PackageUpgradeConfig) -> None:
        package_name = config.package_path.name
        package_size = config.package_path.stat().st_size
        master_package = f"{config.master_storage.rstrip('/')}/{package_name}"

        def validate(output: str) -> str:
            if dir_contains_package(
                output,
                storage=config.master_storage,
                package_name=package_name,
                expected_size=package_size,
            ):
                return ""
            return "主控未确认到目标包，或目标包大小与本地文件不匹配。"

        self.send_package_upgrade_command_and_wait(
            tab_id,
            f"dir {master_package}",
            step_key="verify",
            detail="确认主控目标包",
            validate=validate,
            on_done=lambda _output: self._run_package_upgrade_slave_sync(tab_id, config),
        )

    def _run_package_upgrade_slave_sync(self, tab_id: str, config: PackageUpgradeConfig) -> None:
        package_name = config.package_path.name
        package_size = config.package_path.stat().st_size
        master_package = f"{config.master_storage.rstrip('/')}/{package_name}"
        slave_package = f"{config.slave_storage.rstrip('/')}/{package_name}"
        if not config.include_slave:
            self.set_package_upgrade_step_status("verify", "完成", "单主控目标包已确认")
            self._run_package_upgrade_startup(tab_id, config)
            return

        def verify_slave() -> None:
            def validate(output: str) -> str:
                if dir_contains_package(
                    output,
                    storage=config.slave_storage,
                    package_name=package_name,
                    expected_size=package_size,
                ):
                    return ""
                return "备控未确认到目标包，或目标包大小与本地文件不匹配。"

            self.send_package_upgrade_command_and_wait(
                tab_id,
                f"dir {slave_package}",
                step_key="verify",
                detail="确认备控目标包",
                validate=validate,
                on_done=lambda _output: self._run_package_upgrade_startup(tab_id, config),
            )

        self.send_package_upgrade_command_and_wait(
            tab_id,
            f"copy {master_package} {slave_package}",
            step_key="verify",
            detail="同步目标包到备控",
            on_done=lambda _output: verify_slave(),
            timeout_ms=90_000,
        )

    def _run_package_upgrade_startup(self, tab_id: str, config: PackageUpgradeConfig) -> None:
        package_name = config.package_path.name
        master_package = f"{config.master_storage.rstrip('/')}/{package_name}"
        slave_package = f"{config.slave_storage.rstrip('/')}/{package_name}"
        command = (
            f"startup system-software {master_package} all"
            if config.include_slave
            else f"startup system-software {master_package}"
        )

        def after_startup(output: str) -> None:
            if config.include_slave and find_upgrade_failure(output):
                self.set_package_upgrade_step_status("startup", "重试", "all 不可用，尝试主备分开设置")
                fallback = [
                    f"startup system-software {master_package}",
                    f"startup system-software {slave_package} slave-board",
                ]
                self._run_package_upgrade_command_sequence(
                    tab_id,
                    fallback,
                    step_key="startup",
                    detail="主备分开设置启动项",
                    on_done=lambda: self._run_package_upgrade_confirm(tab_id, config),
                )
                return
            self.set_package_upgrade_step_status("startup", "完成", "启动项命令已发送")
            self._run_package_upgrade_confirm(tab_id, config)

        self.send_package_upgrade_command_and_wait(
            tab_id,
            command,
            step_key="startup",
            detail="设置下次启动系统包",
            on_done=after_startup,
            stop_on_failure=False,
        )

    def _run_package_upgrade_confirm(self, tab_id: str, config: PackageUpgradeConfig) -> None:
        def validate(output: str) -> str:
            if startup_uses_package(output, config.package_path.name):
                return ""
            return "最终 display startup 未确认目标包为下次启动系统包，已停止。"

        def after_confirm(_output: str) -> None:
            self.set_package_upgrade_step_status("confirm", "完成", "下次启动项已确认")
            if not config.reboot_after_setting:
                self.finish_package_upgrade_run("换包已完成并确认下次启动项。请人工确认业务窗口后重启。")
                return
            self._run_package_upgrade_reboot(tab_id)
            return
            self.send_package_upgrade_command_and_wait(
                tab_id,
                "reboot",
                step_key="confirm",
                detail="发送 reboot",
                on_done=lambda _output: self.finish_package_upgrade_run("已发送 reboot，请观察设备重启。"),
                stop_on_failure=False,
                timeout_ms=20_000,
            )

        self.send_package_upgrade_command_and_wait(
            tab_id,
            "display startup",
            step_key="confirm",
            detail="最终确认启动项",
            validate=validate,
            on_done=after_confirm,
        )

    def _run_package_upgrade_reboot(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            self.fail_package_upgrade_run("confirm", "目标终端会话已关闭，无法发送 reboot。")
            return
        self.set_package_upgrade_step_status("confirm", "进行中", "发送 reboot 并等待重启完成")
        offset = self.package_upgrade_output_offset(state)
        started = time.monotonic()
        run = getattr(self, "package_upgrade_run", {})
        self.send_session_text(
            tab_id,
            "reboot\r",
            origin="package_upgrade",
            execution_id=str(run.get("lease_owner_id") or ""),
        )
        self._wait_package_upgrade_reboot_completion(tab_id, offset, started)

    def _wait_package_upgrade_reboot_completion(self, tab_id: str, offset: int, started: float) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            self.fail_package_upgrade_run("confirm", "目标终端会话已关闭，未确认重启完成。")
            return
        output = self.package_upgrade_output_since(state, offset)
        lowered = output.casefold()
        complete_markers = (
            "system ready",
            "login:",
            "username:",
            "<sim> ",
        )
        if "reboot" in lowered and any(marker in lowered for marker in complete_markers):
            self.finish_package_upgrade_run("reboot 已完成，设备已重新进入可交互状态。")
            return
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if elapsed_ms >= 180_000:
            self.fail_package_upgrade_run("confirm", "已发送 reboot，但 180 秒内未确认设备重启完成。")
            return
        self.set_package_upgrade_step_status("confirm", "等待", f"reboot 中 {elapsed_ms // 1000}s")
        if QTimer is None:
            self.fail_package_upgrade_run("confirm", "已发送 reboot，但当前环境无法继续等待重启完成。")
            return
        QTimer.singleShot(
            1000,
            lambda tab_id=tab_id, offset=offset, started=started: self._wait_package_upgrade_reboot_completion(
                tab_id,
                offset,
                started,
            ),
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
        self.send_session_text(
            tab_id,
            f"{command}\r",
            origin="package_upgrade",
        )
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
