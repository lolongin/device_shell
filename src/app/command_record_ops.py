"""Command record management mixin for DeviceDesktopApp."""
from __future__ import annotations

import re
from typing import Any

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLineEdit, QMenu, QToolButton, QWidget
except ModuleNotFoundError:
    Qt = None
    QTextCursor = None
    QHBoxLayout = None
    QInputDialog = None
    QLineEdit = None
    QMenu = None
    QToolButton = None
    QWidget = None

from ..command_suggestions import CommandHistoryItem, record_command_history, suggest_commands


class CommandRecordOpsMixin:
    """Mixin providing command record (常用命令) input, tab, and panel operations."""

    def submit_command_record_input(self, command: str) -> None:
        self.remember_command_history(command)
        self._save_current_command_content()
        self.schedule_desktop_state_save()
        self.send_command_text_to_current_session(command)

    def submit_current_command_record(self) -> None:
        command = self.command_record_input.current_command_line()
        if not command:
            self.set_status_message("请先将光标放到要发送的命令行。")
            return
        self.submit_command_record_input(command)

    def send_command_text_to_current_session(self, command: str) -> None:
        state = self.current_session_state()
        if state is None:
            self.set_status_message("命令已记录，当前没有打开的终端会话。")
            return
        self.send_session_text(state.tab_id, self.command_record_payload(command))
        self.focus_current_terminal(force=True)

    def broadcast_command_record_input(self) -> None:
        command = self.command_record_input.current_command_line()
        if not command:
            self.set_status_message("请先将光标放到要广播发送的命令行。")
            return
        self._save_current_command_content()
        connected_states = [
            state for state in self.session_tabs_by_id.values() if state.session.is_connected
        ]
        if not connected_states:
            self.set_status_message("命令已记录，当前没有已连接的终端会话。")
            return
        payload = self.command_record_payload(command)
        for state in connected_states:
            self.send_session_text(state.tab_id, payload)
        self.remember_command_history(command)
        self.schedule_desktop_state_save()
        self.set_status_message(f"已广播发送到 {len(connected_states)} 个终端会话。")

    def command_record_payload(self, command: str) -> str:
        normalized = command.replace("\r\n", "\n").replace("\r", "\n")
        payload = normalized.replace("\n", "\r")
        return f"{payload}\r"

    def remember_command_history(self, command: str, state: Any | None = None) -> None:
        if state is None:
            state = self.current_session_state()
        self.command_history = record_command_history(
            self.command_history,
            command,
            device_id=state.device_id if state is not None else "",
            session_kind=state.kind if state is not None else "",
        )
        self.refresh_command_suggestions()

    def refresh_command_suggestions(self) -> None:
        if not hasattr(self, "command_suggestion_bar") or not hasattr(self, "command_record_input"):
            return
        while self.command_suggestion_layout.count():
            item = self.command_suggestion_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        query = self.command_record_input.current_command_line()
        state = self.current_session_state()
        suggestions = suggest_commands(
            self.command_suggestion_history(),
            query,
            device_id=state.device_id if state is not None else "",
            session_kind=state.kind if state is not None else "",
            limit=5,
        )
        self.current_command_suggestions = suggestions
        self.command_suggestion_buttons = []
        if not suggestions:
            self.command_suggestion_bar.setVisible(False)
            return
        self.command_suggestion_bar.setVisible(True)
        for suggestion in suggestions:
            button = QToolButton()
            button.setObjectName("commandSuggestionButton")
            button.setText(suggestion)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setToolTip("点击填入命令，Tab 使用第一条建议")
            button.clicked.connect(
                lambda _checked=False, command=suggestion: self.apply_command_suggestion(command)
            )
            self.command_suggestion_buttons.append(button)
            self.command_suggestion_layout.addWidget(button)
        self.command_suggestion_layout.addStretch(1)

    def accept_first_command_suggestion(self) -> bool:
        if not self.current_command_suggestions:
            self.refresh_command_suggestions()
        if not self.current_command_suggestions:
            return False
        self.apply_command_suggestion(self.current_command_suggestions[0])
        return True

    def apply_command_suggestion(self, command: str) -> None:
        cursor = self.command_record_input.textCursor()
        cursor.select(QTextCursor.LineUnderCursor)
        cursor.insertText(command)
        self.command_record_input.setTextCursor(cursor)
        self.command_record_input.setFocus()
        self.refresh_command_suggestions()

    def command_suggestion_history(self) -> list[CommandHistoryItem]:
        history = list(self.command_history)
        known_commands = {item.command for item in history}
        for command in self.current_command_records():
            if command in known_commands:
                continue
            history.append(CommandHistoryItem(command=command, count=1, last_used_at=0))
            known_commands.add(command)
        return history

    def terminal_command_suggestion(self, state: Any, query: str) -> str:
        suggestions = suggest_commands(
            self.command_suggestion_history(),
            query,
            device_id=getattr(state, "device_id", ""),
            session_kind=getattr(state, "kind", ""),
            limit=1,
        )
        return suggestions[0] if suggestions else ""

    def toggle_command_find_replace(self) -> None:
        if self.command_find_replace_visible:
            self.hide_command_find_replace()
            return
        self.show_command_find_replace()

    def show_command_find_replace(self) -> None:
        if self.command_record_collapsed:
            self.command_record_collapsed = False
        selected = self.command_record_input.textCursor().selectedText().replace("\u2029", "\n")
        if selected:
            self.command_find_input.setText(selected)
        self.command_find_replace_visible = True
        self.apply_command_record_panel_state()
        self.command_find_input.setFocus()
        self.command_find_input.selectAll()

    def hide_command_find_replace(self) -> None:
        self.command_find_replace_visible = False
        self.command_find_replace_bar.setVisible(False)
        if not self.command_record_collapsed:
            self.command_record_input.setFocus()

    def find_next_command_record_match(self) -> None:
        query = self.command_find_input.text()
        if not query:
            self.set_status_message("请输入要查找的命令文本。")
            self.command_find_input.setFocus()
            return
        cursor = self.command_record_input.textCursor()
        start = cursor.selectionEnd() if cursor.hasSelection() else cursor.position()
        if not self._select_command_record_match(query, start):
            self.set_status_message(f"未找到: {query}")

    def replace_current_command_record_match(self) -> None:
        query = self.command_find_input.text()
        if not query:
            self.set_status_message("请输入要替换的命令文本。")
            self.command_find_input.setFocus()
            return
        cursor = self.command_record_input.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        if not cursor.hasSelection() or selected.lower() != query.lower():
            start = cursor.position()
            if not self._select_command_record_match(query, start):
                self.set_status_message(f"未找到: {query}")
                return
            cursor = self.command_record_input.textCursor()
        cursor.insertText(self.command_replace_input.text())
        self._save_current_command_content()
        self.schedule_desktop_state_save()
        self.find_next_command_record_match()

    def replace_all_command_record_matches(self) -> None:
        query = self.command_find_input.text()
        if not query:
            self.set_status_message("请输入要替换的命令文本。")
            self.command_find_input.setFocus()
            return
        content = self.command_record_input.toPlainText()
        replacement = self.command_replace_input.text()
        updated, count = re.subn(re.escape(query), lambda _match: replacement, content, flags=re.IGNORECASE)
        if count == 0:
            self.set_status_message(f"未找到: {query}")
            return
        self.command_record_input.setPlainText(updated)
        self._save_current_command_content()
        self.schedule_desktop_state_save()
        self.set_status_message(f"已替换 {count} 处命令文本。")
        self.command_record_input.setFocus()

    def _select_command_record_match(self, query: str, start: int) -> bool:
        content = self.command_record_input.toPlainText()
        lowered_content = content.lower()
        lowered_query = query.lower()
        index = lowered_content.find(lowered_query, max(0, start))
        wrapped = False
        if index < 0 and start > 0:
            index = lowered_content.find(lowered_query)
            wrapped = index >= 0
        if index < 0:
            return False
        cursor = self.command_record_input.textCursor()
        cursor.setPosition(index)
        cursor.setPosition(index + len(query), QTextCursor.KeepAnchor)
        self.command_record_input.setTextCursor(cursor)
        self.command_record_input.ensureCursorVisible()
        self.command_record_input.setFocus()
        suffix = "（已回到开头）" if wrapped else ""
        self.set_status_message(f"已定位: {query}{suffix}")
        return True

    def add_command_record(self, command: str) -> None:
        normalized = command.strip()
        if not normalized:
            return
        self._save_current_command_content()
        records = self.current_command_records()
        if normalized in records:
            return
        group = self.command_record_groups[self.current_command_group_index()]
        content = str(group.get("content", "")).rstrip()
        group["content"] = f"{content}\n{normalized}" if content else normalized
        self._load_current_command_content(move_cursor_to_end=True)
        self.schedule_desktop_state_save()

    def current_command_group_index(self) -> int:
        index = self.current_command_group
        if index < 0 or index >= len(self.command_record_groups):
            return 0
        return index

    def current_command_records(self) -> list[str]:
        group = self.command_record_groups[self.current_command_group_index()]
        content = str(group.get("content", ""))
        return [line.strip() for line in content.splitlines() if line.strip()]

    def rebuild_command_record_tabs(self) -> None:
        while self.command_tab_row.count():
            item = self.command_tab_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.command_tab_buttons = []
        self.command_tab_close_buttons = []

        for index, group in enumerate(self.command_record_groups):
            tab_item = QWidget()
            tab_item.setObjectName("commandTabItem")
            tab_layout = QHBoxLayout(tab_item)
            tab_layout.setContentsMargins(0, 0, 2, 0)
            tab_layout.setSpacing(0)

            button = QToolButton()
            button.setObjectName("commandTabButton")
            button.setText(str(group["name"]))
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolTip("右键重命名")
            button.setProperty("commandGroupIndex", index)
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.clicked.connect(lambda _checked=False, tab_index=index: self.switch_command_group(tab_index))
            button.customContextMenuRequested.connect(
                lambda pos, tab_index=index, tab_button=button: self.show_command_group_context_menu(
                    tab_index,
                    tab_button,
                    pos,
                )
            )
            self.command_tab_buttons.append(button)
            tab_layout.addWidget(button)

            close_button = QToolButton()
            close_button.setObjectName("commandTabCloseButton")
            close_button.setText("×")
            close_button.setAutoRaise(True)
            close_button.setToolTip("删除页签")
            close_button.clicked.connect(lambda _checked=False, tab_index=index: self.remove_command_group(tab_index))
            self.command_tab_close_buttons.append(close_button)
            tab_layout.addWidget(close_button)
            self.command_tab_row.addWidget(tab_item)

        plus_button = QToolButton()
        plus_button.setObjectName("commandTabButton")
        plus_button.setText("+")
        plus_button.setAutoRaise(True)
        plus_button.clicked.connect(self.add_command_group)
        self.command_tab_row.addWidget(plus_button)
        self.refresh_command_tab_styles()

    def switch_command_group(self, index: int) -> None:
        if index < 0 or index >= len(self.command_record_groups):
            return
        self._save_current_command_content()
        self.current_command_group = index
        self._load_current_command_content(move_cursor_to_end=False)
        self.refresh_command_tab_styles()
        self.schedule_desktop_state_save()

    def add_command_group(self) -> None:
        existing_names = {str(group["name"]) for group in self.command_record_groups}
        next_index = max(len(self.command_record_groups), 1)
        name = f"分组 {next_index}"
        while name in existing_names:
            next_index += 1
            name = f"分组 {next_index}"
        self._save_current_command_content()
        self.command_record_groups.append({"name": name, "content": ""})
        self.rebuild_command_record_tabs()
        self.switch_command_group(len(self.command_record_groups) - 1)
        self.schedule_desktop_state_save()

    def rename_command_group(self, index: int) -> None:
        if QInputDialog is None:
            return
        if index < 0 or index >= len(self.command_record_groups):
            return
        old_name = str(self.command_record_groups[index].get("name") or "").strip()
        new_name, ok = QInputDialog.getText(
            self,
            "重命名页签",
            "页签名称",
            QLineEdit.Normal,
            old_name,
        )
        if not ok:
            return
        name = new_name.strip()
        if not name or name == old_name:
            return
        existing_names = {
            str(group.get("name") or "").strip()
            for group_index, group in enumerate(self.command_record_groups)
            if group_index != index
        }
        if name in existing_names:
            self.show_warning("已存在同名页签。")
            return
        self._save_current_command_content()
        self.command_record_groups[index]["name"] = name
        current_index = self.current_command_group_index()
        self.rebuild_command_record_tabs()
        self.current_command_group = current_index
        self.refresh_command_tab_styles()
        self.set_status_message(f"已重命名常用命令页签: {name}")
        self.schedule_desktop_state_save()

    def show_command_group_context_menu(self, index: int, button: QToolButton, pos: Any) -> None:
        if index < 0 or index >= len(self.command_record_groups):
            return
        menu = QMenu(button)
        rename_action = menu.addAction("重命名")
        chosen = menu.exec(button.mapToGlobal(pos))
        if chosen == rename_action:
            self.rename_command_group(index)

    def remove_command_group(self, index: int) -> None:
        if len(self.command_record_groups) <= 1:
            self.set_status_message("至少保留一个常用命令页签。")
            return
        if index < 0 or index >= len(self.command_record_groups):
            return
        self._save_current_command_content()
        removed_name = str(self.command_record_groups[index]["name"])
        del self.command_record_groups[index]
        if index < self.current_command_group:
            self.current_command_group -= 1
        elif index == self.current_command_group:
            self.current_command_group = min(index, len(self.command_record_groups) - 1)
        self.rebuild_command_record_tabs()
        self._load_current_command_content(move_cursor_to_end=False)
        self.set_status_message(f"已删除常用命令页签: {removed_name}")
        self.schedule_desktop_state_save()

    def refresh_command_tab_styles(self) -> None:
        for index, button in enumerate(self.command_tab_buttons):
            selected = index == self.current_command_group_index()
            button.setChecked(selected)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()
            if index < len(self.command_tab_close_buttons):
                close_button = self.command_tab_close_buttons[index]
                close_button.setVisible(len(self.command_record_groups) > 1)
                close_button.setProperty("selected", selected)
                close_button.style().unpolish(close_button)
                close_button.style().polish(close_button)
                close_button.update()

    def _save_current_command_content(self) -> None:
        if not hasattr(self, "command_record_input"):
            return
        self.command_record_groups[self.current_command_group_index()]["content"] = (
            self.command_record_input.toPlainText()
        )

    def _load_current_command_content(self, move_cursor_to_end: bool) -> None:
        if not hasattr(self, "command_record_input"):
            return
        content = str(self.command_record_groups[self.current_command_group_index()].get("content", ""))
        self.command_record_input.setPlainText(content)
        if move_cursor_to_end:
            cursor = self.command_record_input.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.command_record_input.setTextCursor(cursor)

    def clear_current_command_record(self) -> None:
        self.command_record_input.clear()
        self.command_record_groups[self.current_command_group_index()]["content"] = ""
        self.command_record_input.setFocus()
        self.schedule_desktop_state_save()

    def toggle_command_enter_mode(self) -> None:
        self.command_enter_sends = not self.command_enter_sends
        self.update_command_enter_mode()
        message = "Enter 发送，Ctrl+Enter 换行" if self.command_enter_sends else "Enter 换行，Ctrl+Enter 发送"
        self.set_status_message(f"常用命令已切换为: {message}")
        self.schedule_desktop_state_save()

    def update_command_enter_mode(self) -> None:
        if not hasattr(self, "command_record_input"):
            return
        self.command_record_input.set_enter_sends(self.command_enter_sends)
        hint = (
            "常用命令"
            if self.command_record_collapsed
            else (
                "常用命令  ·  Enter 发送"
                if self.command_enter_sends
                else "常用命令  ·  Ctrl+Enter 发送"
            )
        )
        self.command_record_hint_label.setText(hint)
        self.command_enter_mode_button.setProperty("enterSends", self.command_enter_sends)
        self.command_enter_mode_button.setToolTip(
            "切换为 Ctrl+Enter 发送" if self.command_enter_sends else "切换为 Enter 发送"
        )
        self.command_enter_mode_button.style().unpolish(self.command_enter_mode_button)
        self.command_enter_mode_button.style().polish(self.command_enter_mode_button)
        self.command_enter_mode_button.update()

    def toggle_command_record_panel(self) -> None:
        self._save_current_command_content()
        will_expand = self.command_record_collapsed
        self.command_record_collapsed = not self.command_record_collapsed
        self.apply_command_record_panel_state(focus_editor=will_expand)
        self.schedule_desktop_state_save()

    def clamp_command_record_height(self, height: int) -> int:
        return max(self.COMMAND_RECORD_MIN_HEIGHT, min(self.COMMAND_RECORD_MAX_HEIGHT, height))

    def resize_command_record_panel(self, height: int) -> None:
        if self.command_record_collapsed:
            return
        self.command_record_height = self.clamp_command_record_height(height)
        self.apply_command_record_panel_state()
        self.schedule_desktop_state_save()
