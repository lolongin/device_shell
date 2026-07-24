# MCP Daily Reliability Core Design

## Objective

Extend the existing Device TUI MCP bridge from a demonstration-level control
surface into a reliable single-device daily-operation surface.

This phase focuses on:

- application and session observability;
- deterministic session targeting;
- protocol-aware session lifecycle management; and
- command execution whose result contains only output produced after that
  command was sent.

The existing Device TUI process remains the sole owner of device credentials,
terminal sessions, risk classification, audit logging, and approval policy.

## Scope

### Included

- Add `system_status`.
- Add `device_get`.
- Add `session_list`.
- Add `session_manage`.
- Add `terminal_execute`.
- Preserve all existing MCP tools and HTTP routes.
- Add stable output cursors to terminal session state.
- Detect command completion using prompt matching with an idle fallback.
- Support automatic protocol selection with explicit protocol override.
- Add structured errors and focused unit, service, HTTP, MCP, and Qt
  integration tests.

### Excluded

- File-transfer service management.
- Parameterized package-upgrade preparation.
- Package-upgrade cancellation or retry.
- Multi-device batch execution.
- UI layout or visual changes.
- A second SSH, Telnet, or serial implementation inside the MCP process.

## Architecture

The existing four-layer design remains:

```text
Claude Code / OpenCode
        |
        | stdio MCP
        v
src/mcp_server.py
        |
        | AppControlClient + authenticated loopback HTTP
        v
AppControlService
        |
        | short Qt main-thread dispatches
        v
DeviceDesktopApp sessions and terminals
```

Device TUI continues to start the loopback HTTP server on a random port and
write its process ID, URL, and bearer token to the runtime state file. The MCP
process continues to discover that state for each call.

Long waits must not run on the Qt main thread. Starting a command and reading a
session snapshot are short UI-thread operations. The App Control HTTP worker
performs connection and command-completion polling between those operations.

## Compatibility

The existing tools remain available with their existing input contracts:

- `device_list`
- `device_select`
- `session_open`
- `terminal_send_command`
- `terminal_read`
- `package_upgrade_start`
- `approval_get`
- `operation_get`

Where practical, old tools reuse the new session lookup and output snapshot
helpers. Existing Claude Code and OpenCode MCP registrations do not need to
change.

## New Tool Contracts

### `system_status()`

Returns a credential-free runtime summary:

- application readiness;
- Device TUI approval mode;
- selected device ID;
- total, connecting, connected, and disconnected session counts;
- active operation count; and
- application process ID when available.

The response must not include the App Control bearer token, device passwords,
or transfer-service passwords.

### `device_get(device_id)`

Returns a credential-free device description:

- stable ID and display name;
- status, domain, device type, CPU, vendor, model, version, site, rack, board
  ID, and notes;
- whether the device is simulated;
- supported protocols; and
- protocol endpoint host and port.

Usernames and passwords are excluded.

### `session_list(device_id=None)`

Returns all known sessions, optionally filtered by device:

- runtime-stable `session_id`;
- device ID and name;
- protocol;
- connection state: `connecting`, `connected`, or `disconnected`;
- whether it is the current session;
- whether the underlying transport reports connected;
- current output cursor; and
- recent disconnect or connection message when available.

The existing session tab ID is used as the runtime-stable `session_id` for
this phase. It is not persisted across Device TUI restarts.

### `session_manage(...)`

Inputs:

```text
action: open | status | reconnect | disconnect | close
device_id: optional except when opening
session_id: optional when a device uniquely identifies a session
protocol: auto | telnet | ssh | serial | simulated
timeout_seconds: 1-60, default 15
```

Rules:

- `open` requires `device_id`.
- `protocol=auto` follows the App's normal device connection strategy.
- An explicit protocol must be supported and configured by the target device.
- `status`, `reconnect`, `disconnect`, and `close` prefer `session_id`.
- A `device_id` fallback is accepted only when exactly one matching session
  exists.
- Multiple matching sessions produce `ambiguous_session` and include
  credential-free candidate summaries.
- `open` and `reconnect` wait for the transport to report connected.
- A connection timeout returns the created or reused `session_id` and current
  status so the caller can poll or retry.

### `terminal_execute(...)`

Inputs:

```text
command: required, maximum 16,384 characters
session_id: preferred
device_id: accepted only when the session is unique
timeout_seconds: 1-300, default 30
max_output_chars: 1-32,768, default 16,384
approval_token: optional, used only in required approval mode
idempotency_key: optional
```

Execution flow:

1. Resolve exactly one connected session.
2. Capture its monotonic output cursor.
3. Send the normalized command through the existing risk and audit path.
4. Poll incremental output without blocking the Qt main thread.
5. Finish when a recognized prompt appears after command output.
6. If no prompt is recognized, finish after output has been received and then
   remains unchanged for 800 milliseconds.
7. Finish with a timeout or disconnected result when applicable.

Response data:

```text
execution_id
session_id
device_id
command
status: completed | timed_out | disconnected | failed
output
duration_ms
completion_reason: prompt | idle | timeout | disconnected
prompt_matched
output_cursor_start
output_cursor_end
truncated
```

Timeout and disconnect responses retain partial output. They return a
structured error while preserving the response data.

## Output Cursor Model

Each session stores:

- `output_cursor`: total characters appended over the session lifetime; and
- `output_buffer_start_cursor`: cursor represented by the first character in
  the bounded recent-output buffer.

Appending output increments `output_cursor`. The recent buffer remains bounded
at 120,000 characters. When older output is trimmed,
`output_buffer_start_cursor` advances accordingly.

An incremental read uses absolute cursors:

- If the requested cursor is inside the retained window, return only later
  output.
- If it predates the retained window, return the retained buffer with
  `truncated=true`.
- Never silently reinterpret a stale cursor as an index in the current buffer.

This model remains correct when the recent buffer is trimmed.

## Prompt Detection

Prompt detection operates on ANSI-stripped, newline-normalized output and
recognizes at least:

- Huawei-style operational prompts such as `<Device>`;
- Huawei-style configuration prompts such as `[Device]`;
- simulated prompts such as `<sim>`;
- Linux shell prompts ending in `$` or `#`.

Only output after the captured cursor is inspected. A prompt that existed
before the command cannot complete the new command.

The response states whether completion came from a prompt or idle fallback.
Idle completion is not presented as prompt-confirmed completion.

## Errors

New structured error codes:

- `device_not_found`
- `unsupported_protocol`
- `session_not_found`
- `ambiguous_session`
- `session_connect_timeout`
- `session_not_connected`
- `command_timeout`
- `session_disconnected`

Validation errors remain `invalid_request`. Authentication, request-size,
approval-mode, audit-redaction, and UI-dispatch timeout behavior remain
unchanged.

## Risk, Approval, Audit, and Idempotency

`terminal_execute` uses the same command normalization and risk classifier as
`terminal_send_command`.

Device TUI approval behavior remains controlled by
`DEVICE_TUI_APPROVAL_MODE`. The default disabled mode executes immediately,
while required mode preserves the existing approval-token flow.

Every new action writes an audit entry containing source, tool, device ID,
session ID when available, risk, approval mode, result status, and duration.
Credentials and approval tokens remain redacted.

An optional `idempotency_key` prevents a completed or timed-out execution from
being sent again by a retry from the same source and tool contract. The cached
response retains its original `execution_id`.

## HTTP Routes

The MCP client uses these new App Control routes:

```text
GET  /v1/status
GET  /v1/devices/{device_id}
GET  /v1/sessions?device_id={device_id}
POST /v1/sessions/manage
POST /v1/terminal/execute
```

All five routes require the existing bearer token. Path and query values are
URL encoded by the client.

## Testing

### Unit tests

- Output cursor advancement and buffer trimming.
- Incremental reads before, inside, and after the retained window.
- ANSI stripping and prompt recognition for Huawei, simulated, and Linux
  prompts.
- Idle fallback after output.
- Timeout and disconnect results preserve partial output.
- Device serialization excludes credentials.
- Automatic protocol selection and explicit protocol validation.
- Ambiguous session lookup includes candidates.

### Service and HTTP tests

- All new routes require authentication except health.
- New input limits and enum validation.
- `terminal_execute` preserves risk classification, approval policy, audit,
  and idempotency behavior.
- Connection and command waits do not execute sleep loops on the UI thread.

### MCP tests

- New tool names and schemas are exposed.
- Existing tool names and required parameters remain unchanged.
- MCP returns structured App Control errors instead of raising protocol-level
  failures.

### Qt integration tests

- Open the simulated session and wait for connected state.
- Execute `display version`.
- Verify the result contains the version output and excludes text that existed
  before the captured cursor.
- Open or construct multiple sessions for one device and verify that
  device-only execution is rejected as ambiguous.
- Execute by `session_id` and verify output comes from the selected session.
- Verify disconnect, reconnect, status, and close transitions.

## Acceptance Criteria

- Claude Code or OpenCode can discover a device, inspect it, open a session,
  execute a command, and receive command-specific output without reading stale
  terminal history.
- The result distinguishes prompt completion, idle completion, timeout, and
  disconnect.
- Multiple sessions for one device cannot cause silent execution against the
  wrong session.
- Real SSH, Telnet, serial, and simulated sessions continue to be owned by
  Device TUI.
- Existing MCP clients and tools continue to work.
- No credentials or App Control tokens are exposed by the new tools.
- The focused App Control and MCP test suites pass.
