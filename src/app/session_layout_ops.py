"""Right-side hierarchical session manager and layout switching."""
from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QPushButton,
        QStackedLayout,
        QToolButton,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:
    Qt = None
    QColor = None
    QIcon = None
    QPainter = None
    QPen = None
    QPixmap = None
    QHBoxLayout = None
    QHeaderView = None
    QLabel = None
    QLineEdit = None
    QPushButton = None
    QStackedLayout = None
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
    SESSION_MANAGER_STRIP_WIDTH = 28

    # Tree status-dot colors (green = connected, amber = connecting, gray = offline).
    SESSION_MANAGER_DOT_CONNECTED = "#22c55e"
    SESSION_MANAGER_DOT_CONNECTING = "#f59e0b"
    SESSION_MANAGER_DOT_OFFLINE = "#6b7280"

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
        self.session_manager_expand_all_button = QToolButton()
        self.session_manager_expand_all_button.setObjectName("sessionManagerExpandAll")
        self.session_manager_expand_all_button.setText("⏵")
        self.session_manager_expand_all_button.setToolTip("展开/收起所有设备分组")
        self.session_manager_expand_all_button.setCheckable(True)
        self.session_manager_expand_all_button.clicked.connect(self.toggle_all_session_groups_expanded)
        self.session_manager_collapse_button = QToolButton()
        self.session_manager_collapse_button.setObjectName("sessionManagerCollapse")
        self.session_manager_collapse_button.setText("⏴")
        self.session_manager_collapse_button.setToolTip("收起/展开会话管理器")
        self.session_manager_collapse_button.setCheckable(True)
        self.session_manager_collapse_button.clicked.connect(self.toggle_session_manager_collapsed)
        header_layout.addWidget(title, 1)
        header_layout.addWidget(self.session_manager_count_label)
        header_layout.addWidget(self.session_manager_expand_all_button)
        header_layout.addWidget(self.session_manager_collapse_button)
        layout.addWidget(header)

        self.session_manager_search = QLineEdit()
        self.session_manager_search.setPlaceholderText("搜索设备、会话")
        self.session_manager_search.textChanged.connect(lambda _text: self.refresh_session_manager_tree())
        layout.addWidget(self.session_manager_search)

        self.session_manager_tree = QTreeWidget()
        self.session_manager_tree.setObjectName("sessionManagerTree")
        self.session_manager_tree.setColumnCount(2)
        # Column width policy lives on the QHeaderView even though the header is
        # hidden: both columns stretch proportionally so the metadata column
        # (count / protocol·host:port) shares width with the name column instead
        # of the last column absorbing all leftover space.
        header = self.session_manager_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        # Compact child indent so session rows sit close to their device group.
        self.session_manager_tree.setIndentation(10)
        self.session_manager_tree.customContextMenuRequested.connect(
            self.session_manager_custom_context_menu
        )
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

        panel.setMinimumWidth(self.SESSION_MANAGER_MIN_WIDTH)
        panel.setMaximumWidth(self.SESSION_MANAGER_MAX_WIDTH)
        self.session_manager_panel = panel
        return self._wrap_session_manager_stack(panel)

    def _build_session_manager_strip(self) -> QWidget:
        """Narrow vertical strip shown when the panel is collapsed.

        The strip is a sibling of the full panel inside the same stack, so it
        remains visible when the panel hides — giving the user an always-present
        affordance to re-expand the collapsed manager.
        """
        strip = QWidget()
        strip.setObjectName("sessionManagerStrip")
        strip.setFixedWidth(self.SESSION_MANAGER_STRIP_WIDTH)
        strip_layout = QVBoxLayout(strip)
        strip_layout.setContentsMargins(2, 4, 2, 4)
        strip_layout.setSpacing(0)

        self.session_manager_expand_button = QToolButton()
        self.session_manager_expand_button.setObjectName("sessionManagerExpand")
        self.session_manager_expand_button.setText("▶")
        self.session_manager_expand_button.setToolTip("展开会话管理器")
        self.session_manager_expand_button.setFocusPolicy(Qt.NoFocus)
        self.session_manager_expand_button.clicked.connect(self.expand_session_manager)
        strip_layout.addWidget(self.session_manager_expand_button)
        strip_layout.addStretch(1)

        self.session_manager_collapsed_strip = strip
        return strip

    def _wrap_session_manager_stack(self, panel: QWidget) -> QWidget:
        """Wrap the full panel and the collapsed strip in a stacked container.

        The container occupies the splitter's third slot. The splitter sizing
        math (`set_main_splitter_width`) sees one widget, so the 3-child
        layout is preserved; the panel/strip swap happens entirely inside.
        """
        container = QWidget()
        container.setObjectName("sessionManagerStack")
        stack = QStackedLayout(container)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        # Index 0: full panel; index 1: collapsed strip.
        stack.addWidget(panel)
        stack.addWidget(self._build_session_manager_strip())
        self.session_manager_stack = stack
        self.session_manager_container = container
        return container

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
        # Re-run the full layout apply: this switches the stack page AND
        # re-allocates the splitter so the right region gets the strip width
        # (collapsed) or the remembered panel width (expanded). Without the
        # re-allocation the splitter keeps the panel's old logical slot, leaving
        # a wide gap next to the narrow strip.
        self.apply_session_layout_state()
        self.schedule_desktop_state_save()

    def toggle_all_session_groups_expanded(self) -> None:
        """Expand or collapse every device group in the session-manager tree."""
        tree = getattr(self, "session_manager_tree", None)
        button = getattr(self, "session_manager_expand_all_button", None)
        if tree is None:
            return
        expanded = not bool(button and button.isChecked())
        all_collapsed = self.collapsed_device_groups == list(self.device_tabs_by_id)
        if expanded and all_collapsed:
            # Button toggles checked = collapse; expand everything instead.
            expanded = True
        for index in range(tree.topLevelItemCount()):
            tree.topLevelItem(index).setExpanded(expanded)
        if expanded:
            self.collapsed_device_groups = []
        else:
            self.collapsed_device_groups = sorted(self.device_tabs_by_id)
        self.schedule_desktop_state_save()

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
        # Prune memorized collapsed groups to device tabs that still exist. Only
        # run when there is at least one open device tab: at startup the tree can
        # refresh before remembered sessions are restored (empty tab set), and
        # pruning then would destroy the user's collapse memory.
        if self.collapsed_device_groups and self.device_tabs_by_id:
            current_ids = set(self.device_tabs_by_id)
            pruned = [key for key in self.collapsed_device_groups if key in current_ids]
            if pruned != self.collapsed_device_groups:
                self.collapsed_device_groups = pruned
        self.session_manager_tree.clear()
        query = self._session_manager_filter_query()
        total = 0
        collapsed_set = set(self.collapsed_device_groups)
        current_state = self.current_session_state()
        current_tab_id = current_state.tab_id if current_state is not None else None

        # Theme-aware foreground: dark theme uses light text on dark surfaces;
        # light theme uses dark text on light surfaces (otherwise the tree text
        # becomes invisible on the light background).
        light = getattr(self, "theme_mode", "dark") == "light"
        fg_primary = QColor("#1c2128") if light else QColor("#e5edf6")
        fg_secondary = QColor("#5a6470") if light else QColor("#a7b4c7")

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
            parent.setText(0, label)
            parent.setText(1, str(len(states)))
            parent.setForeground(1, fg_secondary)
            parent.setForeground(0, fg_primary)
            parent.setData(0, Qt.UserRole, group_key)
            parent_icon = self._session_manager_parent_icon(states)
            if parent_icon is not None:
                parent.setIcon(0, parent_icon)
            total += len(states)
            group_visible = self._session_manager_group_matches(query, device)
            for state in states:
                if not group_visible and not self._session_manager_session_matches(
                    query, state, device
                ):
                    continue
                child = QTreeWidgetItem(parent)
                child.setText(0, state.title)
                child.setText(1, self._session_manager_metadata(state))
                child.setForeground(1, fg_secondary)
                child.setForeground(0, fg_primary)
                child.setData(0, Qt.UserRole, state.tab_id)
                child_icon = self._session_manager_session_icon(state)
                if child_icon is not None:
                    child.setIcon(0, child_icon)
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

    def _session_manager_session_icon(self, state: object) -> QIcon | None:
        """Colored status dot for a session child (green/amber/gray)."""
        if hasattr(self, "_tab_connection_state"):
            conn = self._tab_connection_state(state)
        else:
            conn = "connected"
        if conn == "connecting":
            color = self.SESSION_MANAGER_DOT_CONNECTING
        elif conn == "connected":
            color = self.SESSION_MANAGER_DOT_CONNECTED
        else:
            color = self.SESSION_MANAGER_DOT_OFFLINE
        return self._session_manager_dot_icon(color)

    def _session_manager_parent_icon(self, states: list[object]) -> QIcon | None:
        """Device icon tinted by aggregate connection state (green/amber/gray)."""
        kind = states[0].kind if states else "device"
        if hasattr(self, "_tab_connection_state"):
            conns = [self._tab_connection_state(state) for state in states]
            if any(c == "connected" for c in conns):
                color = self.SESSION_MANAGER_DOT_CONNECTED
            elif any(c == "connecting" for c in conns):
                color = self.SESSION_MANAGER_DOT_CONNECTING
            else:
                color = self.SESSION_MANAGER_DOT_OFFLINE
        else:
            color = self.SESSION_MANAGER_DOT_CONNECTED if states else self.SESSION_MANAGER_DOT_OFFLINE
        return self._session_manager_device_icon(kind, color)

    def _session_manager_metadata(self, state: object) -> str:
        """Muted `协议 · host:port` line for a session child (col 1)."""
        kind = self.session_kind_label(state.kind)
        host = getattr(state, "host", "") or ""
        port = getattr(state, "port", 0)
        return f"{kind} · {host}:{port}"

    def _session_manager_dot_icon(self, color: str) -> QIcon | None:
        if QPixmap is None or QPainter is None or QColor is None:
            return None
        pixmap = QPixmap(12, 12)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(2, 2, 8, 8)
        painter.end()
        return QIcon(pixmap)

    def _session_manager_device_icon(self, kind: str, color: str) -> QIcon | None:
        """16x16 device glyph (server/laptop/serial/sim), tinted by connection state."""
        if QPixmap is None or QPainter is None or QColor is None:
            return None
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color), 1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if kind == "linux":
            painter.drawRoundedRect(2, 2, 12, 10, 2, 2)  # laptop body
            painter.drawLine(5, 13, 11, 13)
            painter.drawLine(4, 15, 12, 15)
        elif kind == "serial":
            painter.drawRoundedRect(2, 5, 12, 6, 2, 2)   # DB9-style port
            painter.drawLine(4, 5, 4, 11)
            painter.drawLine(6, 5, 6, 11)
            painter.drawLine(8, 5, 8, 11)
            painter.drawLine(10, 5, 10, 11)
        elif kind == "simulated":
            painter.drawEllipse(3, 3, 10, 10)            # cloud/ball
            painter.drawLine(8, 3, 8, 13)
            painter.drawLine(3, 8, 13, 8)
        else:                                            # device (telnet) = server
            painter.drawRoundedRect(2, 3, 12, 10, 2, 2)
            painter.drawLine(5, 5, 11, 5)
            painter.drawLine(5, 8, 11, 8)
            painter.drawLine(5, 11, 11, 11)
        painter.end()
        return QIcon(pixmap)

    def set_session_manager_visible(self, visible: bool) -> None:
        """Show/hide the right session-manager region (full panel or strip).

        The visibility decision belongs to ``apply_session_manager_collapsed_state``
        / ``toggle_session_manager_collapsed`` via the stack: when collapsed, the
        strip is shown (so the user can always re-expand); when expanded, the full
        panel is shown. ``visible=False`` here hides the whole region.
        """
        container = getattr(self, "session_manager_container", None)
        if container is not None:
            container.setVisible(visible)
        elif self.session_manager_panel is not None:
            # Fallback for the legacy path before the stack wrapper exists.
            self.session_manager_panel.setVisible(visible)

    def _set_session_manager_stack_page(self, collapsed: bool) -> None:
        """Switch the stack between full panel (expanded) and strip (collapsed)."""
        stack = getattr(self, "session_manager_stack", None)
        if stack is None:
            return
        stack.setCurrentIndex(1 if collapsed else 0)
        # The stack container is the splitter's third child; keep its size policy
        # fixed so the splitter doesn't animate the strip to the panel width.
        container = getattr(self, "session_manager_container", None)
        if container is not None:
            if collapsed:
                container.setMinimumWidth(self.SESSION_MANAGER_STRIP_WIDTH)
                container.setMaximumWidth(self.SESSION_MANAGER_STRIP_WIDTH)
            else:
                container.setMinimumWidth(self.SESSION_MANAGER_MIN_WIDTH)
                container.setMaximumWidth(self.SESSION_MANAGER_MAX_WIDTH)

    def expand_session_manager(self) -> None:
        """Re-expand the collapsed right panel (from the strip's expand button)."""
        self.session_manager_collapsed = False
        if self.session_manager_collapse_button is not None:
            self.session_manager_collapse_button.setChecked(False)
        self._set_session_manager_stack_page(False)
        self.apply_session_layout_state()
        self.schedule_desktop_state_save()

    def session_manager_jump_from_item(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        if key in self.session_tabs_by_id:
            self.jump_to_session(key)
        else:
            self.activate_device(key)

    def build_session_breadcrumb(self) -> QWidget:
        breadcrumb = QWidget()
        breadcrumb.setObjectName("sessionBreadcrumb")
        layout = QHBoxLayout(breadcrumb)
        layout.setContentsMargins(14, 5, 14, 5)
        layout.setSpacing(6)
        self.session_breadcrumb_device_label = QLabel()
        self.session_breadcrumb_device_label.setObjectName("breadcrumbDevice")
        self.session_breadcrumb_device_label.setCursor(Qt.PointingHandCursor)
        self.session_breadcrumb_device_label.mousePressEvent = self._breadcrumb_device_click

        layout.addWidget(self.session_breadcrumb_device_label)
        layout.addStretch(1)
        self.session_breadcrumb = breadcrumb
        return breadcrumb

    def _breadcrumb_device_click(self, _event: object = None) -> None:
        label = getattr(self, "session_breadcrumb_device_label", None)
        if label is None:
            return
        device_id = str(label.property("deviceId") or "")
        if device_id:
            self.activate_device(device_id)

    def set_session_tab_bars_visible(self, visible: bool) -> None:
        """Show/hide the top device tab bar and per-device session tab bars.

        In the side layout the device-level bar is hidden (cross-device
        navigation lives in the right session manager), but the ACTIVE device's
        session tabs stay visible so the operator can switch between that
        device's sessions at the top. In the top layout everything follows
        ``visible``.
        """
        side = getattr(self, "session_tab_layout", "top") == "side"
        self.session_tab_widget.tabBar().setVisible(visible and not side)
        active = self.current_device_tab_state() if side else None
        for device_tab in self.device_tabs_by_id.values():
            is_active = device_tab is active
            for tabs in self.session_tab_widgets_for_device(device_tab):
                tabs.tabBar().setVisible(visible and (not side or is_active))

    def set_session_tab_layout(self, mode: str) -> None:
        mode = mode if mode in {"top", "side"} else "top"
        self.session_tab_layout = mode
        self.apply_session_layout_state()
        self.schedule_desktop_state_save()

    def handle_session_manager_width_drag_finished(
        self, _width: int = 0, handle_index: int = 2
    ) -> None:
        # Only the RIGHT boundary (handle index 2) is the session-manager width
        # drag; the left boundary is the left-sidebar drag lifecycle.
        if int(handle_index) != 2:
            return
        # The drag_finished signal emits the LEFT panel width (sizes[0]), so the
        # passed width is ignored. Read the actual right-panel width from the
        # splitter directly — that is exactly what we want to persist. Only
        # persist when the full panel is expanded; the collapsed strip's 28px
        # width must not overwrite the user's remembered panel width.
        if not self._session_manager_panel_active():
            return
        splitter = getattr(self, "main_splitter", None)
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) < 3:
            return
        right_width = int(sizes[-1])
        if right_width <= 0:
            return
        clamped = max(
            self.SESSION_MANAGER_MIN_WIDTH,
            min(self.SESSION_MANAGER_MAX_WIDTH, right_width),
        )
        self.session_manager_width = clamped
        self.schedule_desktop_state_save()

    def _session_manager_panel_active(self) -> bool:
        """Whether the right session-manager panel participates in splitter sizing."""
        return (
            getattr(self, "session_tab_layout", "top") == "side"
            and not getattr(self, "session_manager_collapsed", False)
        )

    def session_manager_splitter_width(self, available: int) -> int:
        """Clamped right-panel width to hand the splitter for a 3-child layout.

        Keeps the user's persisted `session_manager_width` instead of letting
        Qt snap the panel to its minimum when only two sizes are supplied.
        """
        preferred = int(
            getattr(self, "session_manager_width", self.SESSION_MANAGER_DEFAULT_WIDTH)
        )
        right = max(
            self.SESSION_MANAGER_MIN_WIDTH,
            min(self.SESSION_MANAGER_MAX_WIDTH, preferred),
        )
        return max(0, min(right, max(0, int(available))))

    def apply_session_manager_collapsed_state(self) -> None:
        collapsed = self.session_manager_collapsed
        if self.session_manager_collapse_button is not None:
            self.session_manager_collapse_button.setChecked(collapsed)
        self._set_session_manager_stack_page(collapsed)
        # In `side` layout the right region is always visible (strip when
        # collapsed, panel when expanded); in `top` layout it stays hidden.
        self.set_session_manager_visible(self.session_tab_layout == "side")

    def apply_session_layout_state(self) -> None:
        # Refined body (replaces Task 4 version): adds collapse handling and the
        # width-restore block, keeping the pre-build guard.
        # Called from load_desktop_state BEFORE _build_layout builds the
        # widgets — guard against not-yet-created panels and tab widget.
        if not hasattr(self, "session_tab_widget") or self.session_manager_panel is None:
            return
        side = self.session_tab_layout == "side"
        if side:
            if self.session_tab_widget.count() > 0:
                self.show_terminal_workspace()
        self.set_session_tab_bars_visible(True)
        self.apply_session_manager_collapsed_state()
        if getattr(self, "session_breadcrumb", None) is not None:
            self.session_breadcrumb.setVisible(side)
        if side:
            self.refresh_session_manager_tree()
            self.refresh_session_breadcrumb()
            # Restore the remembered right-region width onto the splitter:
            # the strip (collapsed) or the panel's persisted width (expanded).
            if self.session_manager_collapsed:
                target = self.SESSION_MANAGER_STRIP_WIDTH
            else:
                self.session_manager_panel.setMinimumWidth(self.SESSION_MANAGER_MIN_WIDTH)
                self.session_manager_panel.setMaximumWidth(self.SESSION_MANAGER_MAX_WIDTH)
                target = max(
                    self.SESSION_MANAGER_MIN_WIDTH,
                    min(self.SESSION_MANAGER_MAX_WIDTH, self.session_manager_width),
                )
            sizes = self.main_splitter.sizes()
            if len(sizes) >= 3 and sum(sizes) > 0:
                self.main_splitter.setSizes(
                    [sizes[0], max(1, sum(sizes) - sizes[0] - target), target]
                )

    def refresh_session_breadcrumb(self) -> None:
        if getattr(self, "session_breadcrumb_device_label", None) is None:
            return
        state = self.current_session_state()
        device_id = state.device_id if state is not None else ""
        device = self.get_device_by_id(device_id) if device_id else None
        device_name = device.name if device is not None else device_id
        self.session_breadcrumb_device_label.setText(device_name)
        self.session_breadcrumb_device_label.setProperty("deviceId", device_id)

    def apply_font_size_to_terminal(self, terminal: object, size: int) -> None:
        if hasattr(terminal, "set_font_size"):
            terminal.set_font_size(int(size))

    def apply_font_size_to_all_terminals(self) -> None:
        for state in self.session_tabs_by_id.values():
            self.apply_font_size_to_terminal(state.terminal, self.terminal_font_size)

    def attach_settings_menu(self, button: QToolButton) -> QToolButton:
        from PySide6.QtWidgets import QWidgetAction

        button.setToolTip("工作台设置")
        button.setPopupMode(QToolButton.InstantPopup)
        menu = self.new_workspace_menu(button, "工作台设置", "settings")
        menu.setObjectName("workspaceContextMenu")
        panel = self.build_settings_panel()
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)
        button.setMenu(menu)
        self.settings_button = button
        return button

    def build_settings_panel(self) -> QWidget:
        from PySide6.QtWidgets import (
            QCheckBox,
            QComboBox,
            QFormLayout,
            QLabel,
            QSpinBox,
            QVBoxLayout,
            QWidget,
        )

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        self.settings_layout_combo = QComboBox()
        self.settings_layout_combo.addItems(["顶部", "右侧"])
        self.settings_layout_combo.setCurrentText("右侧" if self.session_tab_layout == "side" else "顶部")
        self.settings_layout_combo.currentTextChanged.connect(self._settings_layout_changed)

        self.settings_font_spin = QSpinBox()
        self.settings_font_spin.setRange(9, 28)
        self.settings_font_spin.setValue(self.terminal_font_size)
        self.settings_font_spin.valueChanged.connect(self._settings_font_changed)

        self.settings_default_collapsed_check = QCheckBox()
        self.settings_default_collapsed_check.setChecked(self.session_manager_default_collapsed)
        self.settings_default_collapsed_check.toggled.connect(self._settings_default_collapsed_changed)

        self.settings_theme_combo = QComboBox()
        self.settings_theme_combo.addItems(["深色", "浅色"])
        self.settings_theme_combo.setCurrentText("浅色" if getattr(self, "theme_mode", "dark") == "light" else "深色")
        self.settings_theme_combo.currentTextChanged.connect(self._settings_theme_changed)

        form.addRow("会话页签布局", self.settings_layout_combo)
        form.addRow("终端字体大小", self.settings_font_spin)
        form.addRow("默认折叠", self.settings_default_collapsed_check)
        form.addRow("主题", self.settings_theme_combo)
        layout.addLayout(form)
        hint = QLabel("「默认折叠」仅决定首次进入右侧布局的状态，之后跟随操作记忆。")
        hint.setObjectName("settingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return panel

    def _settings_layout_changed(self, text: str) -> None:
        self.set_session_tab_layout("side" if text == "右侧" else "top")

    def _settings_theme_changed(self, text: str) -> None:
        self.apply_theme("light" if text == "浅色" else "dark")

    def _settings_font_changed(self, value: int) -> None:
        self.terminal_font_size = int(value)
        self.apply_font_size_to_all_terminals()
        self.schedule_desktop_state_save()

    def _settings_default_collapsed_changed(self, checked: bool) -> None:
        self.session_manager_default_collapsed = bool(checked)
        self.schedule_desktop_state_save()

    def apply_theme(self, mode: str) -> None:
        """Apply the dark or light theme across native, canvas, and Web surfaces."""
        mode = "light" if mode == "light" else "dark"
        self.theme_mode = mode
        from src.styles import APP_STYLE, APP_STYLE_LIGHT

        self.setStyleSheet(APP_STYLE_LIGHT if mode == "light" else APP_STYLE)
        # Web widgets push new :root variables.
        for attr in ("web_shell", "device_navigation_web"):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "set_theme"):
                widget.set_theme(mode)
        # Per-session terminals (xterm/canvas) are the sole source of truth for
        # canvas theme application — every canvas terminal lives in
        # session_tabs_by_id, so this loop applies the canvas palette exactly once.
        for state in list(getattr(self, "session_tabs_by_id", {}).values()):
            terminal = getattr(state, "terminal", None)
            if terminal is None:
                continue
            if hasattr(terminal, "set_theme"):
                terminal.set_theme(mode)
            elif hasattr(terminal, "apply_canvas_theme"):
                terminal.apply_canvas_theme(mode)
        # Command-record editor draws its line-number gutter with QPainter, which
        # bypasses QSS — re-theme it explicitly.
        command_input = getattr(self, "command_record_input", None)
        if command_input is not None and hasattr(command_input, "set_theme"):
            command_input.set_theme(mode)
        # Re-populate the session-manager tree so its setForeground brushes pick
        # up the new theme (they are set at fill time; without this the existing
        # items keep the old theme's colors until a click re-populates them).
        if getattr(self, "session_manager_tree", None) is not None:
            self.refresh_session_manager_tree()
        self.schedule_desktop_state_save()

    def session_manager_custom_context_menu(self, pos: object) -> None:
        if pos is None:
            return
        if self.session_manager_tree is None:
            return
        item = self.session_manager_tree.itemAt(pos)
        if item is None:
            return
        key = item.data(0, Qt.UserRole)
        if key in self.session_tabs_by_id:
            state = self.session_tabs_by_id[key]
            menu = self.new_workspace_menu(self.session_manager_tree, state.title, "session-manager")
            close_this = menu.addAction("关闭当前会话")
            close_others = menu.addAction("关闭其他会话")
            close_all = menu.addAction("关闭全部会话")
            chosen = menu.exec(self.session_manager_tree.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            if chosen == close_this:
                self.close_session_tab(state.tab_id)
            elif chosen == close_others:
                for other in list(self.session_tabs_by_id.values()):
                    if other.device_id == state.device_id and other.tab_id != state.tab_id:
                        self.close_session_tab(other.tab_id)
            elif chosen == close_all:
                for other in list(self.session_tabs_by_id.values()):
                    if other.device_id == state.device_id:
                        self.close_session_tab(other.tab_id)
            return
        device_tab = self.device_tabs_by_id.get(key)
        if device_tab is not None:
            menu, close_actions, device_actions, device = self.build_device_tab_context_menu(
                device_tab, self.session_manager_tree
            )
            chosen = menu.exec(self.session_manager_tree.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            for mode, action in close_actions.items():
                if chosen == action:
                    self.close_device_tabs_relative(device_tab, mode)
                    return
            if device is not None:
                self._handle_device_quick_action(chosen, device_actions, device)
                return
