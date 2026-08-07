from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import os
import queue
import re
import shutil
import threading
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import CancelledError as FutureCancelledError, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import pyte
except ModuleNotFoundError:
    pyte = None

try:
    from PySide6.QtCore import (
        QEvent,
        QMimeData,
        QParallelAnimationGroup,
        QPropertyAnimation,
        QSize,
        QTimer,
        Qt,
        QUrl,
    )
    from PySide6.QtGui import (
        QBrush,
        QColor,
        QDesktopServices,
        QDrag,
        QIcon,
        QKeySequence,
        QPainter,
        QPen,
        QPixmap,
        QShortcut,
        QTextBlockFormat,
        QSyntaxHighlighter,
        QTextCharFormat,
        QTextCursor,
        QTextOption,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QInputDialog,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSplitter,
        QSizePolicy,
        QStackedLayout,
        QStatusBar,
        QStyle,
        QStyledItemDelegate,
        QStyleOptionViewItem,
        QTabBar,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without PySide6 installed
    QApplication = None
    QBrush = None
    QColor = None
    QDesktopServices = None
    QDrag = None
    QEvent = None
    QFileDialog = None
    QIcon = None
    QInputDialog = None
    QMimeData = None
    QKeySequence = None
    QParallelAnimationGroup = None
    QPainter = None
    QPen = None
    QPixmap = None
    QShortcut = None
    QPropertyAnimation = None
    QTextBlockFormat = None
    QSyntaxHighlighter = None
    QTextCharFormat = None
    QUrl = None
    QComboBox = None
    QFormLayout = None
    QFrame = None
    QGridLayout = None
    QGroupBox = None
    QHBoxLayout = None
    QHeaderView = None
    QLabel = None
    QLineEdit = None
    QMainWindow = object
    QMenu = None
    QMessageBox = None
    QPlainTextEdit = None
    QPushButton = None
    QScrollArea = None
    QSplitter = None
    QSizePolicy = None
    QStackedLayout = None
    QStatusBar = None
    QStyle = None
    QStyledItemDelegate = None
    QStyleOptionViewItem = None
    QTabBar = None
    QTabWidget = None
    QTableWidget = None
    QTableWidgetItem = None
    QToolButton = None
    QSize = None
    QTimer = None
    QTextCursor = None
    Qt = None
    QVBoxLayout = None
    QWidget = None
    PYSIDE6_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    PYSIDE6_IMPORT_ERROR = None

try:
    from .._sample_data import (
        STATUS_IDLE,
        STATUS_OCCUPIED,
        STATUS_OTHER,
        STATUS_PIPELINE,
    )
    from ..auto_response import default_quick_send_buttons
    from ..command_suggestions import CommandHistoryItem
    from ..data import Device, SavedServer
    from ..styles import APP_STYLE
    from ..helpers import build_search_text, mask_password, status_color
    from ..app_state import RepositorySnapshot, DeviceTabState, SessionTabState
    from ..async_utils import AsyncLoopThread
    from ..linux_session import LinuxSshSession
    from ..repo_factory import create_repository_from_env
    from ..repository import (
        DeviceRepository,
        RepositoryConflictError,
        RepositoryError,
    )
    from ..session_protocol import SessionCallbacks, SessionUnavailableError
    from ..telnet_session import HuaweiTelnetSession, TelnetSessionError
    from ..widgets.device_table import CopyableDeviceTable, VirtualDeviceTable
    from ..widgets.sidebar_splitter import SidebarSplitter
    from ..widgets.device_navigation_web_widget import DeviceNavigationWebWidget
    from ..widgets.web_shell_widget import WebShellWidget
    from ..widgets.search_input import SelectAllLineEdit
    from ..widgets.command_record import (
        CommandRecordInput,
        CommandRecordResizeHandle,
        HorizontalResizeHandle,
        VerticalResizeHandle,
    )
    from ..widgets.password_field import configure_password_visibility
    from ..widgets.terminal_widget import (
        ANSI_ESCAPE_RE,
        InteractiveTerminal,
        TerminalSyntaxHighlighter,
    )
except ImportError:
    from _sample_data import (
        STATUS_IDLE,
        STATUS_OCCUPIED,
        STATUS_OTHER,
        STATUS_PIPELINE,
    )
    from auto_response import default_quick_send_buttons
    from command_suggestions import CommandHistoryItem
    from data import Device, SavedServer
    from styles import APP_STYLE
    from helpers import build_search_text, mask_password, status_color
    from app_state import RepositorySnapshot, DeviceTabState, SessionTabState
    from async_utils import AsyncLoopThread
    from linux_session import LinuxSshSession
    from repo_factory import create_repository_from_env
    from repository import (
        DeviceRepository,
        RepositoryConflictError,
        RepositoryError,
    )
    from session_protocol import SessionCallbacks, SessionUnavailableError
    from telnet_session import HuaweiTelnetSession, TelnetSessionError
    from widgets.device_table import CopyableDeviceTable, VirtualDeviceTable
    from widgets.sidebar_splitter import SidebarSplitter
    from widgets.device_navigation_web_widget import DeviceNavigationWebWidget
    from widgets.web_shell_widget import WebShellWidget
    from widgets.search_input import SelectAllLineEdit
    from widgets.command_record import (
        CommandRecordInput,
        CommandRecordResizeHandle,
        HorizontalResizeHandle,
        VerticalResizeHandle,
    )
    from widgets.password_field import configure_password_visibility
    from widgets.terminal_widget import (
        ANSI_ESCAPE_RE,
        InteractiveTerminal,
        TerminalSyntaxHighlighter,
    )

from .session_ops import SessionOpsMixin
from .session_layout_ops import SessionLayoutOpsMixin
from .occupancy_ops import OccupancyOpsMixin
from .command_record_ops import CommandRecordOpsMixin
from .desktop_state import DesktopStateMixin
from .file_transfer_ops import FileTransferOpsMixin
from .managed_file_transfer_ops import ManagedFileTransferOpsMixin
from .package_upgrade_ops import PackageUpgradeOpsMixin
from .table_ops import TableOpsMixin
from .temporary_device_ops import TemporaryDeviceOpsMixin
from .server_ops import ServerOpsMixin
from .ai_device_ops import AiDeviceOpsMixin

try:
    from ..widgets.xterm_web_widget import prewarm_xterm_webengine
except ImportError:
    prewarm_xterm_webengine = None


ALL_DOMAINS = "全部领域"
ALL_STATUS = "全部状态"
FILTERABLE_STATUSES = [ALL_STATUS, STATUS_OCCUPIED, STATUS_IDLE, STATUS_PIPELINE, STATUS_OTHER]
if PYSIDE6_IMPORT_ERROR is None:

    class DeviceDesktopApp(
        SessionOpsMixin,
        SessionLayoutOpsMixin,
        OccupancyOpsMixin,
        CommandRecordOpsMixin,
        DesktopStateMixin,
        FileTransferOpsMixin,
        ManagedFileTransferOpsMixin,
        PackageUpgradeOpsMixin,
        AiDeviceOpsMixin,
        TemporaryDeviceOpsMixin,
        ServerOpsMixin,
        TableOpsMixin,
        QMainWindow,
    ):
        LOG_FLUSH_INTERVAL_MS = 250
        LOG_FLUSH_IMMEDIATE_CHARS = 65536
        DEFAULT_LOG_ROTATE_SIZE_MB = 10
        ACTIVITY_RAIL_WIDTH = 46
        TERMINAL_SIDEBAR_WIDTH = 360
        TERMINAL_SIDEBAR_CONTENT_WIDTH = 300
        TERMINAL_SIDEBAR_MIN_WIDTH = 300
        TERMINAL_SIDEBAR_CONTENT_MIN_WIDTH = 230
        TERMINAL_SIDEBAR_CONTENT_MAX_WIDTH = 560
        TERMINAL_SIDEBAR_COLLAPSE_THRESHOLD = 180
        SIDEBAR_UNBOUNDED_MAX_WIDTH = 16777215
        TERMINAL_NAVIGATION_WEB_DEFAULT_HEIGHT = 500
        TERMINAL_NAVIGATION_WEB_MIN_HEIGHT = 320
        TERMINAL_NAVIGATION_WEB_MAX_HEIGHT = 900
        TOOL_SIDEBAR_WIDTH = 520
        COMMAND_RECORD_COLLAPSED_HEIGHT = 25
        COMMAND_RECORD_DEFAULT_HEIGHT = 148
        COMMAND_RECORD_MIN_HEIGHT = 116
        COMMAND_RECORD_MAX_HEIGHT = 600

        def __init__(self, repository: DeviceRepository | None = None) -> None:
            super().__init__()
            self.repository = repository or create_repository_from_env()
            self.async_loop = AsyncLoopThread()
            self.ui_thread_ident = threading.get_ident()
            self.ui_queue: queue.SimpleQueue[tuple[Callable[..., None], tuple[object, ...]]] = queue.SimpleQueue()
            self.repository_lock = threading.Lock()
            self.search_index: dict[str, str] = {}
            self.device_by_id: dict[str, Device] = {}
            self.device_table_rows: dict[str, int] = {}
            self.device_table_rendered_rows: set[int] = set()
            self.owned_table_rows: dict[str, int] = {}
            self.owned_table_rendered_rows: set[int] = set()
            self.devices: list[Device] = []
            self.visible_devices: list[Device] = []
            self.visible_device_display_rows: list[dict[str, object]] = []
            self._visible_device_display_row_ids: tuple[str, ...] = ()
            self.owned_visible_devices: list[Device] = []
            self.visible_status_counts: dict[str, int] = {}
            self.selected_device_id = ""
            self.current_user = ""
            self.owned_device_ids: set[str] | None = None
            self.refresh_generation = 0
            self.closed = False
            self.loading_snapshot = False
            self.my_occupancy_filter_enabled = False
            self.temporary_devices: list[Device] = []
            self.saved_servers: list[SavedServer] = []
            self.saved_server_groups: list[str] = []
            self.local_credential_overrides: dict[str, dict[str, dict[str, str]]] = {}
            self.editing_temporary_device_id = ""
            self.recent_device_ids: list[str] = []
            self.command_record_groups: list[dict[str, object]] = [
                {"name": "终端", "content": ""},
            ]
            self.current_command_group = 0
            self.command_record_collapsed = True
            self.command_enter_sends = False
            self.command_find_replace_visible = False
            self.command_record_height = self.COMMAND_RECORD_DEFAULT_HEIGHT
            self.session_quick_bar_collapsed = False
            self.session_jump_combo_width = 280
            self.command_history: list[CommandHistoryItem] = []
            self.command_suggestion_buttons: list[QToolButton] = []
            self.current_command_suggestions: list[str] = []
            self.connection_params_collapsed = False
            self.device_navigation_collapsed = False
            self.terminal_navigation_active_tab = "devices"
            self.terminal_navigation_device_query = ""
            self.terminal_navigation_expanded_device_id = ""
            self.terminal_navigation_web_height = self.TERMINAL_NAVIGATION_WEB_DEFAULT_HEIGHT
            self.terminal_sidebar_collapsed = False
            self.left_sidebar_collapsed = False
            self.left_sidebar_compact = False
            self.left_device_workspace_expanded = True
            self.terminal_sidebar_width = self.TERMINAL_SIDEBAR_WIDTH
            self.center_stage_mode = "home"
            self._last_center_stage_mode: str | None = None
            self.always_on_top = False
            self.remembered_auto_response_rules = []
            self.remembered_quick_send_buttons = default_quick_send_buttons()
            self.remembered_terminal_sessions: list[dict[str, object]] = []
            self.terminal_sessions_restored = False
            self.state_path = self.desktop_state_path()
            self.log_directory = self.default_log_directory()
            self.log_rotate_size_bytes = self.DEFAULT_LOG_ROTATE_SIZE_MB * 1024 * 1024
            self.transfer_protocol = "ftp"
            self.transfer_host = "0.0.0.0"
            self.transfer_port = 2121
            self.transfer_root_directory = self.state_path.parent / "transfer"
            self.transfer_username = "device"
            self.transfer_password = "device"
            self.transfer_writable = True
            self.session_manager_panel = None
            self.session_manager_tree = None
            self.session_manager_search = None
            self.session_manager_collapse_button = None
            self.session_manager_count_label = None
            self.session_breadcrumb = None
            self.session_breadcrumb_device_label = None
            self.session_breadcrumb_session_label = None
            self.settings_button = None
            self.session_tab_layout = "top"
            self.terminal_font_size = 14
            self.session_manager_default_collapsed = False
            self.theme_mode = "dark"
            self.session_manager_width = 260
            self.session_manager_collapsed = False
            self.collapsed_device_groups: list[str] = []
            self.transfer_service = None
            self.package_upgrade_send_interval_ms = 900
            self.left_sidebar_active_panel = "devices"
            self.left_sidebar_animation = None
            self.left_sidebar_user_dragging = False
            self.left_sidebar_programmatic_resize = False
            self.command_tab_buttons: list[QToolButton] = []
            self.command_tab_close_buttons: list[QToolButton] = []
            self.device_tabs_by_id: dict[str, DeviceTabState] = {}
            self.session_tabs_by_id: dict[str, SessionTabState] = {}
            self.pending_futures: set[Future] = set()
            self._drag_session_tab_id = ""
            self._last_desktop_state_payload = ""
            self._last_device_table_signature: tuple[object, ...] = ()
            self._last_owned_table_signature: tuple[object, ...] = ()
            self._table_render_jobs: list[dict[str, object]] = []
            self._table_render_generation = 0
            self.next_session_sequence = 1
            self._xterm_prewarm_page = None
            self.app_control_service = None
            self.app_control_server = None

            self.refresh_timer = QTimer(self)
            self.refresh_timer.setSingleShot(True)
            self.refresh_timer.timeout.connect(self.refresh_snapshot)
            self.filter_timer = QTimer(self)
            self.filter_timer.setSingleShot(True)
            self.filter_timer.setInterval(120)
            self.filter_timer.timeout.connect(self.apply_filters)
            self.state_save_timer = QTimer(self)
            self.state_save_timer.setSingleShot(True)
            self.state_save_timer.timeout.connect(self.save_desktop_state)
            self.ui_timer = QTimer(self)
            self.ui_timer.setInterval(10)
            self.ui_timer.timeout.connect(self._drain_ui_queue)
            self.log_flush_timer = QTimer(self)
            self.log_flush_timer.setSingleShot(True)
            self.log_flush_timer.timeout.connect(self.flush_pending_session_logs)
            self.table_render_timer = QTimer(self)
            self.table_render_timer.setSingleShot(True)
            self.table_render_timer.timeout.connect(self.process_table_render_jobs)
            self.device_table_visible_render_timer = QTimer(self)
            self.device_table_visible_render_timer.setSingleShot(True)
            self.device_table_visible_render_timer.timeout.connect(self.render_visible_device_table_rows)
            self.owned_table_visible_render_timer = QTimer(self)
            self.owned_table_visible_render_timer.setSingleShot(True)
            self.owned_table_visible_render_timer.timeout.connect(self.render_visible_owned_table_rows)

            self.load_desktop_state()
            self._build_window()
            self._build_layout()
            self.initialize_terminal_execution_coordinator()
            self.initialize_ai_gateway_service()
            config = getattr(self, "ai_gateway_result_store_config", None)
            if config is not None and hasattr(self, "ai_gateway_service"):
                from src.ai_gateway.result_store import ResultStore

                self.ai_gateway_service.result_store = ResultStore(
                    max_entries=config["max_entries"],
                    ttl_seconds=config["ttl_hours"] * 3600,
                )
            self.apply_always_on_top_state()
            self._wire_events()
            self.update_controls()
            self.ui_timer.start()
            self.refresh_snapshot()
            control_enabled = os.getenv("DEVICE_TUI_APP_CONTROL", "1").strip().casefold()
            if control_enabled not in {"0", "false", "no", "off"} and not os.getenv(
                "PYTEST_CURRENT_TEST"
            ):
                self.start_app_control_server()
            QTimer.singleShot(300, self._prewarm_terminal_webengine)

        def _prewarm_terminal_webengine(self) -> None:
            if prewarm_xterm_webengine is None:
                return
            terminal_mode = os.getenv("DEVICE_TUI_TERMINAL_WIDGET", "xterm").lower()
            if terminal_mode in {"canvas", "pyte", "legacy"}:
                return
            try:
                self._xterm_prewarm_page = prewarm_xterm_webengine(self)
                self._xterm_prewarm_page.destroyed.connect(lambda: setattr(self, "_xterm_prewarm_page", None))
            except Exception:
                self._xterm_prewarm_page = None

        def _build_window(self) -> None:
            self.setWindowTitle("设备工作台")
            self.resize(1700, 1000)
            self.setMinimumSize(1280, 800)
            base_font = self.font()
            if base_font.pointSize() <= 0:
                base_font.setPixelSize(13)
                self.setFont(base_font)
            # Apply the loaded theme (defaults to dark) instead of unconditionally
            # resetting to APP_STYLE, so a persisted light theme survives startup.
            self.apply_theme(getattr(self, "theme_mode", "dark"))

            status_bar = QStatusBar(self)
            self.setStatusBar(status_bar)
            status_bar.showMessage("准备就绪")

        def new_workspace_menu(self, parent: QWidget | None, title: str = "", kind: str = "context") -> QMenu:
            menu = QMenu(parent)
            menu.setObjectName("workspaceContextMenu")
            menu.setProperty("menuKind", kind)
            if title:
                title_action = menu.addAction(title)
                title_action.setEnabled(False)
                title_action.setProperty("menuRole", "title")
                menu.addSeparator()
            return menu

        def _build_layout(self) -> None:
            root = QWidget(self)
            root_layout = QVBoxLayout(root)
            root_layout.setContentsMargins(12, 12, 12, 8)
            root_layout.setSpacing(8)

            splitter = SidebarSplitter(Qt.Horizontal, root)
            self.main_splitter = splitter
            root_layout.addWidget(splitter, 1)

            splitter.addWidget(self._build_left_panel())
            splitter.addWidget(self._build_center_panel())
            splitter.addWidget(self.build_session_manager_panel())
            splitter.setStretchFactor(2, 0)
            splitter.setChildrenCollapsible(False)
            splitter.setSizes([520, 1080])
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.splitterMoved.connect(self.handle_main_splitter_moved)
            splitter.drag_started.connect(self.handle_main_splitter_drag_started)
            splitter.drag_finished.connect(self.handle_main_splitter_drag_finished)
            splitter.drag_finished.connect(self.handle_session_manager_width_drag_finished)
            self.apply_left_sidebar_state()
            self.apply_session_layout_state()
            # Deliver the persisted theme to the now-built Web widgets (the
            # earlier apply_theme calls ran before they existed).
            self.apply_theme(getattr(self, "theme_mode", "dark"))

            self.setCentralWidget(root)

        def _build_toolbar(self) -> QWidget:
            frame = QFrame()
            frame.setObjectName("toolbarFrame")
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(16, 12, 16, 12)
            layout.setSpacing(10)

            title_col = QVBoxLayout()
            title_col.setSpacing(2)
            brand = QLabel("设备运维工作台")
            brand.setObjectName("brandLabel")
            copy = QLabel("资产筛选、占用管理、Telnet / SSH 会话集中在同一个桌面工作区")
            copy.setObjectName("sectionCopy")
            title_col.addWidget(brand)
            title_col.addWidget(copy)
            layout.addLayout(title_col)

            layout.addStretch(1)

            self.toolbar_refresh_button = QPushButton("刷新")
            self.toolbar_refresh_button.setObjectName("ghostButton")
            layout.addWidget(self.toolbar_refresh_button)
            return frame

        def _build_left_panel(self) -> QWidget:
            shell = QWidget()
            shell.setObjectName("leftSidebarShell")
            self.left_sidebar_shell = shell
            shell.setMinimumWidth(480)
            shell_layout = QHBoxLayout(shell)
            self.left_sidebar_layout = shell_layout
            shell_layout.setContentsMargins(0, 0, 4, 0)
            shell_layout.setSpacing(6)
            shell_layout.addWidget(self._build_activity_rail(), 0)

            scroll = QScrollArea()
            scroll.setObjectName("inspectorScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.left_sidebar_content = scroll
            scroll.setMinimumWidth(420)
            scroll.setMaximumWidth(760)

            device_panel = QWidget()
            device_panel.setObjectName("leftRail")
            self.device_sidebar_panel = device_panel
            layout = QVBoxLayout(device_panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)

            navigation_group = QGroupBox("终端导航")
            navigation_group.setObjectName("navShell")
            nav_layout = QVBoxLayout(navigation_group)
            nav_layout.setSpacing(8)

            nav_header_frame = QWidget()
            self.device_navigation_header = nav_header_frame
            nav_header = QHBoxLayout(nav_header_frame)
            nav_header.setContentsMargins(0, 0, 0, 0)
            nav_header.setSpacing(8)
            nav_title_col = QVBoxLayout()
            nav_title_col.setSpacing(2)
            nav_title = QLabel("终端会话")
            nav_title.setObjectName("railTitle")
            nav_copy = QLabel("打开终端后在这里跳转会话；设备池请回到首页大屏。")
            nav_copy.setObjectName("railCopy")
            nav_copy.setWordWrap(True)
            nav_copy.setMinimumWidth(0)
            if QSizePolicy is not None:
                nav_copy.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            nav_title_col.addWidget(nav_title)
            nav_title_col.addWidget(nav_copy)
            nav_header.addLayout(nav_title_col, 1)
            self.toolbar_refresh_button = QPushButton("刷新")
            self.toolbar_refresh_button.setObjectName("compactGhostButton")
            self.toolbar_refresh_button.setFixedWidth(58)
            self.always_on_top_button = QPushButton("置顶")
            self.always_on_top_button.setObjectName("compactGhostButton")
            self.always_on_top_button.setCheckable(True)
            self.always_on_top_button.setFixedWidth(58)
            self.always_on_top_button.setToolTip("窗口置顶")
            self.device_navigation_toggle_button = QPushButton("隐藏左侧")
            self.device_navigation_toggle_button.setObjectName("compactGhostButton")
            self.device_navigation_toggle_button.setFixedWidth(76)
            nav_header.addWidget(self.toolbar_refresh_button, 0, Qt.AlignTop)
            nav_header.addWidget(self.always_on_top_button, 0, Qt.AlignTop)
            nav_header.addWidget(self.device_navigation_toggle_button, 0, Qt.AlignTop)
            nav_layout.addWidget(nav_header_frame)

            self.device_navigation_body = QWidget()
            nav_body_layout = QVBoxLayout(self.device_navigation_body)
            nav_body_layout.setContentsMargins(0, 0, 0, 0)
            nav_body_layout.setSpacing(8)

            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("搜索名称、ID、IP、型号")
            self.search_input.setVisible(False)
            nav_body_layout.addWidget(self.search_input)

            filter_frame = QFrame()
            self.device_filter_frame = filter_frame
            filter_frame.setObjectName("navFilterBar")
            filter_row = QHBoxLayout(filter_frame)
            filter_row.setContentsMargins(8, 8, 8, 8)
            filter_row.setSpacing(6)
            self.domain_combo = QComboBox()
            self.domain_combo.addItem(ALL_DOMAINS)
            self.status_combo = QComboBox()
            self.status_combo.addItems(FILTERABLE_STATUSES)
            self.cpu_input = QLineEdit()
            self.cpu_input.setPlaceholderText("CPU")
            self.my_occupancy_filter_button = QPushButton("我的")
            self.my_occupancy_filter_button.setObjectName("filterToggleButton")
            self.my_occupancy_filter_button.setCheckable(True)
            self.my_occupancy_filter_button.setToolTip("只显示当前 API 用户占用的设备")
            self.domain_combo.setMinimumWidth(0)
            self.status_combo.setMinimumWidth(0)
            self.cpu_input.setMinimumWidth(84)
            self.cpu_input.setMaximumWidth(110)
            self.my_occupancy_filter_button.setMinimumWidth(78)
            self.my_occupancy_filter_button.setMaximumWidth(96)
            filter_row.addWidget(self.domain_combo, 1)
            filter_row.addWidget(self.status_combo, 1)
            filter_row.addWidget(self.cpu_input, 0)
            filter_row.addWidget(self.my_occupancy_filter_button, 0)
            filter_frame.setVisible(False)
            nav_body_layout.addWidget(filter_frame)

            stats_frame = QFrame()
            self.device_stats_frame = stats_frame
            stats_frame.setObjectName("navStatsBar")
            stats_layout = QVBoxLayout(stats_frame)
            stats_layout.setContentsMargins(10, 6, 10, 6)
            stats_layout.setSpacing(4)
            stats_top_row = QHBoxLayout()
            stats_top_row.setContentsMargins(0, 0, 0, 0)
            stats_top_row.setSpacing(4)
            stats_bottom_row = QHBoxLayout()
            stats_bottom_row.setContentsMargins(0, 0, 0, 0)
            stats_bottom_row.setSpacing(4)
            self.stats_caption_label = QLabel("筛选结果")
            self.stats_caption_label.setObjectName("sectionCopy")
            self.stats_label = QLabel("设备 0  空闲 0  占用 0  流水线 0  其他 0")
            self.stats_label.setObjectName("navStatsText")
            self.stats_label.setTextFormat(Qt.RichText)
            self.filter_summary_label = QLabel("当前显示全部设备")
            self.filter_summary_label.setObjectName("activeFilterText")
            self.filter_summary_label.setTextFormat(Qt.RichText)
            self.filter_summary_label.setWordWrap(True)
            self.filter_summary_label.setMinimumWidth(0)
            if QSizePolicy is not None:
                self.filter_summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            stats_top_row.addWidget(self.stats_caption_label)
            stats_top_row.addWidget(self.stats_label, 1)
            stats_bottom_row.addWidget(self.filter_summary_label, 1)
            self.clear_filters_button = QPushButton("清空")
            self.clear_filters_button.setObjectName("compactGhostButton")
            self.clear_filters_button.setEnabled(False)
            self.clear_filters_button.setFixedWidth(58)
            stats_bottom_row.addWidget(self.clear_filters_button)
            stats_layout.addLayout(stats_top_row)
            stats_layout.addLayout(stats_bottom_row)
            stats_frame.setVisible(False)
            nav_body_layout.addWidget(stats_frame)

            self.device_table = self._new_table(["序号", "设备", "板类型", "CPU", "Slot", "状态"])
            self.device_table.setMinimumHeight(260)
            self.device_table.setMaximumHeight(340)
            self.device_table.setVisible(False)
            nav_body_layout.addWidget(self.device_table)
            self.device_navigation_web = DeviceNavigationWebWidget(self)
            self.apply_terminal_navigation_web_height()
            nav_body_layout.addWidget(self.device_navigation_web, 1)
            self.device_navigation_resize_handle = VerticalResizeHandle(
                self.resize_terminal_navigation_web,
                self.device_navigation_body,
                height_provider=lambda: self.device_navigation_web.height(),
                grow_down=True,
            )
            self.device_navigation_resize_handle.setObjectName("terminalNavigationResizeHandle")
            self.device_navigation_resize_handle.setToolTip("上下拖动调整终端导航区域高度")
            nav_body_layout.addWidget(self.device_navigation_resize_handle)
            nav_layout.addWidget(self.device_navigation_body)
            self.device_context_panel = self._build_device_context_panel()
            nav_layout.addWidget(self.device_context_panel)
            layout.addWidget(navigation_group)
            layout.addStretch(1)
            stack_container = QWidget()
            stack_container.setObjectName("leftRail")
            stack_container.setMinimumWidth(0)
            if QSizePolicy is not None:
                stack_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self.left_sidebar_stack_container = stack_container
            self.left_sidebar_stack = QStackedLayout(stack_container)
            self.left_sidebar_stack.setContentsMargins(0, 0, 0, 0)
            self.left_sidebar_stack.addWidget(device_panel)
            self.left_sidebar_stack.addWidget(self._build_temporary_panel())
            self.left_sidebar_stack.addWidget(self._build_server_panel())
            self.left_sidebar_stack.addWidget(self._build_transfer_panel())
            self.left_sidebar_stack.addWidget(self._build_package_upgrade_panel())
            self.left_sidebar_stack.addWidget(self._build_ai_device_panel())
            scroll.setWidget(stack_container)
            shell_layout.addWidget(scroll, 1)
            self.apply_left_sidebar_state(animated=True)
            return shell

        def _build_activity_rail(self) -> QWidget:
            rail = QFrame()
            rail.setObjectName("activityRail")
            self.activity_rail = rail
            rail.setFixedWidth(self.ACTIVITY_RAIL_WIDTH)
            layout = QVBoxLayout(rail)
            layout.setContentsMargins(5, 8, 5, 8)
            layout.setSpacing(8)

            self.activity_home_button = self._new_activity_button(
                "home",
                "首页大屏",
                checked=self.center_stage_mode == "home",
            )
            self.activity_temporary_button = self._new_activity_button(
                "connector",
                "临时连接",
            )
            self.activity_server_button = self._new_activity_button(
                "server",
                "我的服务器",
            )
            self.activity_transfer_button = self._new_activity_button(
                "transfer",
                "文件传输",
            )
            self.activity_package_upgrade_button = self._new_activity_button(
                "upgrade",
                "自动换大包",
            )

            self.activity_ai_device_button = self._new_activity_button("ai", "AI 设备助手")

            layout.addWidget(self.activity_home_button)
            layout.addSpacing(4)
            layout.addWidget(self.activity_temporary_button)
            layout.addWidget(self.activity_server_button)
            layout.addWidget(self.activity_transfer_button)
            layout.addWidget(self.activity_package_upgrade_button)
            layout.addWidget(self.activity_ai_device_button)
            layout.addStretch(1)

            self.settings_button = self._new_activity_button(
                "settings",
                "工作台设置",
                checkable=False,
            )
            self.attach_settings_menu(self.settings_button)
            layout.addWidget(self.settings_button)

            self.activity_home_button.clicked.connect(self.show_web_home)
            self.activity_temporary_button.clicked.connect(
                lambda: self.toggle_tool_sidebar_panel("temporary")
            )
            self.activity_server_button.clicked.connect(
                lambda: self.toggle_tool_sidebar_panel("server")
            )
            self.activity_transfer_button.clicked.connect(
                lambda: self.toggle_tool_sidebar_panel("transfer")
            )
            self.activity_package_upgrade_button.clicked.connect(
                lambda: self.toggle_tool_sidebar_panel("package_upgrade")
            )
            self.activity_ai_device_button.clicked.connect(
                lambda: self.toggle_tool_sidebar_panel("ai_device")
            )
            return rail

        def _new_activity_button(self, icon_name: str, tooltip: str, *, checked: bool = False, checkable: bool = True) -> QToolButton:
            button = QToolButton()
            button.setObjectName("activityRailButton")
            button.setToolTip(tooltip)
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setIcon(self._activity_icon(icon_name, "#f8fafc" if checked else "#718096"))
            button.setIconSize(QSize(22, 22))
            button.setFixedSize(34, 34)
            button.setCheckable(checkable)
            button.setChecked(checked)
            button.setAutoRaise(False)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)
            return button

        def _activity_icon(self, kind: str, color: str = "#718096") -> Any:
            if QIcon is None or QPainter is None or QPen is None or QPixmap is None:
                return QIcon() if QIcon is not None else None
            pixmap = QPixmap(24, 24)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(QColor(color), 1.7)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)

            if kind == "home":
                painter.drawLine(4, 11, 12, 4)
                painter.drawLine(12, 4, 20, 11)
                painter.drawLine(6, 10, 6, 20)
                painter.drawLine(18, 10, 18, 20)
                painter.drawLine(6, 20, 18, 20)
                painter.drawRect(10, 14, 4, 6)
            elif kind == "devices":
                painter.drawRoundedRect(6, 4, 11, 15, 2, 2)
                painter.drawLine(9, 8, 14, 8)
                painter.drawLine(9, 12, 14, 12)
                painter.drawLine(9, 16, 12, 16)
            elif kind == "search":
                painter.drawEllipse(5, 5, 10, 10)
                painter.drawLine(13, 13, 19, 19)
            elif kind == "owner":
                painter.drawEllipse(9, 5, 6, 6)
                painter.drawArc(6, 11, 12, 8, 20 * 16, 140 * 16)
                painter.drawLine(7, 20, 17, 20)
            elif kind == "terminal":
                painter.drawRoundedRect(4, 6, 16, 12, 2, 2)
                painter.drawLine(7, 10, 9, 12)
                painter.drawLine(7, 14, 13, 14)
            elif kind == "log":
                painter.drawRoundedRect(7, 4, 11, 16, 2, 2)
                painter.drawLine(10, 8, 15, 8)
                painter.drawLine(10, 12, 15, 12)
                painter.drawLine(10, 16, 13, 16)
            elif kind == "server":
                painter.drawRoundedRect(4, 3, 16, 6, 2, 2)
                painter.drawRoundedRect(4, 9, 16, 6, 2, 2)
                painter.drawRoundedRect(4, 15, 16, 6, 2, 2)
                painter.drawLine(7, 6, 9, 6)
                painter.drawLine(7, 12, 9, 12)
                painter.drawLine(7, 18, 9, 18)
            elif kind == "connector":
                painter.drawRoundedRect(4, 6, 9, 8, 2, 2)
                painter.drawRoundedRect(11, 10, 9, 8, 2, 2)
                painter.drawLine(12, 11, 15, 11)
                painter.drawLine(9, 14, 12, 14)
            elif kind == "transfer":
                painter.drawRoundedRect(5, 5, 14, 14, 2, 2)
                painter.drawLine(8, 9, 16, 9)
                painter.drawLine(16, 9, 13, 6)
                painter.drawLine(16, 9, 13, 12)
                painter.drawLine(16, 15, 8, 15)
                painter.drawLine(8, 15, 11, 12)
                painter.drawLine(8, 15, 11, 18)
            elif kind == "upgrade":
                painter.drawRoundedRect(5, 5, 14, 14, 2, 2)
                painter.drawEllipse(7, 7, 10, 10)
                painter.drawLine(12, 8, 12, 16)
                painter.drawLine(12, 8, 9, 11)
                painter.drawLine(12, 8, 15, 11)
                painter.drawLine(9, 17, 15, 17)
            elif kind == "ai":
                painter.drawRoundedRect(5, 5, 14, 14, 4, 4)
                painter.drawEllipse(8, 9, 2, 2)
                painter.drawEllipse(14, 9, 2, 2)
                painter.drawLine(9, 15, 15, 15)
                painter.drawLine(12, 3, 12, 5)
                painter.drawLine(12, 19, 12, 21)
            elif kind == "settings":
                import math

                center = 12.0
                painter.drawEllipse(9, 9, 6, 6)
                for i in range(8):
                    angle = math.pi * 0.25 * i
                    cos_a, sin_a = math.cos(angle), math.sin(angle)
                    painter.drawLine(
                        center + 5.5 * cos_a,
                        center + 5.5 * sin_a,
                        center + 8.5 * cos_a,
                        center + 8.5 * sin_a,
                    )
            else:
                painter.drawEllipse(7, 7, 10, 10)
            painter.end()
            return QIcon(pixmap)

        def _build_occupancy_panel(self) -> QWidget:
            frame = QFrame()
            frame.setObjectName("myOccupancyCard")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(6)

            header_row = QHBoxLayout()
            title_col = QVBoxLayout()
            title_col.setSpacing(2)
            title = QLabel("我的占用")
            title.setObjectName("railTitle")
            title_col.addWidget(title)
            header_row.addLayout(title_col)
            header_row.addStretch(1)
            self.owned_count_label = QLabel("0")
            self.owned_count_label.setObjectName("navStatsText")
            header_row.addWidget(self.owned_count_label, 0, Qt.AlignTop)
            layout.addLayout(header_row)

            self.owned_table = self._new_table(["设备", "领域", "状态"])
            self.owned_table.setMinimumHeight(150)
            layout.addWidget(self.owned_table, 1)
            return frame

        def _build_temporary_panel(self) -> QWidget:
            panel = QWidget()
            panel.setObjectName("leftRail")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 8, 0)
            layout.setSpacing(8)

            group = QGroupBox("临时连接")
            group.setObjectName("navShell")
            group_layout = QVBoxLayout(group)
            group_layout.setSpacing(8)

            header = QHBoxLayout()
            title_col = QVBoxLayout()
            title_col.setSpacing(2)
            title = QLabel("临时连接")
            title.setObjectName("railTitle")
            copy = QLabel("不进入设备表，直接打开一次性 Telnet / SSH 会话")
            copy.setObjectName("railCopy")
            copy.setWordWrap(True)
            copy.setMinimumWidth(0)
            if QSizePolicy is not None:
                copy.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            title_col.addWidget(title)
            title_col.addWidget(copy)
            header.addLayout(title_col, 1)

            group_layout.addLayout(header)

            form_frame = QFrame()
            form_frame.setObjectName("temporaryFormCard")
            form_layout = QFormLayout(form_frame)
            form_layout.setContentsMargins(10, 10, 10, 10)
            form_layout.setVerticalSpacing(7)
            form_layout.setHorizontalSpacing(8)
            form_layout.setLabelAlignment(Qt.AlignRight)

            self.temporary_name_input = QLineEdit()
            self.temporary_name_input.setPlaceholderText("Temp-10.1.2.3")
            form_layout.addRow("名称", self.temporary_name_input)

            def new_temporary_protocol_card(protocol: str) -> tuple[QFrame, QFormLayout]:
                card = QFrame()
                card.setObjectName("temporaryProtocolCard")
                card.setProperty("protocol", protocol)
                card_layout = QFormLayout(card)
                card_layout.setContentsMargins(10, 9, 10, 9)
                card_layout.setVerticalSpacing(7)
                card_layout.setHorizontalSpacing(8)
                card_layout.setLabelAlignment(Qt.AlignRight)
                return card, card_layout

            telnet_card, telnet_layout = new_temporary_protocol_card("telnet")
            telnet_row = QHBoxLayout()
            telnet_row.setSpacing(6)
            self.temporary_telnet_ip_input = QLineEdit()
            self.temporary_telnet_ip_input.setPlaceholderText("Telnet IP")
            self.temporary_telnet_port_input = QLineEdit()
            self.temporary_telnet_port_input.setPlaceholderText("23")
            self.temporary_telnet_port_input.setMaximumWidth(64)
            telnet_row.addWidget(self.temporary_telnet_ip_input, 1)
            telnet_row.addWidget(self.temporary_telnet_port_input)
            telnet_layout.addRow("地址", telnet_row)
            self.temporary_telnet_username_input = QLineEdit()
            self.temporary_telnet_password_input = QLineEdit()
            configure_password_visibility(self.temporary_telnet_password_input)
            telnet_layout.addRow("账号", self.temporary_telnet_username_input)
            telnet_layout.addRow("密码", self.temporary_telnet_password_input)
            form_layout.addRow("Telnet", telnet_card)

            ssh_card, ssh_layout = new_temporary_protocol_card("ssh")
            ssh_row = QHBoxLayout()
            ssh_row.setSpacing(6)
            self.temporary_ssh_ip_input = QLineEdit()
            self.temporary_ssh_ip_input.setPlaceholderText("SSH IP")
            self.temporary_ssh_port_input = QLineEdit()
            self.temporary_ssh_port_input.setPlaceholderText("22")
            self.temporary_ssh_port_input.setMaximumWidth(64)
            ssh_row.addWidget(self.temporary_ssh_ip_input, 1)
            ssh_row.addWidget(self.temporary_ssh_port_input)
            ssh_layout.addRow("地址", ssh_row)
            self.temporary_ssh_username_input = QLineEdit()
            self.temporary_ssh_password_input = QLineEdit()
            configure_password_visibility(self.temporary_ssh_password_input)
            ssh_layout.addRow("账号", self.temporary_ssh_username_input)
            ssh_layout.addRow("密码", self.temporary_ssh_password_input)
            form_layout.addRow("SSH", ssh_card)

            serial_card, serial_layout = new_temporary_protocol_card("serial")
            serial_row = QHBoxLayout()
            serial_row.setSpacing(6)
            self.temporary_serial_ip_input = QLineEdit()
            self.temporary_serial_ip_input.setPlaceholderText("串口 IP")
            self.temporary_serial_port_input = QLineEdit()
            self.temporary_serial_port_input.setPlaceholderText("23")
            self.temporary_serial_port_input.setMaximumWidth(64)
            serial_row.addWidget(self.temporary_serial_ip_input, 1)
            serial_row.addWidget(self.temporary_serial_port_input)
            serial_layout.addRow("地址", serial_row)
            self.temporary_serial_password_input = QLineEdit()
            configure_password_visibility(self.temporary_serial_password_input)
            serial_layout.addRow("密码", self.temporary_serial_password_input)
            form_layout.addRow("串口", serial_card)

            self.temporary_notes_input = QLineEdit()
            form_layout.addRow("备注", self.temporary_notes_input)

            form_button_row = QHBoxLayout()
            form_button_row.setSpacing(6)
            self.temporary_save_button = QPushButton("保存并打开")
            self.temporary_save_button.setObjectName("primaryButton")
            self.temporary_clear_button = QPushButton("清空")
            self.temporary_clear_button.setObjectName("compactGhostButton")
            form_button_row.addWidget(self.temporary_save_button, 1)
            form_button_row.addWidget(self.temporary_clear_button, 0)
            form_layout.addRow("", form_button_row)
            group_layout.addWidget(form_frame)

            self.temporary_empty_label = QLabel("暂无临时连接")
            self.temporary_empty_label.setObjectName("sectionCopy")
            self.temporary_empty_label.setWordWrap(True)
            group_layout.addWidget(self.temporary_empty_label)

            self.temporary_list_container = QWidget()
            self.temporary_list_container.setObjectName("leftRail")
            self.temporary_list_layout = QVBoxLayout(self.temporary_list_container)
            self.temporary_list_layout.setContentsMargins(0, 0, 0, 0)
            self.temporary_list_layout.setSpacing(6)
            group_layout.addWidget(self.temporary_list_container)
            group_layout.addStretch(1)

            layout.addWidget(group)
            layout.addStretch(1)
            self.refresh_temporary_panel()
            return panel

        def refresh_temporary_panel(self) -> None:
            if not hasattr(self, "temporary_list_layout"):
                return
            while self.temporary_list_layout.count():
                item = self.temporary_list_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.temporary_empty_label.setVisible(not self.temporary_devices)
            for device in self.temporary_devices:
                row = QFrame()
                row.setObjectName("temporaryDeviceCard")
                row.setToolTip("右键打开更多临时连接操作")
                row.setContextMenuPolicy(Qt.CustomContextMenu)
                row.customContextMenuRequested.connect(
                    lambda pos, widget=row, item=device: self.show_temporary_device_context_menu(item, widget, pos)
                )
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(10, 9, 10, 9)
                row_layout.setSpacing(8)

                protocols = []
                if device.telnet_ip.strip():
                    protocols.append("Telnet")
                if device.ssh_ip.strip():
                    protocols.append("SSH")
                if device.serial_ip.strip():
                    protocols.append("Serial")
                info_col = QVBoxLayout()
                info_col.setSpacing(5)
                title_label = QLabel(self.temporary_device_display_name(device))
                title_label.setObjectName("temporaryCardTitle")
                title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                endpoint_label = QLabel(self.temporary_device_endpoint_text(device))
                endpoint_label.setObjectName("temporaryCardEndpoint")
                endpoint_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                endpoint_label.setWordWrap(True)
                info_col.addWidget(title_label)
                info_col.addWidget(endpoint_label)

                protocol_row = QHBoxLayout()
                protocol_row.setSpacing(4)
                for protocol in protocols:
                    pill = QLabel(protocol)
                    pill.setObjectName("temporaryProtocolPill")
                    pill.setProperty("protocol", protocol.lower())
                    protocol_row.addWidget(pill, 0)
                protocol_row.addStretch(1)
                info_col.addLayout(protocol_row)

                if device.notes:
                    notes_label = QLabel(device.notes)
                    notes_label.setObjectName("temporaryCardNotes")
                    notes_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    notes_label.setWordWrap(True)
                    info_col.addWidget(notes_label)

                row_layout.addLayout(info_col, 1)

                open_button = QPushButton("打开")
                open_button.setObjectName("compactGhostButton")
                open_button.setFixedWidth(58)
                open_button.clicked.connect(lambda _checked=False, item=device: self.open_temporary_device(item))
                row_layout.addWidget(open_button)

                edit_button = QPushButton("编辑")
                edit_button.setObjectName("compactGhostButton")
                edit_button.setFixedWidth(58)
                edit_button.clicked.connect(lambda _checked=False, item=device: self.edit_temporary_device(item))
                row_layout.addWidget(edit_button)

                delete_button = QPushButton("删除")
                delete_button.setObjectName("dangerButton")
                delete_button.setFixedWidth(58)
                delete_button.clicked.connect(lambda _checked=False, item=device: self.delete_temporary_device(item))
                row_layout.addWidget(delete_button)

                self.temporary_list_layout.addWidget(row)
            self.temporary_list_layout.addStretch(1)

        def _build_device_context_panel(self) -> QWidget:
            panel = QWidget()
            panel.setObjectName("inspectorRail")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)

            detail_group = QGroupBox("当前选中设备连接")
            detail_group.setObjectName("authCard")
            self.connection_params_group = detail_group
            detail_layout = QVBoxLayout(detail_group)
            detail_layout.setContentsMargins(10, 12, 10, 10)
            detail_layout.setSpacing(6)
            self.device_summary_card = QLabel("请选择一台设备。")
            self.device_summary_card.setObjectName("inspectorText")
            self.device_summary_card.setWordWrap(True)
            self.device_summary_card.setTextFormat(Qt.RichText)
            self.device_summary_card.setTextInteractionFlags(Qt.TextSelectableByMouse)
            detail_layout.addWidget(self.device_summary_card)

            auth_group = QFrame()
            auth_group.setObjectName("connectionParamsPanel")
            auth_layout = QVBoxLayout(auth_group)
            auth_layout.setContentsMargins(0, 0, 0, 0)
            auth_layout.setSpacing(6)

            auth_header_frame = QFrame()
            auth_header_frame.setObjectName("connectionParamsHeader")
            auth_header = QHBoxLayout(auth_header_frame)
            auth_header.setContentsMargins(0, 0, 0, 0)
            auth_header.setSpacing(8)
            auth_hint = QLabel("跟随左侧选中设备，本机覆盖不回写网站")
            auth_hint.setObjectName("sectionCopy")
            auth_hint.setWordWrap(True)
            auth_hint.setMinimumWidth(0)
            if QSizePolicy is not None:
                auth_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self.connection_params_toggle_button = QToolButton()
            self.connection_params_toggle_button.setObjectName("inspectorToggleButton")
            self.connection_params_toggle_button.setText("展开")
            self.connection_params_toggle_button.setToolTip("展开或收起当前选中设备连接")
            self.connection_params_toggle_button.setFixedWidth(58)
            auth_header.addWidget(auth_hint)
            auth_header.addStretch(1)
            auth_header.addWidget(self.connection_params_toggle_button)
            auth_layout.addWidget(auth_header_frame)

            self.connection_params_body = QWidget()
            body_layout = QVBoxLayout(self.connection_params_body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(6)

            device_form_group = QGroupBox("设备 Telnet")
            device_form = QFormLayout(device_form_group)
            device_form.setContentsMargins(8, 10, 8, 8)
            device_form.setVerticalSpacing(6)
            device_form.setHorizontalSpacing(6)
            device_form.setLabelAlignment(Qt.AlignRight)
            self.device_telnet_ip_value = SelectAllLineEdit()
            self.device_username_input = QLineEdit()
            self.device_password_input = QLineEdit()
            configure_password_visibility(self.device_password_input)
            device_form.addRow("Telnet IP", self.device_telnet_ip_value)
            device_form.addRow("用户名", self.device_username_input)
            device_form.addRow("密码", self.device_password_input)
            self.connection_telnet_button = QPushButton("连接 Telnet")
            self.connection_telnet_button.setObjectName("primaryButton")
            device_form.addRow("", self.connection_telnet_button)

            serial_form_group = QGroupBox("串口 Telnet")
            serial_form = QFormLayout(serial_form_group)
            serial_form.setContentsMargins(8, 10, 8, 8)
            serial_form.setVerticalSpacing(6)
            serial_form.setHorizontalSpacing(6)
            serial_form.setLabelAlignment(Qt.AlignRight)
            self.device_serial_ip_value = SelectAllLineEdit()
            self.device_serial_ip_value.setPlaceholderText("占用后可见")
            serial_form.addRow("串口地址", self.device_serial_ip_value)
            self.serial_username_input = QLineEdit()
            self.serial_password_input = QLineEdit()
            configure_password_visibility(self.serial_password_input)
            serial_form.addRow("用户名", self.serial_username_input)
            serial_form.addRow("密码", self.serial_password_input)
            self.connection_serial_button = QPushButton("连接串口")
            self.connection_serial_button.setObjectName("primaryButton")
            serial_form.addRow("", self.connection_serial_button)

            linux_form_group = QGroupBox("Linux SSH")
            linux_form = QFormLayout(linux_form_group)
            linux_form.setContentsMargins(8, 10, 8, 8)
            linux_form.setVerticalSpacing(6)
            linux_form.setHorizontalSpacing(6)
            linux_form.setLabelAlignment(Qt.AlignRight)
            self.device_ssh_ip_value = SelectAllLineEdit()
            self.linux_username_input = QLineEdit()
            self.linux_password_input = QLineEdit()
            configure_password_visibility(self.linux_password_input)
            linux_form.addRow("SSH IP", self.device_ssh_ip_value)
            linux_form.addRow("用户名", self.linux_username_input)
            linux_form.addRow("密码", self.linux_password_input)
            self.connection_ssh_button = QPushButton("连接 SSH")
            self.connection_ssh_button.setObjectName("primaryButton")
            linux_form.addRow("", self.connection_ssh_button)

            self._add_connection_compact_row(
                body_layout,
                "Telnet",
                self.device_telnet_ip_value,
                self.device_username_input,
                self.device_password_input,
                self.connection_telnet_button,
            )
            self._add_connection_compact_row(
                body_layout,
                "SSH",
                self.device_ssh_ip_value,
                self.linux_username_input,
                self.linux_password_input,
                self.connection_ssh_button,
            )
            self._add_connection_compact_row(
                body_layout,
                "串口",
                self.device_serial_ip_value,
                self.serial_username_input,
                self.serial_password_input,
                self.connection_serial_button,
            )
            device_form_group.setVisible(False)
            serial_form_group.setVisible(False)
            linux_form_group.setVisible(False)
            body_layout.addWidget(device_form_group)
            body_layout.addWidget(serial_form_group)
            body_layout.addWidget(linux_form_group)
            auth_layout.addWidget(self.connection_params_body)
            detail_layout.addWidget(auth_group)
            layout.addWidget(detail_group)
            self.apply_connection_params_state()
            return panel

        def _add_connection_compact_row(
            self,
            layout: QVBoxLayout,
            title: str,
            host_input: QLineEdit,
            username_input: QLineEdit,
            password_input: QLineEdit,
            button: QPushButton,
        ) -> None:
            row = QFrame()
            row.setObjectName("connectionCompactRow")
            row.setProperty("surface", "connectionProtocolCard")
            row.setProperty("protocol", title)
            row.setToolTip(f"{title} connection parameters")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(10, 9, 10, 9)
            row_layout.setSpacing(7)

            top_row = QHBoxLayout()
            top_row.setContentsMargins(0, 0, 0, 0)
            top_row.setSpacing(6)
            title_label = QLabel(title)
            title_label.setObjectName("connectionKindLabel")
            title_label.setFixedWidth(52)
            host_label = QLabel("地址")
            host_label.setObjectName("connectionMiniLabel")
            host_label.setFixedWidth(32)
            host_input.setProperty("connectionField", "host")
            host_input.setMinimumWidth(0)
            if QSizePolicy is not None:
                host_input.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.setProperty("connectionAction", "primary")
            button.setFixedWidth(100)
            top_row.addWidget(title_label)
            top_row.addWidget(host_label)
            top_row.addWidget(host_input, 1)
            top_row.addWidget(button)

            credential_row = QHBoxLayout()
            credential_row.setContentsMargins(0, 0, 0, 0)
            credential_row.setSpacing(6)
            user_label = QLabel("账号")
            user_label.setObjectName("connectionMiniLabel")
            user_label.setFixedWidth(32)
            password_label = QLabel("密码")
            password_label.setObjectName("connectionMiniLabel")
            password_label.setFixedWidth(32)
            username_input.setProperty("connectionField", "username")
            password_input.setProperty("connectionField", "password")
            username_input.setMinimumWidth(0)
            password_input.setMinimumWidth(0)
            if QSizePolicy is not None:
                username_input.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
                password_input.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            credential_row.addSpacing(58)
            credential_row.addWidget(user_label)
            credential_row.addWidget(username_input, 1)
            credential_row.addWidget(password_label)
            credential_row.addWidget(password_input, 1)

            row_layout.addLayout(top_row)
            row_layout.addLayout(credential_row)
            layout.addWidget(row)

        def _quick_action_icon(self, kind: str, color: str = "#718096") -> Any:
            if QIcon is None or QPainter is None or QPen is None or QPixmap is None:
                return QIcon() if QIcon is not None else None
            pixmap = QPixmap(18, 18)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(QColor(color), 1.5)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)

            if kind == "terminal":
                painter.drawRoundedRect(3, 5, 14, 10, 2, 2)
                painter.drawLine(6, 8, 8, 10)
                painter.drawLine(6, 12, 11, 12)
            elif kind == "home":
                painter.drawLine(3, 9, 10, 3)
                painter.drawLine(10, 3, 17, 9)
                painter.drawLine(5, 8, 5, 16)
                painter.drawLine(15, 8, 15, 16)
                painter.drawLine(5, 16, 15, 16)
                painter.drawRect(8, 11, 4, 5)
            elif kind == "ssh":
                painter.drawRoundedRect(5, 9, 10, 7, 2, 2)
                painter.drawArc(6, 4, 8, 9, 0, 180 * 16)
                painter.drawLine(10, 12, 10, 14)
            elif kind == "serial":
                painter.drawRoundedRect(4, 4, 12, 8, 2, 2)
                painter.drawLine(7, 14, 13, 14)
                painter.drawLine(8, 17, 12, 17)
                painter.drawLine(10, 12, 10, 17)
                painter.drawPoint(7, 8)
                painter.drawPoint(10, 8)
                painter.drawPoint(13, 8)
            elif kind == "owner":
                painter.drawEllipse(7, 4, 6, 6)
                painter.drawArc(4, 9, 12, 8, 20 * 16, 140 * 16)
                painter.drawLine(5, 17, 15, 17)
            elif kind == "power":
                painter.drawArc(5, 6, 10, 10, 35 * 16, 290 * 16)
                painter.drawLine(10, 3, 10, 10)
            elif kind == "refresh":
                painter.drawArc(4, 4, 12, 12, 35 * 16, 260 * 16)
                painter.drawLine(15, 5, 15, 9)
                painter.drawLine(15, 5, 11, 5)
            elif kind == "auto":
                painter.drawLine(11, 3, 6, 10)
                painter.drawLine(6, 10, 10, 10)
                painter.drawLine(10, 10, 7, 17)
                painter.drawLine(7, 17, 14, 8)
                painter.drawLine(14, 8, 10, 8)
            elif kind == "simulate":
                painter.drawRoundedRect(3, 4, 14, 11, 2, 2)
                painter.drawLine(6, 8, 8, 10)
                painter.drawLine(8, 10, 6, 12)
                painter.drawLine(10, 12, 14, 12)
                painter.drawLine(6, 17, 14, 17)
            elif kind == "log":
                painter.drawRoundedRect(5, 3, 10, 14, 1, 1)
                painter.drawLine(8, 7, 13, 7)
                painter.drawLine(8, 10, 13, 10)
                painter.drawLine(8, 13, 11, 13)
            elif kind == "disconnect":
                painter.drawLine(5, 5, 15, 15)
                painter.drawLine(7, 13, 13, 7)
                painter.drawLine(6, 15, 14, 15)
            elif kind == "close":
                painter.drawLine(6, 6, 14, 14)
                painter.drawLine(14, 6, 6, 14)
                painter.drawRoundedRect(4, 4, 12, 12, 2, 2)
            elif kind == "collapse":
                painter.drawLine(5, 7, 15, 7)
                painter.drawLine(5, 13, 15, 13)
                painter.drawLine(7, 10, 13, 10)
            painter.end()
            return QIcon(pixmap)

        def _configure_quick_action_button(
            self,
            button: QToolButton,
            icon_name: str,
            tooltip: str,
            *,
            danger: bool = False,
        ) -> None:
            button.setObjectName("quickDangerIconButton" if danger else "quickActionIconButton")
            button.setText("")
            button.setToolTip(tooltip)
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setIcon(self._quick_action_icon(icon_name, "#718096" if not danger else "#f87171"))
            button.setIconSize(QSize(14, 14))
            button.setFixedSize(24, 24)
            button.setAutoRaise(False)
            button.setFocusPolicy(Qt.NoFocus)
            button.setCursor(Qt.PointingHandCursor)

        def _build_center_panel(self) -> QWidget:
            panel = QWidget()
            panel.setObjectName("centerStage")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self.center_stage_splitter = QSplitter(Qt.Vertical)
            self.center_stage_splitter.setObjectName("centerStageSplitter")
            self.center_stage_splitter.setChildrenCollapsible(False)
            layout.addWidget(self.center_stage_splitter, 1)

            self.web_shell = WebShellWidget(self)
            self.web_shell.setMinimumHeight(300)

            self.session_tab_widget = QTabWidget()
            self.session_tab_widget.setObjectName("sessionTabs")
            self.session_tab_widget.setDocumentMode(True)
            self.session_tab_widget.setTabsClosable(False)
            self.session_tab_widget.setMovable(True)
            device_tab_bar = self.session_tab_widget.tabBar()
            device_tab_bar.setExpanding(False)
            device_tab_bar.setUsesScrollButtons(True)
            device_tab_bar.setContextMenuPolicy(Qt.CustomContextMenu)
            device_tab_bar.customContextMenuRequested.connect(self.show_device_tab_context_menu)
            self.session_tab_widget.setMinimumHeight(260)
            self.build_session_breadcrumb()
            self.center_stage_splitter.addWidget(self.session_breadcrumb)
            self.center_stage_splitter.addWidget(self.web_shell)
            self.center_stage_splitter.addWidget(self.session_tab_widget)
            quick_action_bar = QFrame()
            self.session_quick_action_bar = quick_action_bar
            quick_action_bar.setObjectName("sessionQuickBar")
            quick_action_layout = QVBoxLayout(quick_action_bar)
            quick_action_layout.setContentsMargins(8, 4, 8, 4)
            quick_action_layout.setSpacing(4)
            quick_action_row = QHBoxLayout()
            quick_action_row.setContentsMargins(0, 0, 0, 0)
            quick_action_row.setSpacing(4)
            terminal_ops_label = QLabel("TERMINAL OPS")
            self.terminal_ops_label = terminal_ops_label
            terminal_ops_label.setObjectName("terminalOpsLabel")
            terminal_ops_label.setVisible(False)
            self.session_jump_combo = QComboBox()
            self.session_jump_combo.setObjectName("sessionJumpCombo")
            self.session_jump_combo.setMinimumWidth(180)
            self.session_jump_combo.setMaximumWidth(520)
            self.session_jump_combo.setFixedWidth(self.session_jump_combo_width)
            self.session_jump_combo.setToolTip("快速跳转到已打开的终端会话")
            self.session_jump_combo.setVisible(False)
            self.session_jump_resize_handle = HorizontalResizeHandle(
                self.resize_session_jump_combo,
                quick_action_bar,
                width_provider=lambda: self.session_jump_combo.width(),
            )
            self.session_jump_resize_handle.setObjectName("sessionJumpResizeHandle")
            self.session_jump_resize_handle.setVisible(False)
            self.session_count_label = QLabel("0 会话")
            self.session_count_label.setObjectName("terminalSessionCountPill")
            self.session_count_label.setMinimumWidth(58)
            self.session_count_label.setAlignment(Qt.AlignCenter)
            self.session_count_label.setVisible(False)
            self.auto_response_rule_bar = QFrame()
            self.auto_response_rule_bar.setObjectName("autoResponseRuleBar")
            self.auto_response_rule_bar.setMinimumHeight(30)
            self.auto_response_rule_bar_layout = QHBoxLayout(self.auto_response_rule_bar)
            self.auto_response_rule_bar_layout.setContentsMargins(0, 0, 0, 0)
            self.auto_response_rule_bar_layout.setSpacing(4)
            self.auto_response_rule_bar.setVisible(False)
            self.quick_reconnect_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_reconnect_button,
                "refresh",
                "重连当前会话",
            )
            self.quick_auto_response_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_auto_response_button,
                "auto",
                "自动响应",
            )
            self.quick_auto_response_menu = self.new_workspace_menu(
                self.quick_auto_response_button,
                kind="auto-response-menu",
            )
            self.quick_auto_response_button.setMenu(self.quick_auto_response_menu)
            self.quick_auto_response_button.setPopupMode(QToolButton.InstantPopup)
            self.quick_auto_response_button.setObjectName("autoResponseMenuButton")
            self.quick_auto_response_button.setText("自动响应")
            self.quick_auto_response_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.quick_auto_response_button.setFixedSize(88, 24)
            self.quick_auto_response_button.setIconSize(QSize(14, 14))
            self.quick_log_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_log_button,
                "log",
                "日志",
            )
            self.quick_log_menu = self.new_workspace_menu(
                self.quick_log_button,
                kind="log-menu",
            )
            self.quick_log_new_action = self.quick_log_menu.addAction("新建日志")
            self.quick_log_open_action = self.quick_log_menu.addAction("打开当前会话日志")
            self.quick_log_directory_action = self.quick_log_menu.addAction("打开日志目录")
            self.quick_log_menu.addSeparator()
            self.quick_log_change_directory_action = self.quick_log_menu.addAction("更改日志位置...")
            self.quick_log_rotate_size_action = self.quick_log_menu.addAction("设置日志分卷大小...")
            self.quick_log_button.setMenu(self.quick_log_menu)
            self.quick_log_button.setPopupMode(QToolButton.InstantPopup)
            self.quick_log_button.setToolTip("日志菜单")
            self.quick_disconnect_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_disconnect_button,
                "disconnect",
                "断开当前会话",
                danger=True,
            )
            self.quick_close_button = QToolButton()
            self._configure_quick_action_button(
                self.quick_close_button,
                "close",
                "关闭终端会话",
                danger=True,
            )
            self.quick_close_menu = self.new_workspace_menu(
                self.quick_close_button,
                kind="close-session-menu",
            )
            self.quick_close_current_action = self.quick_close_menu.addAction("关闭当前会话")
            self.quick_close_other_action = self.quick_close_menu.addAction("关闭其他会话")
            self.quick_close_all_action = self.quick_close_menu.addAction("关闭全部会话")
            self.quick_close_button.setMenu(self.quick_close_menu)
            self.quick_close_button.setPopupMode(QToolButton.InstantPopup)
            self.session_quick_bar_toggle_button = QToolButton()
            self._configure_quick_action_button(
                self.session_quick_bar_toggle_button,
                "collapse",
                "隐藏会话工具栏",
            )
            quick_action_row.addWidget(self.quick_reconnect_button)
            quick_action_row.addWidget(self.quick_auto_response_button)
            quick_action_row.addWidget(self.quick_log_button)
            quick_action_row.addSpacing(6)
            quick_action_row.addWidget(self.quick_disconnect_button)
            quick_action_row.addWidget(self.quick_close_button)
            quick_action_row.addWidget(self.session_quick_bar_toggle_button)
            quick_action_row.addStretch(1)
            quick_action_layout.addLayout(quick_action_row)
            quick_action_layout.addWidget(self.auto_response_rule_bar)
            layout.addWidget(quick_action_bar)
            restore_bar = QFrame()
            self.session_quick_restore_bar = restore_bar
            restore_bar.setObjectName("sessionQuickRestoreBar")
            restore_layout = QHBoxLayout(restore_bar)
            restore_layout.setContentsMargins(8, 3, 8, 3)
            restore_layout.setSpacing(6)
            self.session_quick_restore_button = QToolButton()
            self.session_quick_restore_button.setObjectName("sessionQuickRestoreButton")
            self.session_quick_restore_button.setText("会话工具")
            self.session_quick_restore_button.setToolTip("显示会话工具栏")
            self.session_quick_restore_button.setCursor(Qt.PointingHandCursor)
            restore_layout.addWidget(self.session_quick_restore_button)
            restore_layout.addStretch(1)
            layout.addWidget(restore_bar)
            layout.addWidget(self._build_command_record_panel())
            self.apply_session_quick_bar_state()
            self.refresh_workspace_context()
            self.update_center_stage_state()
            return panel

        def _build_right_panel(self) -> QWidget:
            scroll = QScrollArea()
            scroll.setObjectName("inspectorScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setMaximumWidth(400)

            panel = QWidget()
            panel.setObjectName("inspectorRail")
            layout = QVBoxLayout(panel)
            layout.setContentsMargins(0, 0, 8, 0)
            layout.setSpacing(8)

            detail_group = QGroupBox("当前设备")
            detail_group.setObjectName("deviceDetailCard")
            detail_layout = QVBoxLayout(detail_group)
            detail_layout.setContentsMargins(10, 12, 10, 10)
            detail_layout.setSpacing(6)
            self.device_summary_card = QLabel("请选择一台设备。")
            self.device_summary_card.setObjectName("detailCard")
            self.device_summary_card.setWordWrap(True)
            self.device_summary_card.setTextFormat(Qt.RichText)
            detail_layout.addWidget(self.device_summary_card)
            layout.addWidget(detail_group)

            action_group = QGroupBox("快捷动作")
            action_group.setObjectName("quickActionCard")
            action_layout = QVBoxLayout(action_group)
            action_layout.setContentsMargins(10, 12, 10, 10)
            action_layout.setSpacing(6)
            self.open_device_button = QPushButton("连接设备 Telnet")
            self.open_device_button.setObjectName("primaryButton")
            self.open_linux_button = QPushButton("连接 Linux SSH")
            self.open_linux_button.setObjectName("primaryButton")
            self.toggle_occupancy_button = QPushButton("占用 / 释放")
            self.toggle_occupancy_button.setObjectName("ghostButton")
            action_layout.addWidget(self.open_device_button)
            action_layout.addWidget(self.open_linux_button)
            action_layout.addWidget(self.toggle_occupancy_button)
            layout.addWidget(action_group)

            auth_group = QGroupBox("连接参数")
            auth_group.setObjectName("authCard")
            auth_layout = QVBoxLayout(auth_group)
            auth_layout.setSpacing(6)

            device_form_group = QGroupBox("设备 Telnet")
            device_form = QFormLayout(device_form_group)
            device_form.setContentsMargins(8, 10, 8, 8)
            device_form.setVerticalSpacing(6)
            device_form.setHorizontalSpacing(6)
            device_form.setLabelAlignment(Qt.AlignRight)
            self.device_username_input = QLineEdit()
            self.device_password_input = QLineEdit()
            configure_password_visibility(self.device_password_input)
            device_form.addRow("用户名", self.device_username_input)
            device_form.addRow("密码", self.device_password_input)

            serial_form_group = QGroupBox("串口 Telnet")
            serial_form = QFormLayout(serial_form_group)
            serial_form.setContentsMargins(8, 10, 8, 8)
            serial_form.setVerticalSpacing(6)
            serial_form.setHorizontalSpacing(6)
            serial_form.setLabelAlignment(Qt.AlignRight)
            self.serial_username_input = QLineEdit()
            self.serial_password_input = QLineEdit()
            configure_password_visibility(self.serial_password_input)
            serial_form.addRow("用户名", self.serial_username_input)
            serial_form.addRow("密码", self.serial_password_input)

            linux_form_group = QGroupBox("Linux SSH")
            linux_form = QFormLayout(linux_form_group)
            linux_form.setContentsMargins(8, 10, 8, 8)
            linux_form.setVerticalSpacing(6)
            linux_form.setHorizontalSpacing(6)
            linux_form.setLabelAlignment(Qt.AlignRight)
            self.linux_username_input = QLineEdit()
            self.linux_password_input = QLineEdit()
            configure_password_visibility(self.linux_password_input)
            linux_form.addRow("用户名", self.linux_username_input)
            linux_form.addRow("密码", self.linux_password_input)


            auth_layout.addWidget(device_form_group)
            auth_layout.addWidget(serial_form_group)
            auth_layout.addWidget(linux_form_group)
            layout.addWidget(auth_group)
            layout.addStretch(1)
            scroll.setWidget(panel)
            return scroll

        def _build_command_record_panel(self) -> QWidget:
            frame = QFrame()
            frame.setObjectName("commandRecordDock")
            self.command_record_frame = frame
            frame.setMinimumHeight(self.COMMAND_RECORD_MIN_HEIGHT)
            frame.setMaximumHeight(self.COMMAND_RECORD_MAX_HEIGHT)
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            self.command_record_resize_handle = CommandRecordResizeHandle(
                self.resize_command_record_panel,
                frame,
            )
            layout.addWidget(self.command_record_resize_handle)

            hint_bar = QFrame()
            hint_bar.setObjectName("commandRecordHintBar")
            hint_bar.setFixedHeight(22)
            hint_layout = QHBoxLayout(hint_bar)
            hint_layout.setContentsMargins(10, 0, 10, 0)
            hint_layout.setSpacing(8)
            self.command_record_hint_label = QLabel("")
            self.command_record_hint_label.setObjectName("commandRecordHint")
            hint_layout.addWidget(self.command_record_hint_label)
            self.command_enter_mode_button = QToolButton()
            self.command_enter_mode_button.setObjectName("commandEnterModeButton")
            self.command_enter_mode_button.setText("↵")
            self.command_enter_mode_button.setToolTip("切换 Enter 行为")
            hint_layout.addWidget(self.command_enter_mode_button)
            hint_layout.addStretch(1)
            self.command_record_toggle_button = QToolButton()
            self.command_record_toggle_button.setObjectName("commandCollapseButton")
            self.command_record_toggle_button.setText("收起")
            hint_layout.addWidget(self.command_record_toggle_button)
            layout.addWidget(hint_bar)

            self.command_record_input = CommandRecordInput()
            self.command_record_input.set_submit_handler(self.submit_command_record_input)
            self.command_record_input.set_suggestion_accept_handler(self.accept_first_command_suggestion)
            self.command_record_input.textChanged.connect(self.schedule_desktop_state_save)
            self.command_record_input.textChanged.connect(self.refresh_command_suggestions)
            self.update_command_enter_mode()

            self.command_suggestion_bar = QFrame()
            self.command_suggestion_bar.setObjectName("commandSuggestionBar")
            self.command_suggestion_layout = QHBoxLayout(self.command_suggestion_bar)
            self.command_suggestion_layout.setContentsMargins(8, 4, 8, 4)
            self.command_suggestion_layout.setSpacing(4)
            self.command_suggestion_bar.setVisible(False)

            find_replace_bar = QFrame(frame)
            find_replace_bar.setObjectName("commandFindReplaceBar")
            self.command_find_replace_bar = find_replace_bar
            find_replace_bar.setMinimumWidth(380)
            find_replace_bar.setMaximumWidth(420)
            find_replace_layout = QGridLayout(find_replace_bar)
            find_replace_layout.setContentsMargins(8, 7, 8, 7)
            find_replace_layout.setHorizontalSpacing(5)
            find_replace_layout.setVerticalSpacing(5)
            find_replace_layout.setColumnStretch(0, 1)

            self.command_find_input = QLineEdit()
            self.command_find_input.setObjectName("commandFindInput")
            self.command_find_input.setPlaceholderText("查找")
            self.command_find_input.setMinimumWidth(220)

            self.command_find_next_button = QToolButton()
            self.command_find_next_button.setObjectName("commandFindIconButton")
            self.command_find_next_button.setText("↓")
            self.command_find_next_button.setToolTip("查找下一个")

            self.command_find_count_label = QLabel("0")
            self.command_find_count_label.setObjectName("commandFindCount")
            self.command_find_count_label.setMinimumWidth(42)
            self.command_find_count_label.setAlignment(Qt.AlignCenter)

            self.command_find_close_button = QToolButton()
            self.command_find_close_button.setObjectName("commandFindIconButton")
            self.command_find_close_button.setText("×")
            self.command_find_close_button.setToolTip("关闭查找")

            self.command_replace_input = QLineEdit()
            self.command_replace_input.setObjectName("commandReplaceInput")
            self.command_replace_input.setPlaceholderText("替换为")
            self.command_replace_input.setMinimumWidth(220)

            self.command_replace_button = QToolButton()
            self.command_replace_button.setObjectName("commandFindTextButton")
            self.command_replace_button.setText("替换")
            self.command_replace_all_button = QToolButton()
            self.command_replace_all_button.setObjectName("commandFindTextButton")
            self.command_replace_all_button.setText("全部")
            self.command_replace_button.setToolTip("替换当前匹配")
            self.command_replace_all_button.setToolTip("全部替换")

            find_replace_layout.addWidget(self.command_find_input, 0, 0)
            find_replace_layout.addWidget(self.command_find_next_button, 0, 1)
            find_replace_layout.addWidget(self.command_find_count_label, 0, 2)
            find_replace_layout.addWidget(self.command_find_close_button, 0, 3)
            find_replace_layout.addWidget(self.command_replace_input, 1, 0)
            find_replace_layout.addWidget(self.command_replace_button, 1, 1)
            find_replace_layout.addWidget(self.command_replace_all_button, 1, 2, 1, 2)

            find_replace_bar.setVisible(False)
            layout.addWidget(self.command_suggestion_bar)
            layout.addWidget(self.command_record_input)

            footer = QFrame()
            footer.setObjectName("commandRecordFooter")
            self.command_record_footer = footer
            footer.setFixedHeight(24)
            footer_layout = QHBoxLayout(footer)
            footer_layout.setContentsMargins(8, 0, 8, 0)
            footer_layout.setSpacing(4)

            self.command_tab_row = QHBoxLayout()
            self.command_tab_row.setContentsMargins(0, 0, 0, 0)
            self.command_tab_row.setSpacing(2)
            footer_layout.addLayout(self.command_tab_row)
            footer_layout.addStretch(1)

            self.command_broadcast_button = QToolButton()
            self.command_broadcast_button.setObjectName("commandActionButton")
            self.command_broadcast_button.setProperty("buttonRole", "secondary")
            self.command_broadcast_button.setText("广播发送")
            self.command_send_button = QToolButton()
            self.command_send_button.setObjectName("commandActionButton")
            self.command_send_button.setProperty("buttonRole", "primary")
            self.command_send_button.setText("发送到终端")
            self.command_clear_button = QToolButton()
            self.command_clear_button.setObjectName("commandActionButton")
            self.command_clear_button.setProperty("buttonRole", "danger")
            self.command_clear_button.setText("清除")
            footer_layout.addWidget(self.command_broadcast_button)
            footer_layout.addWidget(self.command_send_button)
            footer_layout.addWidget(self.command_clear_button)
            layout.addWidget(footer)

            self.rebuild_command_record_tabs()
            self._load_current_command_content(move_cursor_to_end=False)
            self.apply_command_record_panel_state()
            return frame

        def _section_label(self, text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("sectionTitle")
            return label

        def _new_table(self, headers: list[str]) -> QTableWidget:
            table_class = VirtualDeviceTable if len(headers) == 6 else CopyableDeviceTable
            table = table_class(
                self.copy_selected_table_row,
                self.copy_selected_device_field,
                self,
            )
            table.setColumnCount(len(headers))
            table.setObjectName("deviceTable")
            table.setHorizontalHeaderLabels(headers)
            table.setSelectionBehavior(QTableWidget.SelectRows)
            table.setSelectionMode(QTableWidget.SingleSelection)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setAlternatingRowColors(False)
            table.setShowGrid(False)
            table.setWordWrap(False)
            table.setMouseTracking(True)
            table.verticalHeader().setVisible(False)
            table.verticalHeader().setDefaultSectionSize(32)
            header = table.horizontalHeader()
            header.setFixedHeight(28)
            header.setStretchLastSection(False)
            header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.setHighlightSections(False)
            header.setSectionsClickable(False)
            if len(headers) == 6:
                header.setSectionResizeMode(0, QHeaderView.Interactive)
                header.setSectionResizeMode(1, QHeaderView.Interactive)
                header.setSectionResizeMode(2, QHeaderView.Interactive)
                header.setSectionResizeMode(3, QHeaderView.Interactive)
                header.setSectionResizeMode(4, QHeaderView.Interactive)
                header.setSectionResizeMode(5, QHeaderView.Interactive)
                header.setStretchLastSection(False)
                header.setMinimumSectionSize(20)
                table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                table.set_stretch_column(1)
                table.setColumnWidth(0, 92)
                table.setColumnWidth(1, 200)
                table.setColumnWidth(2, 118)
                table.setColumnWidth(3, 86)
                table.setColumnWidth(4, 72)
                table.setColumnWidth(5, 106)
                if hasattr(table, "set_fill_column"):
                    table.set_fill_column(5)
            elif len(headers) == 5:
                header.setSectionResizeMode(0, QHeaderView.Interactive)
                header.setSectionResizeMode(1, QHeaderView.Stretch)
                for column in range(2, len(headers)):
                    header.setSectionResizeMode(column, QHeaderView.Interactive)
            else:
                header.setSectionResizeMode(0, QHeaderView.Stretch)
                for column in range(1, len(headers)):
                    header.setSectionResizeMode(column, QHeaderView.Stretch)
            if len(headers) == 5:
                table.setColumnWidth(0, 44)
                table.setColumnWidth(2, 86)
                table.setColumnWidth(3, 66)
                table.setColumnWidth(4, 72)
            elif len(headers) == 4:
                table.setColumnWidth(1, 96)
                table.setColumnWidth(2, 78)
                table.setColumnWidth(3, 74)
            return table

        def _new_stat_chip(self) -> QLabel:
            label = QLabel("-")
            label.setObjectName("statChip")
            label.setTextFormat(Qt.RichText)
            label.setWordWrap(True)
            return label

        def _new_terminal(self) -> QPlainTextEdit:
            terminal = QPlainTextEdit()
            terminal.setObjectName("terminalLog")
            terminal.setReadOnly(True)
            return terminal

        def _wire_events(self) -> None:
            self.search_input.textChanged.connect(self.sync_left_search)
            self.domain_combo.currentTextChanged.connect(self.apply_filters)
            self.status_combo.currentTextChanged.connect(self.apply_filters)
            self.cpu_input.textChanged.connect(self.schedule_apply_filters)
            self.my_occupancy_filter_button.toggled.connect(self.set_my_occupancy_filter)

            self.toolbar_refresh_button.clicked.connect(self.refresh_snapshot)
            self.temporary_save_button.clicked.connect(self.add_and_open_temporary_device)
            self.temporary_clear_button.clicked.connect(self.clear_temporary_form)
            self.wire_transfer_events()
            self.wire_package_upgrade_events()
            self.wire_ai_device_events()
            self.clear_filters_button.clicked.connect(self.clear_filters)
            if hasattr(self, "device_navigation_web"):
                self.device_navigation_web.device_selected.connect(self.activate_device)
                self.device_navigation_web.device_connect_requested.connect(self.open_navigation_device_session)
                self.device_navigation_web.session_selected.connect(self.jump_to_session)
                self.device_navigation_web.session_close_requested.connect(self.close_session_tab)
                self.device_navigation_web.session_close_others_requested.connect(self.close_other_session_tabs)
                self.device_navigation_web.session_close_all_requested.connect(self.close_all_session_tabs)
                self.device_navigation_web.session_context_requested.connect(
                    self.show_web_session_context_menu
                )
                self.device_navigation_web.home_requested.connect(self.show_web_home)
                self.device_navigation_web.filters_changed.connect(self.apply_web_device_filters)
                self.device_navigation_web.refresh_requested.connect(self.refresh_snapshot)
                self.device_navigation_web.clear_requested.connect(self.clear_filters)
                self.device_navigation_web.device_context_requested.connect(
                    self.show_web_device_context_menu
                )
                self.device_navigation_web.navigation_state_changed.connect(
                    self.apply_terminal_navigation_state
                )
            if hasattr(self, "web_shell"):
                self.web_shell.device_selected.connect(self.activate_device)
                self.web_shell.session_selected.connect(self.jump_to_session)
                self.web_shell.filters_changed.connect(self.apply_web_device_filters)
                self.web_shell.action_requested.connect(self.handle_web_shell_action)
                self.web_shell.refresh_requested.connect(self.refresh_snapshot)
                self.web_shell.clear_requested.connect(self.clear_filters)
                self.web_shell.device_context_requested.connect(self.show_web_device_context_menu)
                self.web_shell.session_context_requested.connect(self.show_web_session_context_menu)

            self.device_table.itemSelectionChanged.connect(self.handle_device_table_selected)
            self.device_table.verticalScrollBar().valueChanged.connect(self.schedule_render_visible_device_table_rows)
            self.device_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.device_table.customContextMenuRequested.connect(self.show_device_table_context_menu)
            if hasattr(self, "owned_table"):
                self.owned_table.itemSelectionChanged.connect(self.handle_owned_table_selected)
                self.owned_table.verticalScrollBar().valueChanged.connect(self.schedule_render_visible_owned_table_rows)
                self.owned_table.setContextMenuPolicy(Qt.CustomContextMenu)
                self.owned_table.customContextMenuRequested.connect(self.show_device_table_context_menu)

            self.connection_telnet_button.clicked.connect(self.open_selected_device_session)
            self.connection_ssh_button.clicked.connect(self.open_selected_linux_session)
            self.connection_serial_button.clicked.connect(self.open_selected_serial_session)
            self.quick_reconnect_button.clicked.connect(self.reconnect_current_session)
            self.quick_auto_response_menu.aboutToShow.connect(self.refresh_quick_auto_response_menu)
            self.quick_log_new_action.triggered.connect(self.create_current_session_log)
            self.quick_log_open_action.triggered.connect(self.open_current_session_log)
            self.quick_log_directory_action.triggered.connect(self.open_log_directory)
            self.quick_log_change_directory_action.triggered.connect(self.change_log_directory)
            self.quick_log_rotate_size_action.triggered.connect(self.change_log_rotate_size)
            self.quick_disconnect_button.clicked.connect(self.disconnect_current_session)
            self.quick_close_current_action.triggered.connect(self.close_current_session)
            self.quick_close_other_action.triggered.connect(self.close_other_current_session_tabs)
            self.quick_close_all_action.triggered.connect(self.close_all_session_tabs)
            self.session_quick_bar_toggle_button.clicked.connect(self.toggle_session_quick_bar)
            self.session_quick_restore_button.clicked.connect(
                lambda _checked=False: self.set_session_quick_bar_collapsed(False)
            )
            self.always_on_top_button.toggled.connect(self.toggle_always_on_top)
            self.session_jump_combo.activated.connect(self.handle_session_jump_activated)
            self.command_send_button.clicked.connect(self.submit_current_command_record)
            self.command_broadcast_button.clicked.connect(self.broadcast_command_record_input)
            self.command_clear_button.clicked.connect(self.clear_current_command_record)
            self.command_find_input.returnPressed.connect(self.find_next_command_record_match)
            self.command_find_input.textChanged.connect(self.update_command_find_count)
            self.command_replace_input.returnPressed.connect(self.replace_current_command_record_match)
            self.command_find_next_button.clicked.connect(self.find_next_command_record_match)
            self.command_replace_button.clicked.connect(self.replace_current_command_record_match)
            self.command_replace_all_button.clicked.connect(self.replace_all_command_record_matches)
            self.command_find_close_button.clicked.connect(self.hide_command_find_replace)
            self.command_enter_mode_button.clicked.connect(self.toggle_command_enter_mode)
            self.command_record_toggle_button.clicked.connect(self.toggle_command_record_panel)
            self.connection_params_toggle_button.clicked.connect(self.toggle_connection_params)
            self.device_navigation_toggle_button.clicked.connect(self.toggle_left_sidebar)

            self.session_tab_widget.currentChanged.connect(self.handle_session_tab_changed)
            self.session_tab_widget.tabCloseRequested.connect(self.close_device_tab_at_index)
            if QShortcut is not None:
                self.command_find_shortcut = QShortcut(QKeySequence.Find, self)
                self.command_find_shortcut.setContext(Qt.ApplicationShortcut)
                self.command_find_shortcut.activated.connect(self.toggle_command_find_replace)
                self.command_find_escape_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self.command_find_replace_bar)
                self.command_find_escape_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                self.command_find_escape_shortcut.activated.connect(self.hide_command_find_replace)

        def sync_left_search(self, value: str) -> None:
            del value
            self.schedule_apply_filters()

        def schedule_apply_filters(self) -> None:
            self.filter_timer.start()

        def clear_filters(self) -> None:
            self.search_input.clear()
            self.domain_combo.setCurrentText(ALL_DOMAINS)
            self.status_combo.setCurrentText(ALL_STATUS)
            self.cpu_input.clear()
            self.my_occupancy_filter_enabled = False
            self.my_occupancy_filter_button.blockSignals(True)
            self.my_occupancy_filter_button.setChecked(False)
            self.my_occupancy_filter_button.blockSignals(False)
            self.apply_filters()

        def set_my_occupancy_filter(self, enabled: bool) -> None:
            self.my_occupancy_filter_enabled = enabled
            self.apply_filters()

        def apply_web_device_filters(self, filters: dict[str, object]) -> None:
            self.search_input.blockSignals(True)
            self.domain_combo.blockSignals(True)
            self.status_combo.blockSignals(True)
            self.cpu_input.blockSignals(True)
            self.my_occupancy_filter_button.blockSignals(True)
            try:
                self.search_input.setText(str(filters.get("search") or ""))
                domain = str(filters.get("domain") or ALL_DOMAINS)
                self.domain_combo.setCurrentText(domain if self.domain_combo.findText(domain) >= 0 else ALL_DOMAINS)
                status = str(filters.get("status") or ALL_STATUS)
                self.status_combo.setCurrentText(status if self.status_combo.findText(status) >= 0 else ALL_STATUS)
                self.cpu_input.setText(str(filters.get("cpu") or ""))
                self.my_occupancy_filter_enabled = bool(filters.get("mine"))
                self.my_occupancy_filter_button.setChecked(self.my_occupancy_filter_enabled)
            finally:
                self.search_input.blockSignals(False)
                self.domain_combo.blockSignals(False)
                self.status_combo.blockSignals(False)
                self.cpu_input.blockSignals(False)
                self.my_occupancy_filter_button.blockSignals(False)
            self.apply_filters()

        def apply_terminal_navigation_state(self, state: dict[str, object]) -> None:
            tab = str(state.get("activeTab") or "").strip().lower()
            if tab in {"sessions", "devices"}:
                self.terminal_navigation_active_tab = tab
            query = str(state.get("deviceQuery") or "")
            if len(query) <= 120:
                self.terminal_navigation_device_query = query
            expanded_device_id = str(state.get("expandedDeviceId") or "")
            self.terminal_navigation_expanded_device_id = expanded_device_id
            self.schedule_desktop_state_save()

        def handle_web_shell_action(self, action: str) -> None:
            if action == "sessions":
                self.show_terminal_workspace()
                return
            if action == "telnet":
                self.open_selected_device_session()
                return
            if action == "ssh":
                self.open_selected_linux_session()
                return
            if action == "serial":
                self.open_selected_serial_session()
                return
            if action == "occupancy":
                self.toggle_occupancy()

        def toggle_always_on_top(self, enabled: bool) -> None:
            self.always_on_top = enabled
            self.apply_always_on_top_state()
            self.schedule_desktop_state_save()
            self.set_status_message("窗口已置顶" if enabled else "窗口已取消置顶")

        def apply_always_on_top_state(self) -> None:
            was_visible = self.isVisible()
            was_maximized = self.isMaximized()
            was_fullscreen = self.isFullScreen()
            native_applied = self._apply_native_always_on_top()
            if not native_applied:
                self.setWindowFlag(Qt.WindowStaysOnTopHint, self.always_on_top)
            if hasattr(self, "always_on_top_button"):
                self.always_on_top_button.blockSignals(True)
                self.always_on_top_button.setChecked(self.always_on_top)
                self.always_on_top_button.setToolTip(
                    "取消窗口置顶" if self.always_on_top else "窗口置顶"
                )
                self.always_on_top_button.blockSignals(False)
            if was_visible and not native_applied:
                if was_fullscreen:
                    self.showFullScreen()
                elif was_maximized:
                    self.showMaximized()
                else:
                    self.show()
                if self.always_on_top:
                    self.raise_()
                    self.activateWindow()

        def _apply_native_always_on_top(self) -> bool:
            if os.name != "nt":
                return False
            try:
                import ctypes
                from ctypes import wintypes

                hwnd = wintypes.HWND(int(self.winId()))
                insert_after = wintypes.HWND(-1 if self.always_on_top else -2)
                flags = 0x0001 | 0x0002 | 0x0010 | 0x0200  # NOSIZE | NOMOVE | NOACTIVATE | NOOWNERZORDER
                result = ctypes.windll.user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags)
            except (AttributeError, OSError, TypeError, ValueError):
                return False
            return bool(result)

        def toggle_connection_params(self) -> None:
            self.connection_params_collapsed = not self.connection_params_collapsed
            self.apply_connection_params_state()
            self.schedule_desktop_state_save()

        def expand_connection_params(self) -> None:
            if not self.connection_params_collapsed:
                return
            self.connection_params_collapsed = False
            self.apply_connection_params_state()
            self.schedule_desktop_state_save()

        def toggle_device_navigation(self) -> None:
            self.device_navigation_collapsed = not self.device_navigation_collapsed
            self.apply_device_navigation_state()
            self.schedule_desktop_state_save()

        def apply_device_navigation_state(self) -> None:
            if not hasattr(self, "device_navigation_body"):
                return
            collapsed = self.device_navigation_collapsed
            self.device_navigation_body.setVisible(not collapsed)
            self.device_navigation_toggle_button.setText("显示导航" if collapsed else "隐藏导航")
            self.device_navigation_toggle_button.setToolTip(
                "显示设备列表和筛选" if collapsed else "隐藏设备列表和筛选"
            )

        def toggle_left_sidebar(self) -> None:
            if not self.left_sidebar_collapsed:
                self.remember_current_left_sidebar_width()
            self.left_sidebar_collapsed = not self.left_sidebar_collapsed
            if (
                getattr(self, "left_sidebar_active_panel", "devices") == "devices"
                and getattr(self, "center_stage_mode", "home") != "home"
            ):
                self.terminal_sidebar_collapsed = self.left_sidebar_collapsed
            self.apply_left_sidebar_state()
            self.schedule_desktop_state_save()

        def handle_main_splitter_moved(self, pos: int, index: int) -> None:
            # Only the LEFT sidebar boundary (handle index 1) drives the
            # collapse hint / density pause. The right session-manager
            # boundary is handle index 2 and is handled by session_layout_ops.
            if int(index) != 1:
                return
            if getattr(self, "left_sidebar_programmatic_resize", False):
                return
            if not getattr(self, "left_sidebar_user_dragging", False):
                return
            collapse_hint = int(pos) <= self.TERMINAL_SIDEBAR_COLLAPSE_THRESHOLD
            splitter = getattr(self, "main_splitter", None)
            if splitter is not None and hasattr(splitter, "set_collapse_hint"):
                splitter.set_collapse_hint(collapse_hint)
            table = getattr(self, "device_table", None)
            if table is not None and hasattr(table, "set_density_adaptation_paused"):
                table.set_density_adaptation_paused(collapse_hint)
                if not collapse_hint and hasattr(table, "schedule_column_adapt"):
                    table.schedule_column_adapt()

        def handle_main_splitter_drag_started(self, handle_index: int = 1) -> None:
            # Only left-boundary (handle index 1) drags are the left-sidebar
            # drag lifecycle; right-boundary drags belong to session_layout_ops.
            if int(handle_index) != 1:
                return
            if getattr(self, "left_sidebar_collapsed", False):
                return
            self.left_sidebar_user_dragging = True
            shell = getattr(self, "left_sidebar_shell", None)
            if shell is not None:
                shell.setMinimumWidth(self.ACTIVITY_RAIL_WIDTH)
                shell.setMaximumWidth(self.SIDEBAR_UNBOUNDED_MAX_WIDTH)
                shell.updateGeometry()
            content = getattr(self, "left_sidebar_content", None)
            if content is not None:
                content.setMinimumWidth(0)

        def handle_main_splitter_drag_finished(
            self, released_width: int, handle_index: int = 1
        ) -> None:
            if int(handle_index) != 1:
                return
            if not getattr(self, "left_sidebar_user_dragging", False):
                return
            self.left_sidebar_user_dragging = False
            splitter = getattr(self, "main_splitter", None)
            if splitter is not None and hasattr(splitter, "set_collapse_hint"):
                splitter.set_collapse_hint(False)
            table = getattr(self, "device_table", None)
            if table is not None and hasattr(table, "set_density_adaptation_paused"):
                table.set_density_adaptation_paused(False)

            width = int(released_width)
            if width <= self.TERMINAL_SIDEBAR_COLLAPSE_THRESHOLD:
                self.left_sidebar_collapsed = True
                if getattr(self, "left_sidebar_active_panel", "devices") == "devices":
                    self.terminal_sidebar_collapsed = True
            else:
                self.left_sidebar_collapsed = False
                snapped_width = max(self.TERMINAL_SIDEBAR_MIN_WIDTH, width)
                self.terminal_sidebar_width = self.clamp_left_sidebar_open_width(snapped_width)
                if getattr(self, "left_sidebar_active_panel", "devices") == "devices":
                    self.terminal_sidebar_collapsed = False
            self.apply_left_sidebar_state()
            self.schedule_desktop_state_save()

        def clamp_left_sidebar_open_width(self, width: int) -> int:
            return max(self.TERMINAL_SIDEBAR_MIN_WIDTH, int(width))

        def remember_current_left_sidebar_width(self) -> None:
            if getattr(self, "left_sidebar_collapsed", False):
                return
            splitter = getattr(self, "main_splitter", None)
            if splitter is None:
                return
            sizes = splitter.sizes()
            if not sizes:
                return
            width = int(sizes[0])
            if width >= self.TERMINAL_SIDEBAR_MIN_WIDTH:
                self.terminal_sidebar_width = self.clamp_left_sidebar_open_width(width)

        def set_main_splitter_width(self, width: int) -> None:
            splitter = getattr(self, "main_splitter", None)
            if splitter is None:
                return
            sizes = splitter.sizes()
            total = sum(sizes) if len(sizes) >= 2 else splitter.width()
            if total <= 0:
                return
            target = max(self.ACTIVITY_RAIL_WIDTH, min(int(width), total - 1))
            self.left_sidebar_programmatic_resize = True
            try:
                if len(sizes) >= 3 and self._session_manager_panel_active():
                    # Preserve the right session-manager width; sizing it with
                    # only two entries would let Qt snap the panel to its
                    # minimum and discard the user's dragged/persisted width.
                    right = self.session_manager_splitter_width(total - target)
                    splitter.setSizes([target, max(1, total - target - right), right])
                else:
                    splitter.setSizes([target, max(1, total - target)])
            finally:
                self.left_sidebar_programmatic_resize = False

        def clamp_current_left_sidebar_width(self) -> None:
            if (
                getattr(self, "left_sidebar_collapsed", False)
                or getattr(self, "left_sidebar_user_dragging", False)
                or getattr(self, "left_sidebar_programmatic_resize", False)
            ):
                return
            splitter = getattr(self, "main_splitter", None)
            if splitter is None:
                return
            sizes = splitter.sizes()
            if not sizes:
                return
            current = int(sizes[0])
            preferred = int(
                getattr(self, "terminal_sidebar_width", self.TERMINAL_SIDEBAR_WIDTH)
            )
            clamped = self.clamp_left_sidebar_open_width(preferred)
            shell = getattr(self, "left_sidebar_shell", None)
            if shell is not None:
                shell.setMaximumWidth(self.SIDEBAR_UNBOUNDED_MAX_WIDTH)
            if current != clamped:
                self.set_main_splitter_width(clamped)

        def resizeEvent(self, event: Any) -> None:  # noqa: N802
            super().resizeEvent(event)
            if hasattr(self, "main_splitter"):
                QTimer.singleShot(0, self.clamp_current_left_sidebar_width)

        def open_navigation_device_session(self, device_id: str, kind: str) -> None:
            self.activate_device(device_id)
            normalized = kind.strip().lower()
            if normalized == "ssh":
                self.open_selected_linux_session()
            elif normalized == "serial":
                self.open_selected_serial_session()
            else:
                self.open_selected_device_session()

        def toggle_device_sidebar_panel(self) -> None:
            if not self.left_sidebar_collapsed and self.left_sidebar_active_panel == "devices":
                self.remember_current_left_sidebar_width()
                self.left_sidebar_collapsed = True
                self.terminal_sidebar_collapsed = True
                self.apply_left_sidebar_state()
                self.schedule_desktop_state_save()
                return
            self.show_left_sidebar_panel("devices")

        def activate_terminal_workspace(self) -> None:
            if self.session_tab_widget.count() <= 0:
                return
            self.left_sidebar_active_panel = "devices"
            self.show_terminal_workspace()

        def toggle_tool_sidebar_panel(self, panel: str) -> None:
            if panel not in {"temporary", "server", "transfer", "package_upgrade", "ai_device"}:
                return
            if self.left_sidebar_active_panel == panel and not self.left_sidebar_collapsed:
                self.remember_current_left_sidebar_width()
                self.left_sidebar_collapsed = True
                self.apply_left_sidebar_state()
                self.schedule_desktop_state_save()
                return
            self.show_left_sidebar_panel(panel)

        def show_left_sidebar_panel(self, panel: str) -> None:
            if panel not in {"devices", "temporary", "server", "transfer", "package_upgrade", "ai_device"}:
                panel = "devices"
            self.left_sidebar_active_panel = panel
            if hasattr(self, "left_sidebar_stack"):
                panel_index = {
                    "devices": 0,
                    "temporary": 1,
                    "server": 2,
                    "transfer": 3,
                    "package_upgrade": 4,
                    "ai_device": 5,
                }.get(panel, 0)
                self.left_sidebar_stack.setCurrentIndex(panel_index)
            if self.left_sidebar_collapsed:
                self.left_sidebar_collapsed = False
            if panel == "devices":
                self.terminal_sidebar_collapsed = False
            self.apply_left_sidebar_state()
            self.schedule_desktop_state_save()

        def apply_left_sidebar_state(self, *, animated: bool = False) -> None:
            del animated
            if not hasattr(self, "left_sidebar_content"):
                return
            collapsed = self.left_sidebar_collapsed
            is_device_panel = getattr(self, "left_sidebar_active_panel", "devices") == "devices"
            expanded = (
                bool(getattr(self, "left_device_workspace_expanded", False))
                and is_device_panel
                and not collapsed
            )
            compact = (
                bool(getattr(self, "left_sidebar_compact", False))
                and is_device_panel
                and not expanded
                and not collapsed
            )
            if hasattr(self, "device_navigation_header"):
                self.device_navigation_header.setVisible(not compact and not collapsed)
            if hasattr(self, "device_context_panel"):
                self.device_context_panel.setVisible(expanded)
            if hasattr(self, "search_input"):
                self.search_input.setVisible(expanded)
            if hasattr(self, "device_filter_frame"):
                self.device_filter_frame.setVisible(expanded)
            if hasattr(self, "device_stats_frame"):
                self.device_stats_frame.setVisible(expanded)
            if hasattr(self, "device_table"):
                self.device_table.setVisible(expanded)
                self.device_table.setMinimumHeight(360 if expanded else 260)
                self.device_table.setMaximumHeight(760 if expanded else 340)
                if hasattr(self.device_table, "set_responsive_density_enabled"):
                    self.device_table.set_responsive_density_enabled(expanded)
                if hasattr(self.device_table, "set_density_adaptation_paused"):
                    self.device_table.set_density_adaptation_paused(collapsed)
            if hasattr(self, "device_navigation_web"):
                navigation_visible = not expanded and not collapsed
                self.device_navigation_web.setVisible(navigation_visible)
                if navigation_visible and hasattr(self, "refresh_device_navigation_web"):
                    self.refresh_device_navigation_web()
            if hasattr(self, "device_navigation_resize_handle"):
                self.device_navigation_resize_handle.setVisible(not expanded and not collapsed)
            if hasattr(self, "device_navigation_toggle_button"):
                self.device_navigation_toggle_button.setText("隐藏左侧")
                self.device_navigation_toggle_button.setToolTip("收起终端设备导航，扩大终端区域")
            if self.left_sidebar_animation is not None:
                self.left_sidebar_animation.stop()
                self.left_sidebar_animation = None
            target_width = (
                self.ACTIVITY_RAIL_WIDTH
                if collapsed
                else self.clamp_left_sidebar_open_width(
                    int(getattr(self, "terminal_sidebar_width", self.TERMINAL_SIDEBAR_WIDTH))
                )
            )
            self.left_sidebar_content.setVisible(not collapsed)
            self.left_sidebar_content.setMinimumWidth(0)
            self.left_sidebar_content.setMaximumWidth(
                0 if collapsed else self.SIDEBAR_UNBOUNDED_MAX_WIDTH
            )
            if hasattr(self, "left_sidebar_layout"):
                self.left_sidebar_layout.setContentsMargins(0, 0, 0 if collapsed else 4, 0)
                self.left_sidebar_layout.setSpacing(0 if collapsed else 6)
            if hasattr(self, "left_sidebar_shell"):
                self.left_sidebar_shell.setMinimumWidth(
                    self.ACTIVITY_RAIL_WIDTH if collapsed else self.TERMINAL_SIDEBAR_MIN_WIDTH
                )
                self.left_sidebar_shell.setMaximumWidth(
                    self.ACTIVITY_RAIL_WIDTH
                    if collapsed
                    else self.SIDEBAR_UNBOUNDED_MAX_WIDTH
                )
                self.left_sidebar_shell.updateGeometry()
            self.set_main_splitter_width(target_width)
            if hasattr(self, "left_sidebar_stack"):
                panel_index = {
                    "devices": 0,
                    "temporary": 1,
                    "server": 2,
                    "transfer": 3,
                    "package_upgrade": 4,
                    "ai_device": 5,
                }.get(self.left_sidebar_active_panel, 0)
                self.left_sidebar_stack.setCurrentIndex(panel_index)
            self.sync_activity_rail_state()

        def sync_activity_rail_state(self) -> None:
            if not hasattr(self, "activity_home_button"):
                return
            show_home = getattr(self, "center_stage_mode", "home") == "home"
            has_sessions = hasattr(self, "session_tab_widget") and self.session_tab_widget.count() > 0
            panel = getattr(self, "left_sidebar_active_panel", "devices")
            drawer_open = not self.left_sidebar_collapsed and panel in {
                "temporary",
                "server",
                "transfer",
                "package_upgrade",
                "ai_device",
            }
            states = (
                (self.activity_home_button, "home", "首页大屏", show_home and not drawer_open),
                (
                    self.activity_temporary_button,
                    "connector",
                    "临时连接",
                    drawer_open and panel == "temporary",
                ),
                (
                    self.activity_server_button,
                    "server",
                    "我的服务器",
                    drawer_open and panel == "server",
                ),
                (
                    self.activity_transfer_button,
                    "transfer",
                    "文件传输",
                    drawer_open and panel == "transfer",
                ),
                (
                    self.activity_package_upgrade_button,
                    "upgrade",
                    "自动换大包",
                    drawer_open and panel == "package_upgrade",
                ),
                (
                    self.activity_ai_device_button,
                    "ai",
                    "AI 设备助手",
                    drawer_open and panel == "ai_device",
                ),
            )
            for button, icon_name, tooltip, active in states:
                button.setChecked(active)
                button.setToolTip(tooltip)
                button.setIcon(self._activity_icon(icon_name, "#f8fafc" if active else "#718096"))

        def animate_left_sidebar_state(self, collapsed: bool) -> None:
            self.left_sidebar_collapsed = bool(collapsed)
            self.apply_left_sidebar_state()

        def resize_session_jump_combo(self, width: int) -> None:
            if not hasattr(self, "session_jump_combo"):
                return
            target = max(180, min(520, int(width)))
            self.session_jump_combo_width = target
            self.session_jump_combo.setFixedWidth(target)
            self.session_jump_combo.updateGeometry()

        def clamp_terminal_navigation_web_height(self, height: int) -> int:
            return max(
                self.TERMINAL_NAVIGATION_WEB_MIN_HEIGHT,
                min(self.TERMINAL_NAVIGATION_WEB_MAX_HEIGHT, int(height)),
            )

        def resize_terminal_navigation_web(self, height: int) -> None:
            self.terminal_navigation_web_height = self.clamp_terminal_navigation_web_height(height)
            self.apply_terminal_navigation_web_height()
            self.schedule_desktop_state_save()

        def apply_terminal_navigation_web_height(self) -> None:
            web_nav = getattr(self, "device_navigation_web", None)
            if web_nav is None:
                return
            height = self.clamp_terminal_navigation_web_height(
                getattr(
                    self,
                    "terminal_navigation_web_height",
                    self.TERMINAL_NAVIGATION_WEB_DEFAULT_HEIGHT,
                )
            )
            self.terminal_navigation_web_height = height
            web_nav.setMinimumHeight(height)
            web_nav.setMaximumHeight(height)
            web_nav.updateGeometry()

        def toggle_session_quick_bar(self) -> None:
            self.session_quick_bar_collapsed = not self.session_quick_bar_collapsed
            self.apply_session_quick_bar_state()

        def set_session_quick_bar_collapsed(self, collapsed: bool) -> None:
            self.session_quick_bar_collapsed = collapsed
            self.apply_session_quick_bar_state()

        def apply_session_quick_bar_state(self) -> None:
            if not hasattr(self, "session_quick_action_bar"):
                return
            has_sessions = hasattr(self, "session_tab_widget") and self.session_tab_widget.count() > 0
            should_show = has_sessions
            collapsed = bool(getattr(self, "session_quick_bar_collapsed", False))
            self.session_quick_action_bar.setVisible(should_show and not collapsed)
            if hasattr(self, "session_quick_restore_bar"):
                self.session_quick_restore_bar.setVisible(should_show and collapsed)
            if hasattr(self, "session_quick_bar_toggle_button"):
                self.session_quick_bar_toggle_button.setToolTip("隐藏会话工具栏")

        def apply_connection_params_state(self) -> None:
            if not hasattr(self, "connection_params_body"):
                return
            collapsed = self.connection_params_collapsed
            self.connection_params_body.setVisible(not collapsed)
            self.connection_params_toggle_button.setText("展开" if collapsed else "收起")
            if hasattr(self, "connection_params_group"):
                self.connection_params_group.setMinimumHeight(0)
                self.connection_params_group.setMaximumHeight(16777215)
                self.connection_params_group.updateGeometry()

        def apply_command_record_panel_state(self, focus_editor: bool = False) -> None:
            collapsed = self.command_record_collapsed
            self.command_record_resize_handle.setVisible(not collapsed)
            self.command_record_input.setVisible(not collapsed)
            self.command_find_replace_bar.setVisible(not collapsed and self.command_find_replace_visible)
            if not collapsed and self.command_find_replace_visible:
                bar_width = min(420, max(320, self.command_record_frame.width() - 28))
                self.command_find_replace_bar.setFixedWidth(bar_width)
                self.command_find_replace_bar.move(
                    max(8, self.command_record_frame.width() - bar_width - 14),
                    self.command_record_resize_handle.height() + 28,
                )
                self.command_find_replace_bar.raise_()
            self.command_record_footer.setVisible(not collapsed)
            self.command_enter_mode_button.setVisible(not collapsed)
            target_height = (
                self.COMMAND_RECORD_COLLAPSED_HEIGHT
                if collapsed
                else self.clamp_command_record_height(self.command_record_height)
            )
            self.command_record_frame.setMinimumHeight(target_height)
            self.command_record_frame.setMaximumHeight(target_height)
            self.command_record_frame.updateGeometry()
            self.command_record_toggle_button.setText("展开" if collapsed else "收起")
            self.update_command_enter_mode()
            if collapsed:
                self.set_status_message("常用命令区域已隐藏。")
            else:
                self._load_current_command_content(move_cursor_to_end=False)
                if focus_editor:
                    self.command_record_input.setFocus()

        def dispatch_ui(self, callback: Callable[..., None], *args: object) -> None:
            self.ui_queue.put((callback, args))

        def call_on_ui_thread(
            self,
            callback: Callable[[], object],
            *,
            timeout: float = 10.0,
        ) -> object:
            if threading.get_ident() == self.ui_thread_ident:
                return callback()
            if self.closed:
                raise RuntimeError("Device TUI 正在关闭。")
            result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)
            cancelled = threading.Event()

            def execute() -> None:
                if cancelled.is_set():
                    return
                try:
                    result_queue.put((True, callback()))
                except Exception as exc:
                    result_queue.put((False, exc))

            self.dispatch_ui(execute)
            try:
                ok, value = result_queue.get(timeout=timeout)
            except queue.Empty as exc:
                cancelled.set()
                raise TimeoutError("Qt UI thread call timed out") from exc
            if not ok:
                assert isinstance(value, Exception)
                raise value
            return value

        def _drain_ui_queue(self) -> None:
            processed = 0
            deadline = time.monotonic() + 0.012
            while processed < 48 and time.monotonic() < deadline:
                try:
                    callback, args = self.ui_queue.get_nowait()
                except queue.Empty:
                    break
                callback(*args)
                processed += 1

        def run_blocking(
            self,
            work: Callable[[], object],
            on_success: Callable[[object], None] | None = None,
            on_error: Callable[[Exception], None] | None = None,
        ) -> None:
            def task() -> None:
                try:
                    result = work()
                except Exception as exc:
                    self.dispatch_ui(on_error or self.handle_background_error, exc)
                    return
                if on_success is not None:
                    self.dispatch_ui(on_success, result)

            threading.Thread(target=task, daemon=True, name="device-tui-blocking").start()

        def run_coro(
            self,
            coro: Coroutine[Any, Any, Any],
            on_success: Callable[[object], None] | None = None,
            on_error: Callable[[Exception], None] | None = None,
        ) -> None:
            future = self.async_loop.submit(coro)
            self.pending_futures.add(future)

            def done(completed: Future) -> None:
                self.pending_futures.discard(completed)
                try:
                    result = completed.result()
                except FutureCancelledError:
                    return
                except Exception as exc:
                    if self.closed:
                        return
                    self.dispatch_ui(on_error or self.handle_background_error, exc)
                    return
                if on_success is not None and not self.closed:
                    self.dispatch_ui(on_success, result)

            future.add_done_callback(done)

        def cancel_pending_futures(self) -> None:
            for future in list(self.pending_futures):
                future.cancel()
            self.pending_futures.clear()

        def update_controls(self) -> None:
            device = self.get_quick_action_device()
            selected = device is not None
            state = self.current_session_state()
            simulated_selected = self.is_simulated_device(device)
            saved_server_selected = self.is_saved_server_device(device)
            self.connection_telnet_button.setEnabled(selected and not saved_server_selected)
            self.connection_telnet_button.setText("连接 Telnet")
            self.connection_ssh_button.setEnabled(selected and not simulated_selected)
            self.connection_serial_button.setEnabled(
                selected
                and not simulated_selected
                and not saved_server_selected
                and not self.is_temporary_device(device)
            )
            self.quick_reconnect_button.setEnabled(state is not None and not state.connecting)
            self.quick_auto_response_button.setEnabled(True)
            self.quick_log_button.setEnabled(True)
            self.quick_log_new_action.setEnabled(state is not None)
            self.quick_log_open_action.setEnabled(state is not None)
            self.quick_disconnect_button.setEnabled(
                state is not None and (state.session.is_connected or state.connecting)
            )
            session_count = len(self.ordered_session_states()) if hasattr(self, "ordered_session_states") else 0
            self.quick_close_button.setEnabled(session_count > 0)
            self.quick_close_current_action.setEnabled(state is not None)
            self.quick_close_other_action.setEnabled(state is not None and session_count > 1)
            self.quick_close_all_action.setEnabled(session_count > 0)
            self.update_center_stage_state()

        def refresh_current_operation_label(
            self,
            device: Device | None,
            state: SessionTabState | None,
        ) -> None:
            if not hasattr(self, "current_operation_label"):
                return
            if device is None:
                self.current_operation_label.setText("当前操作：未选择")
                self.current_operation_label.setToolTip("")
                return
            if state is not None:
                text = f"当前操作：{device.name} / {state.title}"
                tip = f"右下角快捷动作将作用于当前终端页签：{device.name} - {state.title}"
            else:
                text = f"当前操作：{device.name}"
                tip = f"右下角快捷动作将作用于左侧选中设备：{device.name}"
            self.current_operation_label.setText(text)
            self.current_operation_label.setToolTip(tip)

        def set_status_message(self, message: str) -> None:
            if self.statusBar() is not None:
                self.statusBar().showMessage(message)

        def handle_background_error(self, exc: Exception) -> None:
            if isinstance(exc, RepositoryError):
                self.show_error(str(exc))
                self.set_status_message(f"数据加载失败: {exc}")
                self.update_controls()
                return
            self.show_error(f"未处理异常: {exc}")
            self.set_status_message(str(exc))
            self.update_controls()

        def show_warning(self, message: str) -> None:
            QMessageBox.warning(self, "设备工作台", message)

        def show_error(self, message: str) -> None:
            QMessageBox.critical(self, "设备工作台", message)

        def closeEvent(self, event: Any) -> None:  # noqa: N802
            if self.closed:
                event.accept()
                return

            self.stop_app_control_server()
            self.closed = True
            self.save_desktop_state()
            self.state_save_timer.stop()
            self.ui_timer.stop()
            self.refresh_timer.stop()
            self.log_flush_timer.stop()
            for state in self.session_tabs_by_id.values():
                self.write_session_log_line(state, "SYS", "Application closing")
                self.flush_session_log_state(state)

            self.cancel_pending_futures()
            self.async_loop.cancel_pending(timeout=2.0)
            if self.transfer_service is not None and self.transfer_service.is_running:
                self.transfer_service.stop()

            async def shutdown_sessions() -> None:
                await asyncio.gather(
                    *[state.session.disconnect("") for state in self.session_tabs_by_id.values()],
                    return_exceptions=True,
                )

            try:
                self.async_loop.submit(shutdown_sessions()).result(timeout=3.0)
            except Exception:
                pass
            self.async_loop.cancel_pending(timeout=1.0)
            self.async_loop.stop()
            event.accept()

else:

    class DeviceDesktopApp:  # pragma: no cover - simple placeholder when dependency is absent
        def __init__(self, repository: DeviceRepository | None = None) -> None:
            del repository
            raise RuntimeError("PySide6 is required to launch the desktop app.")


def main() -> None:
    if PYSIDE6_IMPORT_ERROR is not None:
        raise SystemExit(
            "PySide6 is not installed. Run `pip install -e .` or `pip install PySide6` and try again."
        )

    assert QApplication is not None
    app = QApplication.instance() or QApplication([])
    window = DeviceDesktopApp()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
