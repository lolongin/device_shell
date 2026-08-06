# Right Session Manager Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Theme the right session-manager panel (currently the only unstyled Qt surface) with the workspace OLED skin and enrich it with a two-column compact layout — device icon + name / count badge on parents, status dot + title / protocol·host:port on sessions.

**Architecture:** Two independent changes. (1) `SessionLayoutOpsMixin` tree becomes two-column: parents get a connection-tinted device icon (new `_session_manager_device_icon`) + bare name in col0 and a count badge in col1; session children keep their status dot + title in col0 and gain `协议 · host:port` metadata in col1. (2) A single additive `/* Session manager panel */` QSS block is inserted into `APP_STYLE` before the final `/* Global text selection */` block, giving every manager widget a dark workspace surface.

**Tech Stack:** PySide6 (QTreeWidget, QTreeWidgetItem, QPainter icons), Python, Qt QSS, pytest.

## Global Constraints

(Values copied verbatim from `docs/superpowers/specs/2026-08-07-session-manager-upgrade-design.md`.)

- Additive-only CSS: do NOT edit existing rules in `src/styles.py`; only insert the new `/* Session manager panel */` block.
- `/* Global text selection */` must remain the **last** block in `APP_STYLE`. The new session-manager block goes immediately **before** it (i.e., after the existing `/* Unified component system */` block).
- Device group parent row: col0 = connection-tinted device icon + **bare** device name (no `(n)` suffix); col1 = session-count badge `str(len(states))`.
- Session child row: col0 = existing status dot + `state.title` (current session stays bold); col1 = `"协议 · host:port"` built from `session_kind_label(state.kind)` + `state.host:state.port`, muted and truncated.
- Both col-0 icons must remain non-null (existing tests `tests/test_session_layout_manager.py::test_tree_items_have_status_dot_icons` assert `not parent.icon(0).isNull()` and `not child.icon(0).isNull()`).
- Parent device-icon color: green if any child `connected`, amber if any `connecting`, gray otherwise (mirror the existing `_session_manager_parent_icon` aggregation).
- All colors are existing workspace tokens — no new tokens.
- `main_splitter.count() == 3`, collapse/expand, context menu, search filter, and collapse memory are unchanged.

---

### Task 1: Two-column tree with device icons and session metadata

**Files:**
- Modify: `src/app/session_layout_ops.py:86-100` (`build_session_manager_panel` — add `setColumnCount(2)`), `:218-276` (`refresh_session_manager_tree` — col0/col1 content), `:278-314` (icon helpers — add `_session_manager_device_icon`, extend `_session_manager_parent_icon`)
- Test: `tests/test_session_layout_manager.py` (extend)

**Interfaces:**
- Consumes: `self._tab_connection_state(state) -> str`, `self.session_kind_label(kind) -> str` (staticmethod on `SessionOpsMixin`), `state.kind`, `state.host`, `state.port`, `state.title`, `state.tab_id`. **NOTE: `Device` has no `kind` field** — the parent device glyph derives its kind from the first session's `state.kind` (`states[0].kind`), defaulting to `"device"` when no sessions exist.
- Produces: `SessionLayoutOpsMixin._session_manager_device_icon(self, kind: str, color: str) -> QIcon | None` (16×16, 1.7px stroke). Parent rows expose col0 = device icon + name, col1 = count; child rows expose col0 = dot + title, col1 = `协议 · host:port`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session_layout_manager.py`:

```python
def test_tree_has_two_columns_with_session_metadata(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window, count=1)
    monkeypatch.setattr(window, "connect_session_tab", lambda tab_id: None)
    device = window.devices[0]
    window.ensure_session_tab(
        kind="simulated",
        device=device,
        host=device.ssh_ip or "10.0.0.1",
        port=device.ssh_port or 22,
        username="admin",
        password="secret",
        title="SSH 双列",
        suppress_initial_error=True,
    )
    window.refresh_session_manager_tree()
    tree: QTreeWidget = window.session_manager_tree

    assert tree.columnCount() == 2
    child = tree.topLevelItem(0).child(0)
    assert child is not None
    assert not child.icon(0).isNull()
    assert "SSH 双列" in child.text(0)
    assert "模拟" in child.text(1)
    assert "10.0.0.1" in child.text(1)
    assert "22" in child.text(1)
    window.close()


def test_device_parent_column1_shows_session_count(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window, count=1)
    monkeypatch.setattr(window, "connect_session_tab", lambda tab_id: None)
    device = window.devices[0]
    window.ensure_session_tab(
        kind="simulated",
        device=device,
        host=device.ssh_ip or "10.0.0.1",
        port=device.ssh_port or 22,
        username="admin",
        password="secret",
        title="SSH 计数",
        suppress_initial_error=True,
    )
    window.ensure_session_tab(
        kind="simulated",
        device=device,
        host=device.ssh_ip or "10.0.0.1",
        port=device.ssh_port or 23,
        username="admin",
        password="secret",
        title="SSH 计数 2",
        suppress_initial_error=True,
    )
    window.refresh_session_manager_tree()
    tree: QTreeWidget = window.session_manager_tree

    parent = tree.topLevelItem(0)
    assert parent is not None
    assert not parent.icon(0).isNull()
    assert parent.text(1) == "2"
    assert parent.childCount() == 2
    window.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_session_layout_manager.py::test_tree_has_two_columns_with_session_metadata tests/test_session_layout_manager.py::test_device_parent_column1_shows_session_count -v`
Expected: FAIL — `tree.columnCount()` is 1, `parent.text(1)` is empty, `child.text(1)` is empty.

- [ ] **Step 3: Make the tree two-column** (`src/app/session_layout_ops.py:86-100`)

In `build_session_manager_panel`, after `self.session_manager_tree.setObjectName("sessionManagerTree")` (~line 87), add:

```python
        self.session_manager_tree.setColumnCount(2)
```

- [ ] **Step 4: Add the device icon helper** (`src/app/session_layout_ops.py`, after `_session_manager_dot_icon` ~line 314)

```python
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
```

(`QPen` is NOT imported at the top of `session_layout_ops.py` — add `QPen` to the `try` import block at line 6 and to the `except` fallback at line 21.)

- [ ] **Step 5: Rework parent/child icon + metadata in `refresh_session_manager_tree`** (`src/app/session_layout_ops.py:244-274`)

Replace the parent construction block (currently `parent = QTreeWidgetItem(...)` through `parent.setExpanded(...)`) with:

```python
            parent = QTreeWidgetItem(self.session_manager_tree)
            group_key = device_id
            label = (device.name if device is not None else device_tab.title) or device_id
            parent.setText(0, label)
            parent.setText(1, str(len(states)))
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
```

- [ ] **Step 6: Extend `_session_manager_parent_icon` to tint by state and add the metadata helper** (`src/app/session_layout_ops.py:292-301`)

Replace `_session_manager_parent_icon` with a version that returns the new device icon, deriving the glyph `kind` from the first session's kind (`Device` has no `kind` field):

```python
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
```

The call site at line ~249 keeps its existing signature `self._session_manager_parent_icon(states)` — no call-site change needed (`device` is no longer a parameter).

- [ ] **Step 7: Run the session-manager tests**

Run: `pytest tests/test_session_layout_manager.py -v`
Expected: PASS (existing 4 + 2 new = 6).

- [ ] **Step 8: Run the layout smoke tests**

Run: `pytest tests/test_session_layout_context_menu.py tests/test_session_layout_memory.py tests/test_desktop_state_session_layout.py -q`
Expected: PASS (context menu, collapse memory, desktop state unaffected by two columns).

- [ ] **Step 9: Compile check**

Run: `python -m py_compile src/app/session_layout_ops.py`
Expected: OK.

- [ ] **Step 10: Commit**

```bash
git add src/app/session_layout_ops.py tests/test_session_layout_manager.py
git commit -m "feat(session-manager): two-column tree with device icons and session metadata"
```

---

### Task 2: Theme the session manager panel (additive QSS)

**Files:**
- Modify: `src/styles.py:3276-3278` (insert `/* Session manager panel */` block before `/* Global text selection */`)
- Test: `tests/test_session_layout_theme.py` (NEW — this file)

**Interfaces:**
- Consumes: `APP_STYLE` from `src/styles.py`; the workspace token values from the spec (all existing, e.g. `#020617`, `#0f172a`, `#08101d`, `#243244`, `#334155`, `#f8fafc`, `#a7b4c7`, `#111c2f`, `#24324a`, `#60a5fa`).
- Produces: `tests/test_session_layout_theme.py` (theme-block assertions, terminal state).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_session_layout_theme.py`:

```python
from __future__ import annotations

from src.styles import APP_STYLE


def test_session_manager_theme_block_present_before_text_selection() -> None:
    assert "/* Session manager panel */" in APP_STYLE
    assert APP_STYLE.index("/* Session manager panel */") < APP_STYLE.rindex(
        "/* Global text selection */"
    )


def test_session_manager_tree_is_dark_and_has_selected_state() -> None:
    block = APP_STYLE[APP_STYLE.index("/* Session manager panel */") :]
    assert "QTreeWidget#sessionManagerTree {" in block
    assert "background: #020617;" in block
    assert "border: none;" in block
    assert "QTreeWidget#sessionManagerTree::item:selected {" in block
    assert "background: #24324a;" in block


def test_session_manager_panel_and_strip_surfaces() -> None:
    block = APP_STYLE[APP_STYLE.index("/* Session manager panel */") :]
    assert "QWidget#sessionManagerPanel {" in block
    assert "background: transparent;" in block
    assert "QWidget#sessionManagerStrip {" in block
    assert "background: #0f172a;" in block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_session_layout_theme.py -v`
Expected: FAIL (block not present).

- [ ] **Step 3: Insert the QSS block** (`src/styles.py`, immediately after the `/* Unified component system */` block's last rule at line 3276, before `/* Global text selection */` at line 3278)

```css
/* Session manager panel */
QWidget#sessionManagerPanel {
    background: transparent;
}
QLabel#sessionManagerTitle {
    background: transparent;
    color: #f8fafc;
    font-weight: 700;
    font-size: 13px;
}
QLabel#sessionManagerCount {
    background: transparent;
    color: #a7b4c7;
    font-size: 11px;
    font-weight: 700;
}
QToolButton#sessionManagerCollapse,
QToolButton#sessionManagerExpand {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 6px;
    color: #a7b4c7;
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
    padding: 0px;
    font-size: 11px;
}
QToolButton#sessionManagerCollapse:hover,
QToolButton#sessionManagerExpand:hover {
    background: #111c2f;
    border-color: #60a5fa;
    color: #f8fafc;
}
QToolButton#sessionManagerCollapse:checked {
    background: #163326;
    border-color: #22c55e;
    color: #d8fff0;
}
QWidget#sessionManagerStrip {
    background: #0f172a;
    border: 1px solid #243244;
    border-radius: 8px;
}
QTreeWidget#sessionManagerTree {
    background: #020617;
    border: none;
    border-radius: 10px;
    alternate-background-color: #020617;
    outline: none;
    show-decoration-selected: 0;
}
QTreeWidget#sessionManagerTree::item {
    min-height: 26px;
    padding: 2px 4px;
    border: none;
    border-radius: 6px;
    color: #e5edf6;
}
QTreeWidget#sessionManagerTree::item:hover {
    background: #111c2f;
}
QTreeWidget#sessionManagerTree::item:selected {
    background: #24324a;
    color: #f8fafc;
}
QTreeWidget#sessionManagerTree::item:selected:active {
    background: #24324a;
}
QTreeWidget#sessionManagerTree QHeaderView::section {
    background: transparent;
    border: none;
    color: #a7b4c7;
}
QTreeWidget#sessionManagerTree QTreeView::branch {
    background: transparent;
}
```

- [ ] **Step 4: Run the new theme tests**

Run: `pytest tests/test_session_layout_theme.py -v`
Expected: PASS (all 3).

- [ ] **Step 5: Run the stylesheet regression tests**

Run: `pytest tests/test_session_credentials.py -k "style or theme or scrollbar or button" -q`
Expected: PASS (all `APP_STYLE` substring assertions still hold).

Run: `pytest tests/test_text_selection_theme.py tests/test_ui_unification.py -q`
Expected: PASS (`/* Global text selection */` still the last block; unification tests unaffected).

- [ ] **Step 6: Run the session-manager + theme tests together**

Run: `pytest tests/test_session_layout_manager.py tests/test_session_layout_theme.py -v`
Expected: PASS (6 + 3 = 9).

- [ ] **Step 7: Full test suite**

Run: `pytest -q`
Expected: 494 passed, 3 failed — the 3 failures are the known pre-existing set:
- `tests/test_auto_response.py::test_terminal_command_suggestion_uses_history_and_defaults`
- `tests/test_session_credentials.py::test_temporary_panel_uses_workspace_cards`
- `tests/test_session_credentials.py::test_web_pages_share_workspace_theme`
These are unrelated to this plan (they assert on `auto_response_editor.html` / auto-response suggestion content) and were failing before this plan began. Do NOT try to fix them; confirm your change introduces no NEW failures.

- [ ] **Step 8: Commit**

```bash
git add src/styles.py tests/test_session_layout_theme.py
git commit -m "style(session-manager): theme panel, tree, and strip with workspace skin"
```
