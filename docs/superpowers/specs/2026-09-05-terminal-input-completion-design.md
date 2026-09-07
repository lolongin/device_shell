# Terminal Input Completion Design

## Goal

Restore command completion for the live terminal input without taking control
away from the device shell. Suggestions should be useful for incomplete command
lines, remain scoped to the active session, and never make horizontal cursor
movement unexpectedly accept a command.

## Scope

- Apply completion only to the live terminal in `TerminalPane.vue`.
- Reuse the existing `/api/v1/commands/suggestions` endpoint and its history,
  command-group, default-command, device, and session-kind ranking.
- Keep command-workspace editing behavior unchanged.
- Keep device protocols and PTY/server input contracts unchanged.

## Interaction

The renderer maintains a shadow model of the current terminal input line. It is
updated from the data emitted by xterm.js, including printable characters,
backspace, delete, home/end, cursor movement, clear-line controls, and Enter.
The model is reset after Enter, Ctrl+C, Ctrl+U, a prompt-like output boundary,
or a session reconnect.

Suggestions are requested only when all of these conditions hold:

- the session is active and can accept input;
- the current line is non-empty and is not a sensitive prompt;
- the shadow cursor is at the end of the current line;
- no completion acceptance is already being applied.

Only the top-ranked result is shown. It is rendered as a single gray hint at
the right edge of the terminal input area. A request sequence number prevents
a late response from replacing the hint for newer input. Clearing the line or
moving away from the line end immediately hides the hint.

Keyboard behavior is intentionally explicit:

- `Tab` is always forwarded unchanged to the device shell so native shell
  completion keeps its normal behavior.
- `ArrowRight` accepts the candidate when the hint is visible and the
  cursor is at the line end. Otherwise it is forwarded unchanged.
- `ArrowUp` and `ArrowDown` always retain the shell's normal history behavior.
- `ArrowLeft` always moves the shell cursor and closes the hint; it
  never accepts a candidate.
- `Escape` closes the hint without sending input.
- `Enter` keeps the existing reconnect and send behavior.

Accepting a candidate sends only the missing suffix from the current line to
the device. The renderer updates the shadow line optimistically and keeps the
candidate list closed until new input changes the query.

## Components and Data Flow

`TerminalPane.vue` owns the shadow input state because it already owns the
xterm.js instance and raw input forwarding. The state consists of:

- current line text and cursor offset;
- the top-ranked candidate string;
- a monotonically increasing request id;
- a debounce timer and an acceptance-in-progress flag.

The existing Pinia store method and API transport remain the request boundary.
The terminal component calls the store/API with the active session id and the
current line query. No suggestion data is persisted in the renderer.

The gray hint is rendered as a non-interactive overlay within the terminal
pane, aligned to the right edge with ellipsis for long commands. It never
steals focus from xterm.js.

## Input Parsing and Safety

The shadow model is deliberately conservative. ANSI escape sequences and
control sequences that cannot be mapped to a deterministic line edit invalidate
the model and hide suggestions until the next prompt or printable input. This
prevents the renderer from sending a suffix at the wrong cursor position.

Sensitive prompts use the existing prompt-output detection used by command
history recording. No request is sent and no candidate text is rendered while a
password, secret, token, or equivalent prompt is active.

Candidate acceptance is a renderer-side input operation: it sends the missing
suffix through the same local-terminal or WebSocket path as normal input and
updates the shadow model only after the send operation is scheduled. It does not
send Enter, execute a command, or alter command history by itself.

## Error Handling

- Failed suggestion requests silently clear candidates; terminal input remains
  usable.
- Out-of-order responses are ignored by request id.
- Disconnection, reconnect, session switching, and component unmount cancel
  pending timers and invalidate pending requests.
- If the socket/local terminal cannot accept the suffix, the shadow model is
  invalidated so a later request cannot duplicate text.

## Testing

Add focused renderer-facing unit coverage for the pure input-state helpers:

- printable input and backspace update text and cursor offsets;
- left/right movement keeps the cursor model correct;
- right-arrow accepts only when a candidate is visible; Tab always reaches the shell;
- left-arrow never accepts a candidate;
- the single top-ranked candidate is the only visible result;
- Enter, Ctrl+C, and Ctrl+U reset the line;
- stale asynchronous responses cannot replace current candidates;
- sensitive prompts and non-end cursors suppress requests.

Update Electron parity/smoke assertions to cover the gray hint contract and the
keyboard acceptance rules. Run the focused tests, `npm run typecheck`, and the
desktop production build.

## Non-Goals

- Do not implement device-specific shell completion or modify PTY behavior.
- Do not add AI prediction, filesystem/path completion, or command-workspace
  autocomplete.
- Do not change Enter/send preferences or terminal history semantics.
