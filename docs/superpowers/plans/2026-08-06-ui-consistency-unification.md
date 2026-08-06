# UI Consistency Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce visual fragmentation by moving the settings button to the activity-rail bottom in rail-button style and unifying scrollbar / button / panel / input-control appearance via an additive CSS layer.

**Architecture:** Three isolated changes. (1) The settings button moves from the status bar's bottom-right into the left activity rail, created through the existing `_new_activity_button` helper (rail icon style, non-checkable) with its popup menu attached via a renamed `attach_settings_menu`. (2) The xterm scrollbar is resized to match the Web capsule standard (10px, pill radius, 2px inset) while continuing to consume CSS variables. (3) A single new `/* Unified component system */` block is appended to `APP_STYLE` (before the last `/* Global text selection */` block) to style `QSpinBox`, unify two stray card radii, and style the settings-panel hint label.

**Tech Stack:** PySide6 (QToolButton, QMenu, QWidgetAction, QPainter icons), Python, CSS (Qt QSS + Web CSS variables), pytest.

## Global Constraints

(Values copied verbatim from `docs/superpowers/specs/2026-08-06-ui-consistency-unification-design.md`.)

- Additive-only CSS: do NOT edit existing rules in `src/styles.py`; only insert the new `/* Unified component system */` block.
- `/* Global text selection */` must remain the **last** block in `APP_STYLE` (constraint from `tests/test_text_selection_theme.py`). The new unified block goes immediately **before** it.
- Scrollbar capsule spec across all surfaces: 10px wide, thumb `#334155`, track `#08101d`, hover `#475569`, pill radius (`999px` in Web), 2px inset. Colors already agree — only xterm's 14px / 8px / 3px values change.
- xterm page must keep consuming CSS variables — no `:root` block, no hardcoded palette literals (constraint from `tests/test_session_credentials.py::test_web_pages_link_shared_theme`).
- Settings button is a rail icon button: object name `activityRailButton`, 34×34, `ToolButtonIconOnly`, non-checkable, `InstantPopup` menu with the existing settings panel.
- Qt scrollbar (`src/styles.py`) and Web scrollbar (`workspace-theme.css`) are already at spec and are NOT modified.
- Icon-button radius spread (5/6/7px) is intentionally left alone (spec: no forced radius across the family).

## File Structure

- `src/app/main_window.py` — settings-button wiring moves here: `_build_activity_rail` creates the button (stores `self.activity_rail`), `_build_window` no longer attaches it to the status bar, `_new_activity_button` gains a `checkable` param, `_activity_icon` gains a `"settings"` gear branch.
- `src/app/session_layout_ops.py` — `build_settings_button()` becomes `attach_settings_menu(self, button: QToolButton)` (builds menu + panel, applies to a caller-created button, stores `self.settings_button`).
- `src/styles.py` — one additive `/* Unified component system */` block inserted before `/* Global text selection */`.
- `src/web/xterm_terminal.html` — xterm viewport scrollbar resized to capsule spec.
- `tests/test_session_layout_settings.py` — settings-button placement test updated.
- `tests/test_ui_unification.py` — NEW: string-level tests for the xterm scrollbar and the unified CSS block.

---

### Task 1: Move the settings button into the activity rail

**Files:**
- Modify: `src/app/session_layout_ops.py:544-562` (rename + rework `build_settings_button`)
- Modify: `src/app/main_window.py:718-775` (`_build_activity_rail`), `:777-790` (`_new_activity_button`), `:860-868` (`_activity_icon` settings branch), `:468-471` (`_build_window` status bar)
- Test: `tests/test_session_layout_settings.py:18-24`

**Interfaces:**
- Consumes: `self._new_activity_button(icon_name: str, tooltip: str, *, checked: bool = False, checkable: bool = True) -> QToolButton` (already exists; gains `checkable`), `self._activity_icon(kind: str, color: str = "#718096")`, `self.build_settings_panel() -> QWidget` (unchanged).
- Produces: `SessionLayoutOpsMixin.attach_settings_menu(self, button: QToolButton) -> QToolButton` — attaches the settings popup menu/panel to the given button and stores it as `self.settings_button`. `self.activity_rail: QFrame` on `DeviceDesktopApp`.

- [ ] **Step 1: Update the failing test**

Replace the body of `test_settings_button_created_and_attached_to_status_bar` in `tests/test_session_layout_settings.py:18-24` with a placement test for the rail:

```python
def test_settings_button_sits_at_activity_rail_bottom(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.settings_button is not None
    assert window.settings_button.objectName() == "activityRailButton"
    assert window.settings_button.parent() is window.activity_rail
    assert not window.settings_button.isCheckable()
    window.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_layout_settings.py::test_settings_button_sits_at_activity_rail_bottom -v`
Expected: FAIL — the old code still builds `sessionSettingsButton` and never sets `activity_rail`, so the `objectName() == "activityRailButton"` assert fails (or `AttributeError: ... activity_rail`). Either failure is the correct red signal.

- [ ] **Step 3: Rework the settings-button builder** (`src/app/session_layout_ops.py:544-562`)

Replace `build_settings_button` (the whole method) with:

```python
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
```

(`QToolButton` is already imported at module top; `from __future__ import annotations` is present, so the annotation works without a local import.)

- [ ] **Step 4: Add `checkable` param to `_new_activity_button`** (`src/app/main_window.py:777-790`)

Change the signature to `def _new_activity_button(self, icon_name: str, tooltip: str, *, checked: bool = False, checkable: bool = True) -> QToolButton:` and replace `button.setCheckable(True)` with `button.setCheckable(checkable)`.

- [ ] **Step 5: Add the gear icon branch** (`src/app/main_window.py:860-868`)

Insert an `elif kind == "settings":` branch before the trailing `else:` in `_activity_icon`:

```python
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
```

- [ ] **Step 6: Wire the rail and detach from the status bar** (`src/app/main_window.py`)

In `_build_activity_rail` (line ~719), right after `rail.setObjectName("activityRail")`, add `self.activity_rail = rail`. After `layout.addStretch(1)` (line ~757), add:

```python
self.settings_button = self._new_activity_button(
    "settings",
    "工作台设置",
    checkable=False,
)
self.attach_settings_menu(self.settings_button)
layout.addWidget(self.settings_button)
```

In `_build_window`, delete the line `status_bar.addPermanentWidget(self.build_settings_button())` (line ~471).

- [ ] **Step 7: Run the settings tests**

Run: `pytest tests/test_session_layout_settings.py -v`
Expected: PASS (all 4 tests, including the updated placement test).

- [ ] **Step 8: Run the layout/rail smoke tests**

Run: `pytest tests/test_session_credentials.py -k "activity_rail" -v`
Expected: PASS (tests reference `activity_home_button`, unaffected by the new uncheckable button).

- [ ] **Step 9: Commit**

```bash
git add src/app/main_window.py src/app/session_layout_ops.py tests/test_session_layout_settings.py
git commit -m "feat(ui): move settings button to activity rail bottom in rail style"
```

---

### Task 2: Align xterm scrollbar to the Web capsule standard

**Files:**
- Modify: `src/web/xterm_terminal.html:54-76` (viewport scrollbar rules)
- Test: `tests/test_ui_unification.py` (NEW — this file)

**Interfaces:**
- Produces: `tests/test_ui_unification.py` with `test_xterm_scrollbar_matches_workspace_capsule` (used again in Task 3 for the CSS-block tests).
- Consumes: the Web capsule spec from Global Constraints.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ui_unification.py`:

```python
from __future__ import annotations

from pathlib import Path

from src.styles import APP_STYLE


def _web_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "web"


def test_xterm_scrollbar_matches_workspace_capsule() -> None:
    page = (_web_root() / "xterm_terminal.html").read_text(encoding="utf-8")
    viewport = page[page.index(".xterm .xterm-viewport") :]
    assert "scrollbar-width: thin;" in viewport
    scrollbar_block = viewport[viewport.index("::-webkit-scrollbar") :]
    assert "width: 10px;" in scrollbar_block
    assert "border: 2px solid var(--input);" in scrollbar_block
    assert "border-radius: 999px;" in scrollbar_block
```

(APP_STYLE is imported here so the file's helper layout is shared with Task 3.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_unification.py::test_xterm_scrollbar_matches_workspace_capsule -v`
Expected: FAIL — current values are `scrollbar-width: auto`, `width: 14px`, `border: 3px solid var(--input)`, `border-radius: 8px`.

- [ ] **Step 3: Resize the xterm scrollbar** (`src/web/xterm_terminal.html:54-76`)

In `.xterm .xterm-viewport`, change `scrollbar-width: auto;` → `scrollbar-width: thin;`.
In `.xterm .xterm-viewport::-webkit-scrollbar`, change `width: 14px;` → `width: 10px;`.
In `.xterm .xterm-viewport::-webkit-scrollbar-thumb`, change `border: 3px solid var(--input);` → `border: 2px solid var(--input);` and `border-radius: 8px;` → `border-radius: 999px;`.

All colors remain `var(--...)` — no literals, no `:root`.

- [ ] **Step 4: Run the new test + web theme regression**

Run: `pytest tests/test_ui_unification.py::test_xterm_scrollbar_matches_workspace_capsule -v`
Expected: PASS.

Run: `pytest tests/test_session_credentials.py -k "web_pages_link_shared_theme" -v`
Expected: PASS (xterm page still has no `:root` / palette literals).

- [ ] **Step 5: Commit**

```bash
git add src/web/xterm_terminal.html tests/test_ui_unification.py
git commit -m "style(ui): align xterm scrollbar with workspace capsule spec"
```

---

### Task 3: Add the unified component system CSS layer

**Files:**
- Modify: `src/styles.py:3239-3240` (insert unified block before `/* Global text selection */`)
- Test: `tests/test_ui_unification.py` (extend)

**Interfaces:**
- Consumes: `APP_STYLE` from `src/styles.py`; the Web capsule / token values from Global Constraints.
- Produces: none (terminal state).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_unification.py`:

```python
def test_unified_component_block_lands_before_global_text_selection() -> None:
    assert "/* Unified component system */" in APP_STYLE
    assert APP_STYLE.index("/* Unified component system */") < APP_STYLE.rindex(
        "/* Global text selection */"
    )


def test_spinbox_uses_workspace_input_surface() -> None:
    block = APP_STYLE[APP_STYLE.index("/* Unified component system */") :]
    assert "QSpinBox,\nQAbstractSpinBox {" in block
    assert "background: #08101d;" in block
    assert "border: 1px solid #243244;" in block
    assert "border-radius: 8px;" in block


def test_server_cards_radius_unified_to_12() -> None:
    block = APP_STYLE[APP_STYLE.index("/* Unified component system */") :]
    assert "QFrame#serverCard,\nQFrame#serverGroupHeader {" in block
    assert "border-radius: 12px;" in block


def test_settings_hint_label_styled() -> None:
    block = APP_STYLE[APP_STYLE.index("/* Unified component system */") :]
    assert "QLabel#settingsHint {" in block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_unification.py -v`
Expected: `test_xterm_scrollbar_matches_workspace_capsule` PASSES; the four new tests FAIL (block not present).

- [ ] **Step 3: Insert the unified CSS block** (`src/styles.py:3240`)

Edit so the block sits immediately before `/* Global text selection */` (it will win the cascade for everything it touches; text-selection stays the final block):

```css
/* Unified component system */
QSpinBox,
QAbstractSpinBox {
    background: #08101d;
    border: 1px solid #243244;
    border-radius: 8px;
    color: #f8fafc;
    padding: 5px 8px;
    selection-background-color: #315f9f;
    selection-color: #f8fafc;
    min-height: 22px;
}
QSpinBox:focus,
QAbstractSpinBox:focus {
    border-color: #60a5fa;
}
QSpinBox::up-button,
QSpinBox::down-button {
    background: transparent;
    border: none;
    width: 18px;
}
QFrame#serverCard,
QFrame#serverGroupHeader {
    border-radius: 12px;
}
QLineEdit#detailValueInput,
QLineEdit#commandFindInput,
QLineEdit#commandReplaceInput {
    border-radius: 8px;
}
QLabel#settingsHint {
    background: transparent;
    color: #a7b4c7;
    font-size: 11px;
    line-height: 1.4;
}

/* Global text selection */
```

- [ ] **Step 4: Run the full UI-unification test file**

Run: `pytest tests/test_ui_unification.py -v`
Expected: PASS (all 5 tests).

- [ ] **Step 5: Run the stylesheet regression tests**

Run: `pytest tests/test_session_credentials.py -k "style or theme or scrollbar or button" -v`
Expected: PASS (all `APP_STYLE` substring assertions still hold — existing rules untouched).

Run: `pytest tests/test_text_selection_theme.py -v`
Expected: PASS (`/* Global text selection */` still the last block).

- [ ] **Step 6: Full test suite**

Run: `pytest`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/styles.py tests/test_ui_unification.py
git commit -m "style(ui): add unified component system layer for spinbox, cards, and settings hint"
```
