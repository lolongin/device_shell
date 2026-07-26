# Command Send Scroll-to-Live-Input Design

## Goal

When the user sends a command with the command panel's **发送到终端**
action, the active terminal must leave any historical scroll position and
show the live input/cursor location before the command is sent.

This behavior applies only to single-terminal sending. **广播发送** keeps its
current behavior and must not change the visible scroll position.

## Current Problem

`send_command_text_to_current_session()` sends the command and forces focus
to the active terminal, but focusing does not reset the terminal's historical
scroll position. If the user has scrolled upward, the command and subsequent
output can be written outside the visible area.

The application supports three terminal renderers:

- `XtermWebWidget`
- `TerminalCanvasWidget`
- `InteractiveTerminal`

The command panel must not depend on renderer-specific implementation details.

## Design

Each terminal renderer exposes the same public method:

```python
scroll_to_live_input()
```

The method means: clear any historical viewing position or selection that
prevents following live input, then reveal the terminal cursor/current input
location.

Renderer behavior:

- `XtermWebWidget` calls a JavaScript bridge method that clears the xterm
  selection and invokes `term.scrollToBottom()`.
- `TerminalCanvasWidget` exposes its existing internal live-input scrolling
  behavior through the public method.
- `InteractiveTerminal` restores the terminal cursor, clears a selection when
  necessary, and calls `ensureCursorVisible()`.

`send_command_text_to_current_session()` performs operations in this order:

1. Resolve the current session.
2. Ask its terminal to scroll to the live input location.
3. Queue the command for sending.
4. Preserve the existing forced terminal-focus behavior.

The broadcast path does not call `scroll_to_live_input()`.

## Edge Cases

- If no session is open, the existing status message is retained and no
  scrolling is attempted.
- If xterm has not finished loading, the scroll request is safely ignored;
  command sending continues through the existing queue.
- Sending while the terminal already follows live input is idempotent and
  produces no visible jump.
- A deliberate single-terminal send may clear a terminal selection because
  the user's explicit action requests a return to live input.

## Testing

Add tests that verify:

- Single-terminal command sending requests live-input scrolling before send.
- Broadcast sending does not request scrolling.
- All three terminal renderers expose `scroll_to_live_input()`.
- The xterm page exposes and uses `scrollToBottom()`.
- Existing command formatting, history recording, and focus behavior remain
  unchanged.

Run focused command/session tests, syntax checks, and the existing regression
suite before restarting the desktop application.
