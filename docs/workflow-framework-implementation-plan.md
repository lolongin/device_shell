# Workflow Framework Implementation Plan

## 1. Objective

The backend should provide one reusable execution framework for local device
operations, package building, package replacement, and test scripts. A user
facing `Task` may compose multiple reusable `Workflow` instances. A workflow
is made of side-effecting `Activity` invocations and should not depend on a
vendor, UI, or transport implementation.

The current `WorkflowRuntime` is the target workflow executor. The legacy
`WorkflowEngine` and `TaskManager` remain compatibility surfaces until all
built-in tasks have migrated.

### Current implementation status (2026-08-29)

- Activity contracts, lifecycle events, structured results, and the local
  `ActivityExecutor` are implemented.
- `script.run` and `artifact.build` are registered as process-backed Activities;
  when an artifact path is supplied, `artifact.build` verifies that the output
  exists and is non-empty before succeeding.
- `file.transfer` has a `TerminalTransferAdapter` over the existing
  `DeviceControlService`/`ManagedTransferService`; it converts durable
  `OperationView` revisions into monitor observations and preserves
  `interrupted`/timeout as `unknown`.
- Huawei package upgrade's local transfer state now invokes the generic
  `file.transfer` Activity. The plugin supplies source/destination paths,
  protocol interaction profile, and a probe-backed `skip_if_present` flag;
  generic transfer events replace the old Huawei-specific watchdog events.
- `device.reboot`, `device.wait_online`, `device.verify_version`,
  `device.verify_artifact`,
  `device.storage.cleanup`, `device.storage.sync`,
  `device.startup.configure`, and `device.startup.rollback` have generic
  Activity IDs and definitions. The artifact/storage/startup Activities
  currently use a migration
  adapter whose Huawei command generation and read-back verification remain in
  the vendor bridge; the runtime owns their lifecycle and recovery semantics.
- The desktop composition root exposes the Activity executor and a
  `TaskOrchestrator`; `TaskService` is wired to that orchestrator for generic
  plan start/execute calls while retaining its lifecycle facade over the
  compatibility manager. Huawei package workflows retain the compatibility
  device bridge only as the implementation adapter for vendor-specific
  storage/startup behavior.
- `TaskRunStore` and `SQLiteTaskRunStore` now persist Task composition state
  (`node_runs`, outputs, status, errors, and execution context); production
  desktop composition wires this store to the existing SQLite database.
- The default Workflow registry now exposes one-step reusable providers for
  `script.run`, `artifact.build`, `file.transfer`, `device.reboot`,
  `device.wait_online`, `device.verify_version`, `device.verify_artifact`,
  `device.storage.cleanup`,
  `device.storage.sync`, `device.startup.configure`, and
  `device.startup.rollback`. A migration dispatcher
  routes marked Activity-backed steps to the new executor while legacy Huawei
  actions continue to use the compatibility bridge.
- Task orchestration preserves child `waiting_decision`, recovery, cancelled,
  failed, and unknown states when a TaskRun is resumed, and rejects execution
  against a different plan id.
- Huawei package upgrade now routes `reboot`, `wait_online`, and final startup
  version verification through the generic Activity IDs. The compatibility
  bridge still publishes the legacy semantic events consumed by existing
  state transitions.
- `LeaseResourceCoordinator` now provides one resource contract for Task and
  Workflow execution. Device leases are backed by the existing
  `DeviceLeaseService`; same-owner acquisition is reference-counted so a child
  Workflow cannot release its parent Task's device lease. The contract also
  covers future session, process, and transfer-operation resources.
- The desktop composition root injects the same coordinator into
  `TaskOrchestrator` and `WorkflowRuntime`; a resumed Task reacquires its lease
  before creating a child Workflow.
- The compatibility `TaskManager` also uses the coordinator for legacy task
  leases when it is available; direct `DeviceLeaseService` calls remain only as
  a fallback for external callers during migration.
- `DeviceVendorAdapter` and `DeviceVendorActivityHandler` now form the vendor
  port for generic device Activities. The Huawei implementation maps stable
  Activity ids to the existing bridge internally, so generic handlers no longer
  depend on `DeviceExecutionActionHandler`; the bridge can be replaced behind
  the adapter without changing Workflow definitions.
- `WorkflowRuntime.recover_inflight()` scans stores that expose `list()` during
  composition startup and fences persisted `running/recovering` runs as
  `paused`. Resume then reacquires resources and enters the existing reconcile
  path before any Activity retry.
- `ActivityProbe` is now an optional read-only probe port. When registered, the
  `ActivityExecutor` evaluates `GuardSpec`, invokes a declared preparation
  Activity when needed, and rechecks the guard before dispatch. Missing probes
  remain compatible with legacy adapters, which may perform the check inside
  their transport implementation.
- `TaskRunProjector` now provides a read-only `TaskRun` -> `TaskRecord`
  projection for legacy desktop/MCP DTOs. The projection does not participate
  in scheduling or recovery.
- `TaskOrchestrator` now owns TaskRun-level pause/resume/cancel coordination and
  delegates control to the active child `WorkflowRun`; `TaskService` exposes
  these operations through explicit `*_plan` methods.
- Framework-backed `TaskManager` lifecycle calls now delegate to the same
  `TaskOrchestrator` instance. Resume drives an existing `running/recovering`
  child through `WorkflowRuntime.run_until_blocked`, and TaskRecord projection
  remains consistent even when pause/cancel occurs before child creation.
- `TaskPlanLifecycle` is an explicit port between `TaskService` and framework
  orchestration. It is intentionally separate from the legacy `TaskLifecycle`
  protocol; process-backed `script.run` and `artifact.build` have no legacy
  `TaskManager` entry point to migrate or keep in sync.
- The current verification baseline is the full Python suite (`626 passed`).

## 2. Target Ownership

```text
TaskService
  -> TaskOrchestrator
      -> WorkflowExecutor / WorkflowRuntime
          -> ActivityExecutor
              -> ActivityHandler
                  -> Infrastructure Adapter
```

`WorkflowRun` is the source of truth for a workflow execution. `TaskRun` owns
composition, dependencies, and aggregate status. `TaskRecord` is an API/UI
projection and must not be used as a second scheduler state.

Resource ownership follows the same boundary:

```text
TaskRun (owner lease)
  -> WorkflowRun (re-entrant reference)
      -> Activity (short-lived session/process/transfer claims)
```

Only `ResourceCoordinator` acquires, renews, and releases claims. Runtime
handlers receive a fencing token through execution context but never persist
the token in `TaskRun` or `WorkflowRun` state.

## 3. Activity Contract

Every Activity declares:

- input and output schemas;
- read-only preconditions (`GuardSpec`);
- protocol exchanges and acknowledgement signals (`ExchangeSpec`);
- long-running observation (`MonitorSpec`);
- business postconditions (`VerificationSpec`);
- retry, timeout, cancellation, idempotency, and reconcile policies.

The lifecycle is:

```text
planned -> precondition_checking -> preparing -> dispatching
  -> waiting_ack -> monitoring -> verifying -> succeeded
```

An uncertain side effect is represented as `unknown` and is reconciled before
retrying. `unknown` must never be collapsed into `failed`.

## 4. Delivery Phases

### Phase 0: Baseline and boundaries

Keep the current behavior and tests as the migration baseline. Inventory every
entry point that creates a `Task`, every path that invokes `WorkflowEngine`,
and every framework action registered in `ActionRegistry`.

Exit criteria:

- current full test suite is green;
- each task type has documented inputs, outputs, events, and recovery behavior;
- no new feature is added to the legacy scheduler path.

### Phase 1: Framework contracts

Use `device_tui.application.workflows.activity` for the versioned Activity
contracts and `ActivityRegistry` for definitions and handlers. Keep
`ActionSpec`/`ActionRegistry` as a compatibility layer only.

Exit criteria:

- FTP can express view checks, login acknowledgements, transfer monitoring,
  and target-file verification;
- reboot can express an uncertain outcome and a reconcile policy;
- script execution can express process completion and output verification.

### Phase 2: Activity execution boundary

Introduce an `ActivityExecutor` that owns Activity-level supervision and emits
phase events. It must not parse vendor output. Protocol adapters emit semantic
events; verifiers inspect structured facts; reconcilers handle only uncertain
outcomes.

Migration order:

1. `script.run` using a subprocess adapter;
2. `artifact.build` using the same process adapter;
3. `file.transfer` using an FTP/SFTP adapter;
4. `device.wait_online` and `device.verify_version`;
5. `device.reboot` with mandatory reconcile.

Exit criteria:

- each Activity has a structured `ActivityResult`;
- timeout and cancellation preserve an `unknown` result when completion cannot
  be proven;
- progress and evidence are append-only events.

### Phase 3: Task orchestration

Split `TaskManager` into the following application services:

- `TaskService`: public lifecycle API;
- `TaskOrchestrator`: child Workflow creation, dependency ordering, and data
  mapping;
- `WorkflowExecutor`: drives one WorkflowRun;
- `TaskProjection`: derives `TaskRecord` for current API/UI clients;
- `ResourceCoordinator`: leases, subprocesses, transfer registrations, and
  cleanup.

The coordinator is injected into both the Task and Workflow layers. Device
claims are re-entrant by owner and released only after the last reference is
closed. A conflict is reported before a child Workflow is started; terminal
Task states release the owner claim, while waiting/recovery states retain it.

The orchestrator passes outputs explicitly, for example:

```text
${artifact.build.outputs.package_path}
${file.transfer.outputs.operation_id}
${device.verify_version.outputs.version}
```

Do not encode child workflow calls in `metadata.canonical_workflow_id` or
`metadata.framework_inputs` after the migration of the corresponding task.

### Phase 4: Workflow migration

Create reusable workflows for:

```text
artifact.build
script.run
file.transfer
device.configure_startup
device.reboot
device.wait_online
device.verify_version
```

Compose the package operation as:

```text
upgrade_and_validate
  -> artifact.build
  -> file.transfer
  -> device.configure_startup
  -> device.reboot
  -> device.wait_online
  -> device.verify_version
  -> script.run
```

The Huawei package workflow becomes a plugin that selects vendor commands and
parsers; it does not own generic scheduling or transfer supervision.

### Phase 5: Adapter separation

Move concrete behavior behind infrastructure contracts:

- `SessionAdapter`: SSH, Telnet, and serial sessions;
- `TransferAdapter`: FTP and SFTP protocol handling;
- `ProcessAdapter`: package builders and test scripts;
- `DeviceVendorAdapter`: Huawei VRP command generation and output parsing.

`DeviceExecutionActionHandler` is temporary migration code. New Activity
handlers must not import `TaskManager`, FastAPI, Electron, or another
Workflow's implementation.

### Phase 6: Persistence and recovery

Persist WorkflowRun, ActivityAttempt, events, operation IDs, and evidence. On
restart, mark in-flight side effects as recoverable/unknown and run reconcile
before allowing retry. Persist enough data to resume without re-sending an
unsafe command.

The local startup hook is `WorkflowRuntime.recover_inflight()`. It only fences
records; it does not guess an outcome or issue a new command. A store without a
`list()` capability remains compatible but must be reconciled by its owning
application service before exposing resume controls.

Exit criteria:

- process restart resumes from a durable WorkflowRun;
- transfer and reboot recovery never blindly repeats an unsafe operation;
- all UI state is a projection of persisted execution state.

### Phase 7: Remove the legacy path

After all Task sources, including Agent/MCP requests, use the new orchestrator:

1. stop creating `WorkflowEngine` instances;
2. remove the old `_run` and `_run_stateful` branches;
3. retain read/API compatibility conversions;
4. remove duplicated state fields only after projection consumers migrate;
5. delete `WorkflowEngine` and compatibility imports in a separate release.

## 5. Acceptance Matrix

The migration is complete only when these scenarios pass end to end:

- FTP starts from a non-user view, enters the required view, and confirms it;
- username, password, and FTP prompt are acknowledged separately;
- transfer reports started, progress, and completed;
- transfer timeout becomes `unknown` and reconciles before retry;
- completed transfer verifies file existence and size/checksum;
- reboot confirms disconnect, online recovery, and expected version;
- package build validates process exit code and output artifact;
- test script captures output, exit code, timeout, cancellation, and evidence;
- application restart resumes the correct WorkflowRun;
- manual retry, skip, reconnect, and cancel decisions are audited.

## 6. Rules During Migration

- Do not add vendor-specific branches to `workflow_core`.
- Do not make a single Activity such as `upgrade_everything`.
- Do not treat a protocol acknowledgement as business success.
- Do not retry an unsafe Activity without reconcile or explicit human approval.
- Do not introduce Temporal until the local executor is no longer sufficient for
  the required scale and worker topology.
