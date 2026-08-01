# Session Tab Layout Settings Design

## Goal

Let operators choose where terminal session navigation lives: the current top tab rows or a collapsible right-side hierarchical session manager. A settings entry in the bottom-left status bar exposes the choice together with terminal font size, default collapsed state, and close confirmation.

## Scope

- Add a bottom-left settings button and an in-menu settings panel.
- Add `session_tab_layout` (`top` or `side`) with persistent state.
- Add terminal font size control applied to open and future terminals through the existing xterm bridge.
- Add a right-side hierarchical session manager listing devices and their terminal sessions, with click-to-jump and context menus for close operations.
- Add close-session confirmation as an opt-in setting.
- Persist all new settings in desktop state.
- Keep the existing top tab rows as the default and do not change their behavior in `top` mode.

## Settings

| Setting | Key | Default | Behavior |
| --- | --- | --- | --- |
| Session tab layout | `session_tab_layout` | `top` | `top` keeps current two-row tabs; `side` hides top tab bars and shows the right manager |
| Terminal font size | `terminal_font_size` | `14` | Applied to all current and future xterm terminals |
| Manager default collapsed | `session_manager_default_collapsed` | `false` | Right manager starts collapsed when entering `side` layout |
| Close session confirmation | `close_session_confirm` | `false` | Asks before close-session and bulk close actions |

The settings button sits at the left side of the status bar. Clicking it opens a workspace-styled menu whose embedded widget contains the settings. Changes apply immediately and are scheduled for save.

## Right Session Manager

The right manager is the third widget of the main splitter, after the left device panel and the center terminal workspace.

- Header shows the title, total session count, and a collapse toggle.
- A tree lists one parent item per open device and child items for that device's terminal sessions.
- Parent rows show a status dot and session count; child rows show the session title and connection status.
- Clicking a child jumps to that session using the existing `jump_to_session()`.
- Clicking a parent activates that device's top-level page.
- A context menu on a child offers close this session, close other sessions, and close all sessions.
- A context menu on a parent offers the same device-tab close operations as the top device tab bar context menu.
- A bottom action creates a new terminal on the current device.

In `side` layout, the top device tab bar and every device page's session tab bars are hidden; a compact breadcrumb above the terminal shows the current device and session path. In `top` layout, the manager and breadcrumb are hidden and the existing tab bars remain visible.

## Implementation Notes

- Add `set_font_size()` to `XtermWebWidget`, invoking `window.deviceTerminal.setFontSize(n)` and reapplying on terminal-ready.
- Apply font size on settings change, on workspace refresh, and to newly created session states.
- Confirmations are checked once per user action; bulk operations pass an already-confirmed flag so they do not prompt once per tab.
- Desktop state version advances from `13` to `14`.

## Testing

Add focused tests covering settings defaults, persistence round trip, layout switching visibility, manager tree population and click dispatch, font-size application, and opt-in close confirmation. Run focused tests, then the full suite with the repository's known unrelated exclusions.

## Acceptance Criteria

- Default behavior remains the existing top tab rows.
- Choosing `side` hides top tab bars, shows the right manager and breadcrumb, and lets the operator switch sessions from the tree.
- Choosing `top` restores the previous layout.
- Font size changes apply immediately and persist.
- Opt-in close confirmation works for session and bulk-close actions.
- Settings persist across restarts.
