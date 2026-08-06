# Side-Layout Active-Device Session Tab Bar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the side (right) session layout, keep the **active device's** session tab bar visible at the top of the terminal so the operator can switch between that device's sessions, while the device-level bar and other devices' session bars stay hidden (cross-device navigation lives in the right session manager tree).

**Architecture:** One method change in `set_session_tab_bars_visible` (`src/app/session_layout_ops.py`) plus one call-site fix in `apply_session_layout_state`. The method becomes layout-aware: in side layout it hides the device-level bar and shows only the active device's session bars; in top layout it shows everything. Because the method now encapsulates the layout rule, the call site must pass `True` (not `not side`) — otherwise the active device's bar would be hidden by the `visible=False` it currently receives in side layout.

**Tech Stack:** PySide6 (QTabWidget/QTabBar), Python, pytest.

## Global Constraints

(Values copied verbatim from `docs/superpowers/specs/2026-08-07-side-layout-active-device-tab-bar-design.md`, with one plan-level correction noted inline.)

- In side layout: the **device-level** tab bar (`session_tab_widget.tabBar()`) stays hidden.
- In side layout: only the **active device's** session tab bars are visible; all other devices' session tab bars are hidden.
- In top layout: behavior unchanged — all tab bars follow the `visible` flag.
- `current_device_tab_state()` (`src/app/session_ops.py:3106`) identifies the active device (the one whose `page` is `session_tab_widget.currentWidget()`); returns `None` when no device tab is active, in which case no session bar shows.
- **PLAN CORRECTION (deviates from spec's call-site implication):** `apply_session_layout_state` currently calls `set_session_tab_bars_visible(not side)`. With the new method body this must change to `set_session_tab_bars_visible(True)` — the method now decides layout-specific visibility itself. Keeping `not side` would pass `False` in side layout and hide the active device's bar too (the spec's method body would be dead code). This is required for the feature to work.
- Commit `1fb2b74` behavior is preserved: a freshly-created split tab bar starts hidden in side layout (via `create_session_tab_widget`); once the layout re-applies, the active device's split bar becomes visible through this method.
- Full suite expectation: 501 passed / 3 known pre-existing failures (auto_response suggestion, temporary-panel cards, web-pages theme) — do NOT fix them; confirm no NEW failures.

---

### Task 1: Show the active device's session tab bar in side layout

**Files:**
- Modify: `src/app/session_layout_ops.py:473-478` (`set_session_tab_bars_visible`), `:558` (call site in `apply_session_layout_state`)
- Test: `tests/test_session_layout_visibility.py` (extend)

**Interfaces:**
- Consumes: `self.current_device_tab_state() -> DeviceTabState | None` (exists), `self.session_tab_widgets_for_device(device_tab) -> list[QTabWidget]` (exists), `self.session_tab_layout` (str, `"top"` or `"side"`).
- Produces: `set_session_tab_bars_visible(visible: bool) -> None` — layout-aware visibility; callers pass `True` and the method applies the top/side rule.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_session_layout_visibility.py`:

```python
def _setup_devices(window: DeviceDesktopApp, count: int = 2) -> list[object]:
    from src._sample_data import sample_devices

    devices = sample_devices()[:count]
    for index, device in enumerate(devices):
        device.id = f"vis-device-{index}"
        device.name = f"可见设备 {index + 1}"
    window.devices = devices
    window.rebuild_device_indexes()
    return devices


def _open_session(window: DeviceDesktopApp, device: object, title: str) -> None:
    window.ensure_session_tab(
        kind="simulated",
        device=device,
        host="10.0.0.1",
        port=22,
        username="admin",
        password="secret",
        title=title,
        suppress_initial_error=True,
    )


def _session_tabs_for(window: DeviceDesktopApp, device_id: str):
    device_tab = window.device_tabs_by_id[device_id]
    return window.session_tab_widgets_for_device(device_tab)[0]


def test_side_layout_shows_only_active_device_session_bars(app: QApplication) -> None:
    """In side layout the active device's session tab bar shows; inactive
    devices' bars and the device-level bar stay hidden."""
    _ = app
    window = DeviceDesktopApp()
    devices = _setup_devices(window, count=2)
    _open_session(window, devices[0], "会话 A")
    _open_session(window, devices[1], "会话 B")  # B becomes the active device
    window.session_tab_layout = "side"
    window.apply_session_layout_state()
    window.show()
    QApplication.processEvents()
    tabs_a = _session_tabs_for(window, devices[0].id)
    tabs_b = _session_tabs_for(window, devices[1].id)
    try:
        assert not window.session_tab_widget.tabBar().isVisible()
        assert tabs_b.tabBar().isVisible()
        assert not tabs_a.tabBar().isVisible()
    finally:
        window.close()


def test_side_layout_hides_inactive_device_without_sessions(app: QApplication) -> None:
    """A device tab with no sessions is inactive; its (empty) session bar stays
    hidden while the active device's bar shows."""
    _ = app
    window = DeviceDesktopApp()
    devices = _setup_devices(window, count=2)
    window.ensure_device_tab(devices[0])  # open device tab, no sessions
    window.ensure_device_tab(devices[1])  # active device
    _open_session(window, devices[1], "会话 B")
    window.session_tab_layout = "side"
    window.apply_session_layout_state()
    window.show()
    QApplication.processEvents()
    tabs_a = _session_tabs_for(window, devices[0].id)
    tabs_b = _session_tabs_for(window, devices[1].id)
    try:
        assert not window.session_tab_widget.tabBar().isVisible()
        assert tabs_b.tabBar().isVisible()
        assert not tabs_a.tabBar().isVisible()
    finally:
        window.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_session_layout_visibility.py -v`
Expected: `test_side_layout_shows_only_active_device_session_bars` and
`test_side_layout_hides_inactive_device_without_sessions` FAIL — current code hides all
session bars in side layout (both `tabs_a` and `tabs_b` are hidden), so
`assert tabs_b.tabBar().isVisible()` fails. The two existing split-widget tests still PASS
(they're unaffected by this method).

- [ ] **Step 3: Rework `set_session_tab_bars_visible`** (`src/app/session_layout_ops.py:473-478`)

Replace the whole method:

```python
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
```

- [ ] **Step 4: Fix the call site** (`src/app/session_layout_ops.py:558`)

In `apply_session_layout_state`, change:

```python
        self.set_session_tab_bars_visible(not side)
```

to:

```python
        self.set_session_tab_bars_visible(True)
```

(This is the plan's correction: the method now decides layout-specific visibility itself, so
the caller always passes `True`. With `not side` the side-layout call would pass `False` and
hide the active device's bar — the new feature would be dead code.)

- [ ] **Step 5: Run the visibility tests**

Run: `pytest tests/test_session_layout_visibility.py -v`
Expected: PASS (4 tests — 2 existing split-widget + 2 new).

- [ ] **Step 6: Run the session-layout regression tests**

Run: `pytest tests/test_session_layout_manager.py tests/test_session_layout_context_menu.py tests/test_session_layout_memory.py tests/test_session_layout_search.py tests/test_desktop_state_session_layout.py tests/test_session_layout_theme.py -q`
Expected: PASS (no behavior regression — top layout unchanged; side layout panel/memory/context unaffected).

- [ ] **Step 7: Compile check**

Run: `python -m py_compile src/app/session_layout_ops.py tests/test_session_layout_visibility.py`
Expected: OK.

- [ ] **Step 8: Full test suite**

Run: `pytest -q`
Expected: 501 passed / 3 failed — the 3 failures are the known pre-existing set
(`test_auto_response.py::test_terminal_command_suggestion_uses_history_and_defaults`,
`test_session_credentials.py::test_temporary_panel_uses_workspace_cards`,
`test_session_credentials.py::test_web_pages_share_workspace_theme`). Confirm your change
introduces no NEW failures.

- [ ] **Step 9: Commit**

```bash
git add src/app/session_layout_ops.py tests/test_session_layout_visibility.py
git commit -m "feat(session-layout): show active device's session tab bar in side layout"
```
