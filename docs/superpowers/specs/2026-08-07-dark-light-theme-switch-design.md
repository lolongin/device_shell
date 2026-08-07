# Dark/Light Theme Switch — Design

Date: 2026-08-07
Status: Approved (user)

## Goal

Add a theme switch in the workspace settings that toggles the whole app between
**深色 (OLED 亮)** and **浅色 (晨光)**. Covers every surface: native Qt widgets, Web
pages (home dashboard, terminal navigation, xterm terminal), and the canvas terminal.

## Decisions (confirmed with user)

- Full-surface switch: native + Web + terminal all follow the selected theme.
- Dark (OLED 亮) is the default; light (晨光) is optional.
- Approach: keep `APP_STYLE` (dark) unchanged (tests guard its values); generate a light
  variant via a dark→light color mapping and swap the applied stylesheet at runtime.
- Web theme switches via a per-page `window.setWorkspaceTheme(theme)` JS hook (bridge
  `runJavaScript`), updating `:root` CSS variables in place (no page reload flash).

## Current State (discovery)

- **Native**: `src/styles.py` `APP_STYLE` is one big QSS string with hardcoded dark colors
  (`#020617`, `#0f172a`, `#22c55e`, …). Applied once in `DeviceDesktopApp._build_window`
  (`setStyleSheet(APP_STYLE)`). Many tests assert `APP_STYLE` contains dark values
  (`#15803d`, `#22c55e`, `/* ... */` section comments) — so `APP_STYLE` must stay dark.
- **Tokens**: `src/theme_tokens.py` holds the dark token constants (`WORKSPACE_BG`, …),
  read by canvas terminal and Python-rendered HTML helpers.
- **Web**: `src/web/assets/workspace-theme.css` defines `:root` CSS variables consumed by
  `web_shell.html`, `device_navigation.html`, `auto_response_editor.html`,
  `xterm_terminal.html`. Pages already expose `window.setWebShellPayload` /
  `window.setDeviceNavigationPayload` (JSON payload bridges). xterm reads variables via
  `cssVar('--bg')` and builds its terminal theme from them.
- **Settings**: `build_settings_panel` (`session_layout_ops.py:635`) has a QFormLayout with
  layout/font/collapse controls; persisted via `desktop_state.py` (`session_layout` JSON).
- **Canvas terminal**: `src/widgets/terminal_canvas.py` uses `theme_tokens` colors for its
  ANSI palette.

## Design

### 1. Dark→light token mapping (`src/theme_tokens.py`)

Add a `DARK_TO_LIGHT` dict mapping every dark color literal that appears in `APP_STYLE` /
`workspace-theme.css` to its light counterpart. This is the single source of truth for the
light theme. (Values below are the 晨光 scheme from `palette_picker.html`; rgba status colors
mapped to light-appropriate values.)

```python
DARK_TO_LIGHT: dict[str, str] = {
    # base surfaces
    "#020617": "#f2f4f6",   # --bg
    "#0f172a": "#ffffff",   # --panel
    "#111c2f": "#e8ebef",   # --panel-2 / raised
    "#08101d": "#fafbfc",   # --input
    "#24324a": "#dbe6f2",   # --selected
    # borders
    "#243244": "#d5dae1",   # --line
    "#334155": "#c0c7d1",   # --line-strong
    "#475569": "#aeb6c2",   # --scroll-hover
    # text
    "#f8fafc": "#1c2128",   # --text
    "#a7b4c7": "#5a6470",   # --muted
    "#718096": "#87919d",   # --soft
    # accents
    "#22c55e": "#1f8a4c",   # --accent
    "#60a5fa": "#3a7ecf",   # --accent-2 / --blue
    "#fbbf24": "#b7791f",   # --warn
    "#f87171": "#c74a4a",   # --danger
    # text-selection
    "#315f9f": "#3a7ecf",   # --text-selection-bg
    # status soft/line rgba (dark) → light equivalents
    "rgba(34, 197, 94, 0.14)": "rgba(31, 138, 76, 0.12)",
    "rgba(34, 197, 94, 0.42)": "rgba(31, 138, 76, 0.38)",
    "rgba(251, 191, 36, 0.13)": "rgba(183, 121, 31, 0.14)",
    "rgba(251, 191, 36, 0.42)": "rgba(183, 121, 31, 0.38)",
    "rgba(96, 165, 250, 0.13)": "rgba(58, 126, 207, 0.13)",
    "rgba(96, 165, 250, 0.42)": "rgba(58, 126, 207, 0.38)",
    "rgba(113, 128, 150, 0.14)": "rgba(135, 145, 157, 0.16)",
    "rgba(113, 128, 150, 0.36)": "rgba(135, 145, 157, 0.32)",
    # legacy Linear/Vercel palette (kept so the whole APP_STYLE maps cleanly)
    "#080808": "#f2f4f6",
    "#0c0c0c": "#ffffff",
    "#1a1a1a": "#e3e6ea",
    "#262626": "#c8ced6",
    "#333333": "#aab2bd",
    "#111111": "#eef0f3",
    "#141414": "#fbfcfd",
    "#0e0e0e": "#f5f7f9",
    "#ededed": "#1a1f26",
    "#808080": "#6a737e",
    "#a0a0a0": "#5a6470",
    "#d0d0d0": "#3a424b",
    "#707070": "#8a939e",
    "#4d4d4d": "#a0a8b2",
}
```

### 2. Light stylesheet generation (`src/styles.py`)

Add `APP_STYLE_LIGHT` derived from `APP_STYLE` by replacing every mapped color:

```python
def _apply_light_mapping(style: str) -> str:
    out = style
    for dark, light in DARK_TO_LIGHT.items():
        out = out.replace(dark, light)
    return out

APP_STYLE_LIGHT = _apply_light_mapping(APP_STYLE)
```

`APP_STYLE` stays dark (tests keep passing). `APP_STYLE_LIGHT` is the light variant. A test
asserts: (a) `APP_STYLE_LIGHT` contains no dark base `#020617`, (b) contains light `#f2f4f6`,
(c) `APP_STYLE` is unchanged.

### 3. Theme state + runtime switch (native)

- `self.theme_mode: str = "dark"` (default) in `DeviceDesktopApp.__init__`.
- `apply_theme(mode)`: `self.setStyleSheet(APP_STYLE_LIGHT if mode == "light" else APP_STYLE)`,
  update canvas terminals' palettes, and notify each Web widget to swap its variables.
- Called at startup (from `load_desktop_state`, default dark) and on settings change.

### 4. Web theme switching (bridge)

Each Web widget (`WebShellWidget`, `DeviceNavigationWebWidget`, `XtermWebWidget`) gains a
`set_theme(mode: str)` method that runs JS on the page:

- Add to each HTML page a `window.setWorkspaceTheme = function(theme) { ... }` that sets
  `:root` CSS variables from a theme map (dark/light literal objects generated to match
  `DARK_TO_LIGHT`), and for xterm additionally re-applies `term.options.theme`.
- Python side: `view.page().runJavaScript("window.setWorkspaceTheme('light')")`.
- Call this from `apply_theme` for every loaded Web widget.

### 5. Settings UI + persistence

- `build_settings_panel`: add a "主题" `QComboBox` (深色 / 浅色), wired to `_settings_theme_changed`.
- `_settings_theme_changed(mode)`: set `self.theme_mode`, call `apply_theme`, persist.
- `desktop_state.py`: save/load `theme_mode` in the state JSON (new top-level `theme` key or
  inside `session_layout`); apply at startup.

### 6. Terminal palettes

- Canvas terminal: add `set_palette(light: bool)` that re-reads `theme_tokens` (dark or light
  constants) and repaints.
- xterm terminal: the CSS-variable update (step 4) already re-themes it; ensure it also
  refreshes on theme switch after load.

### 7. Files touched

- `src/theme_tokens.py` — add `DARK_TO_LIGHT` + light token constants.
- `src/styles.py` — add `_apply_light_mapping` + `APP_STYLE_LIGHT`.
- `src/app/session_layout_ops.py` — settings "主题" combo + `_settings_theme_changed`.
- `src/app/main_window.py` — `self.theme_mode`, `apply_theme`.
- `src/app/desktop_state.py` — persist/load `theme_mode`.
- `src/widgets/web_shell_widget.py`, `device_navigation_web_widget.py`, `xterm_web_widget.py` — `set_theme` bridge.
- `src/web/*.html` — `window.setWorkspaceTheme` hook.
- `src/widgets/terminal_canvas.py` — light palette support.
- `src/web/assets/workspace-theme.css` — optionally add a `.light` override or keep :root dark + JS override.
- Tests: new `tests/test_theme_switch.py`.

## Verification

- `pytest tests/test_theme_switch.py tests/test_session_credentials.py tests/test_text_selection_theme.py -q` — pass.
- `APP_STYLE` dark assertions still hold (unchanged).
- Full suite: 513 passed / 3 known pre-existing failures.
- Manual: settings → 主题 → 浅色; entire UI (native panels, home dashboard, terminal nav, xterm terminal) switches to light; switch back to dark restores.

## Out of scope

- More than two themes.
- Per-component theme overrides.
- Auto-following OS dark/light.
