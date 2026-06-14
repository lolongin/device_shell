"""Server management mixin for DeviceDesktopApp."""
from __future__ import annotations

import uuid
from typing import Any

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMenu,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:
    QAction = None
    QCheckBox = None
    QComboBox = None
    QDialog = None
    QDialogButtonBox = None
    QFormLayout = None
    QFrame = None
    QGroupBox = None
    QHBoxLayout = None
    QInputDialog = None
    QLabel = None
    QLineEdit = None
    QMenu = None
    QMessageBox = None
    QPlainTextEdit = None
    QPushButton = None
    QScrollArea = None
    QSizePolicy = None
    QSpinBox = None
    Qt = None
    QToolButton = None
    QTimer = None
    QVBoxLayout = None
    QWidget = None

try:
    from ..data import Device, SavedServer
except ImportError:
    from data import Device, SavedServer


def _generate_server_id() -> str:
    return f"srv-{uuid.uuid4().hex[:12]}"


def _is_server_expandable_group(name: str) -> bool:
    return bool(name)


class ServerOpsMixin:
    """Mixin providing saved SSH server management UI."""

    def _build_server_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("leftRail")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)

        group = QGroupBox("我的服务器")
        group.setObjectName("navShell")
        group.setContextMenuPolicy(Qt.CustomContextMenu) if Qt is not None else None
        if hasattr(group, "customContextMenuRequested"):
            group.customContextMenuRequested.connect(
                lambda pos, widget=group: self._show_server_panel_context_menu(widget, pos)
            )
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("我的服务器")
        title.setObjectName("railTitle")
        copy = QLabel("管理常用 SSH 服务器，点击一键连接")
        copy.setObjectName("railCopy")
        copy.setWordWrap(True)
        copy.setMinimumWidth(0)
        if QSizePolicy is not None:
            copy.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title_col.addWidget(title)
        title_col.addWidget(copy)
        header.addLayout(title_col, 1)
        group_layout.addLayout(header)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.server_search_input = QLineEdit()
        self.server_search_input.setPlaceholderText("搜索服务器名、IP、分组")
        self.server_search_input.textChanged.connect(self._refresh_server_panel)
        search_row.addWidget(self.server_search_input, 1)

        self.server_add_button = QPushButton("添加")
        self.server_add_button.setObjectName("compactGhostButton")
        self.server_add_button.setFixedWidth(58)
        self.server_add_button.clicked.connect(self._show_add_server_dialog)
        search_row.addWidget(self.server_add_button)

        group_layout.addLayout(search_row)

        self.server_empty_label = QLabel('还没有保存的服务器。点击「添加」新增。')
        self.server_empty_label.setObjectName("sectionCopy")
        self.server_empty_label.setWordWrap(True)
        group_layout.addWidget(self.server_empty_label)

        self.server_list_container = QWidget()
        self.server_list_container.setObjectName("leftRail")
        self.server_list_container.setContextMenuPolicy(Qt.CustomContextMenu) if Qt is not None else None
        if hasattr(self.server_list_container, "customContextMenuRequested"):
            self.server_list_container.customContextMenuRequested.connect(
                lambda pos, widget=self.server_list_container: self._show_server_panel_context_menu(widget, pos)
            )
        self.server_list_layout = QVBoxLayout(self.server_list_container)
        self.server_list_layout.setContentsMargins(0, 0, 0, 0)
        self.server_list_layout.setSpacing(6)
        group_layout.addWidget(self.server_list_container)
        group_layout.addStretch(1)

        layout.addWidget(group)
        layout.addStretch(1)
        self._refresh_server_panel()
        return panel

    def _toggle_server_group(self, group_name: str) -> None:
        expanded = getattr(self, "_server_group_expanded", {})
        expanded[group_name] = not expanded.get(group_name, True)
        self._refresh_server_panel()

    def _refresh_server_panel(self) -> None:
        if not hasattr(self, "server_list_layout"):
            return
        while self.server_list_layout.count():
            item = self.server_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        query = self.server_search_input.text().strip().lower() if hasattr(self, "server_search_input") else ""
        servers = getattr(self, "saved_servers", [])
        filtered = [s for s in servers if not query or query in s.name.lower() or query in s.host.lower() or query in s.group.lower()]

        groups: dict[str, list[SavedServer]] = {}
        if not query:
            for group_name in self._server_group_names():
                groups.setdefault(group_name, [])
        for s in filtered:
            g = s.group or "未分组"
            groups.setdefault(g, []).append(s)

        self.server_empty_label.setVisible(not groups)
        if not groups:
            if query and (servers or self._server_group_names()):
                self.server_empty_label.setText("没有匹配的服务器。清空搜索条件后可查看全部。")
            else:
                self.server_empty_label.setText('还没有保存的服务器或分组。右键新建分组，或点击「添加」新增。')
            return

        expanded = dict(getattr(self, "_server_group_expanded", {}))
        for g_name in groups:
            if g_name not in expanded:
                expanded[g_name] = True
        self._server_group_expanded = expanded

        for g_name in sorted(groups, key=lambda x: (x == "未分组", x)):
            members = groups[g_name]
            is_expanded = expanded.get(g_name, True)

            group_header = self._server_group_header(g_name, len(members), is_expanded)
            group_header.setProperty("serverGroupName", g_name)
            group_header.mousePressEvent = lambda event, name=g_name: self._toggle_server_group(name)
            group_header.keyPressEvent = lambda event, name=g_name: self._handle_server_group_key_press(event, name)
            group_header.setContextMenuPolicy(Qt.CustomContextMenu) if Qt is not None else None
            if hasattr(group_header, "customContextMenuRequested"):
                group_header.customContextMenuRequested.connect(
                    lambda pos, name=g_name, widget=group_header: self._show_server_group_context_menu(name, widget, pos)
                )
            self.server_list_layout.addWidget(group_header)

            if is_expanded:
                for server in members:
                    card = self._server_card(server)
                    self.server_list_layout.addWidget(card)

    def _server_group_header(self, name: str, count: int, expanded: bool) -> QFrame:
        frame = QFrame()
        frame.setObjectName("serverGroupHeader")
        frame.setCursor(Qt.PointingHandCursor) if Qt is not None else None
        frame.setFocusPolicy(Qt.StrongFocus) if Qt is not None else None
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        arrow = QLabel("▼" if expanded else "▶")
        arrow.setObjectName("serverGroupArrow")
        layout.addWidget(arrow)
        label = QLabel(f"{name}  ({count})")
        label.setObjectName("serverGroupTitle")
        layout.addWidget(label, 1)
        return frame

    def _handle_server_group_key_press(self, event: Any, group_name: str) -> None:
        if Qt is not None and hasattr(event, "key") and event.key() in (
            Qt.Key_Return,
            Qt.Key_Enter,
            Qt.Key_Space,
        ):
            self._toggle_server_group(group_name)
            return
        if hasattr(event, "ignore"):
            event.ignore()

    def _server_card(self, server: SavedServer) -> QFrame:
        card = QFrame()
        card.setObjectName("serverCard")
        card.setToolTip("点击卡片连接 SSH，右键更多操作")
        card.setCursor(Qt.PointingHandCursor) if Qt is not None else None
        card.setFocusPolicy(Qt.StrongFocus) if Qt is not None else None
        card.mousePressEvent = lambda event, s=server: self._handle_server_card_press(event, s)
        card.keyPressEvent = lambda event, s=server: self._handle_server_card_key_press(event, s)
        card.setContextMenuPolicy(Qt.CustomContextMenu) if Qt is not None else None
        if QFrame is not None and hasattr(card, "customContextMenuRequested"):
            card.customContextMenuRequested.connect(
                lambda pos, s=server: self._show_server_context_menu(s, card, pos)
            )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        name_label = QLabel(server.name)
        name_label.setObjectName("serverCardName")
        top_row.addWidget(name_label, 1)

        connect_btn = QPushButton("连接")
        connect_btn.setObjectName("primaryButton")
        connect_btn.setFixedWidth(58)
        connect_btn.clicked.connect(lambda _checked=False, s=server: self._open_server_session(s))
        top_row.addWidget(connect_btn)

        edit_btn = QPushButton("编辑")
        edit_btn.setObjectName("compactGhostButton")
        edit_btn.setFixedWidth(52)
        edit_btn.clicked.connect(lambda _checked=False, s=server: self._show_edit_server_dialog(s))
        top_row.addWidget(edit_btn)

        layout.addLayout(top_row)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        host_label = QLabel(f"{server.host}:{server.port}")
        host_label.setObjectName("serverCardMeta")
        meta_row.addWidget(host_label)
        if server.username:
            user_label = QLabel(server.username)
            user_label.setObjectName("serverCardMeta")
            meta_row.addWidget(user_label)
        meta_row.addStretch(1)
        layout.addLayout(meta_row)

        return card

    def _normalized_server_group_name(self, name: str) -> str:
        group_name = name.strip()
        return "" if group_name == "未分组" else group_name

    def _server_group_names(self) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for group_name in getattr(self, "saved_server_groups", []):
            normalized = self._normalized_server_group_name(str(group_name))
            if normalized and normalized not in seen:
                seen.add(normalized)
                names.append(normalized)
        for server in getattr(self, "saved_servers", []):
            normalized = self._normalized_server_group_name(server.group)
            if normalized and normalized not in seen:
                seen.add(normalized)
                names.append(normalized)
        return sorted(names)

    def _remember_server_group(self, group_name: str) -> str:
        normalized = self._normalized_server_group_name(group_name)
        if not normalized:
            return ""
        groups = list(getattr(self, "saved_server_groups", []))
        if normalized not in groups:
            groups.append(normalized)
            self.saved_server_groups = sorted(groups)
        return normalized

    def _show_server_panel_context_menu(self, widget: QWidget, pos: Any) -> None:
        if QMenu is None:
            return
        menu = QMenu(widget)
        menu.setObjectName("workspaceContextMenu")
        add_group_action = menu.addAction("新建分组...")
        add_server_action = menu.addAction("新增服务器...")
        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen == add_group_action:
            self._create_server_group()
        elif chosen == add_server_action:
            self._show_server_dialog()

    def _create_server_group(self, initial_name: str = "") -> str:
        if QInputDialog is None:
            return ""
        name, accepted = QInputDialog.getText(
            self,
            "新建分组",
            "分组名称：",
            text=initial_name,
        )
        if not accepted:
            return ""
        group_name = self._normalized_server_group_name(name)
        if not group_name:
            self.set_status_message("分组名称不能为空")
            return ""
        if group_name in self._server_group_names():
            self.set_status_message(f"分组「{group_name}」已存在")
            return group_name
        self._remember_server_group(group_name)
        expanded = dict(getattr(self, "_server_group_expanded", {}))
        expanded[group_name] = True
        self._server_group_expanded = expanded
        self._refresh_server_panel()
        self.schedule_desktop_state_save()
        self.set_status_message(f"已创建分组 {group_name}")
        return group_name

    def _handle_server_card_press(self, event: Any, server: SavedServer) -> None:
        if Qt is not None and hasattr(event, "button") and event.button() == Qt.LeftButton:
            self._open_server_session(server)
            return
        if hasattr(event, "ignore"):
            event.ignore()

    def _handle_server_card_key_press(self, event: Any, server: SavedServer) -> None:
        if Qt is not None and hasattr(event, "key") and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._open_server_session(server)
            return
        if hasattr(event, "ignore"):
            event.ignore()

    def _show_server_group_context_menu(self, group_name: str, widget: QWidget, pos: Any) -> None:
        if QMenu is None:
            return
        menu = QMenu(widget)
        menu.setObjectName("workspaceContextMenu")
        add_action = menu.addAction(f"在「{group_name}」中新增服务器")
        create_group_action = menu.addAction("新建分组...")
        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen == add_action:
            self._show_server_dialog(prefill_group=group_name)
        elif chosen == create_group_action:
            self._create_server_group()

    def _show_server_context_menu(self, server: SavedServer, widget: QWidget, pos: Any) -> None:
        if QMenu is None or QWidget is None:
            return
        menu = QMenu(widget)
        menu.setObjectName("workspaceContextMenu")
        connect_action = menu.addAction("连接 SSH")
        edit_action = menu.addAction("编辑...")
        copy_action = menu.addAction("复制连接信息")
        move_menu = menu.addMenu("移动到分组")
        move_actions: dict[Any, str] = {}
        ungrouped_action = move_menu.addAction("未分组")
        move_actions[ungrouped_action] = ""
        group_names = self._server_group_names()
        if group_names:
            move_menu.addSeparator()
        for group_name in group_names:
            action = move_menu.addAction(group_name)
            action.setEnabled(group_name != server.group)
            move_actions[action] = group_name
        move_menu.addSeparator()
        create_group_action = move_menu.addAction("新建分组...")
        menu.addSeparator()
        delete_action = menu.addAction("删除")
        delete_action.setProperty("danger", True)
        chosen = menu.exec(widget.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == connect_action:
            self._open_server_session(server)
        elif chosen == edit_action:
            self._show_edit_server_dialog(server)
        elif chosen == copy_action:
            self._copy_server_connection(server)
        elif chosen in move_actions:
            self._move_server_to_group(server, move_actions[chosen])
        elif chosen == create_group_action:
            group_name = self._create_server_group()
            if group_name:
                self._move_server_to_group(server, group_name)
        elif chosen == delete_action:
            self._delete_server(server)

    def _move_server_to_group(self, server: SavedServer, group_name: str) -> None:
        normalized_group = self._remember_server_group(group_name)
        servers = list(getattr(self, "saved_servers", []))
        updated = SavedServer(
            id=server.id,
            name=server.name,
            host=server.host,
            port=server.port,
            username=server.username,
            password=server.password,
            group=normalized_group,
            notes=server.notes,
        )
        for index, candidate in enumerate(servers):
            if candidate.id == server.id:
                servers[index] = updated
                break
        self.saved_servers = servers
        self._refresh_server_panel()
        self.schedule_desktop_state_save()
        target = normalized_group or "未分组"
        self.set_status_message(f"已将 {server.name} 移动到 {target}")

    def _copy_server_connection(self, server: SavedServer) -> None:
        from PySide6.QtWidgets import QApplication
        text = f"ssh {server.username}@{server.host} -p {server.port}" if server.username else f"ssh {server.host} -p {server.port}"
        QApplication.clipboard().setText(text)
        if hasattr(self, "set_status_message"):
            self.set_status_message(f"已复制 {server.name} 的连接信息")

    def saved_server_by_id(self, server_id: str) -> SavedServer | None:
        for server in getattr(self, "saved_servers", []):
            if server.id == server_id:
                return server
        return None

    def is_saved_server_device(self, device: Device | None) -> bool:
        if device is None:
            return False
        return device.domain == "server" or self.saved_server_by_id(device.id) is not None

    def _show_add_server_dialog(self) -> None:
        self._show_server_dialog()

    def _show_edit_server_dialog(self, server: SavedServer | None = None) -> None:
        self._show_server_dialog(server)

    def _find_duplicate_server(self, host: str, port: int, *, ignore_id: str = "") -> SavedServer | None:
        normalized_host = host.strip().lower()
        for candidate in getattr(self, "saved_servers", []):
            if ignore_id and candidate.id == ignore_id:
                continue
            if candidate.host.strip().lower() == normalized_host and candidate.port == port:
                return candidate
        return None

    def _show_server_dialog(self, server: SavedServer | None = None, *, prefill_group: str = "") -> None:
        if QDialog is None:
            return
        is_edit = server is not None
        dialog = QDialog(self)
        dialog.setObjectName("workspaceDialog")
        dialog.setWindowTitle("编辑服务器" if is_edit else "添加服务器")
        dialog.setMinimumWidth(400)
        dialog.setModal(True)

        form_card = QFrame()
        form_card.setObjectName("dialogFormCard")
        form = QFormLayout(form_card)
        form.setContentsMargins(12, 12, 12, 12)
        form.setVerticalSpacing(8)
        form.setHorizontalSpacing(10)

        name_input = QLineEdit()
        name_input.setPlaceholderText("例如：核心路由-北京")
        if is_edit:
            name_input.setText(server.name)
        form.addRow("名称", name_input)

        host_input = QLineEdit()
        host_input.setPlaceholderText("IP 地址或域名")
        if is_edit:
            host_input.setText(server.host)
        form.addRow("主机", host_input)

        port_input = QSpinBox()
        port_input.setRange(1, 65535)
        port_input.setValue(server.port if is_edit else 22)
        form.addRow("端口", port_input)

        user_input = QLineEdit()
        user_input.setPlaceholderText("SSH 用户名")
        if is_edit:
            user_input.setText(server.username)
        else:
            user_input.setText("root")
        form.addRow("用户名", user_input)

        pass_input = QLineEdit()
        pass_input.setPlaceholderText("（可选）留空则连接时手动输入")
        pass_input.setEchoMode(QLineEdit.Password)
        if is_edit:
            pass_input.setText(server.password)
        form.addRow("密码", pass_input)

        save_password_checkbox = QCheckBox("保存密码到本机配置")
        save_password_checkbox.setToolTip("未勾选时仅保存账号，连接时手动输入密码。")
        save_password_checkbox.setChecked(bool(server.password) if is_edit else False)
        form.addRow("", save_password_checkbox)
        password_hint = QLabel("密码会写入本机桌面状态文件；不勾选则连接时手动输入。")
        password_hint.setObjectName("sectionCopy")
        password_hint.setWordWrap(True)
        form.addRow("", password_hint)

        existing_groups = self._server_group_names()
        group_combo = QComboBox()
        group_combo.setEditable(True)
        group_combo.addItem("")
        for g in existing_groups:
            group_combo.addItem(g)
        group_combo.setCurrentText(
            server.group if is_edit and server.group else (prefill_group if prefill_group else "")
        )
        group_combo.lineEdit().setPlaceholderText("新建或选择分组")
        form.addRow("分组", group_combo)

        notes_input = QPlainTextEdit()
        notes_input.setPlaceholderText("备注（可选）")
        notes_input.setMaximumHeight(68)
        if is_edit and server.notes:
            notes_input.setPlainText(server.notes)
        form.addRow("备注", notes_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.setObjectName("workspaceDialogButtons")
        buttons.rejected.connect(dialog.reject)
        connect_after_save = {"value": False}
        primary_button = buttons.addButton("保存" if is_edit else "保存并连接", QDialogButtonBox.AcceptRole)
        primary_button.setObjectName("primaryButton")
        save_only_button = None
        if not is_edit:
            save_only_button = buttons.addButton("仅保存", QDialogButtonBox.ActionRole)
            save_only_button.setObjectName("compactGhostButton")

        def update_password_save_state() -> None:
            has_password = bool(pass_input.text())
            save_password_checkbox.setEnabled(has_password)
            if not has_password:
                save_password_checkbox.setChecked(False)

        def update_accept_enabled() -> None:
            enabled = bool(name_input.text().strip()) and bool(host_input.text().strip())
            primary_button.setEnabled(enabled)
            if save_only_button is not None:
                save_only_button.setEnabled(enabled)

        def submit_dialog(*, connect: bool) -> None:
            new_name = name_input.text().strip()
            new_host = host_input.text().strip()
            if not new_name or not new_host:
                self.set_status_message("名称和主机不能为空")
                (name_input if not new_name else host_input).setFocus()
                return

            duplicate = self._find_duplicate_server(
                new_host,
                port_input.value(),
                ignore_id=server.id if is_edit else "",
            )
            if duplicate is not None and QMessageBox is not None:
                confirm = QMessageBox.question(
                    dialog,
                    "服务器已存在",
                    f"已存在相同地址的服务器「{duplicate.name}」。仍要继续保存吗？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if confirm != QMessageBox.Yes:
                    host_input.setFocus()
                    return

            connect_after_save["value"] = connect
            dialog.accept()

        primary_button.clicked.connect(lambda: submit_dialog(connect=not is_edit))
        if save_only_button is not None:
            save_only_button.clicked.connect(lambda: submit_dialog(connect=False))
        name_input.textChanged.connect(update_accept_enabled)
        host_input.textChanged.connect(update_accept_enabled)
        pass_input.textChanged.connect(update_password_save_state)
        update_password_save_state()
        update_accept_enabled()

        main_layout = QVBoxLayout(dialog)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(form_card, 1)
        main_layout.addWidget(buttons)

        if dialog.exec() != QDialog.Accepted:
            return

        new_name = name_input.text().strip()
        new_host = host_input.text().strip()
        new_id = server.id if is_edit else _generate_server_id()
        updated = SavedServer(
            id=new_id,
            name=new_name,
            host=new_host,
            port=port_input.value(),
            username=user_input.text().strip(),
            password=pass_input.text() if save_password_checkbox.isChecked() else "",
            group=group_combo.currentText().strip(),
            notes=notes_input.toPlainText().strip(),
        )

        servers = list(getattr(self, "saved_servers", []))
        if is_edit:
            for i, s in enumerate(servers):
                if s.id == server.id:
                    servers[i] = updated
                    break
        else:
            servers.append(updated)
        self.saved_servers = servers
        if updated.group:
            self._remember_server_group(updated.group)
        self._refresh_server_panel()
        self.schedule_desktop_state_save()
        self.set_status_message(f"已{'更新' if is_edit else '添加'}服务器 {new_name}")
        if connect_after_save["value"]:
            self._open_server_session(updated)

    def _delete_server(self, server: SavedServer) -> None:
        from PySide6.QtWidgets import QMessageBox
        confirm = QMessageBox.question(
            self,
            "删除服务器",
            f"确定要删除服务器「{server.name}」吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        servers = [s for s in getattr(self, "saved_servers", []) if s.id != server.id]
        self.saved_servers = servers
        self._refresh_server_panel()
        self.schedule_desktop_state_save()
        self.set_status_message(f"已删除服务器 {server.name}")

    def _open_server_session(self, server: SavedServer) -> None:
        host = server.host
        port = server.port
        username = server.username or "root"
        password = server.password
        if not host:
            self.set_status_message("服务器主机地址不能为空")
            return
        # Create an ephemeral Device to reuse ensure_session_tab
        device = self._server_to_ephemeral_device(server)
        if not hasattr(self, "ensure_session_tab"):
            self.set_status_message("无法创建终端会话")
            return
        self.set_status_message(f"正在连接 {server.name}...")
        self.ensure_session_tab(
            kind="linux",
            device=device,
            host=host,
            port=port,
            username=username,
            password=password,
            title=server.name,
        )

    def _server_to_ephemeral_device(self, server: SavedServer) -> Device:
        """Build a Device-like object from a SavedServer for session routing."""
        return Device(
            id=server.id,
            name=server.name,
            domain="server",
            device_type="linux",
            cpu="",
            status="idle",
            owner=None,
            ssh_ip=server.host,
            ssh_port=server.port,
            ssh_username=server.username,
            ssh_password=server.password,
            telnet_ip="",
            username=server.username,
            password=server.password,
            vendor="",
            model="",
            site="",
            rack="",
            version="",
            notes=server.notes or "",
        )
