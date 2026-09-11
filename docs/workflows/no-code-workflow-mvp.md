# No-Code Workflow MVP

The MVP keeps three boundaries separate:

- `device_tui.application.workflow_studio` owns workflow drafts, published snapshots, ActionSpec metadata, and validation.
- `SQLiteWorkflowDefinitionStore` persists drafts and immutable versions. A Task records the published workflow id and version it used.
- `device_tui.interfaces.desktop_api.routers.workflow_definitions` is the transport adapter. The renderer only receives JSON definitions and catalog-compatible validation results.

To add an Action, register an `ActionSpec` in `build_action_catalog()` with its stable id, input/output schema, risk, and executor id. The Studio can display the schema without importing a device transport. The execution compiler is the only layer that maps that id to a Task/Framework executor.

Published versions are snapshots. Saving a draft never changes an existing version, and publishing increments the integer version. A version marked as referenced by a Task cannot be deleted.

The current run adapter supports the first generic actions (`device.command`, `device.reboot`, and `utility.wait`) through the existing `TaskService`. Additional action ids should be added to that explicit allow-list together with an executor-backed test.
