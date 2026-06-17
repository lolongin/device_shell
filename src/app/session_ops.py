"""Session management mixin for DeviceDesktopApp."""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from PySide6.QtCore import QObject, QEvent, QMimeData, QPoint, Qt, QTimer, QUrl, Signal, Slot
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
        QTextBrowser,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:
    QObject = None
    QEvent = None
    QMimeData = None
    QPoint = None
    Qt = None
    QTimer = None
    QUrl = None
    Signal = None
    Slot = None
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
    QTextBrowser = None
    QToolButton = None
    QVBoxLayout = None
    QWidget = None

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebChannel = None
    QWebEngineView = None

from ..app_state import DeviceTabState, SessionTabState
from ..auto_response import (
    AutoResponseAction,
    AutoResponseRule,
    AutoResponseStep,
    TerminalQuickButton,
    auto_response_rule_allows_startup_trigger,
    decode_response_text,
)
from ..auto_response_parser import (
    ParsedAutoResponseRule,
    normalize_auto_response_rule_kind,
    parse_simple_auto_response_rule,
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
            self.setObjectName("workspaceDialog")
            self.setMinimumWidth(820)
            self.resize(860, 620)

            layout = QFormLayout(self)
            layout.setContentsMargins(18, 16, 18, 14)
            layout.setSpacing(10)

            self.name_input = QLineEdit(rule.name if rule is not None else "")
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
            buttons.setObjectName("workspaceDialogButtons")
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
                "step_append_enters": self.step_append_enters(),
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
                rule.pattern if rule is not None else "",
                rule.response_text if rule is not None and rule.response_text else (
                    "Ctrl+B" if rule is not None else ""
                ),
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

        def step_append_enters(self) -> list[bool]:
            return [self.append_enter_input.isChecked() for _target in self.step_targets()]


    class AutoResponseRuleWebBridge(QObject):
        """Bridge between the web rule editor and the Python dialog."""

        payload_changed = Signal(str)
        preview_requested = Signal(str)

        def __init__(self, payload: dict[str, Any], parent: QObject | None = None) -> None:
            super().__init__(parent)
            self._payload = payload

        @Slot(result=str)
        def initialPayload(self) -> str:
            return json.dumps(self._payload, ensure_ascii=False)

        @Slot(str)
        def updatePayload(self, payload: str) -> None:
            self.payload_changed.emit(payload)

        @Slot(str)
        def requestPreviewScreen(self, payload: str) -> None:
            self.preview_requested.emit(payload)


    class AutoResponseRulePreviewDialog(QDialog):
        """Non-modal side window for the auto-response flow preview."""

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("自动响应流程图")
            self.setObjectName("workspaceDialog")
            self.setModal(False)
            self.setWindowModality(Qt.NonModal)
            self.resize(420, 680)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self.preview = QTextBrowser(self)
            self.preview.setOpenExternalLinks(False)
            self.preview.setFrameShape(QFrame.NoFrame)
            self.preview.setStyleSheet(
                """
                QTextBrowser {
                    background: #0f172a;
                    color: #f8fafc;
                    border: 1px solid #334155;
                    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                    font-size: 13px;
                }
                """
            )
            layout.addWidget(self.preview, 1)

        def show_for_owner(self, owner: QWidget) -> None:
            self._move_next_to(owner)
            self.show()
            self.raise_()
            self.activateWindow()

        def _move_next_to(self, owner: QWidget) -> None:
            owner_rect = owner.frameGeometry()
            screen = owner.screen() or QApplication.primaryScreen()
            if screen is None:
                self.move(owner_rect.right() + 12, owner_rect.top())
                return
            available = screen.availableGeometry()
            width = min(max(380, self.width()), max(380, available.width() // 3))
            height = min(max(520, owner_rect.height()), available.height())
            self.resize(width, height)
            right_x = owner_rect.right() + 12
            if right_x + width <= available.right():
                x = right_x
            else:
                x = max(available.left(), available.right() - width + 1)
            y = max(available.top(), min(owner_rect.top(), available.bottom() - height + 1))
            self.move(x, y)

        def update_payload(self, payload: dict[str, Any]) -> None:
            self.preview.setHtml(self.preview_html(payload))

        @classmethod
        def preview_html(cls, payload: dict[str, Any]) -> str:
            target_labels = {
                str(item.get("value")): str(item.get("label"))
                for item in payload.get("targets", [])
                if isinstance(item, dict)
            }
            lines = [
                "<html><head><style>",
                "body{margin:0;padding:14px;background:#0f172a;color:#f8fafc;}",
                ".title{font-weight:700;font-size:15px;margin-bottom:10px;}",
                ".flow{display:block;}",
                ".node{border:1px solid #243244;background:#08101d;border-radius:8px;padding:8px 10px;margin:0;}",
                ".node.start{border-color:rgba(34,197,94,.62);background:rgba(34,197,94,.14);}",
                ".node.send .node-title,.node.condition .node-title{color:#d8fff0;}",
                ".node.loop .node-title,.node.wait .node-title{color:#f8e7a1;}",
                ".node.exit .node-title{color:#fecaca;}",
                ".node-title{display:block;font-weight:700;}",
                ".meta{display:block;color:#a7b4c7;font-size:12px;margin-top:4px;}",
                ".connector{text-align:center;color:#718096;line-height:1.7;}",
                ".children{border-left:2px solid #334155;margin:7px 0 0 8px;padding-left:10px;}",
                "</style></head><body>",
                '<div class="title">流程图副屏</div>',
                '<div class="flow">',
            ]
            trigger_type = str(payload.get("triggerType") or "match")
            if trigger_type == "manual":
                name = str(payload.get("name") or "未命名按钮")
                lines.append(cls.node_html("start", f"开始：点击按钮 {name}"))
            else:
                pattern = str(payload.get("triggerPattern") or payload.get("pattern") or "未填写")
                lines.append(cls.node_html("start", f"开始：终端输出包含 {pattern}"))
            actions = payload.get("actions")
            if not isinstance(actions, list) or not actions:
                lines.append(cls.connector_html())
                lines.append(cls.node_html("wait", "尚未添加动作", "从左侧添加发送、等待、判断或循环"))
            else:
                for action in actions:
                    lines.append(cls.connector_html())
                    lines.append(cls.action_html(action, target_labels))
            if bool(payload.get("once", True)):
                lines.append(cls.connector_html())
                lines.append(cls.node_html("wait", "执行后停用本规则", "避免重复触发"))
            lines.append(cls.connector_html())
            lines.append(cls.node_html("end", "结束"))
            lines.append("</div></body></html>")
            return "".join(lines)

        @staticmethod
        def connector_html() -> str:
            return '<div class="connector">↓</div>'

        @staticmethod
        def int_value(value: object, fallback: int = 0) -> int:
            try:
                return max(0, int(str(value).strip() or str(fallback)))
            except (TypeError, ValueError):
                return fallback

        @classmethod
        def node_html(cls, kind: str, title: str, meta: str = "") -> str:
            meta_html = f'<span class="meta">{html.escape(meta)}</span>' if meta else ""
            return (
                f'<div class="node {html.escape(kind)}">'
                f'<span class="node-title">{html.escape(title)}</span>{meta_html}</div>'
            )

        @classmethod
        def action_html(cls, action: object, target_labels: dict[str, str]) -> str:
            if not isinstance(action, dict):
                return cls.node_html("wait", "未知动作")
            kind = str(action.get("kind") or "send")
            if kind == "send":
                text = str(action.get("text") or "未填写")
                target = target_labels.get(str(action.get("target") or "current"), "当前选中终端")
                delay = cls.int_value(action.get("delayMs") or action.get("delay_ms"))
                enter = "，追加 Enter" if bool(action.get("appendEnter") or action.get("append_enter")) else ""
                wait = f"，发送前等待 {delay} ms" if delay else ""
                return cls.node_html("send", f"发送 {text}", f"发送到 {target}{wait}{enter}")
            if kind == "wait":
                return cls.node_html("wait", f"等待 {cls.int_value(action.get('delayMs'))} ms", "延迟一段时间再继续")
            if kind == "exit":
                scope = "停止整个规则" if action.get("exitScope") == "rule" else "退出当前循环"
                return cls.node_html("exit", f"退出：{str(action.get('exitPattern') or '未填写')}", scope)
            if kind in {"condition", "loop"}:
                children = action.get("actions")
                child_count = len(children) if isinstance(children, list) else 0
                if kind == "condition":
                    title = f"判断：{str(action.get('conditionPattern') or '未填写')}"
                    meta = f"命中后执行 {child_count} 个动作"
                else:
                    repeat = cls.int_value(action.get("repeatCount"), 1)
                    title = "一直循环" if repeat == 0 else f"循环 {repeat} 次"
                    meta = f"每轮间隔 {cls.int_value(action.get('intervalMs'))} ms，包含 {child_count} 个动作"
                inner = [cls.node_html(kind, title, meta)]
                if isinstance(children, list) and children:
                    inner.append('<div class="children">')
                    for index, child in enumerate(children):
                        if index > 0:
                            inner.append(cls.connector_html())
                        inner.append(cls.action_html(child, target_labels))
                    inner.append("</div>")
                return "".join(inner)
            return cls.node_html("wait", f"未知动作：{kind}")


    class AutoResponseRuleWebDialog(QDialog):
        """Web-based editor for auto-response workflow rules."""

        def __init__(
            self,
            parent: QWidget | None = None,
            rule: AutoResponseRule | None = None,
        ) -> None:
            if QWebChannel is None or QWebEngineView is None or QUrl is None:
                raise RuntimeError("QWebEngineView is not available")
            super().__init__(parent)
            self.setWindowTitle("编辑自动响应规则" if rule is not None else "新增自动响应规则")
            self.setObjectName("workspaceDialog")
            self.setModal(False)
            self.setWindowModality(Qt.NonModal)
            self.setMinimumSize(1180, 760)
            self.resize(1280, 860)

            self._payload = self.payload_from_rule(rule, parent)
            self._preview_dialog: AutoResponseRulePreviewDialog | None = None
            self._bridge = AutoResponseRuleWebBridge(self._payload, self)
            self._bridge.payload_changed.connect(self._set_payload_from_json)
            self._bridge.preview_requested.connect(self._show_preview_screen)

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self.web_view = QWebEngineView(self)
            self.web_channel = QWebChannel(self.web_view.page())
            self.web_channel.registerObject("autoResponseBridge", self._bridge)
            self.web_view.page().setWebChannel(self.web_channel)
            layout.addWidget(self.web_view, 1)

            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.setObjectName("workspaceDialogButtons")
            buttons.setContentsMargins(16, 10, 16, 12)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

            editor_path = Path(__file__).resolve().parents[1] / "web" / "auto_response_editor.html"
            self.web_view.load(QUrl.fromLocalFile(str(editor_path)))

        def _set_payload_from_json(self, payload: str) -> None:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return
            if isinstance(data, dict):
                self._payload = data
                if self._preview_dialog is not None and self._preview_dialog.isVisible():
                    self._preview_dialog.update_payload(self._payload)

        def _show_preview_screen(self, payload: str) -> None:
            self._set_payload_from_json(payload)
            if self._preview_dialog is None:
                self._preview_dialog = AutoResponseRulePreviewDialog(self)
            self._preview_dialog.update_payload(self._payload)
            self._preview_dialog.show_for_owner(self)

        def _close_preview_screen(self) -> None:
            if self._preview_dialog is not None:
                self._preview_dialog.close()

        def accept(self) -> None:
            name = str(self._payload.get("name") or "").strip()
            if not name:
                if QMessageBox is not None:
                    QMessageBox.warning(self, "规则名称", "规则名称需要手动填写。")
                field_id = "manualButtonName" if self._payload.get("triggerType") == "manual" else "ruleName"
                self.web_view.page().runJavaScript(
                    f"document.getElementById('{field_id}')?.focus();"
                )
                return
            self._close_preview_screen()
            super().accept()

        def reject(self) -> None:
            self._close_preview_screen()
            super().reject()

        def closeEvent(self, event: Any) -> None:  # noqa: N802
            self._close_preview_screen()
            super().closeEvent(event)

        def values(self) -> dict[str, object]:
            return self.values_from_payload(self._payload)

        @staticmethod
        def parse_nonnegative_int(value: object) -> int:
            try:
                return max(0, int(str(value).strip() or "0"))
            except (TypeError, ValueError):
                return 0

        @classmethod
        def payload_from_rule(
            cls,
            rule: AutoResponseRule | None,
            parent: QWidget | None = None,
        ) -> dict[str, Any]:
            steps = cls.steps_payload_from_rule(rule)
            return {
                "name": rule.name if rule is not None else "",
                "matchType": rule.match_type if rule is not None else "contains",
                "appendEnter": rule.append_enter if rule is not None else False,
                "caseSensitive": rule.case_sensitive if rule is not None else True,
                "once": rule.once if rule is not None else True,
                "allowStartupTrigger": rule.allow_startup_trigger if rule is not None else False,
                "delayMs": rule.delay_ms if rule is not None else 0,
                "maxTriggers": rule.max_triggers if rule is not None else 0,
                "triggerType": rule.trigger_type if rule is not None else "match",
                "triggerDelayMs": rule.trigger_delay_ms if rule is not None else 0,
                "loopCount": rule.loop_count if rule is not None else 1,
                "kind": rule.kind if rule is not None else "capture",
                "simpleRuleText": cls.simple_rule_text_from_rule(rule),
                "steps": steps,
                "actions": cls.actions_payload_from_rule(rule),
                "targets": cls.response_target_payload(parent),
            }

        @staticmethod
        def simple_rule_text_from_rule(rule: AutoResponseRule | None) -> str:
            if rule is None:
                return ""
            response_text = rule.response_text or rule.response
            if rule.kind == "manual_loop" or rule.trigger_type == "manual":
                if rule.loop_count > 1:
                    delay = 0
                    if rule.steps and rule.steps[0].response_delays:
                        delay = rule.steps[0].response_delays[0]
                    suffix = f"，每 {delay}ms" if delay > 0 else ""
                    return f"手动循环 {rule.loop_count} 次{suffix} => {response_text}"
                return f"手动 => {response_text}"
            if rule.trigger_type == "connected":
                return f"连接后 => {response_text}"
            if rule.trigger_type == "delay":
                return f"延时 {rule.trigger_delay_ms}ms => {response_text}"
            pattern = rule.pattern or (rule.steps[0].pattern if rule.steps else "")
            return f'看到 "{pattern}" => {response_text}' if pattern else f"手动 => {response_text}"

        @staticmethod
        def steps_payload_from_rule(rule: AutoResponseRule | None) -> list[dict[str, Any]]:
            if rule is not None and rule.steps:
                return [
                    {
                        "pattern": step.pattern,
                        "responses": [
                            {
                                "text": response_text,
                                "target": step.response_targets[index]
                                if index < len(step.response_targets)
                                else "current",
                                "delay": step.response_delays[index]
                                if index < len(step.response_delays)
                                else 0,
                                "appendEnter": step.response_append_enters[index]
                                if index < len(step.response_append_enters)
                                else (rule.append_enter if rule is not None else False),
                            }
                            for index, response_text in enumerate(step.response_texts or [""])
                        ],
                    }
                    for step in rule.steps
                ]
            pattern = rule.pattern if rule is not None else ""
            response = rule.response_text if rule is not None and rule.response_text else (
                "Ctrl+B" if rule is not None else ""
            )
            append_enter = rule.append_enter if rule is not None else False
            return [
                {
                    "pattern": pattern,
                    "responses": [
                        {"text": response, "target": "current", "delay": 0, "appendEnter": append_enter}
                    ],
                }
            ]

        @classmethod
        def actions_payload_from_rule(cls, rule: AutoResponseRule | None) -> list[dict[str, Any]]:
            if rule is not None and rule.actions:
                return [cls.action_payload_from_action(action) for action in rule.actions]
            if rule is None:
                return [
                    {
                        "kind": "send",
                        "text": "",
                        "target": "current",
                        "delayMs": 0,
                        "appendEnter": False,
                    }
                ]
            return cls.actions_payload_from_steps(rule)

        @classmethod
        def actions_payload_from_steps(cls, rule: AutoResponseRule) -> list[dict[str, Any]]:
            actions: list[dict[str, Any]] = []
            for step in rule.steps:
                for index, response_text in enumerate(step.response_texts):
                    actions.append(
                        {
                            "kind": "send",
                            "text": response_text,
                            "target": step.response_targets[index]
                            if index < len(step.response_targets)
                            else "current",
                            "delayMs": step.response_delays[index]
                            if index < len(step.response_delays)
                            else 0,
                            "appendEnter": step.response_append_enters[index]
                            if index < len(step.response_append_enters)
                            else rule.append_enter,
                        }
                    )
            if actions:
                return actions
            return [
                {
                    "kind": "send",
                    "text": rule.response_text or rule.response,
                    "target": "current",
                    "delayMs": 0,
                    "appendEnter": rule.append_enter,
                }
            ]

        @classmethod
        def action_payload_from_action(cls, action: AutoResponseAction) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "kind": action.kind,
                "text": action.text,
                "target": action.target,
                "delayMs": action.delay_ms,
                "appendEnter": action.append_enter,
                "repeatCount": action.repeat_count,
                "intervalMs": action.interval_ms,
                "exitPattern": action.exit_pattern,
                "exitScope": action.exit_scope,
                "conditionPattern": action.condition_pattern,
                "conditionMatchType": action.condition_match_type,
            }
            if action.actions:
                payload["actions"] = [cls.action_payload_from_action(child) for child in action.actions]
            return payload

        @staticmethod
        def response_target_payload(parent: QWidget | None) -> list[dict[str, str]]:
            targets = [{"label": "当前选中终端", "value": "current"}]
            if parent is None or not hasattr(parent, "ordered_session_states"):
                return targets
            try:
                states = parent.ordered_session_states()
            except Exception:
                return targets
            for state in states:
                if not isinstance(state, SessionTabState):
                    continue
                label = parent.session_jump_text(state) if hasattr(parent, "session_jump_text") else state.title
                targets.append(
                    {
                        "label": f"已打开：{label}",
                        "value": f"session:{state.device_id}:{state.kind}:{state.title}",
                    }
                )
            return targets

        @classmethod
        def values_from_payload(cls, payload: dict[str, Any]) -> dict[str, object]:
            actions_payload = payload.get("actions")
            if isinstance(actions_payload, list) and actions_payload:
                first_send = cls.first_send_action_payload(actions_payload)
                return {
                    "name": str(payload.get("name") or "").strip(),
                    "pattern": str(payload.get("triggerPattern") or payload.get("pattern") or "").strip(),
                    "response_text": str((first_send or {}).get("text") or ""),
                    "steps_text": "",
                    "step_targets": [],
                    "step_delays": [],
                    "step_append_enters": [],
                    "append_enter": bool((first_send or {}).get("appendEnter", payload.get("appendEnter", False))),
                    "case_sensitive": bool(payload.get("caseSensitive", True)),
                    "once": bool(payload.get("once", True)),
                    "allow_startup_trigger": bool(payload.get("allowStartupTrigger")),
                    "match_type": str(payload.get("matchType") or "contains"),
                    "delay_ms": cls.parse_nonnegative_int(payload.get("delayMs")),
                    "max_triggers": cls.parse_nonnegative_int(payload.get("maxTriggers")),
                    "trigger_type": str(payload.get("triggerType") or "match"),
                    "trigger_delay_ms": cls.parse_nonnegative_int(payload.get("triggerDelayMs")),
                    "loop_count": max(1, min(10, cls.parse_nonnegative_int(payload.get("loopCount")) or 1)),
                    "kind": normalize_auto_response_rule_kind(payload.get("kind")) or "advanced",
                    "simple_rule_text": str(payload.get("simpleRuleText") or ""),
                    "actions": actions_payload,
                }
            steps = payload.get("steps")
            if not isinstance(steps, list) or not steps:
                steps = [{"pattern": "", "responses": [{"text": "", "target": "current", "delay": 0}]}]
            lines: list[str] = []
            step_targets: list[str] = []
            step_delays: list[int] = []
            step_append_enters: list[bool] = []
            first_pattern = ""
            first_response = ""
            first_seen = False
            for step in steps:
                if not isinstance(step, dict):
                    continue
                pattern = str(step.get("pattern") or "").strip()
                responses = step.get("responses")
                if not isinstance(responses, list) or not responses:
                    responses = [{"text": "", "target": "current", "delay": 0}]
                for index, response in enumerate(responses):
                    if not isinstance(response, dict):
                        response = {}
                    text = str(response.get("text") or "")
                    lines.append(f"{pattern} => {text}" if index == 0 else f"=> {text}")
                    step_targets.append(SessionOpsMixin.normalize_auto_response_target(response.get("target")))
                    step_delays.append(cls.parse_nonnegative_int(response.get("delay")))
                    step_append_enters.append(bool(response.get("appendEnter")))
                    if not first_seen:
                        first_pattern = pattern
                        first_response = text
                        first_seen = True
            return {
                "name": str(payload.get("name") or "").strip(),
                "pattern": first_pattern,
                "response_text": first_response,
                "steps_text": "\n".join(lines),
                "step_targets": step_targets,
                "step_delays": step_delays,
                "step_append_enters": step_append_enters,
                "append_enter": any(step_append_enters) if step_append_enters else bool(payload.get("appendEnter")),
                "case_sensitive": bool(payload.get("caseSensitive", True)),
                "once": bool(payload.get("once", True)),
                "allow_startup_trigger": bool(payload.get("allowStartupTrigger")),
                "match_type": str(payload.get("matchType") or "contains"),
                "delay_ms": cls.parse_nonnegative_int(payload.get("delayMs")),
                "max_triggers": cls.parse_nonnegative_int(payload.get("maxTriggers")),
                "trigger_type": str(payload.get("triggerType") or "match"),
                "trigger_delay_ms": cls.parse_nonnegative_int(payload.get("triggerDelayMs")),
                "loop_count": max(1, min(10, cls.parse_nonnegative_int(payload.get("loopCount")) or 1)),
                "kind": normalize_auto_response_rule_kind(payload.get("kind")),
                "simple_rule_text": str(payload.get("simpleRuleText") or ""),
                "actions": actions_payload if isinstance(actions_payload, list) else [],
            }

        @classmethod
        def first_send_action_payload(cls, actions: list[Any]) -> dict[str, Any] | None:
            for action in actions:
                if not isinstance(action, dict):
                    continue
                if str(action.get("kind") or "").lower() == "send":
                    return action
                children = action.get("actions")
                if isinstance(children, list):
                    found = cls.first_send_action_payload(children)
                    if found is not None:
                        return found
            return None


    class QuickSendButtonDialog(QDialog):
        """Single-form editor for a direct terminal send button."""

        def __init__(
            self,
            parent: QWidget | None = None,
            button: TerminalQuickButton | None = None,
        ) -> None:
            super().__init__(parent)
            self.setWindowTitle("编辑快捷发送按钮" if button is not None else "新增快捷发送按钮")
            self.setObjectName("workspaceDialog")
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
            buttons.setObjectName("workspaceDialogButtons")
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
    AutoResponseRuleWebDialog = None
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

        menu = self.new_workspace_menu(terminal, self.session_display_title(state, self.session_kind_label(state.kind)), "terminal")
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
        menu = self.new_workspace_menu(widget, self.temporary_device_display_name(device), "session-device")
        close_action = menu.addAction("关闭此会话")
        close_other_action = menu.addAction("关闭其他会话")
        close_all_action = menu.addAction("关闭全部会话")
        menu.addSeparator()
        actions = self._add_device_quick_actions(menu)
        self.update_device_quick_actions_for_device(actions, device)
        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == close_action:
            self.close_session_tab(tab_id)
            return
        if chosen == close_other_action:
            self.close_other_session_tabs(tab_id)
            return
        if chosen == close_all_action:
            self.close_all_session_tabs()
            return
        self._handle_device_quick_action(chosen, actions, device)

    def show_web_session_context_menu(self, tab_id: str, global_x: int, global_y: int) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None or QPoint is None:
            return
        device = self.get_device_by_id(state.device_id)
        if device is None:
            return
        self.jump_to_session(tab_id)
        menu = self.new_workspace_menu(self, self.temporary_device_display_name(device), "session-device")
        close_action = menu.addAction("关闭此会话")
        close_other_action = menu.addAction("关闭其他会话")
        close_all_action = menu.addAction("关闭全部会话")
        menu.addSeparator()
        actions = self._add_device_quick_actions(menu)
        self.update_device_quick_actions_for_device(actions, device)
        chosen = menu.exec(QPoint(global_x, global_y))
        if chosen is None:
            return
        if chosen == close_action:
            self.close_session_tab(tab_id)
            return
        if chosen == close_other_action:
            self.close_other_session_tabs(tab_id)
            return
        if chosen == close_all_action:
            self.close_all_session_tabs()
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
        self.refresh_terminal_web_actions()
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
            is_running = bool(state is not None and signature in state.auto_response_running_rules)
            startup_suppressed = bool(
                state is None
                or (state.suppress_auto_response_until_input and not state.user_input_seen)
            )
            allows_startup_trigger = auto_response_rule_allows_startup_trigger(rule)
            waiting_for_input = bool(startup_suppressed and rule.enabled and not allows_startup_trigger)
            trigger_limit_reached = bool(rule.max_triggers and rule.trigger_count >= rule.max_triggers)
            effective_enabled = bool(
                is_running
                or (rule.enabled and not completed_once and not waiting_for_input and not trigger_limit_reached)
            )
            is_manual_rule = rule.trigger_type == "manual"
            button = QToolButton()
            button.setObjectName("autoResponseRuleButton")
            button.setText(self.auto_response_rule_button_text(rule))
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setCheckable(True)
            button.setChecked(is_running if is_manual_rule else effective_enabled)
            button.setProperty("waitingForInput", "true" if waiting_for_input else "false")
            button.setProperty("running", "true" if is_running else "false")
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

    def refresh_terminal_web_actions(self) -> None:
        for state in getattr(self, "session_tabs_by_id", {}).values():
            terminal = getattr(state, "terminal", None)
            if hasattr(terminal, "refresh_terminal_actions"):
                terminal.refresh_terminal_actions()

    def terminal_web_actions(self, state: SessionTabState) -> list[dict[str, object]]:
        actions: list[dict[str, object]] = []
        for index, quick_button in enumerate(self.remembered_quick_send_buttons):
            actions.append(
                {
                    "kind": "quick",
                    "index": index,
                    "label": self.quick_send_button_text(quick_button),
                    "title": (
                        f"{quick_button.name}\n"
                        f"点击发送: {quick_button.response_text or '<原始内容>'}\n"
                        f"已点击 {quick_button.trigger_count} 次"
                    ),
                    "enabled": True,
                    "checked": False,
                    "status": "quick",
                }
            )

        for index, rule in enumerate(self.remembered_auto_response_rules):
            status = self.auto_response_rule_effective_status(rule, state)
            actions.append(
                {
                    "kind": "rule",
                    "index": index,
                    "label": self.auto_response_rule_button_text(rule),
                    "title": self.auto_response_rule_action_tooltip(rule, status),
                    "enabled": bool(status["clickable"]),
                    "checked": bool(status["effective_enabled"]),
                    "status": status["status"],
                }
            )
        return actions

    def auto_response_rule_effective_status(
        self,
        rule: AutoResponseRule,
        state: SessionTabState | None,
    ) -> dict[str, object]:
        signature = self.auto_response_rule_signature(rule)
        completed_once = bool(
            state is not None
            and rule.once
            and signature in state.auto_response_triggered_rules
        )
        is_running = bool(state is not None and signature in state.auto_response_running_rules)
        startup_suppressed = bool(
            state is None
            or (state.suppress_auto_response_until_input and not state.user_input_seen)
        )
        allows_startup_trigger = auto_response_rule_allows_startup_trigger(rule)
        waiting_for_input = bool(startup_suppressed and rule.enabled and not allows_startup_trigger)
        trigger_limit_reached = bool(rule.max_triggers and rule.trigger_count >= rule.max_triggers)
        effective_enabled = bool(
            is_running
            or (rule.enabled and not completed_once and not waiting_for_input and not trigger_limit_reached)
        )
        if is_running:
            status = "running"
        elif rule.trigger_type == "manual":
            status = "manual"
            effective_enabled = False
        elif completed_once:
            status = "completed"
        elif trigger_limit_reached:
            status = "exhausted"
        elif waiting_for_input:
            status = "waiting"
        elif effective_enabled:
            status = "enabled"
        else:
            status = "disabled"
        return {
            "completed_once": completed_once,
            "waiting_for_input": waiting_for_input,
            "trigger_limit_reached": trigger_limit_reached,
            "running": is_running,
            "effective_enabled": effective_enabled,
            "clickable": True,
            "status": status,
        }

    def auto_response_rule_action_tooltip(self, rule: AutoResponseRule, status: dict[str, object]) -> str:
        state_text = {
            "completed": "已执行，本终端不会再次自动发送；点击可重新启用",
            "exhausted": "触发次数已用完；点击可重新启用",
            "waiting": "已启用，等待本终端第一次用户输入后开始监听；点击可停用",
            "enabled": "已启用，对本终端生效；点击停用",
            "disabled": "已停用；点击启用",
        }.get(str(status.get("status")), "")
        if str(status.get("status")) == "running":
            state_text = "正在运行；点击停止"
        if str(status.get("status")) == "manual":
            state_text = "点击运行手动自动化"
        return f"{rule.name}\n匹配: {rule.pattern}\n{state_text}"

    def handle_terminal_web_action(self, tab_id: str, action: dict[str, object]) -> None:
        kind = str(action.get("kind") or "")
        try:
            index = int(action.get("index", -1))
        except (TypeError, ValueError):
            return
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            return
        if kind == "quick":
            if 0 <= index < len(self.remembered_quick_send_buttons):
                self.send_quick_button_to_state(self.remembered_quick_send_buttons[index], state)
            return
        if kind == "rule":
            if 0 <= index < len(self.remembered_auto_response_rules):
                checked = bool(action.get("checked"))
                self.toggle_auto_response_rule_from_button(self.remembered_auto_response_rules[index], checked)

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
        self.send_quick_button_to_state(button, state)

    def send_quick_button_to_state(self, button: TerminalQuickButton, state: SessionTabState) -> None:
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
        menu = self.new_workspace_menu(button, button.text() or "快捷发送", "quick-send")
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
        state = self.current_session_state()
        if state is not None and self.auto_response_rule_signature(rule) in state.auto_response_running_rules:
            self.stop_auto_response_rule_run(state, rule)
            if rule.trigger_type != "manual" and not enabled:
                rule.enabled = False
                self.remember_auto_response_rule(rule)
            self.refresh_auto_response_rule_buttons()
            return
        if rule.trigger_type == "manual":
            if state is not None:
                rule.enabled = True
                state.auto_response_triggered_rules.discard(self.auto_response_rule_signature(rule))
                self.apply_auto_response_rules(state, "", trigger_event="manual")
            self.refresh_auto_response_rule_buttons()
            return
        if enabled:
            rule.trigger_count = 0
        self.set_auto_response_rule_enabled(rule, enabled)
        self.refresh_auto_response_rule_buttons()

    def show_auto_response_rule_button_menu(self, rule: AutoResponseRule, button: QToolButton, pos: Any) -> None:
        if rule not in self.remembered_auto_response_rules:
            return
        menu = self.new_workspace_menu(button, button.text() or "自动响应", "auto-response")
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
        dialog_class = self.auto_response_rule_dialog_class()
        if dialog_class is None:
            return
        dialog = dialog_class(self)
        if self.show_auto_response_rule_dialog_non_modal(
            dialog,
            self.apply_added_auto_response_rule_values,
        ):
            return
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        rule_kind = normalize_auto_response_rule_kind(values.get("kind"))
        if rule_kind == "quick_send":
            quick_button = self.create_quick_send_button_from_rule_values(values)
            if quick_button is None:
                return
            self.remembered_quick_send_buttons.append(quick_button)
            self.schedule_desktop_state_save()
            self.set_status_message(f"已添加快捷发送按钮: {quick_button.name}")
            self.refresh_auto_response_rule_buttons()
            return
        pattern = str(values["pattern"]).strip()
        rule = self.create_auto_response_rule(
            name=str(values["name"]),
            pattern=pattern,
            response_text=str(values["response_text"]),
            steps_text=str(values["steps_text"]),
            step_targets=list(values.get("step_targets", [])),
            step_delays=list(values.get("step_delays", [])),
            step_append_enters=list(values.get("step_append_enters", [])),
            append_enter=bool(values["append_enter"]),
            case_sensitive=bool(values["case_sensitive"]),
            once=bool(values["once"]),
            allow_startup_trigger=bool(values.get("allow_startup_trigger", False)),
            match_type=str(values.get("match_type") or "contains"),
            delay_ms=int(values.get("delay_ms") or 0),
            max_triggers=int(values.get("max_triggers") or 0),
            trigger_type=str(values.get("trigger_type") or "match"),
            trigger_delay_ms=int(values.get("trigger_delay_ms") or 0),
            loop_count=int(values.get("loop_count") or 1),
            kind=rule_kind,
            simple_rule_text=str(values.get("simple_rule_text") or ""),
            actions=list(values.get("actions", [])),
        )
        if rule is None:
            return
        self.remember_auto_response_rule(rule)
        self.set_status_message(f"已添加自动响应规则: {rule.name}")
        self.refresh_auto_response_rule_buttons()
        state = self.current_session_state()
        if state is not None:
            self.apply_auto_response_rules(state, "", trigger_event="immediate")

    def edit_auto_response_rule(self, rule: AutoResponseRule) -> None:
        dialog_class = self.auto_response_rule_dialog_class()
        if dialog_class is None:
            return
        dialog = dialog_class(self, rule)
        if self.show_auto_response_rule_dialog_non_modal(
            dialog,
            lambda values, current_rule=rule: self.apply_edited_auto_response_rule_values(current_rule, values),
        ):
            return
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        rule_kind = normalize_auto_response_rule_kind(values.get("kind"))
        if rule_kind == "quick_send":
            quick_button = self.create_quick_send_button_from_rule_values(values)
            if quick_button is None:
                return
            self.forget_auto_response_rule(rule)
            self.remembered_quick_send_buttons.append(quick_button)
            self.schedule_desktop_state_save()
            self.set_status_message(f"已转换为快捷发送按钮: {quick_button.name}")
            self.refresh_auto_response_rule_buttons()
            return
        pattern = str(values["pattern"]).strip()
        old_signature = self.auto_response_rule_signature(rule)
        updated = self.create_auto_response_rule(
            name=str(values["name"]),
            pattern=pattern,
            response_text=str(values["response_text"]),
            steps_text=str(values["steps_text"]),
            step_targets=list(values.get("step_targets", [])),
            step_delays=list(values.get("step_delays", [])),
            step_append_enters=list(values.get("step_append_enters", [])),
            append_enter=bool(values["append_enter"]),
            case_sensitive=bool(values["case_sensitive"]),
            once=bool(values["once"]),
            allow_startup_trigger=bool(values.get("allow_startup_trigger", False)),
            match_type=str(values.get("match_type") or "contains"),
            delay_ms=int(values.get("delay_ms") or 0),
            max_triggers=int(values.get("max_triggers") or 0),
            trigger_type=str(values.get("trigger_type") or "match"),
            trigger_delay_ms=int(values.get("trigger_delay_ms") or 0),
            loop_count=int(values.get("loop_count") or 1),
            kind=rule_kind,
            simple_rule_text=str(values.get("simple_rule_text") or ""),
            actions=list(values.get("actions", [])),
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
        rule.trigger_type = updated.trigger_type
        rule.trigger_delay_ms = updated.trigger_delay_ms
        rule.loop_count = updated.loop_count
        rule.kind = updated.kind
        rule.steps = updated.steps
        rule.actions = updated.actions
        rule.enabled = True
        rule.trigger_count = 0
        self.remember_auto_response_rule(rule, old_signature=old_signature)
        self.set_status_message(f"已更新自动响应规则: {rule.name}")
        self.refresh_auto_response_rule_buttons()
        state = self.current_session_state()
        if state is not None:
            self.apply_auto_response_rules(state, "", trigger_event="immediate")

    def show_auto_response_rule_dialog_non_modal(
        self,
        dialog: QDialog,
        on_accept: Callable[[dict[str, object]], None],
    ) -> bool:
        if AutoResponseRuleWebDialog is None or not isinstance(dialog, AutoResponseRuleWebDialog):
            return False
        dialogs = getattr(self, "_auto_response_rule_dialogs", None)
        if dialogs is None:
            dialogs = []
            self._auto_response_rule_dialogs = dialogs
        dialogs.append(dialog)

        def cleanup() -> None:
            if dialog in dialogs:
                dialogs.remove(dialog)
            dialog.deleteLater()

        dialog.accepted.connect(lambda current_dialog=dialog: on_accept(current_dialog.values()))
        dialog.finished.connect(lambda _result: cleanup())
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True

    def apply_added_auto_response_rule_values(self, values: dict[str, object]) -> None:
        rule_kind = normalize_auto_response_rule_kind(values.get("kind"))
        if rule_kind == "quick_send":
            quick_button = self.create_quick_send_button_from_rule_values(values)
            if quick_button is None:
                return
            self.remembered_quick_send_buttons.append(quick_button)
            self.schedule_desktop_state_save()
            self.set_status_message(f"已添加快捷发送按钮: {quick_button.name}")
            self.refresh_auto_response_rule_buttons()
            return
        rule = self.create_auto_response_rule_from_values(values, kind=rule_kind)
        if rule is None:
            return
        self.remember_auto_response_rule(rule)
        self.set_status_message(f"已添加自动响应规则: {rule.name}")
        self.refresh_auto_response_rule_buttons()
        state = self.current_session_state()
        if state is not None:
            self.apply_auto_response_rules(state, "", trigger_event="immediate")

    def apply_edited_auto_response_rule_values(
        self,
        rule: AutoResponseRule,
        values: dict[str, object],
    ) -> None:
        rule_kind = normalize_auto_response_rule_kind(values.get("kind"))
        if rule_kind == "quick_send":
            quick_button = self.create_quick_send_button_from_rule_values(values)
            if quick_button is None:
                return
            self.forget_auto_response_rule(rule)
            self.remembered_quick_send_buttons.append(quick_button)
            self.schedule_desktop_state_save()
            self.set_status_message(f"已转换为快捷发送按钮: {quick_button.name}")
            self.refresh_auto_response_rule_buttons()
            return
        old_signature = self.auto_response_rule_signature(rule)
        updated = self.create_auto_response_rule_from_values(values, kind=rule_kind)
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
        rule.trigger_type = updated.trigger_type
        rule.trigger_delay_ms = updated.trigger_delay_ms
        rule.loop_count = updated.loop_count
        rule.kind = updated.kind
        rule.steps = updated.steps
        rule.actions = updated.actions
        rule.enabled = True
        rule.trigger_count = 0
        self.remember_auto_response_rule(rule, old_signature=old_signature)
        self.set_status_message(f"已更新自动响应规则: {rule.name}")
        self.refresh_auto_response_rule_buttons()
        state = self.current_session_state()
        if state is not None:
            self.apply_auto_response_rules(state, "", trigger_event="immediate")

    def create_auto_response_rule_from_values(
        self,
        values: dict[str, object],
        *,
        kind: str | None,
    ) -> AutoResponseRule | None:
        return self.create_auto_response_rule(
            name=str(values["name"]),
            pattern=str(values["pattern"]).strip(),
            response_text=str(values["response_text"]),
            steps_text=str(values["steps_text"]),
            step_targets=list(values.get("step_targets", [])),
            step_delays=list(values.get("step_delays", [])),
            step_append_enters=list(values.get("step_append_enters", [])),
            append_enter=bool(values["append_enter"]),
            case_sensitive=bool(values["case_sensitive"]),
            once=bool(values["once"]),
            allow_startup_trigger=bool(values.get("allow_startup_trigger", False)),
            match_type=str(values.get("match_type") or "contains"),
            delay_ms=int(values.get("delay_ms") or 0),
            max_triggers=int(values.get("max_triggers") or 0),
            trigger_type=str(values.get("trigger_type") or "match"),
            trigger_delay_ms=int(values.get("trigger_delay_ms") or 0),
            loop_count=int(values.get("loop_count") or 1),
            kind=kind,
            simple_rule_text=str(values.get("simple_rule_text") or ""),
            actions=list(values.get("actions", [])),
        )

    def auto_response_rule_dialog_class(self) -> type[QDialog] | None:
        if AutoResponseRuleWebDialog is not None and QWebChannel is not None and QWebEngineView is not None:
            return AutoResponseRuleWebDialog
        return AutoResponseRuleDialog

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
        step_append_enters: list[bool] | None = None,
        append_enter: bool = False,
        case_sensitive: bool = False,
        once: bool = True,
        allow_startup_trigger: bool = False,
        match_type: str = "contains",
        delay_ms: int = 0,
        max_triggers: int = 0,
        trigger_type: str = "match",
        trigger_delay_ms: int = 0,
        loop_count: int = 1,
        kind: str = "capture",
        simple_rule_text: str = "",
        actions: list[Any] | None = None,
    ) -> AutoResponseRule | None:
        normalized_kind = normalize_auto_response_rule_kind(kind)
        parsed_simple_rule = self.parse_simple_auto_response_rule_for_create(
            simple_rule_text,
            expected_kind=normalized_kind,
        )
        if parsed_simple_rule is None and str(simple_rule_text or "").strip():
            return None
        if parsed_simple_rule is not None:
            if parsed_simple_rule.kind == "quick_send":
                self.show_warning("快捷发送请使用“按一下发送”按钮类型。")
                return None
            normalized_kind = parsed_simple_rule.kind
            name = str(name).strip() or parsed_simple_rule.name
            pattern = parsed_simple_rule.pattern
            response_text = parsed_simple_rule.response_text
            append_enter = parsed_simple_rule.append_enter
            once = parsed_simple_rule.once
            trigger_type = parsed_simple_rule.trigger_type
            trigger_delay_ms = parsed_simple_rule.trigger_delay_ms
            loop_count = parsed_simple_rule.loop_count
            steps_text = self.steps_text_from_parsed_simple_rule(parsed_simple_rule)
            step_delays = [parsed_simple_rule.step_delay_ms]
            step_append_enters = [parsed_simple_rule.append_enter]
        normalized_name = str(name).strip()
        if not normalized_name:
            self.show_warning("规则名称需要手动填写。")
            return None
        normalized_match_type = match_type if match_type in {"contains", "regex"} else "contains"
        normalized_trigger_type = trigger_type if trigger_type in {"match", "immediate", "connected", "delay", "manual"} else "match"
        try:
            normalized_delay_ms = max(0, int(delay_ms))
        except (TypeError, ValueError):
            normalized_delay_ms = 0
        try:
            normalized_max_triggers = max(0, int(max_triggers))
        except (TypeError, ValueError):
            normalized_max_triggers = 0
        try:
            normalized_trigger_delay_ms = max(0, int(trigger_delay_ms))
        except (TypeError, ValueError):
            normalized_trigger_delay_ms = 0
        try:
            normalized_loop_count = max(1, min(10, int(loop_count)))
        except (TypeError, ValueError):
            normalized_loop_count = 1
        steps = self.parse_auto_response_steps(
            steps_text,
            append_enter=append_enter,
            step_targets=step_targets,
            step_delays=step_delays,
            step_append_enters=step_append_enters,
        )
        if steps is None:
            return None
        parsed_actions = self.parse_auto_response_actions(
            actions,
            append_enter=append_enter,
        )
        if parsed_actions is None:
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
        elif parsed_actions:
            first_send = self.first_send_auto_response_action(parsed_actions)
            if first_send is None:
                self.show_warning("动作流程至少需要一个发送动作。")
                return None
            response_text = first_send.text
            response = decode_response_text(response_text, append_enter=first_send.append_enter)
            if normalized_trigger_type == "match" and not pattern.strip():
                self.show_warning("匹配输出触发需要填写匹配内容。")
                return None
        else:
            if not pattern.strip():
                self.show_warning("匹配内容不能为空。")
                return None
            response = decode_response_text(response_text, append_enter=append_enter)
        if not response:
            self.show_warning("发送内容不能为空。")
            return None
        name = normalized_name
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
            trigger_type=normalized_trigger_type,
            trigger_delay_ms=normalized_trigger_delay_ms,
            loop_count=normalized_loop_count,
            kind=normalized_kind,
            steps=steps,
            actions=parsed_actions,
        )

    def first_send_auto_response_action(
        self,
        actions: list[AutoResponseAction],
    ) -> AutoResponseAction | None:
        for action in actions:
            if action.kind == "send":
                return action
            child = self.first_send_auto_response_action(action.actions)
            if child is not None:
                return child
        return None

    def parse_auto_response_actions(
        self,
        actions: list[Any] | None,
        *,
        append_enter: bool,
    ) -> list[AutoResponseAction] | None:
        if not actions:
            return []
        parsed: list[AutoResponseAction] = []
        for index, action in enumerate(actions, start=1):
            if not isinstance(action, dict):
                continue
            kind = str(action.get("kind") or "").strip().lower()
            if kind not in {"send", "wait", "loop", "exit", "condition"}:
                self.show_warning(f"动作 {index} 类型无效。")
                return None
            parsed_action = self.parse_auto_response_action(action, append_enter=append_enter)
            if parsed_action is None:
                return None
            parsed.append(parsed_action)
        return parsed

    def parse_auto_response_action(
        self,
        action: dict[str, Any],
        *,
        append_enter: bool,
    ) -> AutoResponseAction | None:
        kind = str(action.get("kind") or "").strip().lower()
        delay_ms = self.parse_nonnegative_action_int(action.get("delayMs", action.get("delay_ms", 0)))
        repeat_count = self.normalize_auto_response_repeat_count(
            action.get("repeatCount", action.get("repeat_count", 1))
        )
        interval_ms = self.parse_nonnegative_action_int(action.get("intervalMs", action.get("interval_ms", 0)))
        exit_scope = str(action.get("exitScope", action.get("exit_scope", "loop")) or "loop").strip().lower()
        if exit_scope not in {"loop", "rule"}:
            exit_scope = "loop"
        condition_match_type = str(
            action.get("conditionMatchType", action.get("condition_match_type", "contains")) or "contains"
        ).strip().lower()
        if condition_match_type not in {"contains", "regex"}:
            condition_match_type = "contains"
        child_actions = self.parse_auto_response_actions(
            action.get("actions") if isinstance(action.get("actions"), list) else [],
            append_enter=append_enter,
        )
        if child_actions is None:
            return None
        text = str(action.get("text") or "")
        action_append_enter = bool(action.get("appendEnter", action.get("append_enter", append_enter)))
        if kind == "send" and not text.strip():
            self.show_warning("发送动作的内容不能为空。")
            return None
        if kind == "loop" and not child_actions:
            self.show_warning("循环动作中至少需要一个动作。")
            return None
        condition_pattern = str(
            action.get("conditionPattern", action.get("condition_pattern", "")) or ""
        )
        if kind == "condition":
            if not condition_pattern.strip():
                self.show_warning("判断动作需要填写匹配内容。")
                return None
            if not child_actions:
                self.show_warning("判断动作中至少需要一个动作。")
                return None
            if condition_match_type == "regex":
                try:
                    re.compile(condition_pattern)
                except re.error as exc:
                    self.show_warning(f"Invalid condition regex pattern: {exc}")
                    return None
        return AutoResponseAction(
            kind=kind,
            text=text,
            target=self.normalize_auto_response_target(action.get("target")),
            delay_ms=delay_ms,
            append_enter=action_append_enter,
            repeat_count=repeat_count,
            interval_ms=interval_ms,
            exit_pattern=str(action.get("exitPattern", action.get("exit_pattern", "")) or ""),
            exit_scope=exit_scope,
            condition_pattern=condition_pattern,
            condition_match_type=condition_match_type,
            actions=child_actions,
        )

    @staticmethod
    def parse_nonnegative_action_int(value: object) -> int:
        try:
            return max(0, int(str(value).strip() or "0"))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def normalize_auto_response_repeat_count(value: object) -> int:
        try:
            count = int(str(value).strip() or "1")
        except (TypeError, ValueError):
            count = 1
        if count <= 0:
            return 0
        return max(1, min(100, count))

    def create_quick_send_button_from_rule_values(
        self,
        values: dict[str, object],
    ) -> TerminalQuickButton | None:
        parsed_simple_rule = self.parse_simple_auto_response_rule_for_create(
            str(values.get("simple_rule_text") or ""),
            expected_kind="quick_send",
        )
        if parsed_simple_rule is not None:
            return self.create_quick_send_button(
                name=parsed_simple_rule.name,
                response_text=parsed_simple_rule.response_text,
                append_enter=parsed_simple_rule.append_enter,
            )
        if str(values.get("simple_rule_text") or "").strip():
            return None
        return self.create_quick_send_button(
            name=values.get("name", ""),
            response_text=values.get("response_text", ""),
            append_enter=values.get("append_enter", False),
        )

    def parse_simple_auto_response_rule_for_create(
        self,
        simple_rule_text: str,
        *,
        expected_kind: str,
    ) -> ParsedAutoResponseRule | None:
        if not simple_rule_text.strip() or expected_kind == "advanced":
            return None
        result = parse_simple_auto_response_rule(simple_rule_text)
        if result.error is not None:
            self.show_warning(f"简单规则第 {result.error.line_number} 行：{result.error.message}")
            return None
        if result.rule is None:
            return None
        if expected_kind == "quick_send" and result.rule.kind != "quick_send":
            self.show_warning("按一下发送请使用：按钮 名称 => 发送内容。")
            return None
        if expected_kind != "quick_send" and result.rule.kind == "quick_send":
            self.show_warning("快捷发送规则请切换到“按一下发送”。")
            return None
        return result.rule

    @staticmethod
    def steps_text_from_parsed_simple_rule(rule: ParsedAutoResponseRule) -> str:
        if rule.pattern:
            return f"{rule.pattern} => {rule.response_text}"
        return f"=> {rule.response_text}"

    def parse_auto_response_steps(
        self,
        steps_text: str,
        *,
        append_enter: bool,
        step_targets: list[str] | None = None,
        step_delays: list[int] | None = None,
        step_append_enters: list[bool] | None = None,
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
            response_append_enter = (
                bool(step_append_enters[target_index])
                if step_append_enters is not None and target_index < len(step_append_enters)
                else append_enter
            )
            response = decode_response_text(response_text, append_enter=response_append_enter)
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
            current_step.response_append_enters.append(response_append_enter)
            target_index += 1
        if not steps:
            self.show_warning("流程步骤不能为空。")
            return None
        return steps

    def parse_auto_response_steps(
        self,
        steps_text: str,
        *,
        append_enter: bool,
        step_targets: list[str] | None = None,
        step_delays: list[int] | None = None,
        step_append_enters: list[bool] | None = None,
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
                current_step = AutoResponseStep(pattern="")
                steps.append(current_step)
            response_append_enter = (
                bool(step_append_enters[target_index])
                if step_append_enters is not None and target_index < len(step_append_enters)
                else append_enter
            )
            response = decode_response_text(response_text, append_enter=response_append_enter)
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
            current_step.response_append_enters.append(response_append_enter)
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
        if hasattr(self, "refresh_device_navigation_web"):
            self.refresh_device_navigation_web()
        if hasattr(self, "refresh_web_shell"):
            self.refresh_web_shell()

    def refresh_session_jump_combo(self) -> None:
        if not hasattr(self, "session_jump_combo"):
            return
        current_tab_id = self.current_session_key()
        combo = self.session_jump_combo
        combo.blockSignals(True)
        combo.clear()
        states = self.ordered_session_states()
        if hasattr(self, "session_count_label"):
            self.session_count_label.setText(f"{len(states)} 会话")
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

    def serialize_terminal_sessions(self) -> list[dict[str, object]]:
        current_tab_id = self.current_session_key()
        remembered: list[dict[str, object]] = []
        for state in self.ordered_session_states():
            remembered.append({
                "device_id": state.device_id,
                "kind": state.kind,
                "title": state.title,
                "host": state.host,
                "port": state.port,
                "active": state.tab_id == current_tab_id,
            })
            if len(remembered) >= 20:
                break
        return remembered

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
        self.show_terminal_workspace()
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
        if not hasattr(self, "center_stage_splitter"):
            return
        has_sessions = self.session_tab_widget.count() > 0
        if not has_sessions:
            self.center_stage_mode = "home"
            self.left_device_workspace_expanded = True
        show_home = getattr(self, "center_stage_mode", "home") == "home"
        current_mode = "home" if show_home else "sessions"
        mode_changed = getattr(self, "_last_center_stage_mode", None) != current_mode
        self._last_center_stage_mode = current_mode
        self.web_shell.setVisible(False)
        self.session_tab_widget.setVisible(True)
        self.center_stage_splitter.setSizes([0, 1])
        if hasattr(self, "activity_home_button"):
            self.activity_home_button.setToolTip("首页大屏")
        if hasattr(self, "sync_activity_rail_state"):
            self.sync_activity_rail_state()
        for widget_name in ("command_record_frame",):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setVisible(has_sessions)
        if hasattr(self, "apply_session_quick_bar_state"):
            self.apply_session_quick_bar_state()
        compact_left = False
        compact_changed = getattr(self, "left_sidebar_compact", False) != compact_left
        self.left_sidebar_compact = compact_left
        if getattr(self, "left_sidebar_active_panel", "devices") != "devices":
            return
        if not show_home and has_sessions:
            if mode_changed and self.left_sidebar_collapsed:
                self.left_sidebar_collapsed = False
                self.apply_left_sidebar_state()
            elif mode_changed or compact_changed:
                self.apply_left_sidebar_state()
        elif mode_changed:
            self.apply_left_sidebar_state()
        elif compact_changed:
            self.apply_left_sidebar_state()

    def show_web_home(self) -> None:
        self.center_stage_mode = "home"
        self.left_sidebar_active_panel = "devices"
        self.left_device_workspace_expanded = True
        self.left_sidebar_collapsed = False
        if hasattr(self, "left_sidebar_stack"):
            self.left_sidebar_stack.setCurrentIndex(0)
        self.update_center_stage_state()
        self.apply_left_sidebar_state()
        self.refresh_workspace_context()

    def show_terminal_workspace(self) -> None:
        if self.session_tab_widget.count() <= 0:
            return
        was_in_terminal = getattr(self, "center_stage_mode", "home") != "home"
        self.center_stage_mode = "sessions"
        self.left_sidebar_active_panel = "devices"
        self.left_device_workspace_expanded = True
        if was_in_terminal and self.left_sidebar_collapsed:
            self.terminal_sidebar_collapsed = False
        self.left_sidebar_collapsed = False
        if hasattr(self, "left_sidebar_stack"):
            self.left_sidebar_stack.setCurrentIndex(0)
        self.update_center_stage_state()
        self.apply_left_sidebar_state()
        self.refresh_workspace_context()
        self.focus_current_terminal()

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
                trigger_type=rule.trigger_type,
                trigger_delay_ms=rule.trigger_delay_ms,
                loop_count=rule.loop_count,
                kind=rule.kind,
                trigger_count=0,
                steps=[
                    AutoResponseStep(
                        pattern=step.pattern,
                        responses=list(step.responses),
                        response_texts=list(step.response_texts),
                        response_targets=list(step.response_targets),
                        response_delays=list(step.response_delays),
                        response_append_enters=list(step.response_append_enters),
                    )
                    for step in rule.steps
                ],
                actions=SessionOpsMixin.clone_auto_response_actions(rule.actions),
            )
            for rule in rules
        ]

    @staticmethod
    def clone_auto_response_actions(actions: list[AutoResponseAction]) -> list[AutoResponseAction]:
        return [
            AutoResponseAction(
                kind=action.kind,
                text=action.text,
                target=action.target,
                delay_ms=action.delay_ms,
                append_enter=action.append_enter,
                repeat_count=action.repeat_count,
                interval_ms=action.interval_ms,
                exit_pattern=action.exit_pattern,
                exit_scope=action.exit_scope,
                condition_pattern=action.condition_pattern,
                condition_match_type=action.condition_match_type,
                actions=SessionOpsMixin.clone_auto_response_actions(action.actions),
            )
            for action in actions
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
                tuple(step.response_append_enters),
            )
            for step in rule.steps
        )
        def action_signature(action: AutoResponseAction) -> tuple[object, ...]:
            return (
                action.kind,
                action.text,
                action.target,
                action.delay_ms,
                action.append_enter,
                action.repeat_count,
                action.interval_ms,
                action.exit_pattern,
                action.exit_scope,
                action.condition_pattern,
                action.condition_match_type,
                tuple(action_signature(child) for child in action.actions),
            )

        actions_signature = tuple(action_signature(action) for action in rule.actions)
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
            rule.trigger_type,
            rule.trigger_delay_ms,
            rule.loop_count,
            rule.kind,
            steps_signature,
            actions_signature,
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
            state.auto_response_rule_loops.pop(signature, None)
            state.auto_response_running_rules.discard(signature)
            state.auto_response_rule_run_tokens[signature] = state.auto_response_rule_run_tokens.get(signature, 0) + 1

    def start_auto_response_rule_run(self, state: SessionTabState, rule: AutoResponseRule) -> int:
        signature = self.auto_response_rule_signature(rule)
        token = state.auto_response_rule_run_tokens.get(signature, 0) + 1
        state.auto_response_rule_run_tokens[signature] = token
        state.auto_response_running_rules.add(signature)
        return token

    def auto_response_rule_run_is_active(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        run_token: int,
    ) -> bool:
        signature = self.auto_response_rule_signature(rule)
        return (
            signature in state.auto_response_running_rules
            and state.auto_response_rule_run_tokens.get(signature) == run_token
            and self.auto_response_rule_is_registered(state, rule)
        )

    def finish_auto_response_rule_run(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        run_token: int,
    ) -> None:
        if not self.auto_response_rule_run_is_active(state, rule, run_token):
            return
        signature = self.auto_response_rule_signature(rule)
        state.auto_response_running_rules.discard(signature)
        self.refresh_auto_response_rule_buttons()
        self.schedule_desktop_state_save()

    def stop_auto_response_rule_run(self, state: SessionTabState, rule: AutoResponseRule) -> None:
        signature = self.auto_response_rule_signature(rule)
        state.auto_response_running_rules.discard(signature)
        state.auto_response_rule_steps.pop(signature, None)
        state.auto_response_rule_loops.pop(signature, None)
        state.auto_response_rule_run_tokens[signature] = state.auto_response_rule_run_tokens.get(signature, 0) + 1
        state.auto_response_buffer = ""
        self.set_status_message(f"已停止自动响应规则: {rule.name}")
        self.refresh_auto_response_rule_buttons()
        self.schedule_desktop_state_save()

    def schedule_auto_response_rule_run_finish(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        run_token: int,
        delay_ms: int,
    ) -> None:
        delay_ms = max(0, int(delay_ms or 0))
        if delay_ms > 0 and QTimer is not None:
            QTimer.singleShot(
                delay_ms,
                lambda: self.finish_auto_response_rule_run(state, rule, run_token),
            )
            return
        self.finish_auto_response_rule_run(state, rule, run_token)

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

    # ---- Remembered terminal sessions ----

    def schedule_restore_remembered_terminal_sessions_once(self) -> None:
        if getattr(self, "terminal_sessions_restored", False):
            return
        remembered = list(getattr(self, "remembered_terminal_sessions", []))
        if not remembered:
            self.terminal_sessions_restored = True
            return
        enabled = os.getenv("DEVICE_TUI_AUTO_RESTORE_SESSIONS", "").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            self.terminal_sessions_restored = True
            return
        QTimer.singleShot(1500, self.restore_remembered_terminal_sessions_once)

    def restore_remembered_terminal_sessions_once(self) -> None:
        if getattr(self, "terminal_sessions_restored", False):
            return
        self.terminal_sessions_restored = True
        remembered = list(getattr(self, "remembered_terminal_sessions", []))
        if not remembered:
            return

        active_tab_id = ""
        restored_count = 0
        for item in remembered:
            state = self.restore_remembered_terminal_session(item)
            if state is None:
                continue
            restored_count += 1
            if bool(item.get("active", False)):
                active_tab_id = state.tab_id
        if active_tab_id:
            self.jump_to_session(active_tab_id)
        elif restored_count:
            self.show_terminal_workspace()
        if restored_count:
            self.set_status_message(f"已自动重连 {restored_count} 个上次终端会话")
            self.schedule_desktop_state_save()

    def restore_remembered_terminal_session(self, item: dict[str, object]) -> SessionTabState | None:
        kind = str(item.get("kind") or "").strip()
        device_id = str(item.get("device_id") or "").strip()
        if kind not in {"device", "linux", "serial", "simulated"} or not device_id:
            return None

        device = self.simulated_device() if kind == "simulated" else self.get_device_by_id(device_id)
        if device is None:
            return None
        if kind == "serial" and not self.can_view_serial_connection(device):
            return None

        host = str(item.get("host") or "").strip()
        try:
            port = int(item.get("port", 0))
        except (TypeError, ValueError):
            port = 0
        host, port = self.remembered_session_endpoint(device, kind, host, port)
        if not host:
            return None

        for existing in self.ordered_session_states():
            if (
                existing.device_id == device.id
                and existing.kind == kind
                and existing.host == host
                and existing.port == port
            ):
                return existing

        username, password = self.remembered_session_credentials(device, kind)
        if kind != "simulated" and (not username or not password):
            return None
        credential_candidates = (
            self.linux_ssh_credential_candidates(device, username, password)
            if kind == "linux"
            else None
        )
        title = str(item.get("title") or "").strip() or None
        return self.ensure_session_tab(
            kind=kind,
            device=device,
            host=host,
            port=port,
            username=username,
            password=password,
            credential_candidates=credential_candidates,
            title=title,
            suppress_initial_error=True,
        )

    def remembered_session_endpoint(
        self,
        device: Device,
        kind: str,
        saved_host: str,
        saved_port: int,
    ) -> tuple[str, int]:
        if saved_host:
            return saved_host, saved_port
        if kind == "simulated":
            return "localhost", 0
        if kind == "device":
            return device.telnet_ip.strip(), device.telnet_port
        if kind == "serial":
            return device.serial_ip.strip(), device.serial_port
        return device.ssh_ip.strip(), device.ssh_port

    def remembered_session_credentials(self, device: Device, kind: str) -> tuple[str, str]:
        if kind == "simulated":
            return "sim", ""
        if kind == "device":
            return self.session_telnet_credentials(device)
        if kind == "serial":
            return self.session_serial_credentials(device)
        return self.session_ssh_credentials(device)

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
        title: str | None = None,
        suppress_initial_error: bool = False,
    ) -> SessionTabState | None:
        if not host:
            self.show_warning("目标地址不能为空。")
            return None

        self.center_stage_mode = "sessions"
        device_tab = self.ensure_device_tab(device)
        if title:
            self.advance_session_title_counter(device_tab, kind, title)
        else:
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
        state.suppress_next_connection_error = suppress_initial_error
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
        self.schedule_desktop_state_save()
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

    def advance_session_title_counter(self, device_tab: DeviceTabState, kind: str, title: str) -> None:
        match = re.search(r"#\s*(\d+)", title)
        if match is None:
            return
        next_index = int(match.group(1)) + 1
        if kind == "simulated":
            device_tab.next_session_index = max(device_tab.next_session_index, next_index)
        elif kind == "device":
            device_tab.next_telnet_index = max(device_tab.next_telnet_index, next_index)
        elif kind == "serial":
            device_tab.next_serial_index = max(device_tab.next_serial_index, next_index)
        else:
            device_tab.next_ssh_index = max(device_tab.next_ssh_index, next_index)

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
        terminal.set_command_recorder(lambda command, state=state: self.remember_command_history(command, state=state))
        if hasattr(terminal, "set_command_suggestion_provider"):
            terminal.set_command_suggestion_provider(
                lambda query, state=state: self.terminal_command_suggestion(state, query)
            )
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

    def close_session_tab(self, tab_id: str) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is None:
            self.refresh_workspace_context()
            return
        device_tab = self.device_tabs_by_id.get(state.device_id)
        if device_tab is None:
            return
        tabs = self.find_session_tab_widget(device_tab, state.page)
        if tabs is None:
            return
        index = tabs.indexOf(state.page)
        if index >= 0:
            self.close_child_session_tab_at_index(device_tab.device_id, index, tabs)

    def close_other_session_tabs(self, keep_tab_id: str) -> None:
        states = [state for state in self.ordered_session_states() if state.tab_id != keep_tab_id]
        if not states:
            self.set_status_message("没有其他可关闭的终端会话。")
            return
        for state in states:
            self.close_session_tab(state.tab_id)
        self.set_status_message(f"正在关闭 {len(states)} 个其他终端会话。")

    def close_all_session_tabs(self) -> None:
        states = self.ordered_session_states()
        if not states:
            self.set_status_message("当前没有可关闭的终端会话。")
            return
        for device_tab in list(self.device_tabs_by_id.values()):
            self.close_device_tab_state(device_tab)
        self.set_status_message(f"正在关闭 {len(states)} 个终端会话。")

    def close_current_session(self) -> None:
        state = self.current_session_state()
        if state is None:
            self.set_status_message("当前没有可关闭的终端会话。")
            return
        self.close_session_tab(state.tab_id)

    def close_other_current_session_tabs(self) -> None:
        state = self.current_session_state()
        if state is None:
            self.set_status_message("当前没有可保留的终端会话。")
            return
        self.close_other_session_tabs(state.tab_id)

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
                term_size=state.terminal.terminal_dimensions(),
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
            current_state.suppress_next_connection_error = False
            current_state.connecting = False
            self.set_session_status(tab_id, "Connected")
            self.write_session_log_line(current_state, "SYS", "Connected")
            self.apply_auto_response_rules(current_state, "", trigger_event="connected")
            self.set_status_message(f"会话已连接: {current_state.title}")
            self.focus_current_terminal()

        def failure(exc: Exception) -> None:
            current_state = self.session_tabs_by_id.get(tab_id)
            if current_state is None:
                return
            suppress_error_dialog = current_state.suppress_next_connection_error
            current_state.suppress_next_connection_error = False
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
                if not suppress_error_dialog:
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
        if state is None or not hasattr(state.session, "resize_terminal"):
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

    def apply_auto_response_rules(
        self,
        state: SessionTabState,
        message: str,
        *,
        trigger_event: str = "output",
    ) -> None:
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
            if signature in state.auto_response_running_rules and trigger_event not in {"step", "loop", "delayed"}:
                continue
            if rule.actions:
                has_infinite_loop = self.auto_response_actions_have_infinite_loop(rule.actions)
                scan_text = self.auto_response_scan_text(previous_buffer, message, rule.pattern)
                if self.auto_response_rule_needs_delayed_start(rule, trigger_event, 0):
                    run_token = self.start_auto_response_rule_run(state, rule)
                    self.refresh_auto_response_rule_buttons()
                    self.schedule_delayed_auto_response_rule(state, rule, run_token=run_token)
                    continue
                if not self.auto_response_action_flow_ready(rule, scan_text, trigger_event):
                    continue
                rule.trigger_count += 1
                run_token = self.start_auto_response_rule_run(state, rule)
                final_delay_ms, exit_scope = self.execute_auto_response_action_flow(state, rule, scan_text, run_token)
                infinite_loop_running = state.auto_response_rule_loops.get(signature) == -1
                state.auto_response_buffer = ""
                if rule.once and not infinite_loop_running:
                    state.auto_response_triggered_rules.add(signature)
                    rule.enabled = False
                if rule.max_triggers and rule.trigger_count >= rule.max_triggers and not infinite_loop_running:
                    rule.enabled = False
                if exit_scope == "rule":
                    rule.enabled = False
                if not infinite_loop_running:
                    self.schedule_auto_response_rule_run_finish(state, rule, run_token, final_delay_ms)
                self.refresh_auto_response_rule_buttons()
                self.schedule_desktop_state_save()
                return
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
            if self.auto_response_rule_needs_delayed_start(rule, trigger_event, step_index):
                run_token = self.start_auto_response_rule_run(state, rule)
                self.refresh_auto_response_rule_buttons()
                self.schedule_delayed_auto_response_rule(state, rule, run_token=run_token)
                continue
            if not self.auto_response_step_ready(rule, step, scan_text, trigger_event, step_index):
                continue
            rule.trigger_count += 1
            run_token = self.start_auto_response_rule_run(state, rule)
            final_delay_ms = self.execute_auto_response_step(state, rule, step, step_index, len(steps), run_token)
            next_step_index = step_index + 1
            completed_rule = next_step_index >= len(steps)
            if completed_rule:
                current_loop = state.auto_response_rule_loops.get(signature, 0) + 1
                if current_loop < self.auto_response_loop_count(rule):
                    state.auto_response_rule_loops[signature] = current_loop
                    state.auto_response_rule_steps[signature] = 0
                    state.auto_response_buffer = ""
                    if steps and not steps[0].pattern.strip():
                        self.apply_auto_response_rules(state, "", trigger_event="loop")
                else:
                    state.auto_response_rule_steps.pop(signature, None)
                    state.auto_response_rule_loops.pop(signature, None)
                    if rule.once:
                        state.auto_response_triggered_rules.add(signature)
                        rule.enabled = False
            else:
                state.auto_response_rule_steps[signature] = next_step_index
                state.auto_response_buffer = ""
                next_step = steps[next_step_index]
                if not next_step.pattern.strip():
                    self.apply_auto_response_rules(state, "", trigger_event="step")
            if rule.max_triggers and rule.trigger_count >= rule.max_triggers:
                rule.enabled = False
            self.refresh_auto_response_rule_buttons()
            self.schedule_desktop_state_save()
            return

    @staticmethod
    def auto_response_loop_count(rule: AutoResponseRule) -> int:
        try:
            return max(1, min(10, int(rule.loop_count)))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def auto_response_rule_needs_delayed_start(
        rule: AutoResponseRule,
        trigger_event: str,
        step_index: int,
    ) -> bool:
        return (
            rule.trigger_type == "delay"
            and step_index == 0
            and trigger_event in {"connected", "immediate", "manual"}
        )

    def schedule_delayed_auto_response_rule(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        *,
        run_token: int,
    ) -> None:
        delay_ms = max(0, int(rule.trigger_delay_ms or 0))
        if delay_ms > 0 and QTimer is not None:
            QTimer.singleShot(
                delay_ms,
                lambda tab_id=state.tab_id, token=run_token: self.apply_delayed_auto_response_rule(
                    tab_id,
                    rule,
                    token,
                ),
            )
            return
        self.apply_delayed_auto_response_rule(state.tab_id, rule, run_token)

    def apply_delayed_auto_response_rule(
        self,
        tab_id: str,
        rule: AutoResponseRule,
        run_token: int,
    ) -> None:
        state = self.session_tabs_by_id.get(tab_id)
        if state is not None and self.auto_response_rule_run_is_active(state, rule, run_token):
            signature = self.auto_response_rule_signature(rule)
            state.auto_response_running_rules.discard(signature)
            self.apply_auto_response_rules(state, "", trigger_event="delayed")

    def auto_response_step_ready(
        self,
        rule: AutoResponseRule,
        step: AutoResponseStep,
        output: str,
        trigger_event: str,
        step_index: int,
    ) -> bool:
        if not rule.enabled:
            return False
        if not step.pattern.strip():
            if step_index > 0 or trigger_event in {"step", "loop"}:
                return True
            return (
                (rule.trigger_type == "immediate" and trigger_event in {"immediate", "connected"})
                or (rule.trigger_type == "connected" and trigger_event == "connected")
                or (rule.trigger_type == "delay" and trigger_event == "delayed")
                or (rule.trigger_type == "manual" and trigger_event == "manual")
            )
        return trigger_event == "output" and self.auto_response_step_matches(rule, step, output)

    def auto_response_action_flow_ready(
        self,
        rule: AutoResponseRule,
        output: str,
        trigger_event: str,
    ) -> bool:
        if not rule.enabled:
            return False
        if rule.trigger_type == "manual":
            return trigger_event == "manual"
        if rule.trigger_type == "immediate":
            return trigger_event in {"immediate", "connected"}
        if rule.trigger_type == "connected":
            return trigger_event == "connected"
        if rule.trigger_type == "delay":
            return trigger_event == "delayed"
        if rule.pattern.strip():
            step = AutoResponseStep(pattern=rule.pattern)
            return trigger_event == "output" and self.auto_response_step_matches(rule, step, output)
        return trigger_event in {"immediate", "manual", "connected"}

    def execute_auto_response_step(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        step: AutoResponseStep,
        step_index: int,
        step_count: int,
        run_token: int,
    ) -> int:
        self.write_session_log_line(
            state,
            "SYS",
            f"Auto response sent: {rule.name} step {step_index + 1}/{step_count}",
        )
        self.set_status_message(f"自动化已执行: {rule.name}（命中 {rule.trigger_count} 次）")
        cumulative_delay_ms = max(0, int(rule.delay_ms or 0))
        last_response_index = len(step.responses) - 1
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
                self.set_status_message(f"自动化目标终端不存在: {target}")
                continue
            if cumulative_delay_ms > 0 and QTimer is not None:
                QTimer.singleShot(
                    cumulative_delay_ms,
                    lambda tab_id=target_tab_id, text=response, token=run_token, finish=index == last_response_index: self.send_auto_response_text_if_running(
                        state,
                        rule,
                        token,
                        tab_id,
                        text,
                        finish=finish,
                    ),
                )
            else:
                self.send_auto_response_text_if_running(
                    state,
                    rule,
                    run_token,
                    target_tab_id,
                    response,
                    finish=index == last_response_index,
                )
        return cumulative_delay_ms

    def execute_auto_response_action_flow(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        scan_text: str,
        run_token: int,
    ) -> tuple[int, str | None]:
        self.write_session_log_line(state, "SYS", f"Auto response flow started: {rule.name}")
        self.set_status_message(f"自动化流程已执行: {rule.name}（命中 {rule.trigger_count} 次）")
        return self.schedule_auto_response_actions(
            state,
            rule,
            rule.actions,
            scan_text,
            max(0, int(rule.delay_ms or 0)),
            run_token,
        )

    def schedule_auto_response_actions(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        actions: list[AutoResponseAction],
        scan_text: str,
        cumulative_delay_ms: int,
        run_token: int,
    ) -> tuple[int, str | None]:
        delay_ms = cumulative_delay_ms
        for action in actions:
            kind = action.kind
            if kind == "wait":
                delay_ms += max(0, int(action.delay_ms or 0))
                continue
            if kind == "exit":
                if action.exit_pattern and self.auto_response_pattern_matches(
                    rule,
                    action.exit_pattern,
                    scan_text,
                ):
                    return delay_ms, action.exit_scope
                continue
            if kind == "send":
                delay_ms += max(0, int(action.delay_ms or 0))
                self.schedule_auto_response_send(state, rule, action, delay_ms, run_token)
                continue
            if kind == "condition":
                condition_scan_text = state.auto_response_buffer or scan_text
                if self.auto_response_action_condition_matches(rule, action, condition_scan_text):
                    next_delay, exit_scope = self.schedule_auto_response_actions(
                        state,
                        rule,
                        action.actions,
                        condition_scan_text,
                        delay_ms,
                        run_token,
                    )
                    delay_ms = next_delay
                    if exit_scope is not None:
                        return delay_ms, exit_scope
                continue
            if kind == "loop":
                repeat_count = self.normalize_auto_response_repeat_count(action.repeat_count)
                interval_ms = max(0, int(action.interval_ms or 0))
                if repeat_count == 0:
                    self.schedule_auto_response_infinite_loop(
                        state,
                        rule,
                        action,
                        scan_text,
                        delay_ms,
                        run_token,
                    )
                    return delay_ms, "loop"
                for _iteration in range(repeat_count):
                    next_delay, exit_scope = self.schedule_auto_response_actions(
                        state,
                        rule,
                        action.actions,
                        scan_text,
                        delay_ms,
                        run_token,
                    )
                    delay_ms = next_delay
                    if exit_scope == "rule":
                        return delay_ms, "rule"
                    if exit_scope == "loop":
                        break
                    delay_ms += interval_ms
        return delay_ms, None

    def schedule_auto_response_infinite_loop(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        action: AutoResponseAction,
        scan_text: str,
        start_delay_ms: int,
        run_token: int,
    ) -> None:
        signature = self.auto_response_rule_signature(rule)
        state.auto_response_rule_loops[signature] = -1
        if QTimer is None:
            self.run_auto_response_infinite_loop_iteration(state, rule, action, scan_text, run_token)
            return
        QTimer.singleShot(
            max(0, int(start_delay_ms or 0)),
            lambda: self.run_auto_response_infinite_loop_iteration(state, rule, action, scan_text, run_token),
        )

    def run_auto_response_infinite_loop_iteration(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        action: AutoResponseAction,
        scan_text: str,
        run_token: int,
    ) -> None:
        signature = self.auto_response_rule_signature(rule)
        if (
            not rule.enabled
            or state.auto_response_rule_loops.get(signature) != -1
            or not self.auto_response_rule_run_is_active(state, rule, run_token)
            or not self.auto_response_rule_is_registered(state, rule)
        ):
            state.auto_response_rule_loops.pop(signature, None)
            state.auto_response_running_rules.discard(signature)
            return
        latest_scan_text = state.auto_response_buffer or scan_text
        next_delay, exit_scope = self.schedule_auto_response_actions(
            state,
            rule,
            action.actions,
            latest_scan_text,
            0,
            run_token,
        )
        if exit_scope is not None:
            self.finish_auto_response_infinite_loop(state, rule, exit_scope)
            return
        if QTimer is None:
            self.finish_auto_response_infinite_loop(state, rule, "loop")
            return
        interval_ms = max(0, int(action.interval_ms or 0))
        next_iteration_delay_ms = max(10, int(next_delay or 0) + interval_ms)
        QTimer.singleShot(
            next_iteration_delay_ms,
            lambda: self.run_auto_response_infinite_loop_iteration(state, rule, action, scan_text, run_token),
        )

    def finish_auto_response_infinite_loop(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        exit_scope: str | None,
    ) -> None:
        signature = self.auto_response_rule_signature(rule)
        state.auto_response_rule_loops.pop(signature, None)
        state.auto_response_running_rules.discard(signature)
        if exit_scope == "rule":
            rule.enabled = False
        if rule.once:
            state.auto_response_triggered_rules.add(signature)
            rule.enabled = False
        if rule.max_triggers and rule.trigger_count >= rule.max_triggers:
            rule.enabled = False
        self.refresh_auto_response_rule_buttons()
        self.schedule_desktop_state_save()

    def auto_response_rule_is_registered(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
    ) -> bool:
        signature = self.auto_response_rule_signature(rule)
        rules = self.remembered_auto_response_rules or state.auto_response_rules
        return any(self.auto_response_rule_signature(saved_rule) == signature for saved_rule in rules)

    @classmethod
    def auto_response_actions_have_infinite_loop(cls, actions: list[AutoResponseAction]) -> bool:
        for action in actions:
            if action.kind == "loop" and cls.normalize_auto_response_repeat_count(action.repeat_count) == 0:
                return True
            if action.actions and cls.auto_response_actions_have_infinite_loop(action.actions):
                return True
        return False

    def schedule_auto_response_send(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        action: AutoResponseAction,
        delay_ms: int,
        run_token: int,
    ) -> None:
        response = decode_response_text(action.text, append_enter=action.append_enter)
        if not response:
            return
        target_tab_id = self.auto_response_target_tab_id(state, action.target)
        if not target_tab_id:
            self.write_session_log_line(state, "SYS", f"Auto response target missing: {action.target}")
            self.set_status_message(f"自动化目标终端不存在: {action.target}")
            return
        if delay_ms > 0 and QTimer is not None:
            QTimer.singleShot(
                delay_ms,
                lambda tab_id=target_tab_id, text=response, token=run_token: self.send_auto_response_text_if_running(
                    state,
                    rule,
                    token,
                    tab_id,
                    text,
                ),
            )
        else:
            self.send_auto_response_text_if_running(state, rule, run_token, target_tab_id, response)

    def send_auto_response_text_if_running(
        self,
        state: SessionTabState,
        rule: AutoResponseRule,
        run_token: int,
        tab_id: str,
        text: str,
        *,
        finish: bool = False,
    ) -> None:
        if not self.auto_response_rule_run_is_active(state, rule, run_token):
            return
        self.send_session_text(tab_id, text)
        if finish:
            self.finish_auto_response_rule_run(state, rule, run_token)

    def auto_response_pattern_matches(
        self,
        rule: AutoResponseRule,
        pattern: str,
        output: str,
    ) -> bool:
        step = AutoResponseStep(pattern=pattern)
        return self.auto_response_step_matches(rule, step, output)

    def auto_response_action_condition_matches(
        self,
        rule: AutoResponseRule,
        action: AutoResponseAction,
        output: str,
    ) -> bool:
        pattern = action.condition_pattern.strip()
        if not rule.enabled or not pattern:
            return False
        if action.condition_match_type == "regex":
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            try:
                return re.search(pattern, output, flags) is not None
            except re.error:
                return False
        haystack = output if rule.case_sensitive else output.lower()
        needle = pattern if rule.case_sensitive else pattern.lower()
        return needle in haystack

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
                response_append_enters=[rule.append_enter],
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
                term_size=state.terminal.terminal_dimensions(),
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
            self.apply_auto_response_rules(current_state, "", trigger_event="connected")
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
            self.schedule_desktop_state_save()

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
            self.schedule_desktop_state_save()

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
