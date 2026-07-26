# Left Sidebar Drag and Responsive Device Table Design

## Goal

Make resizing the left workspace predictable and keep the device table useful
at every supported width.

The design replaces competing width decisions with a two-state sidebar model
and gives the six-column device table three explicit density modes.

## Scope

This change covers:

- User dragging of the main horizontal splitter.
- Collapsing and restoring the left sidebar.
- Remembering the preferred open width.
- Device-table column visibility and widths while the sidebar changes size.
- Device group-row spans at each table density.

It does not change device filtering, selection, sorting, connection behavior,
tool-panel contents, or terminal session behavior.

## Sidebar State

The stable sidebar states are:

- `open`: the device or tool content is visible.
- `collapsed`: only the 46-pixel activity rail is visible.

Transient implementation flags are:

- `user_dragging`: the splitter handle is currently being dragged.
- `programmatic_resize`: the application is applying a saved width, snapping,
  or animating.

The persisted width is `preferred_open_width`. Programmatic resizing never
updates this value.

The existing compact and expanded presentation flags may continue to control
which content is shown, but they must not independently set or persist the
main splitter width.

## Width Rules

- Collapsed width: 46 pixels.
- Collapse release threshold: 180 pixels.
- Minimum stable open width: 300 pixels.
- Maximum preferred open width: 620 pixels.
- Effective maximum width: the smaller of 620 pixels and 42 percent of the
  splitter's available width.
- Default preferred open width: the existing configured terminal-sidebar
  width.

When the user releases the splitter:

- At 180 pixels or less, snap to the collapsed width.
- From 181 through 299 pixels, snap back to 300 pixels.
- At 300 pixels or more, keep the clamped released width and save it as the
  preferred open width.

The preferred width is saved only on mouse release, not for every
`splitterMoved` signal.

## Collapse and Restore Behavior

- Collapsing from the activity-rail button saves the current valid open width
  before snapping to 46 pixels.
- Expanding from the activity-rail button restores the preferred open width,
  clamped to the current window.
- Dragging into the collapse range changes the splitter handle to the accent
  color and exposes the tooltip `释放收起`.
- Releasing outside the collapse range removes the collapse hint.
- Switching devices, switching sessions, and entering the terminal workspace
  do not force the sidebar open or overwrite its width.
- Selecting a tool on the activity rail explicitly opens that tool panel at
  the preferred width.
- Window resizing clamps only the effective width. It does not destroy a
  larger preferred width that may become usable when the window expands
  again.

## Splitter Event Flow

User and application resize events are separated:

1. Splitter-handle press sets `user_dragging`.
2. Splitter movement updates the visual width and schedules table-density
   adaptation.
3. Splitter-handle release evaluates the snap rules, stores a valid preferred
   width, and clears `user_dragging`.
4. Application-driven size changes set `programmatic_resize` for their full
   duration.
5. `splitterMoved` ignores persistence while `programmatic_resize` is true.

Animation may update the visual splitter width, but it never changes the
preferred width.

## Responsive Device Table

Density is based on the device table viewport width, not the entire sidebar
width.

### Full density

At a viewport width of 520 pixels or more, show:

`序号 | 设备 | 板类型 | CPU | Slot | 状态`

Column behavior:

- Sequence: fixed compact width.
- Device: stretches into remaining space.
- Board type: fixed preferred width with elision.
- CPU: fixed compact width.
- Slot: fixed compact width.
- Status: fixed width and always readable.

### Medium density

At a viewport width from 340 through 519 pixels, show:

`设备 | 板类型 | CPU | 状态`

Hide sequence and Slot. The device column consumes remaining space.

### Compact density

Below a viewport width of 340 pixels, show:

`设备 | 状态`

The status column remains fixed. The device column consumes all remaining
space.

## Breakpoint Stability

- Resize adaptation is debounced by 40 milliseconds.
- A 16-pixel hysteresis is applied when moving back across a breakpoint.
- During a collapse gesture at or below 180 pixels, table-density adaptation
  pauses until the sidebar is either collapsed or snapped open.
- Density changes do not write user column preferences.
- Returning to full density restores the last full-density user column widths,
  clamped to the viewport.

## Hidden Information

Every device row exposes a tooltip containing:

- Device name and ID.
- Board type.
- CPU.
- Slot.
- Status and occupancy detail.

Therefore information hidden by medium or compact density remains available
without opening another panel.

## Group Rows

SDK/device group rows remain visible in every density:

- The group title is rendered in the first visible column.
- The group title spans all visible non-status columns.
- The board count remains visible when space permits and moves into the group
  tooltip in compact density.
- Recomputing column visibility also recomputes table spans.

Group rows must never disappear because the original sequence column is
hidden.

## Other Left Panels

Temporary devices, servers, file transfer, package upgrade, and AI panels use
the same open, collapsed, snap, and preferred-width behavior.

Responsive device-table density applies only while the device panel is active.

## Verification

Automated tests should cover:

- Programmatic splitter movement does not change the preferred width.
- User release at 180 pixels collapses the sidebar.
- User release from 181 through 299 pixels snaps to 300 pixels.
- User release above 300 pixels stores the clamped preferred width.
- The activity-rail button restores the preferred width.
- Mode and session changes preserve collapsed state and preferred width.
- Full, medium, and compact table densities expose the correct columns.
- Breakpoint hysteresis prevents oscillation.
- Group rows remain visible and span the correct visible columns.
- Hidden row information remains present in tooltips.

Manual verification should cover:

- Slow and fast dragging across both breakpoints.
- Repeated dragging around each breakpoint.
- Collapse by drag and restore by button.
- Window resize while open and collapsed.
- Device, temporary-device, server, transfer, upgrade, and AI panels.
- Large device datasets and SDK groups.
