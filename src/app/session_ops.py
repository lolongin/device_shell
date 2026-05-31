"""Session management mixin for DeviceDesktopApp."""
from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Callable
from typing import Any

try:
    from PySide6.QtCore import QEvent, QMimeData, Qt, QTimer
    from PySide6.QtGui import QAction, QColor, QDrag, QFont, QIcon, QKeySequence, QPixmap, QTextBlockFormat
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
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
    QCheckBox = None
    QComboBox = None
    QDialog = None
    QDialogButtonBox = None
    QFormLayout = None
    QFrame = None
    QGridLayout = None
    QGroupBox = None
    QHBoxLayout = None
    QLabel = None
    QLineEdit = None
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
from ..auto_response import (
    AutoResponseRule,
    AutoResponseStep,
    TerminalQuickButton,
    auto_response_rule_allows_startup_trigger,
    decode_response_text,
)
from ..data import Device
from ..helpers import mask_password
from ..linux_session import LinuxSshSession
from ..session_protocol import SessionCallbacks, SessionUnavailableError
from ..simulated_session import SimulatedTerminalSession
from ..styles import STATUS_COLORS
from ..telnet_session import HuaweiTelnetSession, TelnetSessionError
from ..widgets.terminal_canvas import TerminalCanvasWidget
from ..widgets.terminal_widget import InteractiveTerminal

try:
    from ..widgets.xterm_web_widget import XtermWebWidget
except ImportError:
    XtermWebWidget = None

SESSION_TAB_MIME = "application/x-device-tui-session-tab"


if QDialog is not None:

    class AutoResponseRuleDialog(QDialog):
        """Single-form editor for a current-session auto-response rule."""

        def __init__(
            self,
            parent: QWidget | None = None,
            rule: AutoResponseRule | None = None,
        ) -> None:
            super().__init__(parent)
            self.setWindowTitle("编辑自动响应规则" if rule is not None else "新增自动响应规则")
            self.setMinimumWidth(820)
            self.resize(860, 620)

            layout = QFormLayout(self)
            layout.setContentsMargins(18, 16, 18, 14)
            layout.setSpacing(10)

            self.name_input = QLineEdit(rule.name if rule is not None else "启动菜单 Ctrl+B")
            self.append_enter_input = QCheckBox("发送后追加 Enter")
            self.append_enter_input.setChecked(rule.append_enter if rule is not None else False)
            self.case_sensitive_input = QCheckBox("匹配时区分大小写")
            self.case_sensitive_input.setChecked(rule.case_sensitive if rule is not None else True)
            self.once_input = QCheckBox("命中一次后自动停用")
            self.once_input.setChecked(rule.once if rule is not None else True)
            self.allow_startup_trigger_input = QCheckBox("连接启动阶段允许触发")
            self.allow_startup_trigger_input.setChecked(
                rule.allow_startup_trigger if rule is not None else False
            )
            self.match_type_input = QComboBox()
            self.match_type_input.addItem("包含", "contains")
            self.match_type_input.addItem("正则", "regex")
            match_type = rule.match_type if rule is not None else "contains"
            match_index = self.match_type_input.findData(match_type)
            self.match_type_input.setCurrentIndex(match_index if match_index >= 0 else 0)
            self.delay_ms_input = QLineEdit(str(rule.delay_ms if rule is not None else 0))
            self.delay_ms_input.setPlaceholderText("0")
            self.max_triggers_input = QLineEdit(str(rule.max_triggers if rule is not None else 0))
            self.max_triggers_input.setPlaceholderText("0 = 不限制")

            layout.addRow("规则名称", self.name_input)

            layout.addRow("匹配方式", self.match_type_input)

            self.condition_blocks: list[dict[str, Any]] = []
            step_panel = QWidget()
            step_panel_layout = QVBoxLayout(step_panel)
            step_panel_layout.setContentsMargins(0, 0, 0, 0)
            step_panel_layout.setSpacing(8)

            flow_hint = QLabel("从上到下执行：先等终端出现内容，再按顺序发送下面的动作。")
            flow_hint.setObjectName("sectionCopy")
            flow_hint.setWordWrap(True)
            step_panel_layout.addWidget(flow_hint)

            self.steps_container = QWidget()
            self.steps_layout = QVBoxLayout(self.steps_container)
            self.steps_layout.setContentsMargins(0, 0, 0, 0)
            self.steps_layout.setSpacing(8)
            step_panel_layout.addWidget(self.steps_container)

            add_row = QHBoxLayout()
            add_row.setSpacing(6)
            self.add_wait_step_button = QPushButton("添加下一步")
            self.add_wait_step_button.setObjectName("compactGhostButton")
            self.add_wait_step_button.clicked.connect(lambda _checked=False: self.add_wait_row())
            add_row.addWidget(self.add_wait_step_button)
            add_row.addStretch(1)
            step_panel_layout.addLayout(add_row)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setMinimumHeight(260)
            scroll.setMaximumHeight(260)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(step_panel)
            layout.addRow("执行流程", scroll)

            self.populate_step_rows(rule)
            layout.addRow("", self.append_enter_input)
            layout.addRow("", self.case_sensitive_input)
            layout.addRow("", self.once_input)
            layout.addRow("", self.allow_startup_trigger_input)

            layout.addRow("延迟发送(ms)", self.delay_ms_input)
            layout.addRow("最大触发次数", self.max_triggers_input)

            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addRow(buttons)

        def values(self) -> dict[str, object]:
            first_pattern, first_response = self.first_step_values()
            return {
                "name": self.name_input.text().strip(),
                "pattern": first_pattern,
                "response_text": first_response,
                "steps_text": self.steps_text(),
                "step_targets": self.step_targets(),
                "step_delays": self.step_delays(),
                "append_enter": self.append_enter_input.isChecked(),
                "case_sensitive": self.case_sensitive_input.isChecked(),
                "once": self.once_input.isChecked(),
                "allow_startup_trigger": self.allow_startup_trigger_input.isChecked(),
                "match_type": self.match_type_input.currentData() or "contains",
                "delay_ms": self.parse_nonnegative_int(self.delay_ms_input.text()),
                "max_triggers": self.parse_nonnegative_int(self.max_triggers_input.text()),
            }

        @staticmethod
        def parse_nonnegative_int(value: str) -> int:
            try:
                return max(0, int(value.strip() or "0"))
            except ValueError:
                return 0

        def populate_step_rows(self, rule: AutoResponseRule | None) -> None:
            if rule is not None and rule.steps:
                for step in rule.steps:
                    self.add_condition_block(
                        step.pattern,
                        step.response_texts,
                        step.response_targets,
                        step.response_delays,
                    )
                return
            self.add_wait_row(
                rule.pattern if rule is not None else "Ctrl+B",
                rule.response_text if rule is not None and rule.response_text else "Ctrl+B",
            )

        def add_wait_row(self, pattern: str = "", response_text: str = "") -> None:
            self.add_condition_block(pattern, [response_text])

        def add_condition_block(
            self,
            pattern: str = "",
            response_texts: list[str] | None = None,
            response_targets: list[str] | None = None,
            response_delays: list[int] | None = None,
        ) -> None:
            frame = QFrame()
            frame.setObjectName("navFilterBar")
            if QSizePolicy is not None:
                frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            block_layout = QVBoxLayout(frame)
            block_layout.setContentsMargins(8, 8, 8, 8)
            block_layout.setSpacing(6)

            title_row = QHBoxLayout()
            title_row.setSpacing(6)
            title_label = QLabel("")
            title_label.setObjectName("activeFilterText")
            title_row.addWidget(title_label)
            title_row.addStretch(1)
            block_layout.addLayout(title_row)

            header_layout = QHBoxLayout()
            header_layout.setSpacing(6)

            pattern_input = QLineEdit(pattern)
            pattern_input.setPlaceholderText("设备打印了什么就填什么，例如 Password: / Ctrl+B")
            remove_button = QPushButton("删除步骤")
            remove_button.setObjectName("compactGhostButton")
            remove_button.setFixedWidth(68)

            header_layout.addWidget(QLabel("如果终端出现"))
            header_layout.addWidget(pattern_input, 1)
            header_layout.addWidget(remove_button)
            block_layout.addLayout(header_layout)

            send_title = QLabel("按顺序自动发送")
            send_title.setObjectName("sectionCopy")
            block_layout.addWidget(send_title)

            responses_container = QWidget()
            responses_layout = QVBoxLayout(responses_container)
            responses_layout.setContentsMargins(18, 0, 0, 0)
            responses_layout.setSpacing(4)
            block_layout.addWidget(responses_container)

            add_send_button = QPushButton("再发送一条")
            add_send_button.setObjectName("compactGhostButton")
            add_button_row = QHBoxLayout()
            add_button_row.setContentsMargins(18, 0, 0, 0)
            add_button_row.addWidget(add_send_button)
            add_button_row.addStretch(1)
            block_layout.addLayout(add_button_row)

            block = {
                "frame": frame,
                "title_label": title_label,
                "pattern_input": pattern_input,
                "responses_layout": responses_layout,
                "response_rows": [],
                "remove_button": remove_button,
                "add_send_button": add_send_button,
            }
            remove_button.clicked.connect(
                lambda _checked=False, current_block=block: self.remove_condition_block(current_block)
            )
            add_send_button.clicked.connect(
                lambda _checked=False, current_block=block: self.add_response_row(current_block)
            )
            self.condition_blocks.append(block)
            self.steps_layout.addWidget(frame)
            targets = response_targets or []
            delays = response_delays or []
            for index, response_text in enumerate(response_texts or [""]):
                self.add_response_row(
                    block,
                    response_text,
                    targets[index] if index < len(targets) else "current",
                    delays[index] if index < len(delays) else 0,
                )
            self.refresh_condition_block_titles()

        def add_send_row(self, response_text: str = "") -> None:
            if not self.condition_blocks:
                self.add_condition_block()
            self.add_response_row(self.condition_blocks[-1], response_text)

        def add_response_row(
            self,
            block: dict[str, Any],
            response_text: str = "",
            response_target: str = "current",
            response_delay: int = 0,
        ) -> None:
            responses_layout = block.get("responses_layout")
            if not isinstance(responses_layout, QVBoxLayout):
                return

            response_frame = QWidget()
            if QSizePolicy is not None:
                response_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            row_layout = QHBoxLayout(response_frame)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            response_input = QLineEdit(response_text)
            response_input.setPlaceholderText(r"要发给设备的内容，例如 admin / display version / Ctrl+A")
            delay_input = QLineEdit(str(max(0, int(response_delay or 0))))
            delay_input.setPlaceholderText("0")
            delay_input.setFixedWidth(72)
            target_combo = QComboBox()
            for label, value in self.response_target_options():
                self.add_response_target_option(target_combo, label, value)
            target_combo.setFixedWidth(160)
            response_input.setMinimumWidth(180)
            self.fit_response_target_combo_popup(target_combo)
            remove_button = QPushButton("删除")
            remove_button.setObjectName("compactGhostButton")
            remove_button.setFixedWidth(48)
            response_label = QLabel("")

            row_layout.addWidget(response_label)
            row_layout.addWidget(QLabel("到"))
            row_layout.addWidget(target_combo)
            row_layout.addWidget(response_input, 1)
            row_layout.addWidget(QLabel("等待(ms)"))
            row_layout.addWidget(delay_input)
            row_layout.addWidget(remove_button)

            row = {
                "frame": response_frame,
                "label": response_label,
                "target_combo": target_combo,
                "response_input": response_input,
                "delay_input": delay_input,
                "remove_button": remove_button,
            }
            self.set_response_target_widgets(row, response_target)
            remove_button.clicked.connect(
                lambda _checked=False, current_block=block, current_row=row: self.remove_response_row(
                    current_block,
                    current_row,
                )
            )
            response_rows = block.get("response_rows")
            if isinstance(response_rows, list):
                response_rows.append(row)
            responses_layout.addWidget(response_frame)
            self.refresh_response_row_labels(block)

        def remove_condition_block(self, block: dict[str, Any]) -> None:
            if block not in self.condition_blocks:
                return
            self.condition_blocks.remove(block)
            frame = block.get("frame")
            if isinstance(frame, QWidget):
                frame.setParent(None)
                frame.deleteLater()
            if not self.condition_blocks:
                self.add_wait_row()
            self.refresh_condition_block_titles()

        def remove_response_row(self, block: dict[str, Any], row: dict[str, Any]) -> None:
            response_rows = block.get("response_rows")
            if not isinstance(response_rows, list) or row not in response_rows:
                return
            response_rows.remove(row)
            frame = row.get("frame")
            if isinstance(frame, QWidget):
                frame.setParent(None)
                frame.deleteLater()
            if not response_rows:
                self.add_response_row(block)
                return
            self.refresh_response_row_labels(block)

        def refresh_condition_block_titles(self) -> None:
            for index, block in enumerate(self.condition_blocks, start=1):
                title_label = block.get("title_label")
                if isinstance(title_label, QLabel):
                    title_label.setText(f"第 {index} 步：等待终端输出")

        def refresh_response_row_labels(self, block: dict[str, Any]) -> None:
            response_rows = block.get("response_rows")
            if not isinstance(response_rows, list):
                return
            for index, row in enumerate(response_rows, start=1):
                label = row.get("label")
                if isinstance(label, QLabel):
                    label.setText(f"发送 {index}")

        def set_response_target_widgets(self, row: dict[str, Any], response_target: str) -> None:
            target_combo = row.get("target_combo")
            if not isinstance(target_combo, QComboBox):
                return
            target = SessionOpsMixin.normalize_auto_response_target(response_target)
            index = target_combo.findData(target)
            if index < 0 and target.startswith("title:"):
                self.add_response_target_option(target_combo, f"标题包含：{target[6:]}", target)
                self.fit_response_target_combo_popup(target_combo)
                index = target_combo.findData(target)
            target_combo.setCurrentIndex(index if index >= 0 else 0)

        def add_response_target_option(self, combo: QComboBox, label: str, value: str) -> None:
            combo.addItem(label, value)
            if Qt is None:
                return
            role_group = getattr(Qt, "ItemDataRole", Qt)
            tooltip_role = getattr(role_group, "ToolTipRole", None)
            if tooltip_role is not None:
                combo.setItemData(combo.count() - 1, label, tooltip_role)

        def fit_response_target_combo_popup(self, combo: QComboBox) -> None:
            longest_label_width = 0
            for index in range(combo.count()):
                longest_label_width = max(longest_label_width, combo.fontMetrics().horizontalAdvance(combo.itemText(index)))
            popup_width = min(max(longest_label_width + 48, 260), 560)
            combo.view().setMinimumWidth(popup_width)

        def response_target_options(self) -> list[tuple[str, str]]:
            options = [
                ("当前选中终端", "current"),
            ]
            parent = self.parent()
            if parent is None or not hasattr(parent, "ordered_session_states"):
                return options
            try:
                states = parent.ordered_session_states()
            except Exception:
                return options
            for state in states:
                if not isinstance(state, SessionTabState):
                    continue
                label = parent.session_jump_text(state) if hasattr(parent, "session_jump_text") else state.title
                options.append((f"已打开：{label}", f"session:{state.device_id}:{state.kind}:{state.title}"))
            return options

        def first_step_values(self) -> tuple[str, str]:
            for block in self.condition_blocks:
                pattern_input = block.get("pattern_input")
                response_rows = block.get("response_rows")
                if not isinstance(pattern_input, QLineEdit) or not isinstance(response_rows, list):
                    continue
                for row in response_rows:
                    response_input = row.get("response_input")
                    if isinstance(response_input, QLineEdit):
                        return pattern_input.text().strip(), response_input.text()
            return "", ""

        def steps_text(self) -> str:
            lines: list[str] = []
            for block in self.condition_blocks:
                pattern_input = block.get("pattern_input")
                response_rows = block.get("response_rows")
                if not isinstance(pattern_input, QLineEdit) or not isinstance(response_rows, list):
                    continue
                pattern = pattern_input.text().strip()
                for index, row in enumerate(response_rows):
                    response_input = row.get("response_input")
                    if not isinstance(response_input, QLineEdit):
                        continue
                    response = response_input.text()
                    if index == 0:
                        lines.append(f"{pattern} => {response}")
                    else:
                        lines.append(f"=> {response}")
            return "\n".join(lines)

        def step_targets(self) -> list[str]:
            targets: list[str] = []
            for block in self.condition_blocks:
                response_rows = block.get("response_rows")
                if not isinstance(response_rows, list):
                    continue
                for row in response_rows:
                    target_combo = row.get("target_combo")
                    if not isinstance(target_combo, QComboBox):
                        targets.append("source")
                        continue
                    targets.append(SessionOpsMixin.normalize_auto_response_target(target_combo.currentData()))
            return targets

        def step_delays(self) -> list[int]:
            delays: list[int] = []
            for block in self.condition_blocks:
                response_rows = block.get("response_rows")
                if not isinstance(response_rows, list):
                    continue
                for row in response_rows:
                    delay_input = row.get("delay_input")
                    if not isinstance(delay_input, QLineEdit):
                        delays.append(0)
                        continue
                    delays.append(self.parse_nonnegative_int(delay_input.text()))
            return delays


    class QuickSendButtonDialog(QDialog):
        """Single-form editor for a direct terminal send button."""

        def __init__(
            self,
            parent: QWidget | None = None,
            button: TerminalQuickButton | None = None,
        ) -> None:
            super().__init__(parent)
            self.setWindowTitle("编辑快捷发送按钮" if button is not None else "新增快捷发送按钮")
            self.setMinimumWidth(420)

            layout = QFormLayout(self)
            layout.setContentsMargins(18, 16, 18, 14)
            layout.setSpacing(10)

            self.name_input = QLineEdit(button.name if button is not None else "发送 Ctrl+B")
            self.response_input = QLineEdit(
                button.response_text if button is not None and button.response_text else "Ctrl+B"
            )
            self.append_enter_input = QCheckBox("发送后追加 Enter")
            self.append_enter_input.setChecked(button.append_enter if button is not None else False)
            self.response_input.setPlaceholderText(r"例如 Ctrl+B、admin、\x02、Enter")

            layout.addRow("按钮名称", self.name_input)
            layout.addRow("发送内容", self.response_input)
            layout.addRow("", self.append_enter_input)

            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addRow(buttons)

        def values(self) -> dict[str, object]:
            return {
                "name": self.name_input.text().strip(),
                "response_text": self.response_input.text(),
                "append_enter": self.append_enter_input.isChecked(),
            }


else:
    AutoResponseRuleDialog = None
    QuickSendButtonDialog = None


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
        if self.is_simulated_device(device):
            self.open_simulated_session(device)
            return
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
        if self.is_simulated_device(device):
            self.show_warning("模拟终端不支持 SSH。")
            return
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
        if self.is_simulated_device(device):
            self.open_simulated_session(device)
            return
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
        self.focus_current_terminal()
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

    def refresh_quick_auto_response_menu(self) -> None:
        menu = getattr(self, "quick_auto_response_menu", None)
        if menu is None:
            return
        menu.clear()
        state = self.current_session_state()
        rules = self.remembered_auto_response_rules

        add_quick_button_action = menu.addAction("新增发送按钮...")
        add_quick_button_action.triggered.connect(
            lambda _checked=False: self.add_quick_send_button()
        )
        add_rule_action = menu.addAction("新增规则...")
        add_rule_action.triggered.connect(
            lambda _checked=False: self.add_auto_response_rule_for_session()
        )
        boot_ctrl_b_action = menu.addAction("模板：启动菜单 Ctrl+B")
        boot_ctrl_b_action.triggered.connect(
            lambda _checked=False: self.add_boot_ctrl_b_auto_response_rule()
        )
        if not rules:
            return
        menu.addSeparator()
        for rule in rules:
            rule_menu = menu.addMenu(rule.name)
            rule_action = rule_menu.addAction("启用规则")
            rule_action.setCheckable(True)
            rule_action.setChecked(rule.enabled)
            rule_action.triggered.connect(
                lambda checked=False, current_rule=rule: self.set_auto_response_rule_enabled(
                    current_rule,
                    checked,
                )
            )
            edit_action = rule_menu.addAction("编辑规则...")
            edit_action.triggered.connect(
                lambda _checked=False, current_rule=rule: self.edit_auto_response_rule(current_rule)
            )
            delete_action = rule_menu.addAction("删除规则")
            delete_action.triggered.connect(
                lambda _checked=False, current_rule=rule: self.delete_auto_response_rule(current_rule)
            )

    def send_manual_ctrl_b(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return
        self.send_session_text(tab_id, "\x02")
        self.write_session_log_line(state, "SYS", "Manual send: Ctrl+B")
        self.set_status_message("已发送 Ctrl+B")

    def refresh_auto_response_rule_buttons(self) -> None:
        bar = getattr(self, "auto_response_rule_bar", None)
        layout = getattr(self, "auto_response_rule_bar_layout", None)
        if bar is None or layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        state = self.current_session_state()
        quick_buttons = self.remembered_quick_send_buttons
        rules = self.remembered_auto_response_rules
        if state is None and not quick_buttons and not rules:
            bar.setVisible(False)
            return

        bar.setVisible(True)
        button_index = 0
        for quick_button in quick_buttons:
            button = QToolButton()
            button.setObjectName("autoResponseRuleButton")
            button.setText(self.quick_send_button_text(quick_button))
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setToolTip(
                f"{quick_button.name}\n点击发送: {quick_button.response_text or '<原始内容>'}\n"
                "右键编辑"
            )
            button.clicked.connect(
                lambda _checked=False, current_button=quick_button: self.send_quick_button(current_button)
            )
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, current_button=quick_button, current_widget=button: self.show_quick_send_button_menu(
                    current_button,
                    current_widget,
                    pos,
                )
            )
            self.add_auto_response_bar_button(layout, button_index, button)
            button_index += 1

        for rule in rules:
            signature = self.auto_response_rule_signature(rule)
            completed_once = bool(
                state is not None
                and rule.once
                and signature in state.auto_response_triggered_rules
            )
            startup_suppressed = bool(
                state is None
                or (state.suppress_auto_response_until_input and not state.user_input_seen)
            )
            allows_startup_trigger = auto_response_rule_allows_startup_trigger(rule)
            waiting_for_input = bool(startup_suppressed and rule.enabled and not allows_startup_trigger)
            trigger_limit_reached = bool(rule.max_triggers and rule.trigger_count >= rule.max_triggers)
            effective_enabled = bool(rule.enabled and not completed_once and not waiting_for_input and not trigger_limit_reached)
            button = QToolButton()
            button.setObjectName("autoResponseRuleButton")
            button.setText(self.auto_response_rule_button_text(rule))
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setCheckable(True)
            button.setChecked(effective_enabled)
            button.setProperty("waitingForInput", "true" if waiting_for_input else "false")
            status_text = (
                "已执行，本终端不会再次自动发送；左键可重新启用"
                if completed_once
                else (
                    "触发次数已用完；左键可重新启用，右键编辑"
                    if trigger_limit_reached
                    else (
                    "已启用，等待本终端第一次用户输入后开始监听；左键停用，右键编辑"
                    if waiting_for_input
                    else f"{'启用' if rule.enabled else '停用'}，对当前选中终端生效；左键切换，右键编辑"
                    )
                )
            )
            button.setToolTip(
                f"{rule.name}\n匹配: {rule.pattern}\n"
                f"{status_text}"
            )
            button.clicked.connect(
                lambda checked=False, current_rule=rule: self.toggle_auto_response_rule_from_button(
                    current_rule,
                    checked,
                )
            )
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda pos, current_rule=rule, current_button=button: self.show_auto_response_rule_button_menu(
                    current_rule,
                    current_button,
                    pos,
                )
            )
            self.add_auto_response_bar_button(layout, button_index, button)
            button_index += 1

        layout.addStretch(1)
        layout.activate()

    @staticmethod
    def add_auto_response_bar_button(layout: Any, index: int, button: QToolButton) -> None:
        if QGridLayout is not None and isinstance(layout, QGridLayout):
            columns = 8
            layout.addWidget(button, index // columns, index % columns)
            return
        layout.addWidget(button)

    @staticmethod
    def auto_response_rule_button_text(rule: AutoResponseRule) -> str:
        name = rule.name.strip() or "规则"
        if len(name) > 8:
            name = f"{name[:7]}..."
        return name

    @staticmethod
    def quick_send_button_text(button: TerminalQuickButton) -> str:
        name = button.name.strip() or "快捷发送"
        if len(name) > 12:
            name = f"{name[:11]}..."
        return name

    def send_quick_button(self, button: TerminalQuickButton) -> None:
        state = self.current_session_state()
        if state is None:
            self.show_warning("请先打开或选中一个终端。")
            return
        self.send_session_text(state.tab_id, button.response)
        button.trigger_count += 1
        self.write_session_log_line(state, "SYS", f"Manual send: {button.name}")
        self.set_status_message(f"已发送快捷按钮: {button.name}（点击 {button.trigger_count} 次）")
        self.refresh_auto_response_rule_buttons()

    def show_quick_send_button_menu(
        self,
        quick_button: TerminalQuickButton,
        button: QToolButton,
        pos: Any,
    ) -> None:
        if quick_button not in self.remembered_quick_send_buttons:
            return
        menu = QMenu(button)
        edit_action = menu.addAction("编辑按钮...")
        reset_action = menu.addAction("清零点击次数")
        delete_action = menu.addAction("删除按钮")
        reset_action.setEnabled(bool(quick_button.trigger_count))
        chosen = menu.exec(button.mapToGlobal(pos))
        if chosen == edit_action:
            self.edit_quick_send_button(quick_button)
            return
        if chosen == reset_action:
            quick_button.trigger_count = 0
            self.schedule_desktop_state_save()
            self.refresh_auto_response_rule_buttons()
            return
        if chosen == delete_action:
            self.delete_quick_send_button(quick_button)

    def add_quick_send_button(self) -> None:
        if QuickSendButtonDialog is None:
            return
        dialog = QuickSendButtonDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        quick_button = self.create_quick_send_button(**dialog.values())
        if quick_button is None:
            return
        self.remembered_quick_send_buttons.append(quick_button)
        self.schedule_desktop_state_save()
        self.set_status_message(f"已添加快捷发送按钮: {quick_button.name}")
        self.refresh_auto_response_rule_buttons()

    def edit_quick_send_button(self, quick_button: TerminalQuickButton) -> None:
        if QuickSendButtonDialog is None:
            return
        dialog = QuickSendButtonDialog(self, quick_button)
        if dialog.exec() != QDialog.Accepted:
            return
        updated = self.create_quick_send_button(**dialog.values())
        if updated is None:
            return
        quick_button.name = updated.name
        quick_button.response = updated.response
        quick_button.response_text = updated.response_text
        quick_button.append_enter = updated.append_enter
        quick_button.trigger_count = 0
        self.schedule_desktop_state_save()
        self.set_status_message(f"已更新快捷发送按钮: {quick_button.name}")
        self.refresh_auto_response_rule_buttons()

    def delete_quick_send_button(self, quick_button: TerminalQuickButton) -> None:
        self.remembered_quick_send_buttons = [
            button for button in self.remembered_quick_send_buttons if button is not quick_button
        ]
        self.schedule_desktop_state_save()
        self.set_status_message(f"已删除快捷发送按钮: {quick_button.name}")
        self.refresh_auto_response_rule_buttons()

    def create_quick_send_button(
        self,
        *,
        name: object,
        response_text: object,
        append_enter: object = False,
    ) -> TerminalQuickButton | None:
        text = str(response_text)
        response = decode_response_text(text, append_enter=bool(append_enter))
        if not response:
            self.show_warning("发送内容不能为空。")
            return None
        return TerminalQuickButton(
            name=str(name).strip() or "快捷发送",
            response=response,
            response_text=text,
            append_enter=bool(append_enter),
        )

    def toggle_auto_response_rule_from_button(self, rule: AutoResponseRule, enabled: bool) -> None:
        if enabled:
            rule.trigger_count = 0
        self.set_auto_response_rule_enabled(rule, enabled)
        self.refresh_auto_response_rule_buttons()

    def show_auto_response_rule_button_menu(self, rule: AutoResponseRule, button: QToolButton, pos: Any) -> None:
        if rule not in self.remembered_auto_response_rules:
            return
        menu = QMenu(button)
        edit_action = menu.addAction("编辑规则...")
        delete_action = menu.addAction("删除规则")
        chosen = menu.exec(button.mapToGlobal(pos))
        if chosen == edit_action:
            self.edit_auto_response_rule(rule)
            return
        if chosen == delete_action:
            self.delete_auto_response_rule(rule)

    def delete_auto_response_rule(self, rule: AutoResponseRule) -> None:
        self.forget_auto_response_rule(rule)
        self.set_status_message(f"已删除自动响应规则: {rule.name}")
        self.refresh_auto_response_rule_buttons()

    def clear_auto_response_rules(self) -> None:
        self.remembered_auto_response_rules = []
        self.schedule_desktop_state_save()
        self.set_status_message("已清空自动响应规则")
        self.refresh_auto_response_rule_buttons()

    def set_auto_response_rule_enabled(self, rule: AutoResponseRule, enabled: bool) -> None:
        rule.enabled = enabled
        if enabled:
            rule.trigger_count = 0
            self.reset_auto_response_rule_hits(rule)
        self.remember_auto_response_rule(rule)
        reset_text = "，命中次数已清零" if enabled else ""
        self.set_status_message(f"自动响应规则已{'启用' if rule.enabled else '停用'}: {rule.name}{reset_text}")
        self.refresh_auto_response_rule_buttons()

    def add_auto_response_rule_for_session(self) -> None:
        if AutoResponseRuleDialog is None:
            return
        dialog = AutoResponseRuleDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        pattern = str(values["pattern"]).strip()
        rule = self.create_auto_response_rule(
            name=str(values["name"]),
            pattern=pattern,
            response_text=str(values["response_text"]),
            steps_text=str(values["steps_text"]),
            step_targets=list(values.get("step_targets", [])),
            step_delays=list(values.get("step_delays", [])),
            append_enter=bool(values["append_enter"]),
            case_sensitive=bool(values["case_sensitive"]),
            once=bool(values["once"]),
            allow_startup_trigger=bool(values.get("allow_startup_trigger", False)),
            match_type=str(values.get("match_type") or "contains"),
            delay_ms=int(values.get("delay_ms") or 0),
            max_triggers=int(values.get("max_triggers") or 0),
        )
        if rule is None:
            return
        self.remember_auto_response_rule(rule)
        self.set_status_message(f"已添加自动响应规则: {rule.name}")
        self.refresh_auto_response_rule_buttons()
        state = self.current_session_state()
        if state is not None:
            self.apply_auto_response_rules(state, "")

    def edit_auto_response_rule(self, rule: AutoResponseRule) -> None:
        if AutoResponseRuleDialog is None:
            return
        dialog = AutoResponseRuleDialog(self, rule)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        pattern = str(values["pattern"]).strip()
        old_signature = self.auto_response_rule_signature(rule)
        updated = self.create_auto_response_rule(
            name=str(values["name"]),
            pattern=pattern,
            response_text=str(values["response_text"]),
            steps_text=str(values["steps_text"]),
            step_targets=list(values.get("step_targets", [])),
            step_delays=list(values.get("step_delays", [])),
            append_enter=bool(values["append_enter"]),
            case_sensitive=bool(values["case_sensitive"]),
            once=bool(values["once"]),
            allow_startup_trigger=bool(values.get("allow_startup_trigger", False)),
            match_type=str(values.get("match_type") or "contains"),
            delay_ms=int(values.get("delay_ms") or 0),
            max_triggers=int(values.get("max_triggers") or 0),
        )
        if updated is None:
            return
        rule.name = updated.name
        rule.pattern = updated.pattern
        rule.response = updated.response
        rule.response_text = updated.response_text
        rule.append_enter = updated.append_enter
        rule.case_sensitive = updated.case_sensitive
        rule.once = updated.once
        rule.allow_startup_trigger = updated.allow_startup_trigger
        rule.match_type = updated.match_type
        rule.delay_ms = updated.delay_ms
        rule.max_triggers = updated.max_triggers
        rule.steps = updated.steps
        rule.enabled = True
        rule.trigger_count = 0
        self.remember_auto_response_rule(rule, old_signature=old_signature)
        self.set_status_message(f"已更新自动响应规则: {rule.name}")
        self.refresh_auto_response_rule_buttons()
        state = self.current_session_state()
        if state is not None:
            self.apply_auto_response_rules(state, "")

    def add_boot_ctrl_b_auto_response_rule(self) -> None:
        rule = self.create_auto_response_rule(
            name="启动菜单 Ctrl+B",
            pattern="Ctrl+B",
            response_text="Ctrl+B",
            case_sensitive=True,
            once=True,
            allow_startup_trigger=True,
        )
        if rule is None:
            return
        self.remember_auto_response_rule(rule)
        self.set_status_message("已添加自动响应模板: 启动菜单 Ctrl+B")
        self.refresh_auto_response_rule_buttons()

    def create_auto_response_rule(
        self,
        *,
        name: str,
        pattern: str,
        response_text: str,
        steps_text: str = "",
        step_targets: list[str] | None = None,
        step_delays: list[int] | None = None,
        append_enter: bool = False,
        case_sensitive: bool = False,
        once: bool = True,
        allow_startup_trigger: bool = False,
        match_type: str = "contains",
        delay_ms: int = 0,
        max_triggers: int = 0,
    ) -> AutoResponseRule | None:
        normalized_match_type = match_type if match_type in {"contains", "regex"} else "contains"
        try:
            normalized_delay_ms = max(0, int(delay_ms))
        except (TypeError, ValueError):
            normalized_delay_ms = 0
        try:
            normalized_max_triggers = max(0, int(max_triggers))
        except (TypeError, ValueError):
            normalized_max_triggers = 0
        steps = self.parse_auto_response_steps(
            steps_text,
            append_enter=append_enter,
            step_targets=step_targets,
            step_delays=step_delays,
        )
        if steps is None:
            return None
        if normalized_match_type == "regex":
            for pattern_candidate in [pattern, *(step.pattern for step in steps)]:
                if not pattern_candidate.strip():
                    continue
                try:
                    re.compile(pattern_candidate)
                except re.error as exc:
                    self.show_warning(f"Invalid regex pattern: {exc}")
                    return None
        if steps:
            response = steps[0].responses[0]
            response_text = steps[0].response_texts[0]
            pattern = steps[0].pattern
        else:
            if not pattern.strip():
                self.show_warning("匹配内容不能为空。")
                return None
            response = decode_response_text(response_text, append_enter=append_enter)
        if not response:
            self.show_warning("发送内容不能为空。")
            return None
        return AutoResponseRule(
            name=name.strip() or "自动响应",
            pattern=pattern.strip(),
            response=response,
            response_text=response_text,
            append_enter=append_enter,
            case_sensitive=case_sensitive,
            once=once,
            allow_startup_trigger=allow_startup_trigger,
            match_type=normalized_match_type,
            delay_ms=normalized_delay_ms,
            max_triggers=normalized_max_triggers,
            steps=steps,
        )

    def parse_auto_response_steps(
        self,
        steps_text: str,
        *,
        append_enter: bool,
        step_targets: list[str] | None = None,
        step_delays: list[int] | None = None,
    ) -> list[AutoResponseStep] | None:
        if not steps_text.strip():
            return []
        steps: list[AutoResponseStep] = []
        current_step: AutoResponseStep | None = None
        target_index = 0
        for line_number, raw_line in enumerate(steps_text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            if "=>" not in line:
                self.show_warning(f"流程步骤第 {line_number} 行缺少 =>。")
                return None
            pattern_text, response_text = line.split("=>", 1)
            pattern = pattern_text.strip()
            response_text = response_text.strip()
            if not response_text:
                self.show_warning(f"流程步骤第 {line_number} 行发送内容不能为空。")
                return None
            if pattern:
                current_step = AutoResponseStep(pattern=pattern)
                steps.append(current_step)
            elif current_step is None:
                self.show_warning(f"流程步骤第 {line_number} 行缺少匹配内容。")
                return None
            response = decode_response_text(response_text, append_enter=append_enter)
            if not response:
                self.show_warning(f"流程步骤第 {line_number} 行发送内容不能为空。")
                return None
            current_step.responses.append(response)
            current_step.response_texts.append(response_text)
            current_step.response_targets.append(
                self.normalize_auto_response_target(
                    step_targets[target_index] if step_targets and target_index < len(step_targets) else "current"
                )
            )
            try:
                response_delay = max(
                    0,
                    int(step_delays[target_index] if step_delays and target_index < len(step_delays) else 0),
                )
            except (TypeError, ValueError):
                response_delay = 0
            current_step.response_delays.append(response_delay)
            target_index += 1
        if not steps:
            self.show_warning("流程步骤不能为空。")
            return None
        return steps

    @staticmethod
    def normalize_auto_response_target(target: object) -> str:
        text = str(target or "source").strip()
        if text in {"source", "current", "next"}:
            return text
        if text.startswith("title:") and text[6:].strip():
            return f"title:{text[6:].strip()}"
        if text.startswith("session:"):
            parts = text.split(":", 3)
            if len(parts) == 4 and all(part.strip() for part in parts[1:]):
                return f"session:{parts[1].strip()}:{parts[2].strip()}:{parts[3].strip()}"
        return "source"

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
        self.refresh_auto_response_rule_buttons()

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
        if kind == "simulated":
            return "模拟"
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
        self.focus_current_terminal()
        self.refresh_session_jump_combo()
        self.set_status_message(f"已跳转到会话: {self.session_jump_text(state)}")

    def handle_session_tab_changed(self, _index: int) -> None:
        self.refresh_workspace_context()
        self._refresh_tab_header_styles()
        self.update_controls()
        state = self.current_session_state()
        if state is not None:
            self.focus_current_terminal()

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
            self.focus_current_terminal()

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
        if self.is_simulated_device(device):
            self.open_simulated_session(device)
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
        if self.is_simulated_device(device):
            self.show_warning("模拟终端不支持 Linux 后台。")
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
        if self.is_simulated_device(device):
            self.open_simulated_session(device)
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

    def open_simulated_session(self, device: Device | None = None) -> None:
        device = device if isinstance(device, Device) and self.is_simulated_device(device) else self.simulated_device()
        self.device_by_id[device.id] = device
        self.ensure_session_tab(
            kind="simulated",
            device=device,
            host="localhost",
            port=0,
            username="sim",
            password="",
        )

    @staticmethod
    def clone_auto_response_rules(rules: list[AutoResponseRule]) -> list[AutoResponseRule]:
        return [
            AutoResponseRule(
                name=rule.name,
                pattern=rule.pattern,
                response=rule.response,
                response_text=rule.response_text,
                append_enter=rule.append_enter,
                enabled=rule.enabled,
                case_sensitive=rule.case_sensitive,
                once=rule.once,
                allow_startup_trigger=rule.allow_startup_trigger,
                match_type=rule.match_type,
                delay_ms=rule.delay_ms,
                max_triggers=rule.max_triggers,
                trigger_count=0,
                steps=[
                    AutoResponseStep(
                        pattern=step.pattern,
                        responses=list(step.responses),
                        response_texts=list(step.response_texts),
                        response_targets=list(step.response_targets),
                        response_delays=list(step.response_delays),
                    )
                    for step in rule.steps
                ],
            )
            for rule in rules
        ]

    @staticmethod
    def auto_response_rule_signature(rule: AutoResponseRule) -> tuple[object, ...]:
        steps_signature = tuple(
            (
                step.pattern,
                tuple(step.responses),
                tuple(step.response_texts),
                tuple(step.response_targets),
                tuple(step.response_delays),
            )
            for step in rule.steps
        )
        return (
            rule.name,
            rule.pattern,
            rule.response,
            rule.response_text,
            rule.append_enter,
            rule.case_sensitive,
            rule.once,
            rule.allow_startup_trigger,
            rule.match_type,
            rule.delay_ms,
            rule.max_triggers,
            steps_signature,
        )

    def remember_auto_response_rule(
        self,
        rule: AutoResponseRule,
        *,
        old_signature: tuple[object, ...] | None = None,
    ) -> None:
        remembered = self.remembered_auto_response_rules
        target_signature = old_signature or self.auto_response_rule_signature(rule)
        for index, saved_rule in enumerate(remembered):
            if saved_rule is rule:
                self.schedule_desktop_state_save()
                return
            if self.auto_response_rule_signature(saved_rule) == target_signature:
                remembered[index] = self.clone_auto_response_rules([rule])[0]
                self.schedule_desktop_state_save()
                return
        remembered.append(self.clone_auto_response_rules([rule])[0])
        self.schedule_desktop_state_save()

    def reset_auto_response_rule_hits(self, rule: AutoResponseRule) -> None:
        signature = self.auto_response_rule_signature(rule)
        rule.trigger_count = 0
        for state in self.session_tabs_by_id.values():
            state.auto_response_triggered_rules.discard(signature)
            state.auto_response_rule_steps.pop(signature, None)

    def forget_auto_response_rule(self, rule: AutoResponseRule) -> None:
        target_signature = self.auto_response_rule_signature(rule)
        self.remembered_auto_response_rules = [
            saved_rule
            for saved_rule in self.remembered_auto_response_rules
            if self.auto_response_rule_signature(saved_rule) != target_signature
        ]
        self.schedule_desktop_state_save()

    @staticmethod
    def simulated_device() -> Device:
        return Device(
            id="SIM-TERMINAL",
            name="模拟终端",
            board_id="0000",
            domain="测试",
            device_type="本地终端",
            cpu="ARM",
            status="空闲",
            owner=None,
            ssh_ip="localhost",
            telnet_ip="localhost",
            username="sim",
            password="",
            vendor="本地",
            model="终端",
            site="本机",
            rack="-",
            version="V1.0",
            notes="本机终端，用于验证自动响应规则。",
        )

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
    ) -> SessionTabState | None:
        if not host:
            self.show_warning("目标地址不能为空。")
            return None

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
        self.focus_current_terminal()
        self.connect_session_tab(tab_id)
        return state

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
        if kind == "simulated":
            number = device_tab.next_session_index
            device_tab.next_session_index += 1
            return f"模拟 #{number}"
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

        terminal_mode = os.getenv("DEVICE_TUI_TERMINAL_WIDGET", "xterm").lower()
        if terminal_mode == "legacy":
            terminal = InteractiveTerminal()
        elif terminal_mode in {"canvas", "pyte"} or XtermWebWidget is None:
            terminal = TerminalCanvasWidget()
        else:
            terminal = XtermWebWidget()
        terminal.setContextMenuPolicy(Qt.CustomContextMenu)
        terminal.customContextMenuRequested.connect(
            lambda pos, tab_id=tab_id, terminal=terminal: self.show_terminal_context_menu(tab_id, terminal, pos)
        )
        layout.addWidget(terminal, 1)

        if kind == "simulated":
            session = SimulatedTerminalSession(
                SessionCallbacks(
                    on_output=lambda message, tab_id=tab_id: self.dispatch_ui(self.append_session_output, tab_id, message),
                    on_status=lambda status, tab_id=tab_id: self.dispatch_ui(self.set_session_status, tab_id, status),
                )
            )
        elif kind in {"device", "serial"}:
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

        if isinstance(state.session, LinuxSshSession) and self.defer_until_terminal_dimensions_ready(
            state,
            lambda tab_id=tab_id: self.connect_session_tab(tab_id),
        ):
            return

        state.connecting = True
        self.set_session_status(tab_id, "Connecting")
        self.write_session_log_line(state, "SYS", f"Connecting to {state.host}:{state.port}")
        self.update_controls()

        async def connect() -> tuple[str, str] | None:
            if isinstance(state.session, SimulatedTerminalSession):
                await state.session.connect()
                return None
            if isinstance(state.session, LinuxSshSession):
                candidates = state.credential_candidates or [(state.username, state.password)]
                last_error: Exception | None = None
                for index, (username, password) in enumerate(candidates, start=1):
                    try:
                        if len(candidates) > 1:
                            state.session.callbacks.on_output(
                                self.format_terminal_system_message(
                                    f"Trying SSH credential {index}/{len(candidates)}: {username}"
                                )
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
                        state.session.callbacks.on_output(
                            self.format_terminal_system_message(f"SSH credential failed: {username}")
                        )
                if last_error is not None:
                    raise last_error
                return None
            await state.session.connect(
                state.host,
                state.port,
                state.username,
                state.password,
                login_timeout_seconds=3.0 if state.kind == "serial" else 12.0,
                require_prompt=state.kind != "serial",
                setup_command=None,
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
            self.focus_current_terminal()

        def failure(exc: Exception) -> None:
            current_state = self.session_tabs_by_id.get(tab_id)
            if current_state is None:
                return
            current_state.connecting = False
            self.set_session_status(tab_id, "Disconnected")
            self.write_session_log_line(current_state, "SYS", f"Connection failed: {exc}")
            if isinstance(exc, (OSError, asyncio.TimeoutError, TelnetSessionError, SessionUnavailableError)):
                self.append_session_output(tab_id, self.format_terminal_system_message(f"连接失败: {exc}"))
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

    def defer_until_terminal_dimensions_ready(
        self,
        state: SessionTabState,
        callback: Callable[[], None],
        *,
        mark_connecting: bool = True,
    ) -> bool:
        checker = getattr(state.terminal, "has_valid_terminal_dimensions", None)
        if not callable(checker) or checker():
            state.terminal_ready_wait_attempts = 0
            return False
        state.terminal_ready_wait_attempts += 1
        if state.terminal_ready_wait_attempts > 40 or QTimer is None:
            state.terminal_ready_wait_attempts = 0
            return False
        if mark_connecting and state.terminal_ready_wait_attempts == 1:
            state.connecting = True
            self.set_session_status(state.tab_id, "Connecting")
            self.write_session_log_line(state, "SYS", "Waiting for terminal dimensions")
            self.set_status_message(f"等待终端尺寸: {state.title}")
        QTimer.singleShot(50, callback)
        return True

    @staticmethod
    def format_terminal_system_message(message: str) -> str:
        return f"\r\n=== {message} ===\r\n"

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

        if status in {"Connecting", "Connected"}:
            state.reconnect_hint_visible = False

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
        if state.reconnect_hint_visible:
            return
        state.reconnect_hint_visible = True
        state.terminal.append_output(self.format_terminal_system_message("会话已断开，按 Enter 重连"))

    def append_session_output(self, tab_id: str, message: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None or not message:
            return

        state.terminal.append_output(message)
        self.write_session_log(state, "OUT", message)
        self.apply_auto_response_rules(state, message)

    def apply_auto_response_rules(self, state: SessionTabState, message: str) -> None:
        selected_state = self.current_session_state()
        if selected_state is not None and selected_state is not state:
            return
        startup_suppressed = state.suppress_auto_response_until_input and not state.user_input_seen
        rules = self.remembered_auto_response_rules or state.auto_response_rules
        if startup_suppressed and not any(
            rule.enabled and auto_response_rule_allows_startup_trigger(rule) for rule in rules
        ):
            if message:
                state.auto_response_buffer = ""
            return
        previous_buffer = state.auto_response_buffer
        state.auto_response_buffer = (previous_buffer + message)[-4096:]
        for rule in list(rules):
            if startup_suppressed and not auto_response_rule_allows_startup_trigger(rule):
                continue
            signature = self.auto_response_rule_signature(rule)
            if rule.once and signature in state.auto_response_triggered_rules:
                continue
            if rule.max_triggers and rule.trigger_count >= rule.max_triggers:
                continue
            steps = self.effective_auto_response_steps(rule)
            if not steps:
                continue
            step_index = state.auto_response_rule_steps.get(signature, 0)
            if step_index >= len(steps):
                if rule.once:
                    state.auto_response_triggered_rules.add(signature)
                continue
            step = steps[step_index]
            scan_text = self.auto_response_scan_text(previous_buffer, message, step.pattern)
            if not self.auto_response_step_matches(rule, step, scan_text):
                continue
            rule.trigger_count += 1
            next_step_index = step_index + 1
            completed_rule = next_step_index >= len(steps)
            if next_step_index >= len(steps):
                state.auto_response_rule_steps.pop(signature, None)
                if rule.once:
                    state.auto_response_triggered_rules.add(signature)
            else:
                state.auto_response_rule_steps[signature] = next_step_index
            if rule.once and next_step_index >= len(steps):
                state.auto_response_triggered_rules.add(signature)
            if completed_rule and rule.once:
                rule.enabled = False
            if rule.max_triggers and rule.trigger_count >= rule.max_triggers:
                rule.enabled = False
            state.auto_response_buffer = ""
            self.write_session_log_line(
                state,
                "SYS",
                f"Auto response sent: {rule.name} step {step_index + 1}/{len(steps)}",
            )
            self.set_status_message(f"自动响应已发送: {rule.name}（命中 {rule.trigger_count} 次）")
            cumulative_delay_ms = max(0, int(rule.delay_ms or 0))
            for index, response in enumerate(step.responses):
                target = step.response_targets[index] if index < len(step.response_targets) else "source"
                if index < len(step.response_delays):
                    try:
                        cumulative_delay_ms += max(0, int(step.response_delays[index]))
                    except (TypeError, ValueError):
                        pass
                target_tab_id = self.auto_response_target_tab_id(state, target)
                if not target_tab_id:
                    self.write_session_log_line(state, "SYS", f"Auto response target missing: {target}")
                    self.set_status_message(f"自动响应目标终端不存在: {target}")
                    continue
                if cumulative_delay_ms > 0 and QTimer is not None:
                    QTimer.singleShot(
                        cumulative_delay_ms,
                        lambda tab_id=target_tab_id, text=response: self.send_session_text(tab_id, text),
                    )
                else:
                    self.send_session_text(target_tab_id, response)
            self.refresh_auto_response_rule_buttons()
            self.schedule_desktop_state_save()
            return

    @staticmethod
    def auto_response_scan_text(
        previous_buffer: str, message: str, pattern: str
    ) -> str:
        if not message:
            return previous_buffer
        overlap_length = max(len(pattern) - 1, 0)
        return previous_buffer[-overlap_length:] + message

    @staticmethod
    def effective_auto_response_steps(rule: AutoResponseRule) -> list[AutoResponseStep]:
        if rule.steps:
            return rule.steps
        return [
            AutoResponseStep(
                pattern=rule.pattern,
                responses=[rule.response],
                response_texts=[rule.response_text or rule.response],
                response_targets=["source"],
                response_delays=[0],
            )
        ]

    @staticmethod
    def auto_response_step_matches(
        rule: AutoResponseRule,
        step: AutoResponseStep,
        output: str,
    ) -> bool:
        if not rule.enabled or not step.pattern:
            return False
        if rule.match_type == "regex":
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            try:
                return re.search(step.pattern, output, flags) is not None
            except re.error:
                return False
        haystack = output if rule.case_sensitive else output.lower()
        needle = step.pattern if rule.case_sensitive else step.pattern.lower()
        return needle in haystack

    def auto_response_target_tab_id(self, source_state: SessionTabState, target: str) -> str:
        normalized = self.normalize_auto_response_target(target)
        if normalized == "source":
            return source_state.tab_id
        if normalized == "current":
            current = self.current_session_state()
            return current.tab_id if current is not None else source_state.tab_id
        if normalized == "next":
            same_device_states = [
                state
                for state in self.ordered_session_states()
                if state.device_id == source_state.device_id
            ]
            if not same_device_states:
                return source_state.tab_id
            for index, state in enumerate(same_device_states):
                if state.tab_id == source_state.tab_id:
                    return same_device_states[(index + 1) % len(same_device_states)].tab_id
            return same_device_states[0].tab_id
        if normalized.startswith("title:"):
            needle = normalized[6:].strip().lower()
            for state in self.ordered_session_states():
                if needle in state.title.lower() or needle in self.session_jump_text(state).lower():
                    return state.tab_id
            return ""
        if normalized.startswith("session:"):
            parts = normalized.split(":", 3)
            if len(parts) != 4:
                return ""
            _, device_id, kind, title = parts
            for state in self.ordered_session_states():
                if state.device_id == device_id and state.kind == kind and state.title == title:
                    return state.tab_id
            return ""
        return source_state.tab_id

    def send_session_text(self, tab_id: str, text: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return

        rule_buttons_need_refresh = bool(
            text and state.suppress_auto_response_until_input and not state.user_input_seen
        )
        if text:
            state.user_input_seen = True
            state.suppress_auto_response_until_input = False
            if rule_buttons_need_refresh:
                self.refresh_auto_response_rule_buttons()
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
            if isinstance(exc, (TelnetSessionError, SessionUnavailableError)):
                self.set_session_status(tab_id, "Disconnected")
                if current_state is not None:
                    self.write_session_log_line(
                        current_state, "SYS", f"Send failed: {exc}"
                    )
                    self.set_status_message(f"发送失败/会话已断开: {current_state.title}")
                return
            if current_state is not None:
                self.write_session_log_line(current_state, "SYS", f"Send failed: {exc}")
            self.handle_background_error(exc)

        self.run_coro(send(), on_error=failure)

    def reconnect_session_from_enter(self, tab_id: str) -> bool:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return False
        if state.connecting:
            self.set_status_message("正在连接中，请稍候...")
            return True
        if state.session.is_connected:
            return False
        self.refresh_session_credentials_from_panel(state)
        state.terminal.append_output(self.format_terminal_system_message("正在重连..."))
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

        if isinstance(state.session, LinuxSshSession) and self.defer_until_terminal_dimensions_ready(
            state,
            lambda tab_id=tab_id: self.reconnect_session_tab(tab_id),
            mark_connecting=False,
        ):
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
                                self.format_terminal_system_message(
                                    f"Trying SSH credential {index}/{len(candidates)}: {username}"
                                )
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
                        state.session.callbacks.on_output(
                            self.format_terminal_system_message(f"SSH credential failed: {username}")
                        )
                if last_error is not None:
                    raise last_error
                return None
            await state.session.connect(
                state.host,
                state.port,
                state.username,
                state.password,
                login_timeout_seconds=3.0 if state.kind == "serial" else 12.0,
                require_prompt=state.kind != "serial",
                setup_command=None,
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
            self.focus_current_terminal()
            self.set_status_message(f"会话已重连: {current_state.title}")

        def failure(exc: Exception) -> None:
            current_state = self.session_tabs_by_id.get(tab_id)
            if current_state is not None:
                current_state.connecting = False
                self.set_session_status(tab_id, "Disconnected")
                self.write_session_log_line(current_state, "SYS", f"Reconnect failed: {exc}")
            if isinstance(exc, (OSError, asyncio.TimeoutError, TelnetSessionError, SessionUnavailableError)):
                self.append_session_output(tab_id, self.format_terminal_system_message(f"重连失败: {exc}"))
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

    def focus_current_terminal(self, *, deferred: bool = True, force: bool = False) -> None:
        """Focus the current session terminal.

        Preserves focus on protected input widgets (search, credentials,
        command panel) unless force=True is passed.
        """
        tab_id = self.current_session_key()
        if tab_id is None:
            return
        if deferred and QTimer is not None:
            QTimer.singleShot(0, lambda tid=tab_id, forced=force: self._apply_terminal_focus(tid, forced))
        else:
            self._apply_terminal_focus(tab_id, force)

    def _apply_terminal_focus(self, tab_id: str, force: bool = False) -> None:
        """Re-lookup state by tab_id and focus, avoiding stale references."""
        if not force and self._focus_should_skip():
            return
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return
        state.terminal.setFocus()

    def _focus_should_skip(self) -> bool:
        """Return True if focus is on a protected input widget."""
        if QApplication is None:
            return False
        focused = QApplication.focusWidget()
        if focused is None:
            return False
        protected: set[object] = set()
        for attr in (
            "search_input",
            "device_username_input",
            "device_password_input",
            "serial_username_input",
            "serial_password_input",
            "linux_username_input",
            "linux_password_input",
            "command_record_input",
            "command_find_input",
            "command_replace_input",
            "temporary_name_input",
            "temporary_telnet_ip_input",
            "temporary_telnet_port_input",
            "temporary_telnet_username_input",
            "temporary_telnet_password_input",
            "temporary_ssh_ip_input",
            "temporary_ssh_port_input",
            "temporary_ssh_username_input",
            "temporary_ssh_password_input",
            "temporary_serial_ip_input",
            "temporary_serial_port_input",
            "temporary_serial_password_input",
            "temporary_notes_input",
        ):
            widget = getattr(self, attr, None)
            if widget is not None:
                protected.add(widget)
        return focused in protected

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

    def create_current_session_log(self) -> None:
        state = self.current_session_state()
        if state is None:
            self.set_status_message("当前没有可新建日志的终端会话。")
            return
        new_path = self.create_session_log(state)
        self.set_status_message(f"已新建当前会话日志: {new_path}")

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
