"""Right-side hierarchical session manager and layout switching."""
from __future__ import annotations

import os

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QToolButton,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:
    Qt = None
    QHBoxLayout = None
    QLabel = None
    QLineEdit = None
    QPushButton = None
    QToolButton = None
    QTreeWidget = None
    QTreeWidgetItem = None
    QVBoxLayout = None
    QWidget = None


class SessionLayoutOpsMixin:
    """Build and manage the right-side hierarchical session manager."""

    SESSION_MANAGER_MIN_WIDTH = 200
    SESSION_MANAGER_MAX_WIDTH = 480
    SESSION_MANAGER_DEFAULT_WIDTH = 260

    # NOTE: No `__init__` here — mixins in this codebase do not define
    # `__init__`. All instance state defaults live in `DeviceDesktopApp.__init__`
    # (Task 3 Step 3 wires them there), and the build methods assign the
    # widget references at construction time.

    def build_session_manager_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sessionManagerPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
        title = QLabel("会话管理器")
        title.setObjectName("sessionManagerTitle")
        self.session_manager_count_label = QLabel("共 0")
        self.session_manager_count_label.setObjectName("sessionManagerCount")
        self.session_manager_collapse_button = QToolButton()
        self.session_manager_collapse_button.setObjectName("sessionManagerCollapse")
        self.session_manager_collapse_button.setText("⏴")
        self.session_manager_collapse_button.setToolTip("收起/展开会话管理器")
        self.session_manager_collapse_button.setCheckable(True)
        self.session_manager_collapse_button.clicked.connect(self.toggle_session_manager_collapsed)
        header_layout.addWidget(title, 1)
        header_layout.addWidget(self.session_manager_count_label)
        header_layout.addWidget(self.session_manager_collapse_button)
        layout.addWidget(header)

        self.session_manager_search = QLineEdit()
        self.session_manager_search.setPlaceholderText("搜索设备、会话")
        self.session_manager_search.textChanged.connect(lambda _text: self.refresh_session_manager_tree())
        layout.addWidget(self.session_manager_search)

        self.session_manager_tree = QTreeWidget()
        self.session_manager_tree.setObjectName("sessionManagerTree")
        self.session_manager_tree.setHeaderHidden(True)
        self.session_manager_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.session_manager_tree.itemClicked.connect(self.session_manager_jump_from_item)
        self.session_manager_tree.itemCollapsed.connect(
            lambda item: self._remember_group_collapse(item, True)
        )
        self.session_manager_tree.itemExpanded.connect(
            lambda item: self._remember_group_collapse(item, False)
        )
        layout.addWidget(self.session_manager_tree, 1)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        new_button = QPushButton("＋ 新建终端")
        new_button.setObjectName("compactGhostButton")
        new_button.clicked.connect(self._session_manager_new_terminal)
        footer_layout.addWidget(new_button, 1)
        layout.addWidget(footer)

        panel.setMinimumWidth(self.SESSION_MANAGER_MIN_WIDTH)
        panel.setMaximumWidth(self.SESSION_MANAGER_MAX_WIDTH)
        self.session_manager_panel = panel
        return panel

    def _remember_group_collapse(self, item: QTreeWidgetItem, collapsed: bool) -> None:
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        groups = set(self.collapsed_device_groups)
        if collapsed:
            groups.add(key)
        else:
            groups.discard(key)
        self.collapsed_device_groups = sorted(groups)
        self.schedule_desktop_state_save()

    def toggle_session_manager_collapsed(self) -> None:
        self.session_manager_collapsed = bool(
            self.session_manager_collapse_button and self.session_manager_collapse_button.isChecked()
        )
        # Collapsing hides the panel; in `top` layout it stays hidden regardless.
        self.set_session_manager_visible(
            self.session_tab_layout == "side" and not self.session_manager_collapsed
        )
        self.schedule_desktop_state_save()

    def _session_manager_new_terminal(self) -> None:
        current = self.current_session_state()
        if current is None:
            self.set_status_message("请先选择一个设备。")
            return
        device = self.get_device_by_id(current.device_id)
        if device is None:
            return
        self.open_device_session(device)

    def _session_manager_filter_query(self) -> str:
        if self.session_manager_search is None:
            return ""
        return self.session_manager_search.text().strip().casefold()

    def _session_manager_group_matches(self, query: str, device: object) -> bool:
        if not query:
            return True
        text = " ".join(
            str(getattr(device, field, "") or "").casefold()
            for field in ("id", "name", "domain")
        )
        return query in text

    def _session_manager_session_matches(self, query: str, state: object, device: object) -> bool:
        if not query:
            return True
        session_text = " ".join(
            str(getattr(state, field, "") or "").casefold()
            for field in ("title", "host", "tab_id")
        )
        return query in session_text or query in str(getattr(device, "id", "")).casefold()

    def refresh_session_manager_tree(self) -> None:
        if self.session_manager_tree is None:
            return
        self.session_manager_tree.clear()
        query = self._session_manager_filter_query()
        total = 0
        collapsed_set = set(self.collapsed_device_groups)
        current_state = self.current_session_state()
        current_tab_id = current_state.tab_id if current_state is not None else None

        # One parent per OPEN device (devices that have a device tab). A device
        # with no open tabs is not shown. Temporary devices appear as well.
        for device_id, device_tab in self.device_tabs_by_id.items():
            device = self.get_device_by_id(device_id)
            states = self._session_states_for_device(device_id)
            if not query and not states:
                continue
            parent = QTreeWidgetItem(self.session_manager_tree)
            group_key = device_id
            label = (device.name if device is not None else device_tab.title) or device_id
            parent.setText(0, f"{label} ({len(states)})")
            parent.setData(0, Qt.UserRole, group_key)
            total += len(states)
            group_visible = self._session_manager_group_matches(query, device)
            for state in states:
                if not group_visible and not self._session_manager_session_matches(
                    query, state, device
                ):
                    continue
                child = QTreeWidgetItem(parent)
                child.setText(0, state.title)
                child.setData(0, Qt.UserRole, state.tab_id)
                if state.tab_id == current_tab_id:
                    font = child.font(0)
                    font.setBold(True)
                    child.setFont(0, font)
                parent.addChild(child)
            parent.setExpanded(group_key not in collapsed_set)
            if parent.childCount() == 0:
                self.session_manager_tree.takeTopLevelItem(
                    self.session_manager_tree.indexOfTopLevelItem(parent)
                )
        if self.session_manager_count_label is not None:
            self.session_manager_count_label.setText(f"共 {total}")

    def set_session_manager_visible(self, visible: bool) -> None:
        if self.session_manager_panel is not None:
            self.session_manager_panel.setVisible(visible)

    def session_manager_jump_from_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        if key in self.session_tabs_by_id:
            self.jump_to_session(key)
        else:
            self.activate_device(key)
