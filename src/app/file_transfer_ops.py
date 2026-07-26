"""File transfer service panel and actions."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QFileDialog,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMenu,
        QPushButton,
        QCheckBox,
        QComboBox,
        QPlainTextEdit,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:
    Qt = None
    QFileDialog = None
    QFormLayout = None
    QFrame = None
    QGroupBox = None
    QHBoxLayout = None
    QLabel = None
    QLineEdit = None
    QMenu = None
    QPushButton = None
    QCheckBox = None
    QComboBox = None
    QPlainTextEdit = None
    QSizePolicy = None
    QVBoxLayout = None
    QWidget = None

from .._sample_data import STATUS_IDLE, STATUS_OTHER
from ..file_transfer_service import TransferServiceConfig, TransferServiceController
from ..helpers import html_status_text
from ..styles import STATUS_COLORS
from ..widgets.password_field import configure_password_visibility


class FileTransferOpsMixin:
    """Mixin providing the local file transfer service panel."""

    def _build_transfer_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("leftRail")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)

        group = QGroupBox("文件传输服务")
        group.setObjectName("navShell")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)

        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("文件传输")
        title.setObjectName("railTitle")
        copy = QLabel("在本机启动 FTP / SFTP 服务，供设备上传或下载文件")
        copy.setObjectName("railCopy")
        copy.setWordWrap(True)
        copy.setMinimumWidth(0)
        if QSizePolicy is not None:
            copy.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        header.addWidget(title)
        header.addWidget(copy)
        group_layout.addLayout(header)

        form_frame = QFrame()
        form_frame.setObjectName("transferConfigCard")
        form_layout = QFormLayout(form_frame)
        form_layout.setContentsMargins(10, 10, 10, 10)
        form_layout.setVerticalSpacing(7)
        form_layout.setHorizontalSpacing(8)
        form_layout.setLabelAlignment(Qt.AlignRight)

        self.transfer_protocol_combo = QComboBox()
        self.transfer_protocol_combo.addItems(["FTP", "SFTP"])
        self.transfer_protocol_combo.setCurrentText(self.transfer_protocol.upper())
        form_layout.addRow("协议", self.transfer_protocol_combo)

        endpoint_row = QHBoxLayout()
        endpoint_row.setSpacing(6)
        self.transfer_host_input = QLineEdit(self.transfer_host)
        self.transfer_host_input.setPlaceholderText("0.0.0.0")
        self.transfer_port_input = QLineEdit(str(self.transfer_port))
        self.transfer_port_input.setMaximumWidth(76)
        endpoint_row.addWidget(self.transfer_host_input, 1)
        endpoint_row.addWidget(self.transfer_port_input)
        form_layout.addRow("监听", endpoint_row)

        root_row = QHBoxLayout()
        root_row.setSpacing(6)
        self.transfer_root_input = QLineEdit(str(self.transfer_root_directory))
        self.transfer_root_input.setPlaceholderText("选择共享目录")
        self.transfer_browse_button = QPushButton("选择")
        self.transfer_browse_button.setObjectName("compactGhostButton")
        self.transfer_browse_button.setFixedWidth(58)
        root_row.addWidget(self.transfer_root_input, 1)
        root_row.addWidget(self.transfer_browse_button)
        form_layout.addRow("目录", root_row)

        self.transfer_username_input = QLineEdit(self.transfer_username)
        self.transfer_password_input = QLineEdit(self.transfer_password)
        configure_password_visibility(self.transfer_password_input)
        form_layout.addRow("账号", self.transfer_username_input)
        form_layout.addRow("密码", self.transfer_password_input)

        self.transfer_writable_checkbox = QCheckBox("允许上传/修改")
        self.transfer_writable_checkbox.setChecked(self.transfer_writable)
        form_layout.addRow("", self.transfer_writable_checkbox)
        group_layout.addWidget(form_frame)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.transfer_start_button = QPushButton("启动服务")
        self.transfer_start_button.setObjectName("primaryButton")
        self.transfer_stop_button = QPushButton("停止")
        self.transfer_stop_button.setObjectName("compactGhostButton")
        self.transfer_stop_button.setProperty("buttonRole", "danger")
        self.transfer_stop_button.setEnabled(False)
        action_row.addWidget(self.transfer_start_button, 1)
        action_row.addWidget(self.transfer_stop_button)
        group_layout.addLayout(action_row)

        self.transfer_status_card = QFrame()
        self.transfer_status_card.setObjectName("transferStatusCard")
        self.transfer_status_card.setProperty("state", "stopped")
        status_card_layout = QVBoxLayout(self.transfer_status_card)
        status_card_layout.setContentsMargins(10, 9, 10, 9)
        status_card_layout.setSpacing(6)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.transfer_status_label = QLabel("未启动")
        self.transfer_status_label.setObjectName("activeFilterText")
        self.transfer_status_label.setProperty("surface", "transferStatus")
        self.transfer_status_label.setTextFormat(Qt.RichText)
        self.transfer_status_label.setWordWrap(True)
        self.transfer_endpoint_label = QLabel("")
        self.transfer_endpoint_label.setObjectName("transferEndpointText")
        self.transfer_endpoint_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        status_row.addWidget(self.transfer_status_label, 0)
        status_row.addWidget(self.transfer_endpoint_label, 1)
        status_card_layout.addLayout(status_row)

        self.transfer_hint_label = QLabel("")
        self.transfer_hint_label.setObjectName("transferHintText")
        self.transfer_hint_label.setTextFormat(Qt.RichText)
        self.transfer_hint_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.transfer_hint_label.setWordWrap(True)
        status_card_layout.addWidget(self.transfer_hint_label)
        group_layout.addWidget(self.transfer_status_card)

        self.transfer_log_output = QPlainTextEdit()
        self.transfer_log_output.setObjectName("transferLogOutput")
        self.transfer_log_output.setReadOnly(True)
        self.transfer_log_output.setMaximumBlockCount(300)
        self.transfer_log_output.setMinimumHeight(160)
        self.transfer_log_output.setContextMenuPolicy(Qt.CustomContextMenu)
        self.transfer_log_output.customContextMenuRequested.connect(self.show_transfer_log_context_menu)
        group_layout.addWidget(self.transfer_log_output, 1)

        layout.addWidget(group)
        layout.addStretch(1)
        self.refresh_transfer_panel_state()
        return panel

    def wire_transfer_events(self) -> None:
        self.transfer_browse_button.clicked.connect(self.choose_transfer_root_directory)
        self.transfer_start_button.clicked.connect(self.start_transfer_service)
        self.transfer_stop_button.clicked.connect(self.stop_transfer_service)
        self.transfer_protocol_combo.currentTextChanged.connect(self.update_transfer_default_port)

    def choose_transfer_root_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择文件传输共享目录",
            self.transfer_root_input.text().strip() or str(self.transfer_root_directory),
        )
        if selected:
            self.transfer_root_input.setText(selected)

    def update_transfer_default_port(self, protocol: str) -> None:
        current = self.transfer_port_input.text().strip()
        if current in {"21", "22", "2121", "2222", ""}:
            self.transfer_port_input.setText("2121" if protocol.upper() == "FTP" else "2222")

    def transfer_config_from_panel(self) -> TransferServiceConfig | None:
        protocol = self.transfer_protocol_combo.currentText().strip().lower() or "ftp"
        host = self.transfer_host_input.text().strip() or "0.0.0.0"
        try:
            port = int(self.transfer_port_input.text().strip())
        except ValueError:
            self.show_warning("端口必须是数字。")
            return None
        if not 1 <= port <= 65535:
            self.show_warning("端口必须在 1-65535 之间。")
            return None
        username = self.transfer_username_input.text().strip()
        password = self.transfer_password_input.text()
        if not username or not password:
            self.show_warning("文件传输服务需要账号和密码。")
            return None
        root = Path(self.transfer_root_input.text().strip()).expanduser()
        return TransferServiceConfig(
            protocol=protocol,
            host=host,
            port=port,
            root=root,
            username=username,
            password=password,
            writable=self.transfer_writable_checkbox.isChecked(),
        )

    def remember_transfer_panel_config(self, config: TransferServiceConfig) -> None:
        self.transfer_protocol = config.protocol
        self.transfer_host = config.host
        self.transfer_port = config.port
        self.transfer_root_directory = config.root
        self.transfer_username = config.username
        self.transfer_password = config.password
        self.transfer_writable = config.writable
        self.schedule_desktop_state_save()

    def start_transfer_service(self) -> None:
        config = self.transfer_config_from_panel()
        if config is None:
            return
        try:
            config.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.show_error(f"共享目录不可用: {exc}")
            return
        if self.transfer_service is None:
            self.transfer_service = TransferServiceController(
                lambda message: self.dispatch_ui(self.append_transfer_log, message)
            )
        try:
            self.transfer_service.start(config)
        except RuntimeError as exc:
            self.show_error(str(exc))
            self.set_status_message(str(exc))
            return
        self.remember_transfer_panel_config(config)
        self.append_transfer_log(f"准备启动 {config.protocol.upper()} 服务。")
        self.set_status_message(f"{config.protocol.upper()} 文件传输服务已启动。")
        self.refresh_transfer_panel_state()

    def stop_transfer_service(self) -> None:
        if self.transfer_service is None or not self.transfer_service.is_running:
            return
        self.transfer_service.stop()
        self.set_status_message("文件传输服务已停止。")
        self.refresh_transfer_panel_state()

    def append_transfer_log(self, message: str) -> None:
        if hasattr(self, "transfer_log_output"):
            self.transfer_log_output.appendPlainText(message)

    def show_transfer_log_context_menu(self, pos: Any) -> None:
        if QMenu is None or not hasattr(self, "transfer_log_output"):
            return
        editor = self.transfer_log_output
        menu = self.new_workspace_menu(editor, "文件传输日志", "transfer-log")
        copy_selection_action = menu.addAction("复制选中文本")
        copy_all_action = menu.addAction("复制全部日志")
        menu.addSeparator()
        open_root_action = menu.addAction("打开共享目录")
        clear_action = menu.addAction("清空日志")
        copy_selection_action.setEnabled(editor.textCursor().hasSelection())
        copy_all_action.setEnabled(bool(editor.toPlainText()))
        clear_action.setEnabled(bool(editor.toPlainText()))

        chosen = menu.exec(editor.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == copy_selection_action:
            editor.copy()
            self.set_status_message("已复制选中文本")
            return
        if chosen == copy_all_action:
            self.copy_text_to_clipboard(editor.toPlainText(), "已复制文件传输日志")
            return
        if chosen == open_root_action:
            root = Path(self.transfer_root_input.text().strip() or str(self.transfer_root_directory)).expanduser()
            self.open_local_path(root, "共享目录", is_directory=True)
            return
        if chosen == clear_action:
            editor.clear()
            self.set_status_message("文件传输日志已清空")

    def refresh_transfer_panel_state(self) -> None:
        running = bool(self.transfer_service and self.transfer_service.is_running)
        if hasattr(self, "transfer_start_button"):
            self.transfer_start_button.setEnabled(not running)
            self.transfer_stop_button.setEnabled(running)
            for widget in (
                self.transfer_protocol_combo,
                self.transfer_host_input,
                self.transfer_port_input,
                self.transfer_root_input,
                self.transfer_browse_button,
                self.transfer_username_input,
                self.transfer_password_input,
                self.transfer_writable_checkbox,
            ):
                widget.setEnabled(not running)
        if not hasattr(self, "transfer_status_label"):
            return
        protocol = self.transfer_protocol_combo.currentText().strip().upper() if hasattr(self, "transfer_protocol_combo") else self.transfer_protocol.upper()
        host = self.transfer_host_input.text().strip() if hasattr(self, "transfer_host_input") else self.transfer_host
        port = self.transfer_port_input.text().strip() if hasattr(self, "transfer_port_input") else str(self.transfer_port)
        root = self.transfer_root_input.text().strip() if hasattr(self, "transfer_root_input") else str(self.transfer_root_directory)
        status = "运行中" if running else "未启动"
        color = STATUS_COLORS[STATUS_IDLE] if running else STATUS_COLORS[STATUS_OTHER]
        if hasattr(self, "transfer_status_card"):
            self.transfer_status_card.setProperty("state", "running" if running else "stopped")
            self.transfer_status_card.style().unpolish(self.transfer_status_card)
            self.transfer_status_card.style().polish(self.transfer_status_card)
        self.transfer_status_label.setText(
            html_status_text(status, color, class_name="transfer-status-text")
        )
        if hasattr(self, "transfer_endpoint_label"):
            self.transfer_endpoint_label.setText(f"{protocol} {host}:{port}")
        username = (
            self.transfer_username_input.text().strip()
            if hasattr(self, "transfer_username_input")
            else self.transfer_username
        )
        command = self.transfer_client_hint(protocol.lower(), host, port, username)
        self.transfer_hint_label.setText(
            f"目录: {html.escape(root)}<br>设备侧: <code>{html.escape(command)}</code>"
        )

    @staticmethod
    def transfer_client_hint(protocol: str, host: str, port: str | int, username: str) -> str:
        target = host if host and host != "0.0.0.0" else "<本机IP>"
        if protocol == "sftp":
            return f"sftp -P {port} {username}@{target}"
        return f"ftp {target} {port}"
