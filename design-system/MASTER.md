# Device TUI Design System

This file defines the visual and interaction language for the Electron + Vue
desktop workspace. The implementation source of truth is
`desktop/src/renderer/src/styles.css`; component-specific styles may refine layout
without redefining the shared palette.

## Product Direction

- Present a compact, calm operations workspace rather than a generic admin page.
- Keep the device pool as the home view and terminals as the focused work area.
- Make connection state, active device, destructive actions, and transfer progress
  immediately legible.
- Keep developer-only source/plugin controls out of fixed product builds.

## Theme Tokens

| Token | Dark | Light | Usage |
| --- | --- | --- | --- |
| Background | `#020617` | `#f2f4f6` | App and terminal background |
| Panel | `#0f172a` | `#ffffff` | Cards and menus |
| Panel Raised | `#111c2f` | `#e8ebef` | Hover and secondary surfaces |
| Input | `#08101d` | `#fafbfc` | Inputs and inactive controls |
| Line | `#243244` | `#d5dae1` | Dividers and borders |
| Strong Line | `#334155` | `#c0c7d1` | Focused control boundaries |
| Text | `#f8fafc` | `#1c2128` | Primary text |
| Muted Text | `#a7b4c7` | `#5a6470` | Secondary text |
| Soft Text | `#718096` | `#87919d` | Disabled text |
| Accent | `#22c55e` | `#1f8a4c` | Primary and connected state |
| Blue | `#60a5fa` | `#3a7ecf` | Focus, links, pipeline state |
| Warning | `#fbbf24` | `#b7791f` | Occupied and caution state |
| Danger | `#f87171` | `#c74a4a` | Errors and destructive action |
| Selected | `#24324a` | `#dbe6f2` | Selected rows and tabs |
| Text Selection | `#315f9f` | `#3a7ecf` | Native and terminal selection |

## Typography

- Use the system UI stack for workspace text.
- Use `Fira Code`, `Cascadia Mono`, or `Consolas` for terminal and command text.
- Keep tables dense but preserve readable hit targets and visible focus rings.
- Numeric progress, byte counts, ports, and IP addresses should use tabular figures.

## Surface Rules

- Define global variables and base controls in `styles.css`.
- Components consume shared variables; avoid page-local palette copies.
- Cards use consistent border, radius, spacing, and elevation.
- Forms group related fields and place validation next to the affected control.
- Terminal colors, cursor, selection, and ANSI palette follow the active App theme.
- Dialogs, menus, popovers, and isolated Electron credential windows must all use
  the same theme mode.
- Light-theme text cursors and pointer cursors must remain visible against inputs.

## Interaction Rules

- Every clickable row exposes hover, selected, and keyboard-focus states.
- `Enter` or `Space` activates focused rows where appropriate.
- Context menus have keyboard equivalents through `ContextMenu` or `Shift+F10`.
- Destructive operations require clear labels and preserve backend risk gates.
- Loading, empty, offline, and error states must be distinct and actionable.
- Do not show end users plugin management in `web` or `spreadsheet` products.
- Password fields support visibility toggles without copying values into renderer
  persistence.
- Respect reduced-motion preferences and avoid decorative animation during active
  terminal or transfer work.

## Layout Rules

- Home owns the complete device pool, search, filters, and selected-device detail.
- Terminal mode uses compact session navigation and maximizes terminal space.
- Tool workspaces for transfer, upgrade, automation, and AI retain the current
  device/session context.
- Dialogs must fit common laptop displays and scroll internally when content grows.
- Split panes preserve practical minimum terminal sizes and keyboard navigation.

## Accessibility

- Preserve WCAG AA contrast for text and state indicators.
- Never rely on color alone; pair status colors with labels or icons.
- Inputs have visible labels, error descriptions, and focus rings.
- Icon-only buttons require accessible names and tooltips.
- Maintain logical tab order in dialogs and restore focus when they close.

## Anti-Patterns

- Do not add PySide/PyQt stylesheets, WebEngine pages, or native Qt widgets.
- Do not duplicate device-pool functionality inside terminal navigation.
- Do not expose credentials, cookies, or backend tokens to Vue state.
- Do not hard-code theme colors in feature logic when a shared variable exists.
- Do not leave migrated or unreachable UI implementations in the repository.
