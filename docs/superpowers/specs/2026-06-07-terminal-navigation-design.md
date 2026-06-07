# Terminal Navigation Redesign

## Context

The terminal workspace sidebar currently mixes session navigation, device entry points, summary counts, and bottom terminal operations in a narrow column. When many devices or sessions exist, the content becomes crowded, hard to scan, and partly duplicates the bottom `TERMINAL OPS` area.

The redesign should make the sidebar useful as a fast terminal companion:

- Jump between open terminal sessions.
- Find and connect to devices without returning to the full home device list.
- Keep the panel available when useful and hide it when the terminal needs space.
- Preserve the user's last layout choices after the first launch.

## Decisions

1. The terminal navigation sidebar remains open on first use.
2. The sidebar remembers its last open/collapsed state after that.
3. The sidebar supports horizontal resizing.
4. The sidebar can be fully hidden and restored from a small affordance near the terminal area.
5. The content switches between two tabs: `Sessions` and `Devices`.
6. The device tab remembers its state, including search text and local expanded/collapsed detail state where practical.
7. The default device tab does not show the entire device inventory. It shows a compact useful subset such as recent, current, or commonly used devices.
8. Typing in the device search box shows matching devices from the full inventory.
9. Device rows show only the device name, a short ID or IP helper, status, and connection entry points.
10. Additional device details move to tooltip content or an explicit expanded detail area.

## Primary UX

### Sidebar Shell

The sidebar is a resizable left panel inside the terminal workspace. It should have a clear collapse button and a stable restore affordance when hidden.

Remembered state:

- Width.
- Hidden or visible.
- Active tab.
- Device tab search query if it is still useful across reloads.

Default state:

- Visible.
- Device tab available.
- Width set to a comfortable compact default.

### Sessions Tab

The sessions tab focuses only on active terminal sessions.

Each session item should show:

- Session title.
- Protocol or terminal type when helpful.
- Connection status.
- Close affordance.

Session actions:

- Click to jump to the terminal.
- Close current session.
- Close other sessions.
- Close all sessions.

The session list should not duplicate bottom operation information unless it directly helps navigation.

### Devices Tab

The devices tab acts as a compact terminal-side device finder.

Top area:

- Search input fixed at the top of the tab.
- Placeholder should make clear that name, ID, and IP are searchable.

Default, no search:

- Show a small subset such as recent devices, currently related devices, or commonly used devices.
- Avoid loading a visually huge list into the narrow panel.

Search mode:

- Search across the full device inventory.
- Match device name, short ID, management IP, host/port, and other available searchable identifiers.
- Show empty state when there are no matches.

Device row:

- Primary text: device name.
- Secondary helper beside or below it: short ID or IP.
- Status badge.
- Telnet/SSH/serial action buttons depending on available device capabilities.

Details:

- Board, CPU, slot, vendor, tags, and credential hints should be in tooltip or an expanded row detail.
- Details must not crowd the default row.

## Recommended Layout

```text
+----------------------------------+
| Terminal Workspace         [hide] |
| [ Sessions ] [ Devices ]          |
|                                  |
| Sessions tab:                    |
|   SSH #1        Connected   [x]   |
|   Router-A      Authing     [x]   |
|                                  |
| Devices tab:                     |
|   Search devices...              |
|   Core-Router-CD16  172.18...    |
|   Connected        [SSH] [Telnet] |
+----------------------------------+
```

## Alternatives Considered

### Stacked Sessions And Devices

Keep sessions and devices in separate stacked sections. This preserves the current mental model, but it keeps the narrow sidebar crowded and makes both lists worse when there are many items.

### Search Drawer

Keep only sessions in the sidebar and open device search in a temporary drawer or command palette. This scales well for very large inventories, but it is a larger interaction change and makes persistent device browsing less direct.

### Tabbed Sidebar

Use `Sessions` and `Devices` tabs in the same resizable/collapsible sidebar. This reduces visible clutter, keeps both workflows close to the terminal, and matches the user's preferred direction.

This is the selected approach.

## Implementation Notes

Likely affected areas:

- `src/app/main_window.py`: sidebar layout, splitter state, tab state, restore affordance.
- `src/web/device_navigation.html`: rendered navigation UI, tabs, compact rows, search states.
- `src/widgets/device_navigation_web_widget.py`: bridge events for device search/connect and state updates.
- `src/app/table_ops.py`: payload sent to terminal navigation, including searchable device fields.
- `src/app/session_ops.py`: close current/others/all terminal actions.
- `src/styles.py`: sidebar resize/collapse and compact navigation styles.

State should be persisted using the same settings mechanism already used for window or UI preferences. Avoid adding a new storage layer unless the existing settings path cannot represent the sidebar state cleanly.

## Acceptance Criteria

- First launch shows the terminal navigation sidebar.
- After hiding the sidebar, reopening the app restores it as hidden.
- After resizing the sidebar, reopening the app restores the width.
- The sidebar can be restored without returning to the home page.
- `Sessions` and `Devices` tabs do not show at the same time.
- The sessions tab supports jumping to sessions and closing current/other/all sessions.
- The device tab has a search input.
- With no search term, the device tab shows a small useful subset rather than the full inventory.
- With a search term, the device tab searches the full device inventory.
- Device rows show name, short ID/IP, status, and connection actions without visual crowding.
- Extended device metadata is available through tooltip or expanded detail, not always visible.
- Existing terminal tabs and bottom terminal operations continue to work.

## Validation

Manual validation:

- Launch `python src/desktop_app.py`.
- Open several terminal sessions.
- Resize the sidebar and restart the app.
- Hide and restore the sidebar.
- Switch between `Sessions` and `Devices`.
- Search by device name, short ID, and IP.
- Connect to a device from the device tab.
- Close one session, close other sessions, and close all sessions.

Automated validation where practical:

- Syntax check with `python -m py_compile src\\*.py`.
- Add focused pytest coverage for state persistence helpers, device search filtering, and session close routing if these are factored into testable helpers.
