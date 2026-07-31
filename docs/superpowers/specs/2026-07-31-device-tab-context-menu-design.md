# Device Tab Context Menu Design

## Goal

Add a compact right-click menu to the top-level device tabs so operators can close the clicked tab, tabs on either side, all other tabs, or every device tab without confusing device tabs with their child terminal sessions.

## Scope

- Apply the new menu only to the top-level `sessionTabs` device tab bar.
- Keep the lower per-device terminal tab menus and their behavior unchanged.
- Improve the shared native workspace menu styling so the new menu and existing native context menus use one visual language.
- Reuse the existing device-tab close lifecycle so every terminal session owned by a closed device tab is disconnected and cleaned up normally.

## Interaction Model

The tab under the pointer when the menu opens is the reference tab. Opening the menu does not activate that tab.

The menu contains these groups in order:

1. `关闭当前页签`
2. Separator
3. `关闭左侧页签`
4. `关闭右侧页签`
5. `关闭其他页签`
6. Separator
7. `关闭所有页签`

The menu displays the clicked device name as a disabled title above the actions. A title longer than 30 Unicode characters is shortened to its first 29 characters plus an ellipsis for display only; the underlying device identity is unchanged.

### Enabled States

- `关闭当前页签` is enabled whenever the menu was opened on a valid device tab.
- `关闭左侧页签` is disabled when the clicked tab is the first tab.
- `关闭右侧页签` is disabled when the clicked tab is the last tab.
- `关闭其他页签` is disabled when only one device tab exists.
- `关闭所有页签` is enabled whenever at least one device tab exists.
- If the pointer is not over a device tab, no menu is shown.

## Close Semantics

Bulk operations snapshot the target device-tab states before any tab is removed. They then close those states through the existing `close_device_tab_state()` lifecycle instead of repeatedly closing mutable numeric indexes.

- Closing left removes every device tab that was left of the clicked tab when the menu opened.
- Closing right removes every device tab that was right of the clicked tab when the menu opened.
- Closing others removes every device tab except the clicked tab.
- Closing all removes every device tab, including the clicked tab.
- The clicked tab remains selected after closing left, right, or others.
- No additional confirmation dialog is introduced; the interaction stays consistent with existing tab-close controls.

## Visual Design

All native context menus continue to be created through `new_workspace_menu()`.

- Surface: `#0f172a`
- Border: `#334155`, one pixel
- Outer padding: 6 pixels
- Radius: 10 pixels
- Item hover surface: neutral selected blue-gray `#24324a`
- Primary text: `#f8fafc`
- Disabled text: `#718096`
- Separators: `#243244` with compact vertical spacing
- Minimum item width: 176 pixels
- Item padding: 7 pixels top and bottom, 30 pixels right, and 12 pixels left

The existing green hover treatment is replaced with the neutral selected surface because menu selection is navigation feedback, not a success state. `关闭所有页签` receives a restrained danger cue through a red line icon; the full row is not permanently painted red.

## Architecture

### Menu Creation

Add a focused helper in the session/device-tab operations layer that:

1. Resolves the clicked index from the tab-bar-local position.
2. Resolves the corresponding `DeviceTabState`.
3. Creates the menu through `new_workspace_menu()` with a device-tab-specific `menuKind`.
4. Adds actions, separators, danger cue, and enabled states.
5. Dispatches the selected action to a single bulk-close helper.

### Target Collection

Add a helper that derives an ordered snapshot of `DeviceTabState` objects from the current top-level tab order. A close mode (`current`, `left`, `right`, `others`, or `all`) filters this snapshot relative to the clicked page.

This isolates target calculation from UI creation and makes boundary behavior directly testable.

### Styling

Adjust the final `QMenu#workspaceContextMenu` stylesheet cascade in `src/styles.py`. The update is intentionally shared across native workspace menus to preserve the application's existing global menu standard. No raw `QMenu(...)` construction is added outside the factory.

## Error and Edge Handling

- Ignore a context-menu request when the tab index or device state cannot be resolved.
- Ignore device states that have already been removed before an asynchronous close step reaches them.
- Do not rely on closing by index after the first removal.
- Preserve existing session shutdown behavior, cleanup callbacks, and empty-workspace transitions.

## Testing

Add focused tests covering:

- The top device tab bar uses a custom context-menu policy and routes requests to the new handler.
- Right-clicking a tab produces the approved labels, grouping, title, and `menuKind`.
- Boundary actions are disabled correctly for first, middle, last, and single-tab cases.
- Current, left, right, other, and all target calculations preserve tab order and scope.
- Bulk operations invoke the existing device-tab close lifecycle for the correct snapshot.
- The lower terminal-tab context menu remains unchanged.
- Shared menu styling contains the neutral hover, disabled, border, radius, and separator tokens.

Run focused GUI tests first, followed by the repository test suite while preserving the project's already-known unrelated exclusions if they remain applicable.

## Acceptance Criteria

- A right-click on any top-level device tab opens the optimized workspace menu.
- Every requested close operation acts relative to the tab that was right-clicked.
- Disabled states accurately communicate unavailable operations.
- Bulk closing does not skip tabs because indexes shifted during removal.
- Child terminal sessions use the existing orderly shutdown path.
- The menu visually matches the application's dark workspace design system.
- Existing lower terminal-tab closing behavior is unaffected.
