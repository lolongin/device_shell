# MCP Package Split and Execution Performance Design

## Goal

Restructure the Device TUI MCP implementation into a maintainable
`src/device_mcp/` package and reduce end-to-end command latency without breaking
existing MCP clients, Python imports, command names, approvals, audit logging,
or guarded package-upgrade behavior.

The performance work targets all reported slow paths:

- first or single-command execution;
- several sequential commands;
- commands whose output is complete before MCP returns;
- long stateful workflows such as package replacement.

## Public Compatibility

The following remain available:

- the `device-tui-mcp` console command;
- `python -m src.mcp_server`;
- imports from `src.mcp_server`, `src.app_control`,
  `src.app_control_client`, and `src.app_control_server`;
- all existing MCP tool names and input schemas;
- approval, idempotency, audit, terminal lease, and secret-redaction behavior.

The old modules become small compatibility facades that re-export the new
implementations. New code imports from `src.mcp`.

## Package Architecture

```text
src/device_mcp/
|-- __init__.py
|-- server.py
|-- gateway.py
|-- client.py
|-- http_server.py
|-- core.py
|-- models.py
|-- approval.py
|-- audit.py
|-- validation.py
|-- actions.py
|-- execution.py
|-- operations.py
|-- service.py
`-- tools/
    |-- __init__.py
    |-- system.py
    |-- devices.py
    |-- sessions.py
    |-- terminal.py
    |-- transfers.py
    `-- operations.py
```

Responsibilities:

- `server.py` creates the `FastMCP` instance, registers tool groups, and
  exposes `main()`.
- `tools/` contains only public MCP schemas, descriptions, and delegation to
  the gateway.
- `gateway.py` owns the long-lived application-control client and converts
  transport failures into the stable MCP response envelope.
- `client.py` implements the local HTTP API and a small bounded keep-alive
  connection pool.
- `http_server.py` exposes the loopback HTTP routes using HTTP/1.1 keep-alive.
- `core.py` contains shared constants, errors, backend protocols, timestamps,
  command normalization, and action fingerprints.
- `models.py`, `approval.py`, and `audit.py` isolate records, approval-token
  lifecycle, redaction, and audit persistence.
- `validation.py` owns request coercion and validation.
- `actions.py` converts validated public tool input into guarded device
  actions.
- `execution.py` coordinates session preparation and terminal executions.
- `operations.py` tracks and waits for long-running operations.
- `service.py` remains the thin application-control coordinator.

Lower-level modules must not import tool-registration modules. This keeps the
dependency direction one-way and prevents circular imports.

The package is named `device_mcp` rather than `mcp` because this repository
adds `src` to `sys.path` for tests and direct desktop execution. A local
`src/mcp` directory would shadow the installed Python `mcp` SDK and break
`mcp.server.fastmcp` imports.

## Gateway and Transport Performance

The MCP process creates one `McpGateway` for its lifetime.

- It caches the parsed control state using state-file path, modification time,
  and size.
- It does not issue a `/health` request before every tool call.
- A changed state file rebuilds the client before the next request.
- The client reuses a bounded pool of loopback HTTP/1.1 connections.
- Stale keep-alive connections are discarded and recreated.
- Read-only calls may retry once after reconnecting.
- Mutating calls are not retried automatically unless they have an explicit
  idempotency key, preventing duplicate commands or upgrades.
- Every MCP tool delegates through the same gateway, so errors have one stable
  response shape.

## Preferred `terminal_run` Tool

Add a new preferred tool:

```python
terminal_run(
    commands: list[str],
    session_id: str | None = None,
    device_id: str | None = None,
    ensure_session: bool = True,
    protocol: str = "auto",
    command_timeout_seconds: int = 30,
    total_timeout_seconds: int | None = None,
    max_output_chars_per_step: int = 16_384,
    approval_token: str | None = None,
    idempotency_key: str | None = None,
)
```

Behavior:

1. Require either `session_id` or `device_id`.
2. Reuse a connected matching session when available.
3. When `ensure_session` is true, open or reconnect and wait for a usable
   session inside the same MCP call.
4. Execute one or many commands through `TerminalExecutionCoordinator`.
5. Complete immediately when a known prompt is observed; use the existing
   bounded idle fallback only for unknown prompts.
6. Return a consistent per-step result and timing breakdown.

Calling `terminal_run` with one command uses the event-driven path just like a
multi-command run. `terminal_execute` retains its exact legacy response and
polling semantics for compatibility, while `terminal_execute_batch` keeps its
existing coordinator path. `terminal_send_command` and
`terminal_read` remain available for raw compatibility use, but MCP
instructions identify `terminal_run` as the normal command tool.

## Stateful and Long-Running Workflows

The execution layers are intentionally separate:

- ordinary commands use `terminal_run`;
- prompt-driven generic flows use `terminal_interact`;
- package replacement uses the dedicated package-upgrade state machine;
- other long operations use operation tools.

`terminal_interact` keeps its existing send, expect, automatic-response, and
wait-state steps. It gains bounded branching controls:

- `on_match` can jump forward to a named step;
- `on_failure` can stop, retry within an explicit maximum, or jump to a named
  cleanup step;
- all jumps are validated before execution;
- backward jumps require a finite retry limit;
- existing plans without branching behave exactly as before.

Package replacement is not expressed as a list of raw MCP commands. The
desktop package-upgrade state machine continues to own file selection,
transfer, verification, startup selection, reboot policy, reconnect, final
version checks, rollback-safe stopping, and audit records.

Add `operation_wait(operation_id, timeout_seconds=60, since_revision=0)`.
It waits inside the application-control service until the operation changes,
finishes, or the timeout expires. Service-owned state changes notify waiters;
existing backend operations use a bounded internal refresh interval until
they publish native notifications. This replaces repeated model-paced
`operation_get` polling while preserving `operation_get` for snapshots.

## Timing and Observability

Command and operation responses include a `timing` object where applicable:

- `gateway_ms`: MCP gateway and local transport time;
- `session_prepare_ms`: lookup, open, reconnect, and readiness time;
- `device_execution_ms`: time from first send to terminal completion;
- `total_ms`: total server-side elapsed time.

Per-command steps retain `duration_ms` and `completion_reason`. Audit records
store timings and result metadata but never command secrets or resolved local
credentials.

## Error Handling

- Missing desktop state returns `app_unavailable` without a redundant health
  probe.
- A changed desktop PID, URL, or token invalidates cached connections.
- Session preparation returns the existing session errors and never silently
  targets a different device.
- Terminal leases still prevent concurrent automation on one session.
- User terminal input cancels automation using the current coordinator rules.
- Failed, timed-out, disconnected, and cancelled executions return partial
  redacted output.
- Invalid workflow jumps, cycles without limits, and unknown labels are
  rejected before any command is sent.
- `operation_wait` timeout is a successful wait response with unchanged
  revision, not an operation failure.

## Testing and Acceptance Criteria

Tests cover:

- legacy import and CLI compatibility;
- exact preservation of existing MCP tool schemas;
- registration and schema of `terminal_run` and `operation_wait`;
- gateway state caching and removal of per-call health probes;
- keep-alive reuse, stale-connection recovery, and safe retry rules;
- one-call session preparation plus command execution;
- single-command `terminal_run` use of the event-driven coordinator with no
  50 ms snapshot polling loop;
- multi-command ordering, prompt completion, idle fallback, disconnect,
  cancellation, leases, idempotency, and secret redaction;
- valid and invalid `terminal_interact` branches;
- `operation_wait` change, completion, and timeout behavior;
- unchanged package-upgrade and managed-transfer workflows.

Acceptance criteria:

- an MCP tool call performs no unconditional `/health` preflight;
- one `terminal_run` call can open/reuse a session and execute one or many
  commands;
- known terminal prompts complete through output events rather than service
  polling;
- package upgrade remains a guarded domain workflow;
- the full existing test suite passes, with focused performance-path tests;
- README and project layout documentation describe the new preferred tools
  and compatibility paths.

## Implementation Sequence

The refactor is delivered in dependency-safe phases:

1. Create the package foundations and compatibility facades without changing
   runtime behavior.
2. Split tool registration, introduce the gateway, and add transport caching
   and keep-alive tests.
3. Add `terminal_run` and route legacy execute tools through the event-driven
   coordinator.
4. Add validated interaction branching and `operation_wait`.
5. Update documentation, run focused integration tests, and run the complete
   regression suite.

Each phase must leave the legacy imports and CLI executable so failures are
isolated to a small migration step.

## Non-Goals

- Replacing loopback HTTP with WebSocket, named pipes, or direct GUI imports.
- Letting MCP bypass approvals, audit logging, terminal leases, or package
  guards.
- Automatically parallelizing commands on the same terminal session.
- Retrying arbitrary mutating requests after an ambiguous transport failure.
