# Device TUI Design System

This file is the source of truth for the desktop workspace visual language.
The app is a PySide6 desktop shell with Web-rendered home, device navigation,
auto-response editor, and xterm terminal surfaces.

## Product Direction

- Make the UI feel like a polished Web operations dashboard inside the desktop app.
- Keep the home screen as the full device pool overview.
- Keep terminal sessions as the operator workspace, with the left device pool shown only as a compact session navigation surface.
- Preserve right-click operations by routing all native menus through the workspace menu factory and all Web device rows through QtWebChannel bridge requests.

## Theme Tokens

Use these colors across Web CSS, Qt style sheets, canvas terminal rendering, and generated HTML snippets.

| Token | Value | Usage |
| --- | --- | --- |
| Background | `#020617` | App background, terminal surface |
| Panel | `#0f172a` | Cards, grouped panels, menus |
| Panel Raised | `#111c2f` | Hover rows, secondary surfaces |
| Input | `#08101d` | Inputs, inactive controls |
| Line | `#243244` | Panel borders, table dividers |
| Strong Line | `#334155` | Control borders, scroll thumbs |
| Text | `#f8fafc` | Primary text |
| Muted Text | `#a7b4c7` | Secondary text |
| Soft Text | `#718096` | Disabled and low-emphasis text |
| Accent | `#22c55e` | Primary action, connected, idle |
| Accent Blue | `#60a5fa` | Focus ring, pipeline, links |
| Warning | `#fbbf24` | Occupied, caution |
| Warning Text | `#f8e7a1` | Compact warning metadata |
| Danger | `#f87171` | Errors, destructive actions |
| Success Text | `#d8fff0` | Success button and chip foreground |
| Danger Text | `#fecaca` | Danger button and destructive foreground |
| Selected | `#24324a` | Selected rows and text selection |
| Scroll Hover | `#475569` | Web and terminal scrollbar hover |
| Terminal ANSI Magenta | `#c4b5fd` | xterm ANSI magenta |
| Terminal ANSI Cyan | `#91d7e3` | xterm ANSI cyan |
| Terminal Bright Red | `#fca5a5` | xterm bright red |
| Terminal Bright Green | `#86efac` | xterm bright green |
| Terminal Bright Yellow | `#f5d99a` | xterm bright yellow |
| Terminal Bright Blue | `#b7c8ff` | xterm bright blue |
| Terminal Bright Magenta | `#ddd6fe` | xterm bright magenta |
| Terminal Bright Cyan | `#b5eff7` | xterm bright cyan |
| Terminal Bright White | `#f6f8fb` | xterm bright white |
| Overlay | `rgba(2, 6, 23, 0.72)` | Modal backdrop |
| Home Accent Glow | `rgba(34, 197, 94, 0.08)` | Home dashboard radial glow |
| Home Blue Glow | `rgba(96, 165, 250, 0.10)` | Home dashboard radial glow |
| Surface Top | `rgba(9, 12, 16, 0.86)` | Web top bar surface |
| Surface Filter | `rgba(8, 12, 17, 0.92)` | Web filter bar surface |
| Surface Card | `rgba(13, 17, 23, 0.94)` | Web card surface |
| Status Idle Line | `rgba(34, 197, 94, 0.42)` | Idle status capsule border |
| Status Occupied Soft | `rgba(251, 191, 36, 0.13)` | Occupied status capsule background |
| Status Pipeline Soft | `rgba(96, 165, 250, 0.13)` | Pipeline status capsule background |
| Status Other Soft | `rgba(113, 128, 150, 0.14)` | Other status capsule background |
| Empty Background | `rgba(8, 16, 29, 0.55)` | Empty state placeholder surface |

## CSS Custom Properties

Every Web page should consume these variables from `src/web/assets/workspace-theme.css`.
When adding a new custom property, update this list and the theme tests together.

- `--bg`
- `--panel`
- `--panel-2`
- `--line`
- `--line-strong`
- `--text`
- `--muted`
- `--soft`
- `--accent`
- `--accent-2`
- `--blue`
- `--warn`
- `--danger`
- `--selected`
- `--input`
- `--input-quiet`
- `--success-soft`
- `--success-line`
- `--success-text`
- `--danger-soft`
- `--danger-line`
- `--danger-text`
- `--warn-text`
- `--focus-ring`
- `--focus`
- `--row-line`
- `--home-glow-accent`
- `--home-glow-blue`
- `--surface-top`
- `--surface-filter`
- `--surface-card`
- `--scroll-hover`
- `--terminal-suggestion`
- `--terminal-ansi-magenta`
- `--terminal-ansi-cyan`
- `--terminal-ansi-bright-red`
- `--terminal-ansi-bright-green`
- `--terminal-ansi-bright-yellow`
- `--terminal-ansi-bright-blue`
- `--terminal-ansi-bright-magenta`
- `--terminal-ansi-bright-cyan`
- `--terminal-ansi-bright-white`
- `--overlay`
- `--shadow-strong`
- `--status-idle-soft`
- `--status-idle-line`
- `--status-occupied-soft`
- `--status-occupied-line`
- `--status-pipeline-soft`
- `--status-pipeline-line`
- `--status-other-soft`
- `--status-other-line`
- `--empty-bg`

## Typography

- Use `Fira Sans` for Web and native workspace UI when available.
- Use `Fira Code`, `Cascadia Mono`, or `Consolas` for terminals and command editors.
- Keep font sizes compact and operational: dense tables are acceptable, but focus rings and row states must stay visible.

## Surface Rules

- Web pages must link `src/web/assets/workspace-theme.css`.
- Web pages must not redeclare root-level theme tokens locally.
- Web pages should use shared root classes from `workspace-theme.css`: `workspace-page`, `workspace-compact-page`, or `workspace-terminal-page`.
- Web pages must consume shared `button`, `input`, `select`, and focus-visible control styling from `workspace-theme.css` instead of redefining base controls page by page.
- Web form surfaces should consume shared utilities from `workspace-theme.css`, including `workspace-field`, `workspace-panel`, `workspace-button-row`, and `workspace-step-actions`.
- Web pages should avoid inline `style=` layout overrides; add shared utility classes instead.
- Native style overrides live in `src/styles.py`; the final OLED cascade must remain after legacy overrides.
- Terminal renderers must use the same background, text, cursor, and selection palette as the Web theme.
- xterm ANSI theme colors must be read from `workspace-theme.css` terminal custom properties instead of page-local hex literals.
- Status indicators use shared classes or helpers: `idle`, `occupied`, `pipeline`, `other`.
- Native status statistics must read from `STATUS_COLORS`; do not pass legacy palette literals into stat chips.
- Tool panels should use card surfaces for live status, endpoint metadata, and command hints instead of loose standalone labels.
- Tool forms with multiple protocols should group each protocol into its own card surface so dense native forms still read like Web panels.
- Reusable native cards should expose object names and properties for chips or badges instead of embedding color and border styles in HTML strings.
- Qt rich-text snippets may use shared helpers to emit inline styles, but palette values must be centralized rather than embedded in feature logic.
- Filter chips and badge-like rich text should use shared helpers such as `html_chip()` or `html_badge()` instead of hand-building style strings in feature modules.
- Short colored status values in Qt rich text should use `html_status_text()` so text weight, escaping, and class hooks stay consistent.

## Interaction Rules

- Clickable rows must expose hover and keyboard focus states.
- Device rows in Web views should be marked as contextable and forward context menu requests to Python.
- Web device rows must support keyboard operation: `Enter` or `Space` selects the row, and `ContextMenu` or `Shift+F10` opens the same device context menu as right-click.
- Selected Web device rows must expose `aria-selected` alongside the visual selected state.
- Web editor surfaces should expose page-local context menus for row or card editing actions when the operation no longer lives in native Qt widgets, with `ContextMenu` and `Shift+F10` keyboard equivalents.
- Native right-click menus must be created through `new_workspace_menu()`.
- The xterm WebView must forward its internal context menu event to the outer terminal widget so the terminal menu is preserved.
- Prefer reduced-motion support for Web transitions.

## Anti-Patterns

- Do not introduce page-local `:root` token blocks.
- Do not revive the old `#080808`, `#ededed`, or `#5b6ef5` Linear/Vercel palette as final UI output.
- Do not add raw `QMenu(...)` calls outside the menu factory.
- Do not show the left device pool on the home screen; the home screen already is the device pool.
- Do not keep unreachable legacy UI templates after a visible surface has migrated to the workspace design system.
