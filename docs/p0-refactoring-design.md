# P0 Refactoring Design

## Objective

Turn each P0 file into a composition root or compatibility facade. A new transfer
transport, terminal plan behavior, Electron IPC domain, application workspace
action, or workflow editor capability should have one primary module to change.
Existing IPC channel names, backend routes, persisted payloads, renderer DOM
contracts, and public Python imports remain stable.

## Boundaries

### Electron main process

`desktop/src/main/index.ts` owns process composition only: construct the backend,
window, credential lifecycle, terminal registry, and register domain IPC modules.
Each IPC module owns channel registration and cleanup for one capability. Security
validation and shell escaping are shared policy modules and cannot depend on a
window or Electron application lifecycle.
Current extracted modules include `backend-client.ts`, credential lifecycle and
IPC modules, file/log/local-terminal/runtime/transfer/window IPC modules, and
shared security helpers. The capture/parity smoke is isolated in
`ui-parity-smoke.ts`:
it is test infrastructure and must move as one tested scenario without changing
its `DEVICE_TUI_CAPTURE_*` environment contract.

### Renderer application shell

`desktop/src/renderer/src/App.vue` owns layout composition and binds template
events to focused composables. Device/profile formatting is pure code under
`app/`; DOM interaction and stateful application actions live under
`composables/`. Preferences and navigator sizing have dedicated composables,
and session grouping/actions live in `useSessionWorkspace` and
`useSessionMenuActions`. Resource navigation and the terminal session surface
are presentation modules (`ResourceNavigator.vue` and
`SessionWorkspaceShell.vue`) behind explicit context props. Composables and
presentation modules receive explicit refs and callbacks instead of importing
the workspace store, which keeps their dependencies testable and makes the
shell the only wiring point.

### Workflow editor

`WorkflowLibrary.vue` owns the editor layout and wires focused workflow modules.
Inputs, templates, persistence, execution, catalog data, canvas ordering, panel
resizing, and flow-test presentation have separate modules. Backend payload
construction belongs in pure helpers; asynchronous lifecycle coordination
belongs in composables. Child panels receive explicit props and callbacks and
do not import the workspace store.

### Transfers

`application/transfers.py` remains the public service facade. Models, network
configuration, port selection, service lifecycle, queueing, planning, execution
context, execution strategies, and common helpers are isolated modules.
Credentials stay in the execution context only for the lifetime required to
construct a command and are removed through the existing cleanup path.

### Terminal orchestration

`application/terminal/orchestration.py` remains a compatibility re-export.
Models, parsing, matching, one-plan execution, and multi-plan coordination are
separate modules. Dependencies point from coordinators toward runners and pure
models, never back through the facade.

## Current Status

- Electron main, transfer application, and terminal orchestration are now
  composition/facade roots. IPC domains, transfer strategies, and terminal
  planning/execution live in focused modules.
- App and WorkflowLibrary are composition shells with stateful behavior moved
  into `app/`, composables, and workflow panels. Their remaining large sections
  are layout templates and wiring, not duplicate domain implementations.
- The renderer seams are explicit: preferences, navigator sizing, session
  workspace, workflow inputs, node configuration, persistence, execution, panel
  layout, and flow-test display each have one owner.

## Completion Criteria

- P0 files contain composition, template, or compatibility exports rather than
  duplicate implementations. Python facades, Electron capture smoke, and
  renderer workflow/session behavior meet this criterion; the remaining Vue
  lines are declarative layout and event wiring.
- Adding one capability has one primary ownership module and does not require
  editing unrelated domains.
- Existing public imports, Electron IPC names, backend routes, persisted shapes,
  and renderer selectors remain compatible.
- Python compilation and focused pytest suites pass.
- Desktop typecheck and production build pass.
- `git diff --check` reports no whitespace errors.

## Migration Rules

1. Extract behavior without changing its public contract.
2. Keep a thin proxy only when templates or source-contract tests require the old
   symbol name.
3. Delete migrated duplicate implementations after tests confirm the new owner.
4. Prefer explicit dependency injection at UI and process composition roots.
5. Add focused unit tests for pure modules; use existing integration/source tests
   to protect IPC and DOM compatibility.
