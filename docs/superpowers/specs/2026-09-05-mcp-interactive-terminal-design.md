# MCP Interactive Terminal Execution Design

## Goal

Make interactive SSH/Telnet command flows usable through MCP when a device pauses
for a prompt, confirmation, pagination, or user input. Keep the existing
synchronous `terminal.interact` behavior as a compatibility wrapper.

## API shape

- `terminal.interact.start`: validate a plan, acquire the session execution
  lease, start immediately, and return `execution_id` plus a state snapshot.
- `terminal.interact.get`: return the current or final snapshot for an
  execution.
- `terminal.interact.send`: send text or a supported control to the active
  execution and keep its lease; reject input when the execution is not waiting
  for input.
- `terminal.interact.cancel`: cancel the execution and release its lease.
- `terminal.interact.resume`: resume a user-taken-over execution from its
  checkpoint with the same session.
- Existing `terminal.interact` remains a synchronous convenience call and uses
  the same execution model internally.

## State model

Execution responses expose stable fields: `execution_id`, `session_id`,
`device_id`, `status`, `phase`, `current_step`, `total_steps`, `waiting_for`,
`last_output`, `matched_prompt`, `can_send`, `can_cancel`, `can_resume`, and a
monotonic event cursor. Events identify output, prompt matches, automatic
responses, user takeover, retries, disconnects, and completion.

## Behavior

- Automatic response rules continue to run inside the runner.
- Manual input is associated with `execution_id`, so it does not become an
  unrelated raw command.
- User input marks the execution as `cancelled_by_user` while preserving its
  checkpoint for an explicit resume.
- Disconnect immediately finalizes the execution as `disconnected` and exposes
  a reconnect/resume hint.
- Invalid plans return field-level validation details at the MCP boundary.
- Timeout values preserve numeric semantics; no implicit conversion of zero or
  fractional values occurs.

## Compatibility and testing

The legacy MCP names continue to delegate to the same execution operations.
Tests cover start/get/send/cancel/resume, waiting states, prompt responses,
user takeover, disconnect, invalid plans, and synchronous compatibility.
