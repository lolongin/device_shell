# Compact Terminal Tabs Design

## Goal

Refine the terminal workspace tabs without changing their existing two-level
information model:

- The first level represents devices.
- The second level represents terminal sessions opened for the selected device.

The result should use less vertical space, make the hierarchy easier to scan,
and retain existing multi-session and split-terminal behavior.

## Scope

This change covers the native Qt device and session tab bars in the terminal
workspace. It changes their visual presentation and close-button visibility.

It does not add tab renaming, pinning, a new-session button, or a new navigation
model. It does not change how sessions connect, reconnect, split, persist, or
execute commands.

## Visual Structure

Use the approved flat, compact A3 direction.

### Device tabs

- Use a flat tab row rather than individual bordered cards.
- Use a 28-pixel tab row.
- Use transparent backgrounds for inactive tabs.
- Indicate the selected device with brighter text and a 2-pixel green bottom
  line.
- Use a subtle background on hover without adding a complete border.
- Retain a circular connection-status indicator.

### Session tabs

- Place the session row directly below the device row.
- Use a 24-pixel tab row.
- Use no border for inactive sessions.
- Indicate the selected session with a low-contrast rounded background and
  brighter text.
- Retain a small rounded-square connection-status indicator so that session
  state remains visually distinct from device state.

### Spacing and overflow

- Reduce padding inside both levels of tabs.
- Keep a 2-pixel gap between the two rows.
- Keep 8 pixels between the session row and terminal content.
- Elide long device and session titles rather than shrinking text.
- Keep horizontal tab scrolling and show scroll controls only when content
  overflows.

## Status Presentation

Status colors remain consistent across both levels:

- Connected: green.
- Connecting: amber.
- Disconnected or idle: gray.
- Error: red.

Only the connecting state may animate. Other states remain static to avoid
visual noise.

## Close-Button Behavior

- The close button for the active device and active session remains visible.
- Close buttons for inactive tabs appear only while their tab is hovered.
- Middle-click closes the targeted device or session.
- Existing context-menu actions remain available, including close, close
  others, and close all.
- Closing the final session for a device removes the corresponding device tab,
  preserving current behavior.

Close buttons must keep a reliable click target even though their visual glyph
is compact.

## Interaction Behavior

- Selecting a device restores that device's last active session.
- Selecting a session makes its terminal current.
- Existing device and session tab reordering remains available.
- Existing split-terminal drag behavior remains available.
- A truncated title exposes the full title, address, protocol, and connection
  state through a tooltip.

## Implementation Boundaries

The change should reuse the existing custom tab-header installation and state
refresh paths in `src/app/session_ops.py`.

Shared tab styling remains in `src/styles.py`. Device and session tabs should
receive separate object names or properties where needed so their status
indicator shapes and close-button visibility can be styled independently.

The implementation should avoid creating another tab implementation or
changing the session data model.

## Verification

Automated tests should verify:

- Device and session tabs retain distinct visual properties.
- Active and inactive close-button visibility follows the approved rules.
- Status properties update after connection-state changes.
- Long labels are elided and expose their full tooltip.
- Closing the final child session removes the device tab.
- Existing tab ordering, context-menu, and split-session tests continue to
  pass.

Manual verification should cover:

- One device with multiple terminal sessions.
- Multiple devices with one or more sessions each.
- Connected, connecting, disconnected, and error states.
- Narrow windows where both tab rows overflow.
- Hover, middle-click close, right-click actions, drag reorder, and split drag.
- Readability at the normal Windows display scale and a high-DPI scale.
