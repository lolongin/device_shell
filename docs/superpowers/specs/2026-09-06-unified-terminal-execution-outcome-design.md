# Unified Terminal Execution Outcome Design

## Goal

Make terminal execution results reliable for MCP agents and scripts. A caller
must be able to distinguish transport/API success, execution lifecycle state,
command-level success, interactive suspension, and an indeterminate result
without parsing raw terminal output.

The same state and classification rules apply to `terminal.execute`,
`terminal.batch`, `terminal.interact`, and the incremental interaction tools.

## Current Problems

The existing terminal execution surface has four related gaps:

1. `terminal.interact.start` only consumes output emitted after the runner
   starts. It cannot safely continue a session already stopped at a prompt.
2. A final `expect` match can leave an execution running and retain the session
   lease instead of completing naturally.
3. `terminal.execute` and batch execution can report `completed` when the
   device is actually waiting at a confirmation or other input prompt.
4. Lifecycle fields describe whether the runner stopped, but do not provide a
   machine-readable command outcome. Callers must infer errors and useful
   results from `output` and `events`.

These are one state-model problem rather than four independent API problems.

## Unified State Model

The response keeps the existing top-level `ok`, `status`, `phase`, `message`,
and execution metadata for compatibility. Their meanings are explicit:

- `ok` reports whether the MCP/API request itself was accepted and processed.
- `status` reports execution lifecycle state.
- `phase` reports the runner's current activity.
- `outcome` reports the command-level result.

Lifecycle terminal states remain `completed`, `failed`, `timed_out`,
`cancelled`, `cancelled_by_user`, and `disconnected`. An execution waiting for
input remains `status: running` with `phase: waiting_for_input`; it is not
completed.

Every terminal execution response includes:

```json
{
  "outcome": {
    "status": "success",
    "finished": true,
    "command": "display version",
    "prompt": {
      "type": "command_prompt",
      "text": "<HUAWEI>",
      "view": "user"
    },
    "result_text": "VRP (R) software, Version 8.220",
    "errors": [],
    "basis": "command_prompt_and_no_error",
    "confidence": "high",
    "duration_ms": 272
  }
}
```

`outcome.status` is one of:

- `success`: the terminal command finished under a configured success rule,
  including the generic command-prompt-without-error rule.
- `failure`: explicit failure evidence was detected.
- `interaction_required`: the command is waiting for caller input.
- `unknown`: timeout, disconnect, or insufficient evidence prevents a reliable
  result.

`finished` means the command reached a terminal command prompt or another
explicit completion condition. It is independent of success. An invalid
command that returns to the device prompt has `finished: true` and
`outcome.status: failure`.

## Prompt And Outcome Classification

Introduce one deterministic classifier in the application terminal layer. It
receives normalized incremental output, the current plan step, protocol and
device metadata, and optional workflow/driver rules. It returns prompt and
outcome evidence without owning execution state.

Prompt types are:

- `command_prompt`: a normal user, system, interface, Linux shell, or similar
  command prompt.
- `confirmation_prompt`: a yes/no or destructive confirmation.
- `pagination_prompt`: a pager that expects space, Enter, or quit.
- `credential_prompt`: username, password, token, or host-key input.
- `unknown_input_prompt`: output strongly indicates input is required but no
  specific safe classification is available.

Classification priority is interaction prompt, explicit failure marker,
explicit success marker, and finally command prompt with no failure evidence.
This prevents `[Y/N]` from being treated as command completion. Timeout or
disconnect without conclusive evidence produces `unknown`.

Rules are layered:

1. Conservative common prompt and error rules.
2. Vendor-adapter rules for Huawei, H3C, Cisco, Linux, and future adapters.
3. Workflow or command-specific success and failure markers.

Error evidence is structured and credential-filtered:

```json
{
  "code": "command_rejected",
  "text": "Error: Unrecognized command",
  "pattern_id": "common.unrecognized_command"
}
```

`result_text` is deterministic, credential-filtered evidence extracted from
the real output, not generated prose. The outcome describes the observable
terminal command result; it does not claim that an arbitrary higher-level
business objective was achieved. Raw output and events remain available for
audit and debugging.

## Interactive Attachment

Starting a runner against arbitrary historical output is unsafe because an old
confirmation prompt could trigger a new response. Incremental interaction
therefore supports two explicit attachment modes:

- `fresh` is the default. The backend records the current output cursor as the
  execution baseline. If the current terminal screen is already waiting for
  input, the call fails immediately with `session_not_ready` and includes the
  detected prompt metadata.
- `attach` is opt-in. The caller supplies the observed output cursor and the
  expected prompt type or text. The backend validates both against the current
  session generation and terminal tail before feeding that bounded tail to the
  new runner.

Session generation prevents attaching after reconnect. Output cursor bounds
prevent scanning unrelated terminal history. A mismatch returns
`stale_terminal_cursor` or `prompt_mismatch` without sending input.

An execution suspended by the unified runner does not require a second runner.
Its `execution_id` remains valid for `terminal.interact.send`, `.get`, and
`.cancel`.

## Runner Transitions And Lease Ownership

The runner is the only owner of execution transitions. When an `expect` step
matches, it atomically records the match, completes the active step, advances
the step index, and either arms the next step or finalizes the execution.

Finalization atomically:

1. Sets the terminal lifecycle state.
2. Stores the final `outcome` and matched prompt evidence.
3. Emits one `finished` event.
4. Signals waiters.
5. Invokes completion callbacks that release the session lease.

All terminal lifecycle states release the execution lease exactly once.
`terminal.interact.cancel` remains an explicit abort operation and is not
required to clean up a successful execution.

When `terminal.execute` or batch execution encounters an input prompt, the
runner remains active and retains its lease. The synchronous MCP call returns a
snapshot with `status: running`, `phase: waiting_for_input`, and
`outcome.status: interaction_required`. The caller continues the same
execution with incremental interaction operations. Retaining the lease prevents
an unrelated command from corrupting the suspended device interaction.

## Batch Semantics

Each batch command has its own `outcome`. The batch also exposes an aggregate
outcome using this precedence:

1. `interaction_required` when the current command awaits input.
2. `failure` when any command has explicit failure evidence.
3. `success` when all commands succeed.
4. `unknown` otherwise.

Batch processing stops at `interaction_required`. After input resolves the
prompt, the same execution continues with the remaining commands.

## Compatibility And Security

- Existing response fields and raw step output remain available.
- New consumers use `outcome`; existing consumers can migrate incrementally.
- The top-level `ok` is not reused for command-level success.
- Secrets are filtered before prompt, error, result, and event evidence is
  stored or returned.
- The classifier never sends input. Response policy stays in the runner and
  requires an explicit response rule or caller input.
- `unknown` is preferred over an unsupported success or failure assumption.

## Testing

Add focused unit and MCP integration coverage for:

- `fresh` start rejecting a session already at `[Y/N]` without waiting.
- `attach` accepting a matching cursor, generation, and prompt.
- stale cursors, reconnect generations, and prompt mismatches sending no input.
- a final `expect` match completing automatically and releasing its lease.
- completion, failure, timeout, cancellation, and disconnect each releasing the
  lease exactly once.
- ordinary execution returning `interaction_required` at confirmation,
  pagination, credential, and unknown input prompts.
- continuing the same execution through `terminal.interact.send`.
- an invalid command returning to a command prompt with `finished: true` and
  `outcome.status: failure`.
- successful commands returning a deterministic result summary.
- timeout and disconnect returning `unknown` when evidence is inconclusive.
- batch per-command and aggregate outcome precedence.
- common and vendor-specific patterns, ANSI output, split terminal chunks, and
  credential redaction.

Run the terminal orchestration, backend MCP, gateway, and server test suites,
then the full Python suite. No renderer behavior changes are required unless it
chooses to display the new outcome fields.

## Non-Goals

- Do not infer arbitrary business intent from terminal text with an LLM.
- Do not claim semantic success when no configured rule can establish it.
- Do not automatically answer a pre-existing prompt without explicit `attach`
  validation.
- Do not add vendor rules directly to MCP route handlers.
