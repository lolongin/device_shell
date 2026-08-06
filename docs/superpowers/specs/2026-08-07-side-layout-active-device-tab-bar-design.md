# Side-Layout Active-Device Session Tab Bar — Design

Date: 2026-08-07
Status: Approved (user)

## Goal

In the **side (right)** session layout, keep the **active device's** session tab bar
visible at the top of the terminal so the operator can switch between that device's
sessions (telnet/ssh/…) directly. The device-level tab bar stays hidden — cross-device
navigation lives in the right session manager tree. This complements the existing fix
(commit `1fb2b74`) that hides freshly-created split tab bars in side layout.

## Decisions (confirmed with user)

- In side layout the top shows the **current active device's session tab bar** (the
  `deviceSessionTabs` child tab bar of the currently-active device tab). Other devices'
  session tab bars stay hidden, as does the device-level bar.
- The right session-manager tree keeps its role: **cross-device navigation and global
  overview**.
- Top layout behavior is unchanged.

## Current State (discovery)

- `set_session_tab_bars_visible(visible)` (`src/app/session_layout_ops.py:473`) is the
  single place that toggles tab bars:
  ```python
  self.session_tab_widget.tabBar().setVisible(visible)
  for device_tab in self.device_tabs_by_id.values():
      for tabs in self.session_tab_widgets_for_device(device_tab):
          tabs.tabBar().setVisible(visible)
  ```
  Called only from `apply_session_layout_state()` (`:558`) with `visible = not side`.
  So in side layout **all** tab bars (device-level + every device's session bars) are hidden.
- `current_device_tab_state()` (`src/app/session_ops.py:3106`) returns the active
  `DeviceTabState` (the one whose `page` is `session_tab_widget.currentWidget()`), or `None`.
- `session_tab_widgets_for_device(device_tab)` (`:3125`) returns the device's child
  `QTabWidget` list (split panes).
- Layout switching / device activation re-runs `apply_session_layout_state()`, which calls
  `set_session_tab_bars_visible` — so active-device changes are covered by that existing path.
- Commit `1fb2b74` made `create_session_tab_widget` hide a new split tab bar when
  `session_tab_layout == "side"`. Under the new design that stays correct: a new split tab
  bar on the **active** device should become visible once layout re-applies (via the
  `is_active` branch); a new split tab bar on an **inactive** device stays hidden.

## Design

### 1. Rework `set_session_tab_bars_visible` (`src/app/session_layout_ops.py:473-478`)

```python
def set_session_tab_bars_visible(self, visible: bool) -> None:
    """Show/hide the top device tab bar and per-device session tab bars.

    In the side layout the device-level bar is hidden (cross-device navigation
    lives in the right session manager), but the ACTIVE device's session tabs
    stay visible so the operator can switch between that device's sessions at
    the top. In the top layout everything follows ``visible``.
    """
    side = getattr(self, "session_tab_layout", "top") == "side"
    self.session_tab_widget.tabBar().setVisible(visible and not side)
    active = self.current_device_tab_state() if side else None
    for device_tab in self.device_tabs_by_id.values():
        is_active = device_tab is active
        for tabs in self.session_tab_widgets_for_device(device_tab):
            tabs.tabBar().setVisible(visible and (not side or is_active))
```

Notes:
- `current_device_tab_state()` is only called in side mode (cheap guard).
- When no device tab is active (`active is None`), no session tab bar shows — correct.
- `apply_session_layout_state()` re-applies visibility whenever the active device changes
  (device tab `currentChanged`, right-tree activation, layout toggle), so the active
  device's bar appears/disappears correctly without new wiring.

### 2. Tests

- Update `tests/test_session_layout_visibility.py`:
  - Existing `test_split_tab_bar_hidden_in_side_layout` — keep, but re-scope: the split tab
    bar on an **inactive** device stays hidden; add a companion test that the active
    device's split tab bar is **visible** in side layout.
  - Existing `test_split_tab_bar_visible_in_top_layout` — keep as-is.
- New tests:
  - `test_side_layout_shows_only_active_device_session_bars`: with two open device tabs,
    side layout → active device's session tab bar visible, inactive device's session tab
    bar hidden, device-level bar hidden.
  - `test_side_layout_no_active_device_hides_all_session_bars`: side layout with device
    tabs but no current widget → all session bars hidden.
- Regression: `tests/test_session_layout_manager.py`, `test_session_layout_context_menu.py`,
  `test_session_layout_memory.py`, `test_session_layout_search.py`,
  `test_desktop_state_session_layout.py`, `test_session_layout_theme.py` all stay green.

## Files touched

- `src/app/session_layout_ops.py` — rework `set_session_tab_bars_visible`.
- `tests/test_session_layout_visibility.py` — extend.

## Verification

- `pytest tests/test_session_layout_visibility.py tests/test_session_layout_manager.py -v` — all pass.
- Full suite: 501 passed / 3 known pre-existing failures (unchanged).
- Manual: side layout, open two devices with sessions → active device's top tab bar shows
  its sessions; switching device via right tree swaps which session bar shows; device-level
  bar never shows in side layout.

## Out of scope

- Changing top-layout behavior.
- Altering the right session-manager tree role or structure.
- Re-introducing device-level tab bars in side layout.
