# Local Terminal Orchestration Engine Design

## Objective

Replace model-paced terminal control with a local, event-driven execution
engine owned by Device TUI.

Today an AI must call a tool, wait for the result, inspect an intermediate
prompt, and call another tool. That design makes model and MCP latency part of
the device protocol. Interactive commands such as FTP login can time out
before the next tool call arrives, and multi-command work requires excessive
round trips.

The new design lets an AI submit a complete command list or interaction plan
once. Device TUI then reacts to terminal output locally, advances the plan,
and returns structured step results. FTP, SFTP, pagination, confirmation
questions, reboot waits, and secondary logins become uses of the same engine
rather than independent timing fixes.

## Design Principles

- Device TUI remains the sole owner of transports, sessions, and credentials.
- AI describes work; Device TUI owns terminal timing.
- One terminal session has exactly one active automation owner.
- Explicit output matches determine progress. Fixed delays and idle detection
  are fallbacks, not the primary protocol.
- Long-running work is represented as a queryable and cancellable operation.
- Existing MCP tools remain compatible and become wrappers around the engine
  where practical.
- Results identify the exact step, output, prompt, duration, and failure.
- Secrets are referenced by opaque local names and never returned to the AI.

## Scope

### Included

- Add a reusable, event-driven terminal orchestration engine.
- Add per-session execution leases.
- Cancel active AI execution when a user manually types in the same session.
- Suppress persistent auto-response rules while an execution owns a session.
- Support send, expect/respond, control input, and connection-state steps.
- Support local secret references for transfer credentials.
- Add `terminal_execute_batch`, `terminal_interact`, `execution_get`, and
  `execution_cancel` MCP tools.
- Preserve `terminal_execute` and existing operation tools.
- Migrate the package-upgrade transfer stage to the new interaction engine.
- Add built-in prompt profiles and common interactive failure patterns.
- Replace per-command HTTP/UI output polling with completion notification from
  the local engine.
- Add focused unit, service, MCP, simulated-session, and Qt integration tests.

### Excluded

- A visual workflow editor.
- Arbitrary code execution inside interaction plans.
- Multi-device fan-out or coordinated fleet operations.
- Persisting or resuming an in-flight execution after Device TUI restarts.
- A new SSH, Telnet, serial, FTP, or SFTP transport implementation.
- Replacing the existing package-upgrade planning and validation stages.
- Letting MCP callers read raw local secrets.

## Architecture

The control path becomes:

```text
Codex / Claude Code / OpenCode
             |
             | one MCP tool call
             v
        MCP tool wrappers
             |
             | authenticated loopback HTTP
             v
       AppControlService
             |
             | start execution / wait or return operation
             v
 TerminalExecutionCoordinator
             |
             | one lease per session
             v
   TerminalExecutionRunner
             |
             | send input / receive output events
             v
 Existing Device TUI session transport
```

The coordinator owns execution registration, session leases, cancellation,
completion events, and result retention. Each runner owns one immutable plan
and its mutable step state.

A lease owner may be a terminal runner or an existing higher-level operation.
This allows the package-upgrade state machine to hold one lease for its entire
run while delegating interactive transfer steps to a child runner with the
same owner ID.

`execution_id` is the coordinator's canonical identifier. Existing
package-upgrade `operation_id` values use the same identifier and remain
available under the old field name for compatibility.

`append_session_output()` continues to update the terminal and absolute output
cursors. It additionally forwards each output chunk to the active runner for
that session. Pattern matching and state transitions are fast in-memory work
on bounded text. Sending the next response is queued through the existing Qt
input path and does not wait for another HTTP or MCP call.

The App Control HTTP worker may synchronously wait on a thread-safe completion
event for short executions. It does not poll the Qt UI for terminal output.
Long executions return an `execution_id` immediately and are observed through
`execution_get`.

Completed results are retained for 24 hours, with a hard limit of the most
recent 256 executions. Active executions are never evicted.

## Components

### Plan Model

Create a focused module, `src/terminal_orchestration.py`, containing
Qt-independent data models and the state machine:

- `TerminalExecutionPlan`
- `TerminalExecutionStep`
- `SendStep`
- `ExpectStep`
- `WaitStateStep`
- `TerminalExecutionResult`
- `TerminalStepResult`
- prompt and failure match helpers

The plan is immutable after validation. Runtime state is held by a runner and
includes the current step index, absolute output cursor, bounded step output,
matched prompt, response counts, timeout deadline, retry count, and
cancellation token.

The first version supports these primitives:

#### `send`

Send ordinary text, a control key, or a local secret reference.

```json
{
  "type": "send",
  "text": "display version",
  "append_enter": true
}
```

Exactly one of `text`, `control`, or `secret_ref` is allowed. Supported control
names initially include `enter`, `space`, `ctrl_c`, and `ctrl_y`.

When a send step is immediately followed by an expect step, the runner arms
the expect matcher and captures its output cursor before queuing the input.
This prevents a fast device response from arriving between send completion and
matcher registration.

#### `expect`

Wait for a success match while optionally responding to intermediate prompts.

```json
{
  "type": "expect",
  "success": ["device_prompt"],
  "responses": [
    {
      "match": "---- More ----",
      "control": "space",
      "max_matches": 200
    }
  ],
  "failures": ["Error:", "Unrecognized command"],
  "timeout_seconds": 30
}
```

Matches may be literal strings or built-in aliases. Literal matching is
case-sensitive by default and may opt into case-insensitive matching. The
first version does not accept arbitrary regular expressions from MCP callers;
built-in prompt profiles may use reviewed regular expressions internally.
This avoids executing unbounded regular-expression work on the UI thread.

An expect step can respond many times before its success condition appears,
which covers paging and repeated confirmations without loops or executable
plan logic.

Each response item contains one match and exactly one of `text`, `control`, or
`secret_ref`. It may set `append_enter`, case sensitivity, and
`max_matches`. A response inherits the parent expect-step timeout; every
response match is counted and recorded with sensitive values redacted.

Matching uses a bounded accumulator that spans output chunks. Prompts split
across multiple transport callbacks are therefore detected correctly.

#### `wait_state`

Wait for `connected`, `disconnected`, or a disconnect followed by reconnect.
This is used for reboot and transport lifecycle operations.

Plans are linear in the first version. Failure alternatives and repeated
intermediate responses cover the required interactive cases without adding a
general branching language. A failed plan returns enough structured state for
the AI to submit a new plan.

### Coordinator And Session Lease

Add a `TerminalExecutionCoordinator` owned by `DeviceDesktopApp`.

It provides:

- plan validation and registration;
- one active execution lease per `session_id`;
- output and session-state event delivery;
- explicit and user-triggered cancellation;
- synchronous completion notification;
- bounded retention of completed results; and
- lookup by `execution_id`.

Starting a second execution on a leased session returns `session_busy` and the
active `execution_id`. It never interleaves commands.

All terminal input gains an origin:

```text
user | ai_execution | auto_response | package_upgrade | internal
```

Manual input has priority. If input with origin `user` arrives while a runner
holds the session lease, the coordinator first marks that runner
`cancelled_by_user`, releases the lease, and then sends the user's input.
Device TUI does not automatically send `Ctrl+C`, because doing so could alter
the user's intended input or interrupt a destructive device operation. The
terminal remains in its actual current state and the UI shows that automation
was cancelled.

Existing persistent auto-response rules are suspended for a leased session.
The execution plan's own expect/respond rules are the only automatic
responders until the lease is released. This prevents duplicate responses and
crossed state machines.

The existing pending input string becomes a queue of input records containing
origin, execution ID, sensitivity, and text. Cancelling an execution removes
its unsent records before user input is queued. This guarantees that a delayed
AI response cannot be flushed after manual input has taken control.

Timeout callbacks carry the execution token and step index. A callback from an
old or cancelled step becomes a no-op.

### Prompt Profiles

Prompt profiles convert stable aliases into reviewed matchers. Initial
profiles cover:

- Huawei operational and configuration prompts;
- Linux shell prompts;
- simulated device prompts;
- FTP command prompts;
- username and password prompts;
- SFTP host-key confirmation;
- common pagination prompts; and
- common confirmation prompts.

The profile is selected from session protocol and device metadata, with a
generic fallback. A caller may add literal alternatives to handle an
unrecognized device without changing the profile.

Completion precedence is:

1. explicit failure pattern;
2. explicit success literal;
3. built-in prompt alias;
4. explicit idle fallback when the caller enabled it;
5. timeout.

An intermediate username or password prompt is not an idle-completed command.

### Secret Resolver And Sensitive Input

Device TUI exposes a small internal resolver for approved secret names. The
initial names are:

```text
transfer.username
transfer.password
```

The resolver reads the current file-transfer configuration when execution
starts. It does not expose environment variables, arbitrary settings keys, or
filesystem content. Future secret names must be added explicitly.

Sensitive sends use a dedicated input path:

- plaintext is not written to terminal input logs;
- plaintext is not added to command history;
- plaintext is not included in audit requests or step results;
- audit and UI records contain the secret reference and `***`;
- known secret values are redacted from captured output if a device echoes
  them.

Ordinary literal text supplied by an MCP caller remains auditable. A caller
must use an approved `secret_ref` to receive secret-handling guarantees.

### Tool Wrappers

The engine has one internal execution contract, but MCP exposes ergonomic
tools.

#### `terminal_execute`

The existing contract remains unchanged. Internally it compiles one command
into:

1. a `send` step; and
2. an `expect` step for `device_prompt`.

Its existing idle fallback remains enabled for compatibility, and the response
retains the existing fields.

#### `terminal_execute_batch`

Inputs:

```text
commands: 1-50 non-empty command strings
session_id: preferred
device_id: allowed only for a unique session
stop_on_error: default true
command_timeout_seconds: 1-300, default 30
total_timeout_seconds: 1-3600, default derived from command count
max_output_chars_per_step: 1-32768, default 16384
mode: auto | sync | async, default auto
idempotency_key: optional
```

Each command becomes send plus expect-prompt steps. The response contains one
result per command. With `stop_on_error=true`, a failure or timeout ends the
plan before the next command.

A timeout, disconnect, cancellation, or missing final prompt always stops the
batch, regardless of `stop_on_error`. With `stop_on_error=false`, the next
command may run only after a recognized command failure that also returned to
the expected device prompt.

Risk is the highest classified risk among all commands. Idempotency applies to
the whole batch, so an MCP retry cannot resend a partially completed list.

#### `terminal_interact`

Inputs:

```text
steps: 1-100 validated send, expect, and wait_state objects
session_id or unique device_id
total_timeout_seconds: 1-3600
mode: auto | sync | async, default auto
idempotency_key: optional
```

The service validates size, step types, match counts, timeout ranges, control
names, and secret-reference allowlists before acquiring a lease. Risk is the
highest risk of every literal send. Secret values are resolved only inside
Device TUI after validation and lease acquisition.

Interactive plans have a minimum risk level of `FLOW`, because an apparently
harmless response such as `y` can confirm a destructive operation in context.
Literal sends may raise the final risk above that minimum.

In `auto` mode, plans with a total timeout of at most 60 seconds and no
long-running state wait execute synchronously. Other plans return immediately
as asynchronous operations. Explicit `sync` mode is rejected when the total
timeout exceeds 60 seconds. This keeps MCP and HTTP calls within predictable
client timeout limits.

#### `execution_get`

Returns execution status, current step, completed step results, redacted
partial output, timing, and cancellation state.

#### `execution_cancel`

Cancels an active execution and releases its session lease. It is idempotent:
cancelling an already terminal execution returns its current result.

The existing `operation_get` remains for compatibility. It can delegate
terminal execution IDs to the same registry while preserving current
package-upgrade operation responses.

### Built-In Workflows

Built-in workflows are Python plan factories with validated parameters. They
use the same engine and result model as caller-supplied plans.

The package-upgrade download stage becomes the first migrated workflow:

1. Send `ftp` or `sftp`.
2. Respond to username and password prompts using transfer secret references.
3. For SFTP served by the transfer service started by the current Device TUI
   process, respond `yes` to a first-use host-key question. A changed-key
   warning is a hard failure and is never bypassed.
4. Detect authentication failures explicitly.
5. Enter binary mode for FTP.
6. Start `get` and wait for the transfer prompt, with a package-size-aware
   timeout.
7. Detect transfer errors.
8. Quit and confirm the device prompt.

The rest of package upgrade continues to use its current validation,
space-check, copy, startup-setting, and optional reboot stages. The legacy
`package_upgrade_start` tool remains the public compatibility entry point and
starts the migrated workflow internally.

The package-upgrade operation acquires the session lease before its first
terminal command and holds it through completion, failure, or cancellation.
Existing non-transfer stages send with the same lease owner ID. Manual input
or `execution_cancel` stops future upgrade steps, removes unsent inputs, keeps
partial state for inspection, and releases the lease.

`package_upgrade_start` returns both `operation_id` and `execution_id` with the
same value. Existing clients continue polling `operation_get`; new clients may
use `execution_get` and `execution_cancel`.

MCP server instructions tell agents to prefer the package-upgrade tool for an
upgrade objective. `terminal_interact` remains available for other workflows;
the preference is guidance, not a hard capability restriction.

## Data Flow

### Synchronous Short Execution

1. MCP sends one `terminal_execute_batch` or `terminal_interact` request.
2. App Control validates the complete plan and resolves one session.
3. The coordinator acquires the session lease and returns a completion event
   to the HTTP worker.
4. The runner sends the first step on the Qt thread.
5. Session output enters `append_session_output()`.
6. The runner matches output and immediately queues any response or next step.
7. On completion, failure, timeout, disconnect, or cancellation, the runner
   stores the result, releases the lease, and signals the HTTP worker.
8. MCP receives one structured response for the complete execution.

### Asynchronous Long Execution

Steps 1-6 are the same. The initial request returns after registration with
`execution_id` and `status=running`. The AI uses `execution_get` at a
reasonable interval or `execution_cancel` when needed.

## Error Handling

Add these structured errors and terminal statuses:

- `invalid_plan`
- `session_busy`
- `secret_ref_not_allowed`
- `secret_unavailable`
- `step_timeout`
- `response_limit_exceeded`
- `execution_cancelled`
- `cancelled_by_user`
- `execution_not_found`

Existing `session_not_found`, `ambiguous_session`,
`session_not_connected`, `session_disconnected`, `command_timeout`, approval,
and authentication errors remain.

Every terminal result preserves:

- execution and session IDs;
- final status;
- current or failed step index;
- completed step results;
- redacted partial output;
- matched success or failure pattern;
- duration and response count; and
- whether the lease was released.

Retries are allowed only when a plan or built-in workflow explicitly marks a
step retryable. A retry restarts that step from a known prompt boundary. The
engine does not blindly resend a timed-out destructive command.

If Device TUI closes or the session disappears, the execution becomes
`session_disconnected`, retains partial output, and releases all resources.

## Audit And Compatibility

One audit parent record represents the tool call. Child step metadata records
command risk, status, duration, and redacted output summary. Sensitive text is
never stored.

An idempotency key is reserved when an execution is registered, not only when
it finishes. A retry while the original execution is running receives the
same execution record instead of acquiring a second lease or resending steps.

Existing MCP names and HTTP routes continue to work. New tools are additive.
Claude Code, OpenCode, and Codex MCP registrations do not need to change.

The old `terminal_send_command` and `terminal_read` tools remain available for
low-level compatibility, but MCP instructions recommend `terminal_execute`,
batch execution, or interactive execution when a result is required.

## Performance Targets

- Intermediate prompt to locally queued response: at most 100 ms at p95 under
  normal desktop load.
- A batch of N ordinary commands requires one MCP round trip instead of N.
- No fixed delay is inserted between steps after the expected prompt appears.
- No HTTP worker repeatedly dispatches terminal snapshots to the Qt thread.
- Output matching examines only the bounded output since the active step
  cursor.
- The UI remains responsive during long transfers and waits.

These targets improve execution latency without sending commands before the
device is ready.

## Testing

### Unit Tests

- Plan validation and input limits.
- Prompt aliases and literal alternatives.
- Match priority: failure before success before idle.
- Repeated pagination responses and response limits.
- Step and total timeout behavior.
- Cancellation tokens make stale callbacks inert.
- Session lease acquisition, conflict, and release.
- User input cancels the active runner.
- Secret resolver allowlist and unavailable-secret errors.
- Sensitive text is absent from results, logs, command history, and audit.
- Batch risk is the maximum command risk.
- Completed and partially completed idempotent requests are not resent.

### Simulated Session Tests

Extend the simulator so prompts can be:

- split across multiple output chunks;
- delayed by configurable amounts;
- repeated for paging;
- followed by authentication failure;
- timed out after waiting for input;
- interrupted by disconnect; and
- optionally echoed to verify secret redaction.

Verify FTP and SFTP flows respond locally without a second MCP call and remain
successful when simulated model delay exceeds the device login timeout.

### Service And MCP Tests

- New tool names and schemas are exposed.
- Existing tool schemas remain compatible.
- Batch responses contain per-command output and failure location.
- Interactive plans reject invalid controls, secret references, and excessive
  limits.
- Synchronous and asynchronous execution return consistent results.
- `execution_get` and `execution_cancel` are authenticated.
- Session-busy errors include the active execution ID.
- Structured errors reach MCP as tool results rather than protocol failures.

### Qt Integration Tests

- Execute several commands in one batch against the simulated session.
- Execute FTP login, binary mode, transfer, and quit as one local plan.
- Run the one-click package upgrade through the migrated transfer stage.
- Type manually during an active plan and verify cancellation precedes user
  input.
- Verify persistent auto-response rules are suspended during a lease and
  restored afterward.
- Close and disconnect sessions during execution and verify cleanup.
- Confirm the UI thread stays responsive during delayed output.

## Acceptance Criteria

- An AI can execute a multi-command task with one MCP call and receive
  command-specific structured results.
- Interactive prompts are answered locally without waiting for another model
  or MCP round trip.
- FTP and SFTP credentials come from Device TUI configuration and are not
  exposed to the AI, terminal logs, command history, audit, or results.
- Package upgrade no longer depends on the AI typing transfer credentials.
- A session never runs two automation plans concurrently.
- Manual user input cancels automation before the user input is sent.
- Persistent auto-response rules cannot race an active execution.
- Prompt-driven steps advance immediately and do not use fixed inter-command
  delays.
- Timeout, disconnect, cancellation, and failure preserve redacted partial
  output and identify the failed step.
- Existing MCP clients and existing tools continue to work without
  reconfiguration.
- Focused and full test suites pass except for explicitly documented,
  pre-existing unrelated failures.
