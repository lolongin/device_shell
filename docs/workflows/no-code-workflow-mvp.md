# No-Code Workflow MVP

The MVP keeps three boundaries separate:

- `device_tui.application.workflow_studio` owns workflow drafts, published snapshots, ActionSpec metadata, and validation.
- `SQLiteWorkflowDefinitionStore` persists drafts and immutable versions. A Task records the published workflow id and version it used.
- `device_tui.interfaces.desktop_api.routers.workflow_definitions` is the transport adapter. The renderer only receives JSON definitions and catalog-compatible validation results.

To add an Action, register an `ActionSpec` in `build_action_catalog()` with its stable id, input/output schema, risk, and executor id. Add the corresponding provider to the workflow composition registry and add the id to the compiler allow-list only when it has a concrete executor. The Studio displays the schema without importing a device transport. The execution compiler is the only layer that maps that id to a Task/Framework executor.

Published versions are snapshots. Saving a draft never changes an existing version, and publishing increments the integer version. A version marked as referenced by a Task cannot be deleted.

The run adapter supports device information, commands, connections, file transfers, reboot, waiting, confirmation, and result saving through the existing Task/Framework boundaries. Additional action ids should be added to the explicit compiler allow-list together with an executor-backed test.

## Lifecycle

1. The Studio creates or edits a draft through `/api/v1/workflow-definitions`.
2. `validate` checks required business fields, references, graph reachability, branch rules, retry/repeat limits, and parallel safety.
3. `publish` creates an immutable integer version. Existing tasks continue to reference the version they were created from.
4. `run` compiles the selected published version into a `TaskPlan` for each target device. The renderer never calls SSH, Telnet, transfer, or device executors directly.
5. The Task view projects execution into business states, supports decisions, retry, resume, and CSV report export.

## Parallel groups

Assign the same `parallel_group` value to steps that can run together. The compiler rejects unknown dependencies and keeps dependent steps out of the same batch. At runtime the group is persisted as a batch, child ids are written as soon as they are created, and failures cancel unfinished siblings before the parent task is marked failed.
