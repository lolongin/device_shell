# Session Tab Layout Settings Design

> Supersedes `2026-08-01-session-tab-layout-settings-design.md`. This revision adds: right-side session manager search, draggable width with single global persistence, panel + per-device-group collapse memory (default-collapse setting only governs first entry), and removes the close-session confirmation setting (out of scope per requirement).

## Goal

Let operators choose where terminal session navigation lives: the current top tab rows or a collapsible right-side hierarchical session manager. A settings entry in the bottom-left status bar exposes the choice together with terminal font size and the default collapsed state for the side layout.

## Scope

- Add a bottom-left settings button and an in-menu settings panel.
- Add `session_tab_layout` (`top` or `side`) with persistent state.
- Add terminal font size control applied to open and future terminals through the existing xterm bridge.
- Add a right-side hierarchical session manager listing devices and their terminal sessions, with click-to-jump, inline search, context menus for close operations, draggable width, and per-device-group collapse.
- Add `session_manager_default_collapsed` governing the *initial* state when first entering `side`; afterwards panel and group collapse states follow user actions (memorized).
- Persist all new settings in desktop state (version 13 → 14).
- Keep the existing top tab rows as the default and do not change their behavior in `top` mode.

### Explicitly out of scope

- Close-session confirmation (`close_session_confirm`) — removed per requirement.

## Settings

### User-facing settings (in the settings panel)

The settings button sits at the left side of the status bar. Clicking it opens a workspace-styled menu whose embedded widget contains three controls:

| Setting | Key | Default | Behavior |
| --- | --- | --- | --- |
| Session tab layout | `session_tab_layout` | `top` | `top` keeps current two-row tabs; `side` hides top tab bars and shows the right manager + breadcrumb |
| Terminal font size | `terminal_font_size` | `14` | Applied to all current and future xterm terminals |
| Manager default collapsed | `session_manager_default_collapsed` | `false` | Only the *first* entry into `side` layout; afterwards memorized collapse state wins |

Changes apply immediately and are scheduled for save via `schedule_desktop_state_save()`.

### Auto-memorized state (not exposed as panel controls)

These are persisted automatically from user actions and restored on load / on entering `side`:

| State | Key | Default | Behavior |
| --- | --- | --- | --- |
| Manager width | `session_manager_width` | `260` | Right panel width, draggable, single global value persisted |
| Manager collapsed | `session_manager_collapsed` | `false` | Last panel collapse state, restored on entering `side` |
| Collapsed device groups | `collapsed_device_groups` | `[]` | Tree groups the user collapsed, memorized per device group |

## Right Session Manager

The right manager is the third widget of `main_splitter`, after the left device panel and the center terminal workspace.

### Panel structure

```
┌─ 会话管理器 ────── 共 N  ⏴ ┐
│  🔍 搜索设备、会话         │
│  ▾ R1-核心 (1)            │
│     ● SSH 10.0.1.1        │
│  ▾ R2-汇聚 (2)            │
│     ● SSH 10.0.1.2  ←活跃 │
│     ● SSH 10.0.1.3        │
├───────────────────────────┤
│  [＋ 新建终端]             │
└───────────────────────────┘
```

- Header shows the title, total session count (`共 N`), and a collapse toggle (⏴) that collapses/expands the whole panel.
- A search input filters the tree in real time (see Search below).
- A tree lists one parent item per open device and child items for that device's terminal sessions.
- A bottom action creates a new terminal on the current device.

### Tree parent items (devices)

- Text: device name + session count, e.g. `R2-汇聚 (2)`.
- Status dot: aggregate device state (any active connection → green, all disconnected → gray).
- Click → `activate_device(device_id)`.
- Context menu → reuse `build_device_tab_context_menu()` (close current / left / right / others / all device tabs).

### Tree child items (sessions)

- Text: session title (e.g. `SSH 10.0.1.2`).
- Status dot: session connection state (connecting = amber/green, disconnected = gray).
- Active session: highlighted + bold.
- Click → `jump_to_session(tab_id)` (existing, includes terminal focus).
- Context menu → close this session / close other sessions / close all sessions (via existing close helpers).

### Search

- A search input sits above the tree, placeholder `搜索设备、会话`.
- Filters in real time as the user types: keep a session child if its title (or device name/id) matches; keep a device parent if the device name/id matches (then all its sessions show). Empty query shows everything.
- Builds on the existing `build_search_text` helper convention but is implemented independently (does not share device-pool filter state).

### Collapse memory

- Panel collapse (whole panel via ⏴) and per-device-group collapse are both memorized.
- `session_manager_default_collapsed` only decides the initial state the first time `side` is entered with no history; afterwards the memorized collapse state wins.

### Width

- The panel's left boundary is draggable via `QSplitter` (`setStretchFactor(2, 0)` so it does not steal space).
- Width is a single global value persisted as `session_manager_width`, restored across sessions.

## Breadcrumb (side mode)

- A thin widget (~28px) at the top of `center_stage_splitter`, above `web_shell` / `session_tab_widget`, visible only in `side` mode.
- Structure: `设备池 / 设备名 / 会话名`, e.g. `设备池 / R2-汇聚 / SSH 10.0.1.2`.
- Click interactions: device name → `activate_device()`; session name → `jump_to_session()` + focus terminal; `设备池` → back to home.
- Active device name highlighted green.

## Layout Switching

`set_session_tab_layout(mode)`:

- **→ side**: `session_tab_widget.tabBar().setVisible(False)`; each device page's session `QTabWidget.tabBar().setVisible(False)`; show right tree + breadcrumb.
- **→ top**: reverse — device tab bar visible, session tab bars visible, right tree + breadcrumb hidden.
- On switch, `refresh_session_manager_tree()` and update tree visibility.
- Switching to `side` with existing sessions calls `show_terminal_workspace()` so the terminal area is visible; no sessions → stays on home.

## Implementation Notes

- Add `SessionLayoutOpsMixin` in a new file `src/app/session_layout_ops.py`; add it to the `DeviceDesktopApp` mixin composition (after `SessionOpsMixin`).
- Reuse existing methods as facades — do not modify their internals: `jump_to_session()`, `activate_device()`, `build_device_tab_context_menu()`, `close_session_tab()`, `session_tabs_by_id`, `device_tabs_by_id`, `schedule_desktop_state_save()`, `show_terminal_workspace()`.
- Add `set_font_size()` to `XtermWebWidget`, invoking `window.deviceTerminal.setFontSize(n)` and reapplying on terminal-ready. The xterm bridge already exposes `window.deviceTerminal.setFontSize(n)`.
- Apply font size on settings change, on workspace refresh, and to newly created session states.
- The right manager uses `QTreeWidget` with `new_workspace_menu()` factory (kind `session-manager`) for context menus; tree styling follows `APP_STYLE` OLED theme (selection matches `Selected` token).
- Desktop state version advances from `13` to `14`.

## State Persistence

New `session_layout` section in `load_desktop_state()` / `save_desktop_state()`:

```json
{
  "session_tab_layout": "top",
  "terminal_font_size": 14,
  "session_manager_default_collapsed": false,
  "session_manager_width": 260,
  "session_manager_collapsed": false,
  "collapsed_device_groups": ["R1-核心"]
}
```

Load semantics:
- `session_tab_layout`: whitelist `{"top","side"}`, invalid → `top`.
- `terminal_font_size`: int, clamped to xterm's `MIN_FONT_SIZE`–`MAX_FONT_SIZE`.
- `session_manager_width`: int, clamped to 200–480.
- `collapsed_device_groups`: string list, pruned to groups that still exist.
- For `state_version < 14`, the section is absent → all defaults.

Save triggers (all via existing debounced `schedule_desktop_state_save()`):
- Layout switch, font size change, default-collapse setting change.
- Panel collapse/expand, tree group collapse/expand.
- Panel width drag finished (`splitter.splitterMoved` drag-finished event).
- Session structure change (after tree redraw, current collapse state flushed to memory).

## Testing

Add focused tests in `tests/test_session_layout.py`:

| Test | Coverage |
| --- | --- |
| Settings defaults | New mixin initializes layout=top, font=14, default_collapsed=false, width=260 |
| Persistence round trip | Save side layout + custom width + collapsed groups → reload → state matches |
| Layout switch visibility | To side → device tab bar hidden, session tab bars hidden, tree + breadcrumb shown; back to top → reversed |
| Tree population | Multiple sessions → parent count = device count, child count = session count, counts correct |
| Tree click dispatch | Child click → `jump_to_session`; parent click → `activate_device` |
| Search filtering | Keyword → matching session/device groups kept, others hidden; clear → all restored |
| Font application | `set_font_size` applied to current and new xterm terminals (Python → bridge) |
| Collapse memory | Panel collapse / group collapse → reload → state preserved |

Reuse existing app test fixtures (SampleDeviceRepository + simulated sessions).

Verification:
```bash
python -m py_compile src\*.py src\app\*.py src\device_mcp\*.py src\widgets\*.py
pytest tests/test_session_layout.py -v
pytest tests/ -x
```

## Acceptance Criteria

- Default behavior remains the existing top tab rows.
- Choosing `side` hides top tab bars, shows the right manager + breadcrumb, and lets the operator switch sessions from the tree.
- Tree inline search filters sessions/devices in real time.
- Choosing `top` restores the previous layout.
- Font size changes apply immediately and persist.
- Panel width is draggable, single global value, persisted.
- Panel collapse and per-device-group collapse are memorized; `session_manager_default_collapsed` only governs the first entry into `side`.
- Settings persist across restarts.
