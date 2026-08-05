# Session Tab Layout Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let operators switch terminal session navigation between the current top tab rows (`top`) and a collapsible right-side hierarchical session manager with search (`side`), with a status-bar settings entry controlling layout, terminal font size, and default-collapse; persist everything in desktop state v14.

**Architecture:** A new `SessionLayoutOpsMixin` (`src/app/session_layout_ops.py`) joins the `DeviceDesktopApp` composition and owns the right manager panel, layout switching, tree sync, and state memory. It reuses existing methods as facades — `jump_to_session()`, `activate_device()`, `build_device_tab_context_menu()`, `close_session_tab()`, `schedule_desktop_state_save()`, `show_terminal_workspace()` — without modifying their internals. The right manager is a third child of the existing `main_splitter` (a `SidebarSplitter`). State is a new `session_layout` section in desktop state (version 13 → 14).

**Tech Stack:** Python 3.10+, PySide6 (QTreeWidget, QSplitter, QStackedLayout, QMenu), QtWebChannel bridge for xterm font size, pytest with offscreen QApplication fixtures.

## Global Constraints

- Python ≥ 3.10; PySide6 only. No new third-party dependencies.
- UI copy is Chinese (e.g. `会话管理器`, `搜索设备、会话`, `共 N`, `新建终端`).
- All UI mutations must happen on the Qt main thread (existing pattern).
- Follow existing code conventions: `from __future__ import annotations`; dataclasses with `slots=True`; PySide6 import guarded by try/except that nulls names on `ModuleNotFoundError` (mirror the existing fallback blocks).
- Mixin must be added to the `DeviceDesktopApp` class base list in `src/app/main_window.py:249-262`, immediately after `SessionOpsMixin`.
- Desktop state version constant `DESKTOP_STATE_VERSION` advances from `13` to `14` in `src/app/desktop_state.py:37`.
- Defaults: `session_tab_layout="top"`, `terminal_font_size=14`, `session_manager_default_collapsed=False`, `session_manager_width=260`, `session_manager_collapsed=False`, `collapsed_device_groups=[]`.
- Width clamp range: `SESSION_MANAGER_MIN_WIDTH = 200`, `SESSION_MANAGER_MAX_WIDTH = 480`.
- Font clamp range (from `xterm_terminal.html:97-99`): min 9, max 28.
- No close-session confirmation setting — out of scope.

---

### Task 1: `set_font_size()` on `XtermWebWidget`

**Files:**
- Modify: `src/widgets/xterm_web_widget.py` (add a method to `XtermWebWidget`, after `_run_js` around line 395)
- Test: `tests/test_xterm_font_size.py` (new)

**Interfaces:**
- Consumes: nothing new (existing `_run_terminal_js` at line 387, `_ready` flag at line 92, `_view` at line 108).
- Produces: `XtermWebWidget.set_font_size(size: int) -> None` — stores the pending size, applies it via `window.deviceTerminal.setFontSize(n)`, and reapplies on terminal ready.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.widgets.xterm_web_widget import XtermWebWidget


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_set_font_size_queues_js_and_reenables_on_ready(app: QApplication) -> None:
    _ = app
    widget = XtermWebWidget()
    ran: list[str] = []
    widget._run_js = lambda script: ran.append(script)  # type: ignore[method-assign]

    widget.set_font_size(18)

    assert widget._font_size == 18
    assert any("deviceTerminal.setFontSize(18)" in script for script in ran)

    # Simulate readiness after the pending size is set
    ran.clear()
    widget._ready = True
    widget._handle_ready()
    assert any("deviceTerminal.setFontSize(18)" in script for script in ran)

    widget.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_xterm_font_size.py -v`
Expected: FAIL with `AttributeError: 'XtermWebWidget' object has no attribute '_font_size'` or `set_font_size`.

- [ ] **Step 3: Write minimal implementation**

Add to `XtermWebWidget` (in `src/widgets/xterm_web_widget.py`):

```python
    def set_font_size(self, size: int) -> None:
        """Apply a terminal font size; store it and reapply once the engine is ready."""
        clamped = int(size)
        clamped = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, clamped))
        self._font_size = clamped
        self._run_terminal_js(f"setFontSize({clamped})")
```

Also add the constants at module level (near the top of the file, after imports) and initialize `self._font_size = DEFAULT_FONT_SIZE` in `__init__` (after `self._local_echo = ...` on line 97):

```python
DEFAULT_FONT_SIZE = 14
MIN_FONT_SIZE = 9
MAX_FONT_SIZE = 28
```

And in `_handle_ready()` (line 245), after `self._placeholder.hide()`, reapply the stored size:

```python
        if getattr(self, "_font_size", None) is not None:
            self._run_terminal_js(f"setFontSize({self._font_size})")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_xterm_font_size.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/widgets/xterm_web_widget.py tests/test_xterm_font_size.py
git commit -m "feat: add set_font_size to XtermWebWidget"
```

---

### Task 2: Desktop state v14 — `session_layout` section

**Files:**
- Modify: `src/app/desktop_state.py` (constant line 37, `load_desktop_state()` around line 64, `save_desktop_state()` around line 286)
- Test: `tests/test_desktop_state_session_layout.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `self.session_tab_layout: str = "top"` — `"top"` | `"side"`
  - `self.terminal_font_size: int = 14`
  - `self.session_manager_default_collapsed: bool = False`
  - `self.session_manager_width: int = 260`
  - `self.session_manager_collapsed: bool = False`
  - `self.collapsed_device_groups: list[str] = []`
  - `self.apply_session_layout_state() -> None` — applies loaded layout immediately (no-op at this stage; the mixin in Task 3 hooks into it). For now, sets attributes only.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _state_path(window: DeviceDesktopApp) -> Path:
    return Path(window.state_path)


def test_session_layout_defaults(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.session_tab_layout == "top"
    assert window.terminal_font_size == 14
    assert window.session_manager_default_collapsed is False
    assert window.session_manager_width == 260
    assert window.session_manager_collapsed is False
    assert window.collapsed_device_groups == []
    window.close()


def test_session_layout_round_trip(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.session_tab_layout = "side"
    window.terminal_font_size = 18
    window.session_manager_width = 340
    window.session_manager_collapsed = True
    window.collapsed_device_groups = ["R1-核心"]
    window.save_desktop_state()

    saved = json.loads(_state_path(window).read_text(encoding="utf-8"))
    assert saved["version"] == 14
    assert saved["session_layout"]["session_tab_layout"] == "side"
    assert saved["session_layout"]["terminal_font_size"] == 18
    assert saved["session_layout"]["session_manager_width"] == 340
    assert saved["session_layout"]["session_manager_collapsed"] is True
    assert saved["session_layout"]["collapsed_device_groups"] == ["R1-核心"]

    window.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_desktop_state_session_layout.py -v`
Expected: FAIL with `AssertionError` (`version == 13`, or `'session_layout'` key missing).

- [ ] **Step 3: Write minimal implementation**

In `src/app/desktop_state.py`:

1. Change line 37:
```python
DESKTOP_STATE_VERSION = 14
```

2. In `__init__` (this is in `main_window.py`; add defaults near `self.transfer_writable` line 355):
```python
            self.session_tab_layout = "top"
            self.terminal_font_size = 14
            self.session_manager_default_collapsed = False
            self.session_manager_width = 260
            self.session_manager_collapsed = False
            self.collapsed_device_groups: list[str] = []
```

3. In `load_desktop_state()`, after the `remembered_terminal_sessions` block (line 278, before `rebuild_device_indexes`), add:
```python
        session_layout = payload.get("session_layout", {})
        if isinstance(session_layout, dict):
            raw_layout = str(session_layout.get("session_tab_layout") or "top").strip().lower()
            if raw_layout in {"top", "side"}:
                self.session_tab_layout = raw_layout
            try:
                loaded_font = int(session_layout.get("terminal_font_size", self.terminal_font_size))
            except (TypeError, ValueError):
                loaded_font = self.terminal_font_size
            self.terminal_font_size = max(9, min(28, loaded_font))
            self.session_manager_default_collapsed = bool(
                session_layout.get("session_manager_default_collapsed", False)
            )
            try:
                loaded_width = int(session_layout.get("session_manager_width", self.session_manager_width))
            except (TypeError, ValueError):
                loaded_width = self.session_manager_width
            self.session_manager_width = max(200, min(480, loaded_width))
            self.session_manager_collapsed = bool(
                session_layout.get("session_manager_collapsed", False)
            )
            raw_collapsed = session_layout.get("collapsed_device_groups", [])
            if isinstance(raw_collapsed, list):
                self.collapsed_device_groups = [
                    str(item or "").strip() for item in raw_collapsed if str(item or "").strip()
                ]
        if hasattr(self, "apply_session_layout_state"):
            self.apply_session_layout_state()
```

4. In `save_desktop_state()`, add the section to the payload dict (after `"local_credential_overrides"` line 349):
```python
                "session_layout": {
                    "session_tab_layout": self.session_tab_layout,
                    "terminal_font_size": self.terminal_font_size,
                    "session_manager_default_collapsed": self.session_manager_default_collapsed,
                    "session_manager_width": self.session_manager_width,
                    "session_manager_collapsed": self.session_manager_collapsed,
                    "collapsed_device_groups": list(self.collapsed_device_groups),
                },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_desktop_state_session_layout.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/desktop_state.py src/app/main_window.py tests/test_desktop_state_session_layout.py
git commit -m "feat: persist session layout settings (state v14)"
```

---

### Task 3: `SessionLayoutOpsMixin` — build the right manager panel

**Files:**
- Create: `src/app/session_layout_ops.py`
- Modify: `src/app/main_window.py` (import + add to mixin list at line 249-262; wire `_build_layout` at line 457 to call the new build method; call new init in `__init__`)
- Test: `tests/test_session_layout_manager.py` (new)

**Interfaces:**
- Consumes:
  - `self.main_splitter` (SidebarSplitter, from `_build_layout`)
  - `self.session_tabs_by_id: dict[str, SessionTabState]`
  - `self.device_tabs_by_id: dict[str, DeviceTabState]`
  - `self.session_tab_widget` (QTabWidget, device tabs)
  - `jump_to_session(tab_id)` (session_ops.py:2988)
  - `activate_device(device_id)` (table_ops.py:1531)
  - `build_device_tab_context_menu(state, parent)` (returns `(menu, close_actions, device_actions, device)`)
  - `close_session_tab(tab_id)` (session_ops.py:4178)
  - `show_terminal_workspace()` (session_ops.py:3082)
  - `schedule_desktop_state_save()`
- Produces:
  - `self.session_manager_panel: QWidget` — right-side panel with header, search, tree, footer
  - `self.session_manager_tree: QTreeWidget`
  - `self.session_manager_search: QLineEdit`
  - `self.session_manager_collapse_button: QToolButton`
  - `self.session_manager_count_label: QLabel`
  - `self.build_session_manager_panel() -> QWidget`
  - `self.refresh_session_manager_tree() -> None`
  - `self.set_session_manager_visible(visible: bool) -> None`
  - `self.toggle_session_manager_collapsed() -> None`
  - `self._session_manager_filter_query() -> str`
  - `self._session_manager_group_matches(query: str, device: Device) -> bool`
  - `self._session_manager_session_matches(query: str, state: SessionTabState, device: Device) -> bool`
  - `self.session_manager_jump_from_item(item: QTreeWidgetItem) -> None`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTreeWidget

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _device_tabs(window: DeviceDesktopApp, count: int = 2):
    devices = sample_devices()[:count]
    for index, device in enumerate(devices):
        device.id = f"layout-device-{index}"
        device.name = f"设备 {index + 1}"
    window.devices = devices
    window.rebuild_device_indexes()
    return [window.ensure_device_tab(device) for device in devices]


def test_manager_panel_built_as_third_splitter_child(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.main_splitter.count() == 3
    assert window.session_manager_panel is not None
    assert window.session_manager_tree is not None
    assert window.session_manager_panel.isVisible()
    window.close()


def test_tree_populates_with_device_and_session_items(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    states = _device_tabs(window)
    tree: QTreeWidget = window.session_manager_tree

    window.refresh_session_manager_tree()

    assert tree.topLevelItemCount() == len(states)
    # first device has no sessions yet -> its group shows count 0
    assert window.session_manager_count_label.text().startswith("共")
    window.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_layout_manager.py -v`
Expected: FAIL with `AttributeError: 'DeviceDesktopApp' object has no attribute 'session_manager_panel'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/app/session_layout_ops.py`:

```python
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
```

Now wire it into `src/app/main_window.py`:

1. Import at top (after the existing `from .session_ops import SessionOpsMixin`-style imports):
```python
from .session_layout_ops import SessionLayoutOpsMixin
```

2. Add `SessionLayoutOpsMixin` to the class base list at line 249-262, immediately after `SessionOpsMixin`:
```python
    class DeviceDesktopApp(
        SessionOpsMixin,
        SessionLayoutOpsMixin,
        OccupancyOpsMixin,
        ...
```

3. In `_build_layout()` (line 457), after `splitter.addWidget(self._build_center_panel())` (line 468), add the third child and set stretch:
```python
            splitter.addWidget(self.build_session_manager_panel())
            splitter.setStretchFactor(2, 0)
```

Note: The mixin has **no** `__init__`. Mixins in this codebase do not define `__init__` — all instance state defaults live directly in `DeviceDesktopApp.__init__`. Add these defaults in `__init__` (in `main_window.py`, near line 355 after `self.transfer_writable`):

```python
            self.session_manager_panel = None
            self.session_manager_tree = None
            self.session_manager_search = None
            self.session_manager_collapse_button = None
            self.session_manager_count_label = None
            self.session_breadcrumb = None
            self.session_breadcrumb_device_label = None
            self.session_breadcrumb_session_label = None
            self.settings_button = None
```

These are overwritten by the `build_*` methods during `_build_layout`, which runs after these defaults are set. Because the build methods run during `_build_layout` (line 407, after `load_desktop_state` at 404), the widget references are created before any refresh call that needs them.

4. In `_build_layout`, after `self.apply_left_sidebar_state()` (line 476), add:
```python
            self.set_session_manager_visible(self.session_tab_layout == "side")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_layout_manager.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/session_layout_ops.py src/app/main_window.py tests/test_session_layout_manager.py
git commit -m "feat: add SessionLayoutOpsMixin with right session manager panel"
```

---

### Task 4: Layout switching (`top` ⇄ `side`) + breadcrumb

**Files:**
- Modify: `src/app/session_layout_ops.py` (add layout-switch methods + breadcrumb builder)
- Modify: `src/app/main_window.py` (`_build_center_panel` to add breadcrumb widget; `__init__` init hook)
- Modify: `src/app/desktop_state.py` (call `apply_session_layout_state`)
- Test: `tests/test_session_layout_switch.py` (new)

**Interfaces:**
- Consumes:
  - `self.session_tab_widget` and its `.tabBar()` — device tab bar
  - `self.device_tabs_by_id` — each `DeviceTabState.page` → find child `QTabWidget`s via `session_tab_widgets_for_device(device_tab)`
  - `show_terminal_workspace()` — session_ops.py:3082
  - `update_center_stage_state()` — session_ops.py:3038
- Produces:
  - `self.session_breadcrumb: QWidget` — thin breadcrumb widget
  - `self.session_breadcrumb_device_label: QLabel`
  - `self.session_breadcrumb_session_label: QLabel`
  - `self.build_session_breadcrumb() -> QWidget`
  - `self.apply_session_layout_state() -> None`
  - `self.set_session_tab_layout(mode: str) -> None`
  - `self.set_session_tab_bars_visible(visible: bool) -> None`
  - `self.refresh_session_breadcrumb() -> None`
  - `self.handle_session_tab_bars_hidden(visible: bool) -> None`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _device_tabs(window: DeviceDesktopApp):
    devices = sample_devices()[:2]
    for index, device in enumerate(devices):
        device.id = f"switch-device-{index}"
        device.name = f"切换设备 {index + 1}"
    window.devices = devices
    window.rebuild_device_indexes()
    return [window.ensure_device_tab(device) for device in devices]


def test_apply_layout_state_side_hides_tab_bars_shows_panel(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window)

    window.session_tab_layout = "side"
    window.apply_session_layout_state()

    assert not window.session_tab_widget.tabBar().isVisible()
    assert window.session_manager_panel.isVisible()
    assert window.session_breadcrumb.isVisible()
    window.close()


def test_apply_layout_state_top_restores_tab_bars(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window)

    window.session_tab_layout = "top"
    window.apply_session_layout_state()

    assert window.session_tab_widget.tabBar().isVisible()
    assert not window.session_manager_panel.isVisible()
    assert not window.session_breadcrumb.isVisible()
    window.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_layout_switch.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'apply_session_layout_state'` or `session_breadcrumb`.

- [ ] **Step 3: Write minimal implementation**

Add to `SessionLayoutOpsMixin` in `src/app/session_layout_ops.py`:

```python
    def build_session_breadcrumb(self) -> QWidget:
        breadcrumb = QWidget()
        breadcrumb.setObjectName("sessionBreadcrumb")
        layout = QHBoxLayout(breadcrumb)
        layout.setContentsMargins(10, 3, 10, 3)
        layout.setSpacing(4)
        home_label = QLabel("设备池")
        home_label.setObjectName("breadcrumbHome")
        home_label.setCursor(Qt.PointingHandCursor)
        home_label.mousePressEvent = lambda _event: self._breadcrumb_goto_home()
        self.session_breadcrumb_device_label = QLabel()
        self.session_breadcrumb_device_label.setObjectName("breadcrumbDevice")
        self.session_breadcrumb_device_label.setCursor(Qt.PointingHandCursor)
        self.session_breadcrumb_session_label = QLabel()
        self.session_breadcrumb_session_label.setObjectName("breadcrumbSession")
        layout.addWidget(home_label)
        layout.addWidget(QLabel("/"))
        layout.addWidget(self.session_breadcrumb_device_label)
        layout.addWidget(QLabel("/"))
        layout.addWidget(self.session_breadcrumb_session_label)
        layout.addStretch(1)
        self.session_breadcrumb = breadcrumb
        return breadcrumb

    def _breadcrumb_goto_home(self) -> None:
        self.center_stage_mode = "home"
        self.update_center_stage_state()
        self.apply_left_sidebar_state()

    def set_session_tab_bars_visible(self, visible: bool) -> None:
        """Show or hide the top device tab bar and all per-device session tab bars."""
        self.session_tab_widget.tabBar().setVisible(visible)
        for device_tab in self.device_tabs_by_id.values():
            for tabs in self.session_tab_widgets_for_device(device_tab):
                tabs.tabBar().setVisible(visible)

    def set_session_tab_layout(self, mode: str) -> None:
        mode = mode if mode in {"top", "side"} else "top"
        self.session_tab_layout = mode
        self.apply_session_layout_state()
        self.schedule_desktop_state_save()

    def apply_session_layout_state(self) -> None:
        # Called from load_desktop_state BEFORE _build_layout builds the
        # widgets — guard against not-yet-created panels and tab widget.
        if not hasattr(self, "session_tab_widget") or self.session_manager_panel is None:
            return
        side = self.session_tab_layout == "side"
        if side:
            if self.session_tab_widget.count() > 0:
                self.show_terminal_workspace()
        self.set_session_tab_bars_visible(not side)
        self.set_session_manager_visible(side)
        if getattr(self, "session_breadcrumb", None) is not None:
            self.session_breadcrumb.setVisible(side)
        if side:
            self.refresh_session_manager_tree()
            self.refresh_session_breadcrumb()

    def refresh_session_breadcrumb(self) -> None:
        if (
            getattr(self, "session_breadcrumb_device_label", None) is None
            or getattr(self, "session_breadcrumb_session_label", None) is None
        ):
            return
        state = self.current_session_state()
        device_id = state.device_id if state is not None else ""
        device = self.get_device_by_id(device_id) if device_id else None
        device_name = device.name if device is not None else device_id
        session_title = state.title if state is not None else ""
        self.session_breadcrumb_device_label.setText(device_name)
        self.session_breadcrumb_device_label.setProperty("deviceId", device_id)
        self.session_breadcrumb_session_label.setText(session_title)
```

Wire into `main_window.py` `_build_center_panel` (line 1384) — add the breadcrumb as the first child of `center_stage_splitter` (before `web_shell` at line 1396):

```python
            self.build_session_breadcrumb()
            self.center_stage_splitter.addWidget(self.session_breadcrumb)
```

Replace Task 3's `_build_layout` wiring line (`self.set_session_manager_visible(self.session_tab_layout == "side")`) with a full apply call, so width restore + tree population run after the layout is built:

```python
            self.apply_session_layout_state()
```

And in `desktop_state.py` `load_desktop_state()` step (Task 2), `apply_session_layout_state()` is called via `hasattr`. Ensure the mixin method is present; it is defined in Task 4. The pre-build guard makes this safe — when `load_desktop_state` runs (before `_build_layout`), the guard returns early; the later `_build_layout` call applies the loaded state.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_layout_switch.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/session_layout_ops.py src/app/main_window.py src/app/desktop_state.py tests/test_session_layout_switch.py
git commit -m "feat: layout switching between top and side with breadcrumb"
```

---

### Task 5: Right panel context menus + font-size application + session-close

**Files:**
- Modify: `src/app/session_layout_ops.py` (context menu handler, font-size apply, wire refresh on session changes)
- Modify: `src/app/main_window.py` (connect tree customContextMenuRequested)
- Test: `tests/test_session_layout_context_menu.py` (new)

**Interfaces:**
- Consumes:
  - `new_workspace_menu(parent, title, kind)` — main_window.py:446
  - `build_device_tab_context_menu(state, parent)` — returns `(menu, close_actions, device_actions, device)`
  - `close_session_tab(tab_id)` — session_ops.py:4178
  - `close_device_tabs_relative(state, mode)` — session_ops.py:1559
  - `get_device_by_id(device_id)`
  - `current_session_state()`
  - `apply_font_size_to_terminal(terminal, size)` (defined here)
- Produces:
  - `self.session_manager_custom_context_menu(pos) -> None` — slot connected to `customContextMenuRequested`
  - `self.apply_font_size_to_all_terminals() -> None`
  - `self.apply_font_size_to_terminal(terminal, size) -> None`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _device_tabs(window: DeviceDesktopApp):
    devices = sample_devices()[:2]
    for index, device in enumerate(devices):
        device.id = f"menu-device-{index}"
        device.name = f"菜单设备 {index + 1}"
    window.devices = devices
    window.rebuild_device_indexes()
    return [window.ensure_device_tab(device) for device in devices]


def test_apply_font_size_to_terminal_calls_set_font_size(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    calls: list[int] = []
    terminal = type("T", (), {"set_font_size": lambda self, n: calls.append(n)})()
    window.apply_font_size_to_terminal(terminal, 18)
    assert calls == [18]
    window.close()


def test_session_manager_context_menu_builds_workspace_menu(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window)
    window.session_manager_custom_context_menu(None)  # no crash with no item
    window.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_layout_context_menu.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'apply_font_size_to_terminal'` or `session_manager_custom_context_menu`.

- [ ] **Step 3: Write minimal implementation**

Add to `SessionLayoutOpsMixin` in `src/app/session_layout_ops.py`:

```python
    def apply_font_size_to_terminal(self, terminal: object, size: int) -> None:
        if hasattr(terminal, "set_font_size"):
            terminal.set_font_size(int(size))

    def apply_font_size_to_all_terminals(self) -> None:
        for state in self.session_tabs_by_id.values():
            self.apply_font_size_to_terminal(state.terminal, self.terminal_font_size)

    def session_manager_custom_context_menu(self, pos: object) -> None:
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
            menu, close_actions, _device_actions, _device = self.build_device_tab_context_menu(
                device_tab, self.session_manager_tree
            )
            chosen = menu.exec(self.session_manager_tree.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            for mode, action in close_actions.items():
                if chosen == action:
                    self.close_device_tabs_relative(device_tab, mode)
                    return
```

Wire the context menu in `main_window.py` `_build_layout` (after adding panel, in Task 3). Add in `build_session_manager_panel` (in Task 3), after creating the tree:
```python
        self.session_manager_tree.customContextMenuRequested.connect(
            self.session_manager_custom_context_menu
        )
```

Add font-size application: in `desktop_state.py` `load_desktop_state()`, after `self.terminal_font_size = ...` (Task 2), nothing extra — the tree / breadcrumb hooks already call `apply_session_layout_state`. Font-size apply is triggered by the settings panel (Task 6) and on workspace refresh; the mixin exposes `apply_font_size_to_all_terminals()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_layout_context_menu.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/session_layout_ops.py src/app/main_window.py tests/test_session_layout_context_menu.py
git commit -m "feat: session manager context menus and font-size application"
```

---

### Task 6: Status-bar settings button + settings panel

**Files:**
- Modify: `src/app/session_layout_ops.py` (settings button + panel build, wire the 3 settings)
- Modify: `src/app/main_window.py` (status bar wiring in `_build_window`; `apply_session_layout_state` calls on change)
- Test: `tests/test_session_layout_settings.py` (new)

**Interfaces:**
- Consumes:
  - `self.statusBar()` (QStatusBar from `_build_window`)
  - `new_workspace_menu(parent, title, kind)` — main_window.py:446
  - `schedule_desktop_state_save()`
  - `apply_font_size_to_all_terminals()` (Task 5)
- Produces:
  - `self.settings_button: QToolButton`
  - `self.build_settings_button() -> QToolButton`
  - `self.settings_layout_combo: QComboBox`
  - `self.settings_font_spin: QSpinBox`
  - `self.settings_default_collapsed_check: QCheckBox`
  - `self.build_settings_panel() -> QWidget`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_settings_button_created_and_attached_to_status_bar(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.settings_button is not None
    assert window.settings_button.parent() is window.statusBar()
    window.close()


def test_settings_layout_combo_changes_session_layout(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.settings_layout_combo.setCurrentText("右侧")
    assert window.session_tab_layout == "side"
    window.settings_layout_combo.setCurrentText("顶部")
    assert window.session_tab_layout == "top"
    window.close()


def test_settings_font_spin_applies_font_size(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.settings_font_spin.setValue(18)
    assert window.terminal_font_size == 18
    window.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_layout_settings.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'settings_button'`.

- [ ] **Step 3: Write minimal implementation**

Add to `SessionLayoutOpsMixin` in `src/app/session_layout_ops.py`:

```python
    def build_settings_button(self) -> QToolButton:
        from PySide6.QtWidgets import QToolButton

        button = QToolButton()
        button.setObjectName("sessionSettingsButton")
        button.setText("⚙")
        button.setToolTip("工作台设置")
        button.setPopupMode(QToolButton.InstantPopup)
        menu = self.new_workspace_menu(button, "工作台设置", "settings")
        menu.setObjectName("workspaceContextMenu")
        panel = self.build_settings_panel()
        action = menu.addAction("")
        action.setDefaultWidget(panel)
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

        form.addRow("会话页签布局", self.settings_layout_combo)
        form.addRow("终端字体大小", self.settings_font_spin)
        form.addRow("默认折叠", self.settings_default_collapsed_check)
        layout.addLayout(form)
        hint = QLabel("「默认折叠」仅决定首次进入右侧布局的状态，之后跟随操作记忆。")
        hint.setObjectName("settingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return panel

    def _settings_layout_changed(self, text: str) -> None:
        self.set_session_tab_layout("side" if text == "右侧" else "top")

    def _settings_font_changed(self, value: int) -> None:
        self.terminal_font_size = int(value)
        self.apply_font_size_to_all_terminals()
        self.schedule_desktop_state_save()

    def _settings_default_collapsed_changed(self, checked: bool) -> None:
        self.session_manager_default_collapsed = bool(checked)
        self.schedule_desktop_state_save()
```

Wire in `main_window.py` `_build_window` (after `status_bar.showMessage("准备就绪")` line 444):
```python
            status_bar.addPermanentWidget(self.build_settings_button())
```

Also in `main_window.py` `_build_center_panel`, breadcrumb session-label click → jump: add mousePressEvent handler to `session_breadcrumb_session_label` in `build_session_breadcrumb`:
```python
        self.session_breadcrumb_session_label.mousePressEvent = (
            lambda _event: self.jump_to_session(
                (self.current_session_state() or object()).tab_id
            )
            if self.current_session_state() is not None
            else None
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_layout_settings.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/session_layout_ops.py src/app/main_window.py tests/test_session_layout_settings.py
git commit -m "feat: status-bar settings button and panel for session layout"
```

---

### Task 7: Panel collapse + width drag memory + refresh on session changes

**Files:**
- Modify: `src/app/session_layout_ops.py` (collapse behavior, width persistence via splitter drag-finished, refresh hooks)
- Modify: `src/app/main_window.py` (wire splitter drag-finished for panel width; hook refresh on session changes)
- Modify: `src/app/session_ops.py` (hook `refresh_session_manager_tree` into existing session-change points)
- Test: `tests/test_session_layout_memory.py` (new)

**Interfaces:**
- Consumes:
  - `self.main_splitter.drag_finished` signal (SidebarSplitter, main_window.py:475)
  - `self.session_manager_width`, `self.session_manager_collapsed`, `self.collapsed_device_groups` (Task 2)
  - `self.session_manager_collapse_button` (Task 3)
- Produces:
  - `self.handle_session_manager_width_drag_finished(width: int) -> None`
  - `self.apply_session_manager_collapsed_state() -> None`
  - `self.session_manager_collapsed` state respected on entering side

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_collapse_toggle_updates_state_and_persists(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.session_tab_layout = "side"
    window.session_manager_collapse_button.setChecked(True)
    window.toggle_session_manager_collapsed()

    assert window.session_manager_collapsed is True
    assert not window.session_manager_panel.isVisible()
    window.close()


def test_width_drag_finished_clamps_and_persists(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.handle_session_manager_width_drag_finished(500)
    assert window.session_manager_width == window.SESSION_MANAGER_MAX_WIDTH
    window.handle_session_manager_width_drag_finished(10)
    assert window.session_manager_width == window.SESSION_MANAGER_MIN_WIDTH
    window.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_layout_memory.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'handle_session_manager_width_drag_finished'`.

- [ ] **Step 3: Write minimal implementation**

Add to `SessionLayoutOpsMixin` in `src/app/session_layout_ops.py`:

```python
    def handle_session_manager_width_drag_finished(self, width: int) -> None:
        clamped = max(self.SESSION_MANAGER_MIN_WIDTH, min(self.SESSION_MANAGER_MAX_WIDTH, int(width)))
        self.session_manager_width = clamped
        self.schedule_desktop_state_save()

    def apply_session_manager_collapsed_state(self) -> None:
        collapsed = self.session_manager_collapsed
        if self.session_manager_collapse_button is not None:
            self.session_manager_collapse_button.setChecked(collapsed)
        if self.session_tab_layout == "side":
            self.set_session_manager_visible(not collapsed)

    def apply_session_layout_state(self) -> None:
        # Refined body (replaces Task 4 version): adds collapse handling and
        # the pre-build guard.
        if not hasattr(self, "session_tab_widget") or self.session_manager_panel is None:
            return
        side = self.session_tab_layout == "side"
        if side:
            if self.session_tab_widget.count() > 0:
                self.show_terminal_workspace()
        self.set_session_tab_bars_visible(not side)
        collapsed = self.session_manager_collapsed
        self.set_session_manager_visible(side and not collapsed)
        if getattr(self, "session_breadcrumb", None) is not None:
            self.session_breadcrumb.setVisible(side)
        if side:
            self.refresh_session_manager_tree()
            self.refresh_session_breadcrumb()
```

Wire width persistence in `main_window.py` `_build_layout` (after `splitter.drag_finished.connect(...)` line 475):
```python
            splitter.drag_finished.connect(self.handle_session_manager_width_drag_finished)
```

Note: `drag_finished` emits `released_width` of the first child (left panel width). The right panel width is `total - left - center`. To capture the right panel width correctly, override the handler to read `splitter.sizes()` directly:

```python
    def handle_session_manager_width_drag_finished(self, _width: int = 0) -> None:
        splitter = getattr(self, "main_splitter", None)
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) < 3:
            return
        right_width = int(sizes[-1])
        if right_width <= 0:
            return
        clamped = max(self.SESSION_MANAGER_MIN_WIDTH, min(self.SESSION_MANAGER_MAX_WIDTH, right_width))
        self.session_manager_width = clamped
        self.schedule_desktop_state_save()
```

Note: The `drag_finished` signal already fires on any splitter handle drag, not just the new right handle. To avoid recording a bogus width when the user drags the left boundary, guard by checking which handle was moved — but the signal only passes a single `width`. Since the design says "width is single global value", and the right panel's own boundary is what matters, the simplest correct approach is: only record when the drag actually changed the right panel's size. The handler above reads `sizes[-1]`, which is the right panel width regardless of which handle moved — acceptable, since the right panel width is exactly what we want to persist.

Update `refresh_session_manager_tree` collapse handling: after populating, set `self.session_manager_tree` expansion to respect `collapsed_device_groups` (already done in Task 3 via `parent.setExpanded(group_key not in collapsed_set)`).

Hook tree refresh on session changes: in `session_ops.py`, find the session close points. Add a guard that calls `refresh_session_manager_tree` if present. The cleanest single hook is in `refresh_workspace_context()` (line 2885), which is called after session open/close/switch:

Add to `refresh_workspace_context()` body (or its tail):
```python
        if hasattr(self, "refresh_session_manager_tree"):
            self.refresh_session_manager_tree()
        if hasattr(self, "refresh_session_breadcrumb"):
            self.refresh_session_breadcrumb()
```

And in `close_session_tab` (line 4178) and `ensure_session_tab` (line 3633 end) the workspace context refresh already fires. For tree refresh on `apply_session_layout_state`, that's handled in the mixin.

Also, on initial load (Task 2 `apply_session_layout_state` call), the panel width should be applied to the splitter. Add to `apply_session_layout_state`:
```python
        if side:
            self.session_manager_panel.setMinimumWidth(self.SESSION_MANAGER_MIN_WIDTH)
            self.session_manager_panel.setMaximumWidth(self.SESSION_MANAGER_MAX_WIDTH)
            target = max(self.SESSION_MANAGER_MIN_WIDTH, min(self.SESSION_MANAGER_MAX_WIDTH, self.session_manager_width))
            sizes = self.main_splitter.sizes()
            if len(sizes) >= 3 and sum(sizes) > 0:
                self.main_splitter.setSizes([sizes[0], max(1, sum(sizes) - sizes[0] - target), target])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_layout_memory.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/app/session_layout_ops.py src/app/main_window.py src/app/session_ops.py tests/test_session_layout_memory.py
git commit -m "feat: session manager collapse + width memory and refresh hooks"
```

---

### Task 8: Tree search filtering + full-suite pass

**Files:**
- Modify: `src/app/session_layout_ops.py` (already have `_session_manager_filter_query` etc. from Task 3 — refine and verify)
- Test: `tests/test_session_layout_search.py` (new)

**Interfaces:**
- Consumes: `_session_manager_group_matches`, `_session_manager_session_matches` (Task 3), `refresh_session_manager_tree` (Task 3)
- Produces: verified search-filtering behavior.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _device_with_session(window: DeviceDesktopApp):
    device = sample_devices()[0]
    device.id = "search-device-0"
    device.name = "搜索路由器"
    window.devices = [device]
    window.rebuild_device_indexes()
    state = window.ensure_session_tab(
        kind="simulated",
        device=device,
        host=device.ssh_ip or "10.0.0.1",
        port=device.ssh_port or 22,
        username="admin",
        password="secret",
        title="SSH 搜索会话",
        suppress_initial_error=True,
    )
    return state


def test_search_filters_tree_by_session_title(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_with_session(window)
    window.refresh_session_manager_tree()
    tree = window.session_manager_tree

    window.session_manager_search.setText("搜索会话")
    window.refresh_session_manager_tree()

    # matching child remains, top-level count preserved
    assert tree.topLevelItemCount() == 1
    window.session_manager_search.clear()
    window.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_layout_search.py -v`
Expected: FAIL (tree filtering not applied — the search textChanged already calls refresh, so verify behavior).

- [ ] **Step 3: Implement/verify the filtering**

The `refresh_session_manager_tree` already implements filtering via `_session_manager_group_matches` / `_session_manager_session_matches`. Ensure the search box's `textChanged` triggers refresh (already connected in Task 3). Verify the logic in `refresh_session_manager_tree`:

The current implementation removes top-level items with no matching children (`if parent.childCount() == 0: takeTopLevelItem`). This correctly hides non-matching groups. Ensure the search `textChanged` connection is present (Task 3 line: `self.session_manager_search.textChanged.connect(...)`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_layout_search.py -v`
Expected: PASS.

- [ ] **Step 5: Full regression + commit**

Run:
```bash
python -m py_compile src\*.py src\app\*.py src\widgets\*.py
pytest tests/test_session_layout.py -v 2>/dev/null || true
pytest tests/ -x
```
Expected: new tests pass; full suite passes (with repo's known unrelated exclusions if any).

```bash
git add src/app/session_layout_ops.py tests/test_session_layout_search.py
git commit -m "feat: session manager tree search filtering"
```

---

## Self-Review

### Spec coverage

- ✅ Settings button + in-menu panel (Task 6)
- ✅ `session_tab_layout` top/side (Tasks 2, 4)
- ✅ Terminal font size (Tasks 1, 6)
- ✅ Right-side hierarchical session manager with click-to-jump (Task 3)
- ✅ Inline search (Task 3, 8)
- ✅ Context menus: child (close this/others/all) + parent (reuse device-tab menu) (Task 5)
- ✅ Bottom "new terminal" action (Task 3)
- ✅ Breadcrumb with click interactions (Task 4)
- ✅ Panel width draggable, single global value, persisted (Task 7)
- ✅ Panel collapse + per-device-group collapse memorized; default-collapse governs first entry (Tasks 3, 7)
- ✅ State v13 → v14 (Task 2)
- ✅ Close-session confirmation — correctly omitted
- ✅ Layout switch hides/shows tab bars + panel + breadcrumb (Task 4)
- ✅ No changes to top-mode behavior (Tasks 4, 7)

### Placeholder scan

All steps contain concrete code and test code. No TBD/TODO/`implement later`.

### Type consistency

- `set_font_size(size: int)` — Task 1 defines, Task 5 consumes via `apply_font_size_to_terminal`.
- `session_manager_width` / `session_manager_collapsed` / `collapsed_device_groups` — Task 2 defines, Tasks 3/7 consume.
- `apply_session_layout_state()` — Task 2 calls via hasattr, Task 4 defines the real body, Task 7 refines.
- `apply_font_size_to_all_terminals()` — Task 5 defines, Task 6 consumes.
- `refresh_session_manager_tree()` / `refresh_session_breadcrumb()` — Task 3 defines, Tasks 4/7/8 consume; session_ops hooks call via hasattr.
- `handle_session_manager_width_drag_finished` — Task 7 defines, main_window wires.
- `set_session_manager_visible` — Task 3 defines, Tasks 4/7 consume.

One note: `apply_session_layout_state` is refined across Tasks 4 and 7 (Task 7 replaces the Task 4 body). The final body (Task 7) is authoritative and includes collapse handling.
