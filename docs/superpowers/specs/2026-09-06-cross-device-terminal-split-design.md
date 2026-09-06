# Cross-Device Terminal Split Design

## Goal

Allow operators to split any two already-open terminal sessions into a shared
two-pane workspace, including sessions belonging to different devices. Keep the
existing same-device split behavior and terminal lifecycle intact while making
device-level comparison a first-class workflow.

## Scope

- Replace the current per-device split ownership with one global split workspace
  for the renderer.
- Allow the two panes to display sessions from different devices, connection
  profiles, temporary connections, or local terminals.
- Keep the existing maximum of two panes, four split directions, draggable
  session tabs, resizable divider, persisted layout, and explicit exit action.
- Keep device tabs as navigation and session grouping UI; splitting a session
  must not close, reconnect, or duplicate its backend session.
- Preserve the existing terminal toolbar split button and its disabled state when
  fewer than two sessions are available.

## Interaction Model

The global split workspace is active when it has two assigned sessions. The
primary pane is the focused pane before splitting; the secondary pane receives
the selected session when a split is created.

- The terminal toolbar split button splits the current session to the right using
  another open session as the secondary session. The candidate is the most
  recently active open session that is not the current session; if none exists,
  the button remains disabled.
- Right-clicking any top-level device tab or child terminal tab exposes the same
  four direction actions: left, right, top, and bottom. The selected tab's
  session becomes the target session, regardless of its device.
- Dragging any device tab or terminal tab over a pane edge moves that session to
  the indicated pane and creates or updates the global split.
- Clicking a session in either pane focuses that pane and updates the active
  session without changing the other pane.
- Exiting split returns the normal workspace to the focused session and leaves
  all other sessions open.

When the selected session is already assigned to the requested pane, the action
is idempotent. When a split update would leave a pane without a session, the
workspace falls back to the remaining session and exits split mode.

## Architecture

Introduce a renderer-level split state owned by `App.vue` or a dedicated
composable/store:

- `direction`: `left`, `right`, `top`, `bottom`, or `null`.
- `assignments`: map from session id to `primary` or `secondary`.
- `primaryActiveId`, `secondaryActiveId`, `focusedPane`, and `ratio`.
- A per-user local-storage key stores the global layout, active ids, assignments,
  and divider ratio. Stale session ids are removed during reconciliation.

`TerminalSplitWorkspace.vue` becomes a reusable view over the global session
collection instead of receiving a single device id. `App.vue` remains
responsible for mapping session ids to device/profile labels, opening context
menus, and routing terminal operations to the existing session services.

Device groups and device tabs continue to render normally outside the split
workspace. While split is active, the two selected sessions are rendered only in
the global split view so a session is never mounted twice. Warm-session limits
must include both split-active sessions before applying the existing cache limit.

## Data Flow

1. `workspace.sessions` remains the single source of truth for open sessions.
2. App-level split state reconciles against that list whenever sessions open,
   close, disconnect, or reconnect.
3. A split command resolves a target session id, assigns the target pane and
   direction, focuses the target pane, and persists the new layout.
4. `TerminalPane` emits terminal-specific events exactly as it does today;
   split commands are the only new event path.
5. Session activation updates `workspace.activeSessionId` and the focused pane,
   without changing assignments for the other pane.

## Error and Edge Handling

- A split command is ignored when fewer than two sessions are open.
- If a split-assigned session closes, its pane is replaced with the most recent
  eligible open session. If no replacement exists, split mode exits.
- If a session becomes disconnected or errored, it remains assigned so the user
  can reconnect it in place.
- Local terminals and profile-backed sessions use the same session-id path; no
  special device lookup is required for split assignment.
- Stale local-storage entries never prevent the workspace from opening.
- Backend session shutdown remains controlled by the existing close/disconnect
  actions; split operations never call those APIs.

## Testing

Add focused renderer coverage for:

- Splitting sessions from different device ids into left/right and top/bottom
  layouts.
- Toolbar split candidate selection and disabled behavior with zero or one open
  session.
- Device-tab and terminal-tab context menus routing to the global split state.
- Drag/drop moving sessions across panes and preserving pane focus.
- Session close/reconnect reconciliation and exit-to-focused-session behavior.
- Persisted layout cleanup when a saved session id no longer exists.
- Ensuring each split session mounts exactly once and existing terminal events
  still target the correct session.

Run the renderer type check, production Electron build, and relevant UI parity
smoke tests. Existing unrelated worktree changes must remain untouched.

## Acceptance Criteria

- Any two open terminal sessions, regardless of device, can be shown side by
  side or stacked in the global split workspace.
- The split button is visible on every terminal and enabled whenever a second
  open session exists.
- Device and terminal context menus offer all four split directions.
- The two sessions remain live, independently focusable, and independently
  closable/reconnectable.
- Exiting split restores the focused session without closing the other session.
- Existing same-device split workflows continue to work.
