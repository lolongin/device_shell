# Unbounded Left Sidebar Drag Design

## Goal

Let users expand the left sidebar freely without an application-defined
maximum width.

## Width Rules

- Remove the 620-pixel preferred-width cap.
- Remove the 42-percent window-width cap.
- The splitter and the center workspace determine the natural maximum based
  on the center workspace's minimum width.
- Keep the 300-pixel minimum stable open width.
- Keep the existing release behavior:
  - 180 pixels or less collapses to the activity rail.
  - 181 through 299 pixels snaps to 300 pixels.
  - 300 pixels or more keeps the released width.

## Persistence

- Save the released open width without applying an artificial upper clamp.
- Programmatic splitter movement still does not overwrite the saved width.
- Window resizing may temporarily reduce the visible width when required by
  layout constraints, but it does not destroy the saved preferred width.
- Expanding the window restores the saved width when layout space permits.

## Responsive Table

Device-table density continues to use the table viewport width. Removing the
sidebar maximum allows users to reach full density at any sufficiently wide
sidebar size.

## Verification

Automated tests cover:

- A release wider than 620 pixels is saved and restored.
- No 42-percent clamp is applied.
- Collapse and minimum-open snap behavior remains unchanged.
- Window resize preserves a larger preferred width.
