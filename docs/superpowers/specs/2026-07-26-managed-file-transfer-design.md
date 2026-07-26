# Managed File Transfer Design

## Objective

Add a purpose-built MCP workflow for transferring a file from Device TUI's
configured file-transfer share to a device. The workflow must be fast,
credential-safe, and verifiably correct without requiring the AI to operate an
interactive FTP or SFTP client one prompt at a time.

The user phrase "transfer/send a large package" means file transfer only. It
does not select a startup image, start an upgrade, or reboot the device.
"Replace a package" and "upgrade" continue to use `package_upgrade_start`.

## Problem

The generic terminal tools expose enough freedom for an AI to make protocol
mistakes. In one observed run, the AI sent the FTP connection command as the
username, sent `reboot` as the password, guessed credentials, used `bin`
instead of `binary`, used `put` instead of the device-side `get`, ran a device
directory command inside the FTP client, and ended with `q`.

The simulator accepted several of these invalid actions and returned success
responses. This created a false-positive transfer even though no correctly
verified file had reached device storage.

## Design Principles

- AI selects intent and parameters; Device TUI owns protocol timing.
- Device TUI remains the sole owner of local paths and transfer credentials.
- A transfer succeeds only after the device reports the expected file size.
- High-level file transfer and complete package upgrade remain separate tools.
- Shared-directory containment and explicit overwrite are enforced by the App.
- Incorrect simulator behavior must fail clearly rather than imitate success.
- The existing terminal orchestration engine and session leases are reused.

## Scope

### Included

- List regular files under the configured transfer-service root.
- Start a managed transfer from a relative source path to an AI-specified
  device path.
- Default to refusing an existing destination; allow overwrite only when the
  caller explicitly sets `overwrite=true`.
- Automatically open or reuse a device session and start the configured local
  transfer service when needed.
- Perform FTP or SFTP interaction locally with App-owned credentials.
- Verify the destination file name and exact byte size after transfer.
- Return a queryable, cancellable asynchronous operation.
- Tighten the simulated FTP state machine and its success semantics.
- Update MCP instructions so agents choose the high-level tool.
- Add unit, service, MCP, simulator, Qt integration, and live smoke tests.

### Excluded

- Selecting a startup image, activating a package, or rebooting a device.
- Arbitrary local absolute paths supplied by an MCP caller.
- Exposing transfer usernames, passwords, or the local share's absolute path.
- Device-to-host uploads through this managed workflow.
- Resuming an in-flight transfer after Device TUI restarts.
- Fleet fan-out or one call targeting multiple devices.

## Tool Contract

### `file_transfer_list`

Lists files available below the currently configured file-transfer root.

Inputs:

- `path`: optional relative subdirectory, defaulting to the root.
- `recursive`: optional boolean, defaulting to `true`.
- `limit`: optional bounded result count.

Each result contains:

- `relative_path`
- `name`
- `size_bytes`
- `modified_at`

The result never contains the share's absolute path, username, password, or
other service secrets. Symlinks and paths that resolve outside the configured
root are omitted. Results are sorted by relative path for deterministic agent
behavior.

### `file_transfer_start`

Starts a transfer-only operation.

Inputs:

- `device_id`: target device.
- `source_path`: exact relative path returned by `file_transfer_list`.
- `destination_path`: AI-selected absolute device storage path, such as
  `flash:/image.cc` or `slave#flash:/image.cc`.
- `overwrite`: optional boolean, defaulting to `false`.
- `idempotency_key`: optional caller-generated key.

The call validates inputs, registers an operation, and returns promptly with:

- `operation_id`
- `status`
- non-sensitive source metadata
- destination path

Large transfers are asynchronous by default. The existing `operation_get`
tool reads managed transfer state. Add `operation_cancel` as the common
cancellation tool for cancellable high-level operations. The lower-level
`execution_get` and `execution_cancel` tools remain scoped to terminal plans.

Repeated starts with the same idempotency key and equivalent parameters return
the original operation. Reusing the key with different parameters fails.

## Architecture

Add a focused managed-transfer component owned by `DeviceDesktopApp`. It
depends on:

- the current transfer-service configuration and controller;
- device and session lookup helpers;
- `TerminalExecutionCoordinator` for session leases and interactive plans;
- existing session input/output plumbing; and
- a small device-directory result parser.

The component owns operation state, stage transitions, cancellation, result
retention, and final verification. It does not own FTP or SSH transports and
does not duplicate terminal prompt matching.

The App Control and MCP layers only validate the public request, dispatch the
high-level action, and serialize the non-sensitive result. They do not build
FTP command strings.

`package_upgrade_start` remains unchanged at the public boundary. Its existing
transfer stage may reuse internal helpers, but managed transfer must not call
the startup-image, activation, or reboot stages.

## Execution Flow

1. Resolve `source_path` beneath the configured share root. Reject absolute
   paths, traversal, symlinks escaping the root, missing files, directories,
   and unreadable files. Capture the source's exact byte size.
2. Validate `destination_path`. Reject control characters, relative device
   paths, empty basenames, and unsupported storage forms.
3. Open or reuse a connected session for `device_id`.
4. Acquire one external terminal lease for the complete operation. If another
   automation owns the session, return a busy failure.
5. Run `dir <destination_path>` and parse the destination entry.
6. If the destination exists and `overwrite=false`, fail with a conflict that
   includes its reported size. If overwrite is allowed, continue.
7. Ensure the configured FTP or SFTP service is running with the current
   share, endpoint, and credentials.
8. For simulated sessions, configure the expected endpoint, credentials,
   source name, source size, and target path through a test-only session hook.
9. Submit one local terminal interaction plan. It connects to the service,
   responds to username, password, and optional host-key prompts using approved
   local secret references, selects binary mode where applicable, executes a
   device-side download, exits the transfer client, and waits for the device
   prompt.
10. Run `dir <destination_path>` at the device prompt.
11. Mark the operation successful only when the exact destination basename is
    present and its reported byte size equals the captured source size.
12. Release the lease and retain a redacted structured result.

For FTP, the managed command direction is `get <source> <destination>`. The
first version never emits `put`.

## State And Results

Managed transfer stages are:

- `validating`
- `opening_session`
- `prechecking`
- `starting_service`
- `transferring`
- `verifying`
- `completed`
- `failed`
- `cancelled`

`operation_get` status snapshots include operation ID, operation kind, device
ID, source relative path, source size, destination path, stage, elapsed time,
and a concise message. They do not include raw credentials, local absolute
paths, or sensitive terminal responses.

The operation stores the source metadata captured before transfer. If the
source changes before the transfer command is issued, the operation fails
rather than transferring ambiguous content.

Manual user input in the leased terminal cancels the transfer. Explicit MCP
`operation_cancel` stops the child terminal plan, prevents further queued
input, marks the operation cancelled, and releases the lease.

## Errors

Public error codes distinguish:

- `transfer_source_not_found`
- `transfer_source_outside_root`
- `transfer_source_changed`
- `invalid_destination_path`
- `destination_exists`
- `insufficient_space`
- `session_busy`
- `service_start_failed`
- `transfer_login_failed`
- `transfer_command_failed`
- `transfer_timeout`
- `transfer_cancelled`
- `transfer_verification_failed`

Every failure identifies the stage and includes a recovery-oriented message.
Terminal output in results is bounded and redacted. A transfer-client success
line alone is never treated as proof of completion.

## Simulator Behavior

Replace the permissive simulated FTP handling with an explicit state machine:

- `username`
- `password`
- `ready`
- `closed`

The simulator accepts only the credentials configured by the App. Invalid
credentials return `530 Login incorrect` and do not enter the ready state.
Input timeout closes the simulated transfer client.

In the ready state, supported commands are:

- `binary`
- `get <source> <destination>`
- `quit`
- `bye`

`bin`, `put`, `q`, device commands entered at `ftp>`, malformed `get`
arguments, and unknown commands return a clear 5xx-style failure and do not
alter device storage.

A valid `get` checks the configured source name, then records the expected file
and byte size under the requested device storage only after simulated transfer
completion. Failure toggles can produce login, download, timeout, storage, and
size-mismatch errors for deterministic tests.

## MCP Guidance

Server instructions and tool descriptions explicitly map user intent:

- "transfer/send/upload a package or file to a device" uses
  `file_transfer_list` followed by `file_transfer_start`;
- "replace a package" or "upgrade a device" uses `package_upgrade_start`;
- generic `terminal_interact` is reserved for interactive workflows without a
  dedicated high-level tool;
- agents must not manually log in to FTP/SFTP when managed transfer applies.

The descriptions state that transfer credentials are resolved by Device TUI
and must not be requested from the user or guessed by the agent.

## Testing

### File Catalog

- Lists deterministic relative metadata.
- Does not expose credentials or the local root.
- Rejects traversal and omits escaping symlinks.
- Handles missing roots, subdirectories, limits, and unreadable entries.

### Managed Operation

- Transfers to an AI-selected device path.
- Refuses an existing destination by default.
- Allows an existing destination only with `overwrite=true`.
- Starts the local service when stopped.
- Uses the selected FTP or SFTP configuration.
- Cancels on user input and explicit cancellation.
- Rejects a changed source file.
- Fails on insufficient space, timeout, login failure, command failure, and
  byte-size mismatch.
- Releases the session lease on every terminal state.
- Preserves idempotency behavior.

### Simulator

- Requires exact configured credentials.
- Rejects `bin`, `put`, `q`, and device commands at the FTP prompt.
- Does not create a file after any rejected command.
- Creates the correct file and size only after valid `get`.
- Completes a locally orchestrated login when the input timeout is 200 ms.

### Integration

- Exercise the real `DeviceDesktopApp`, loopback App Control server, client,
  and MCP facade.
- List a temporary shared file, start transfer, query completion, and verify
  the simulated device directory.
- Read terminal output and confirm neither username nor password is present.
- Confirm the operation performs no startup-image command and no reboot.
- Run focused tests, the complete pytest suite, syntax compilation, and a live
  smoke transfer after restarting the current App.

## Acceptance Criteria

- An agent can transfer a shared file with two semantic MCP calls: list and
  start, plus status reads for an asynchronous operation.
- No FTP/SFTP credential or local absolute path is returned through App
  Control or MCP.
- No model-paced interaction is required after the transfer starts.
- A 200 ms simulated login-input deadline does not cause a valid managed
  transfer to fail.
- Invalid FTP sequences cannot produce a successful operation.
- Success requires exact device-side byte-size verification.
- The transfer-only workflow never changes startup software and never reboots.
