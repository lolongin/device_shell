# UI Consistency Unification — Design

Date: 2026-08-06
Status: Approved (user)

## Goal

Reduce the perceived visual fragmentation across the Device TUI desktop shell. The
two named pain points are the scrollbar rendering (four different appearances across
Qt / Web / xterm) and the settings button (unstyled, stuck in the status bar's
bottom-right, visually disconnected). The user additionally wants the button /
panel / input-control families harmonized, all as a **precise, additive** change —
no wholesale restructuring of the layered `styles.py` cascade.

## Decisions (confirmed with user)

- Scope: **precise unification**, not a full stylesheet rewrite.
- Scrollbar look: **capsule style** (narrow, pill radius, thin inset) applied to all surfaces.
- Settings button: move to **bottom of the left activity rail**, styled like the other
  rail icon buttons (`activityRailButton`).
- Also harmonize: button family, panel/card radius, and input controls.

## Current State (discovery)

### Scrollbars — four renderers, slightly different
- Qt native (`src/styles.py`): 10px wide, 5px radius, no inset — already close to capsule.
- Web (`src/web/assets/workspace-theme.css`): 10px, `999px` pill radius, 2px inset — the target standard.
- **xterm (`src/web/xterm_terminal.html`)**: 14px wide, 8px radius, 3px inset — the outlier.
- canvas terminal: reuses the Qt `terminalScrollBar` styles → auto-aligned with Qt.

Colors already agree everywhere: track `#08101d`, thumb `#334155`, hover `#475569`.

### Settings button
- Built by `SessionLayoutOpsMixin.build_settings_button()` (`src/app/session_layout_ops.py`).
- Added to the status bar bottom-right via `status_bar.addPermanentWidget(...)` in
  `DeviceDesktopApp._build_window()` (`src/app/main_window.py`).
- Text-only `⚙`, `InstantPopup`, `QWidgetAction` panel menu (session layout, font size, collapse).
- **No stylesheet rule** for `sessionSettingsButton` — renders as raw default QToolButton.

### Button / panel / input fragmentation
- Icon-button family already broadly unified by the "Global button system" layer, but
  radius varies 5/6/7px across member buttons.
- `serverCard` / `serverGroupHeader` use 8px radius while sibling cards use 12px.
- `QSpinBox` has **no global style** (settings panel font-size spinner renders unstyled).
- `settingsHint` label in the settings panel is unstyled.

### Tests that constrain changes
- `tests/test_session_layout_settings.py::test_settings_button_created_and_attached_to_status_bar`
  asserts `settings_button.parent() is window.statusBar()` — must be updated for the move.
- `tests/test_session_credentials.py` asserts many `APP_STYLE` substrings (comments like
  `/* Global button system */`, `/* Data tables and scrollbars */`, plus specific rules).
  Additive-only changes keep these passing.
- `tests/test_text_selection_theme.py` requires the `/* Global text selection */` block to
  stay the **last** block in `APP_STYLE`. New unification block must be inserted **before** it.
- Web theme test (`test_session_credentials.py` ~1744) asserts xterm page has no `:root`
  block and no hardcoded palette literals — xterm must keep consuming CSS variables.

## Design

### 1. Settings button → activity rail bottom (styled like rail buttons)

**Location & wiring** (`src/app/main_window.py`):
- Remove `status_bar.addPermanentWidget(self.build_settings_button())` from `_build_window()`.
- Store the rail as an attribute: `self.activity_rail = rail` at the top of `_build_activity_rail()`
  (it is currently returned but not retained — the updated test needs the handle).
- In `_build_activity_rail()`, after `layout.addStretch(1)`, insert the settings button.
  Reuse the existing `_new_activity_button("settings", "工作台设置")` helper so the button is
  a rail-style icon button (34×34, `activityRailButton` object name, `ToolButtonIconOnly`).
- It must be **non-checkable** (it opens a popup, it does not toggle a panel). The helper
  defaults to `checkable=True`; override to `False` for this button.
- Menu interaction stays as-is: `InstantPopup` + `QWidgetAction` settings panel
  (`build_settings_panel()` in `session_layout_ops.py`).

**Icon** (`src/app/main_window.py::_activity_icon`): add a `"settings"` gear drawing branch
(16×16 gear, same 1.7px `#718096` stroke as sibling icons).

**Builder adjustment** (`src/app/session_layout_ops.py`): refactor `build_settings_button()`
so the rail wiring is clean — the button keeps its popup menu, but its creation is driven
from the rail. The existing method can be simplified to build only the menu+panel and apply
it to the rail-created button, or be replaced by a small `attach_settings_menu(button)` helper.

**Test update** (`tests/test_session_layout_settings.py`): change the parent assertion from
`window.statusBar()` to the activity rail (e.g. `window.activity_rail`), and assert the
button object name is `activityRailButton`.

### 2. Scrollbar — capsule unification across all surfaces

- `src/web/xterm_terminal.html`: `.xterm .xterm-viewport::-webkit-scrollbar` width 14px → 10px;
  thumb `border-radius` 8px → `999px`; `border` 3px → 2px solid `var(--input)`; and the
  `scrollbar-width` on the viewport from `auto` → `thin` (matches Web). All colors remain CSS
  variables. **No local literals, no `:root`.**
- Qt native (`src/styles.py`): already capsule-consistent (10px / 5px radius). Left unchanged.
- Web (`workspace-theme.css`): the standard; unchanged.

### 3. Unified component system — final additive layer

Append a single new block in `src/styles.py` titled `/* Unified component system */`,
inserted **before** the `/* Global text selection */` final block (test constraint). It wins
the cascade for everything it touches while leaving prior layers intact:

- **Inputs**: give `QSpinBox` (and `QAbstractSpinBox`) the same surface as `QLineEdit` /
  `QComboBox` — background `#08101d`, border `1px solid #243244`, radius 8px, color `#f8fafc`,
  `:focus` border `#60a5fa`, shared `#315f9f` selection. Also normalize stray 7px-radius
  `QLineEdit#detailValueInput` and the find/replace inputs to 8px.
- **Panels/cards**: `QFrame#serverCard`, `QFrame#serverGroupHeader` radius 8px → 12px to match
  sibling cards. Keep their accent left-borders.
- **Settings panel**: `QLabel#settingsHint` → muted text color; scope a rule so `QSpinBox`
  inside the settings menu matches the rest.
- **Icon buttons**: no forced radius change — the activity rail button now inherits the
  existing `activityRailButton` rules, which are already uniform (7px radius, 32×32). Leave the
  5/6/7px spread alone unless a check shows a real outlier after the settings move.

### 4. Tokens

No new tokens needed. Scrollbar colors already live in `theme_tokens.py` /
`workspace-theme.css` (`--scroll-hover`). xterm continues to consume CSS variables.

## Files touched

- `src/app/main_window.py` — rail wiring, settings icon, remove status-bar attachment.
- `src/app/session_layout_ops.py` — settings-button builder refactor (menu attach).
- `src/styles.py` — additive `/* Unified component system */` layer (before Global text selection).
- `src/web/xterm_terminal.html` — capsule scrollbar sizing.
- `tests/test_session_layout_settings.py` — parent/object-name assertion update.

## Verification

- `python -m py_compile src\*.py` and the changed modules.
- `pytest` full run — all existing `APP_STYLE` substring tests must stay green, and the
  updated settings-button test must pass.
- Manual/`run` check: settings gear sits at the bottom-left rail, opens the same panel; xterm
  scrollbar is 10px capsule, visually consistent with Web and Qt surfaces.

## Out of scope

- Rewriting/restructuring the layered `styles.py` cascade.
- Changing the Web `workspace-theme.css` scrollbar (it is the standard).
- Forcing a single radius across the entire icon-button family.
