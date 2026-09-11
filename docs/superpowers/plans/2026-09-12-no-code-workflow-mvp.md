# No-Code Workflow MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a P0 no-code Workflow lifecycle from library and visual editing through validation, publication, Task creation, and execution visibility.

**Architecture:** Add a framework-independent WorkflowDefinitionStore and ActionCatalog boundary, expose CRUD/validate/publish/run APIs, and compile immutable published versions into the existing TaskService boundary. Keep Vue Studio dependent on typed API contracts and catalog metadata; execution remains owned by the existing Task/Workflow engine.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, SQLite, pytest, Vue 3, TypeScript, lucide-vue-next.

**Spec:** `docs/superpowers/specs/2026-09-12-no-code-workflow-mvp-design.md`

## Global Constraints

- Python backend must not add PySide/PyQt dependencies.
- Workflow and Task versions are immutable after publication.
- Renderer must not receive credentials or privileged execution details.
- New Python code uses 4-space indentation, type hints, and snake_case.
- Validate with pytest, `python -m compileall -q device_tui`, `cd desktop && npm run typecheck`, and `cd desktop && npm run build`.

### Task 1: Define generic workflow domain contracts

**Files:**
- Create: `device_tui/application/workflow_studio/models.py`
- Create: `device_tui/application/workflow_studio/catalog.py`
- Create: `device_tui/application/workflow_studio/validation.py`
- Create: `device_tui/application/workflow_studio/__init__.py`
- Test: `tests/test_workflow_studio_models.py`
- Test: `tests/test_workflow_studio_validation.py`

**Interfaces:**
- `WorkflowDraft`, `WorkflowVersion`, `WorkflowNode`, `WorkflowEdge`, `WorkflowInput` dataclasses with `to_dict()`/`from_dict()`.
- `ActionSpec(id, name, category, input_schema, output_schema, risk, executor_id)` and `build_action_catalog()`.
- `validate_workflow(workflow: WorkflowDraft, catalog: ActionCatalog) -> ValidationResult` returning errors and warnings with node ids.

- [ ] Write tests for round-trip serialization, unknown actions, missing required config, disconnected nodes, invalid conditions, and high-risk warnings.
- [ ] Run `pytest tests/test_workflow_studio_models.py tests/test_workflow_studio_validation.py -v` and confirm failures.
- [ ] Implement immutable-friendly models and deterministic validation (including cycle detection and variable reference checks).
- [ ] Re-run the focused tests and confirm pass.
- [ ] Commit `feat: add generic workflow studio contracts`.

### Task 2: Add durable workflow definition store

**Files:**
- Create: `device_tui/application/workflow_studio/store.py`
- Modify: `device_tui/infrastructure/persistence/sqlite_workflows.py`
- Modify: `device_tui/application/desktop.py`
- Test: `tests/test_workflow_definition_store.py`

**Interfaces:**
- `WorkflowDefinitionStore.create/save/get/list/delete/publish` with published snapshot retention.
- `SQLiteWorkflowDefinitionStore(path: Path)` using a dedicated `workflow_definitions` table and JSON payloads.
- Desktop composition exposes `desktop.workflow_definitions`.

- [ ] Write tests covering draft CRUD, version increment, published snapshot immutability, and delete protection for referenced published versions.
- [ ] Run the focused test file and confirm failures.
- [ ] Implement store protocol and SQLite adapter without changing existing run/task tables.
- [ ] Wire the store into desktop composition and run focused tests.
- [ ] Commit `feat: persist workflow definitions and versions`.

### Task 3: Expose Workflow Studio APIs and Task compiler

**Files:**
- Modify: `device_tui/interfaces/desktop_api/models.py`
- Create: `device_tui/interfaces/desktop_api/routers/workflows.py`
- Modify: `device_tui/interfaces/desktop_api/app.py`
- Create: `device_tui/application/workflow_studio/compiler.py`
- Test: `tests/test_workflow_studio_api.py`
- Test: `tests/test_workflow_studio_compiler.py`

**Interfaces:**
- `GET /api/v1/workflow-definitions`
- `POST /api/v1/workflow-definitions`
- `GET /api/v1/workflow-definitions/{id}`
- `PUT /api/v1/workflow-definitions/{id}`
- `DELETE /api/v1/workflow-definitions/{id}`
- `POST /api/v1/workflow-definitions/{id}/validate`
- `POST /api/v1/workflow-definitions/{id}/publish`
- `POST /api/v1/workflow-definitions/{id}/run`
- `compile_published_workflow(version, target, inputs) -> TaskCreate`

- [ ] Write API tests for CRUD, validation errors, publish rejection, and run response containing `workflow_id` and `workflow_version`.
- [ ] Write compiler tests proving action ids map only through catalog executors and preserve node ids in metadata.
- [ ] Run focused tests and confirm failures.
- [ ] Implement request/response models, router authorization, compiler adapter, and app registration.
- [ ] Run focused tests plus existing task API tests.
- [ ] Commit `feat: expose workflow studio APIs and task compilation`.

### Task 4: Implement typed renderer API and Workflow Library

**Files:**
- Modify: `desktop/src/renderer/src/types.ts`
- Modify: `desktop/src/renderer/src/transport/api.ts`
- Modify: `desktop/src/renderer/src/stores/workspace.ts`
- Create: `desktop/src/renderer/src/components/WorkflowLibrary.vue`
- Modify: `desktop/src/renderer/src/App.vue`
- Modify: `desktop/src/renderer/src/styles.css`

**Interfaces:**
- `WorkflowDefinition`, `WorkflowSummary`, `ActionSpec`, `ValidationResult` TypeScript types.
- `desktopApi.workflowDefinitions()`, `createWorkflowDefinition()`, `saveWorkflowDefinition()`, `validateWorkflowDefinition()`, `publishWorkflowDefinition()`, `runWorkflowDefinition()`.
- Store actions `refreshWorkflowDefinitions`, `createWorkflowDraft`, `publishWorkflow`, `runWorkflow`.

- [ ] Add typed API methods and store state without breaking current workflow catalog/task state.
- [ ] Add Library view with search, status filter, new/duplicate/delete, and version/status display.
- [ ] Add navigation entry and styles matching existing desktop visual language.
- [ ] Run `cd desktop && npm run typecheck` and fix all type errors.
- [ ] Commit `feat: add workflow library UI`.

### Task 5: Implement Workflow Studio editor and validation UX

**Files:**
- Create: `desktop/src/renderer/src/components/WorkflowStudio.vue`
- Create: `desktop/src/renderer/src/components/WorkflowCanvas.vue`
- Create: `desktop/src/renderer/src/components/WorkflowProperties.vue`
- Modify: `desktop/src/renderer/src/components/WorkflowLibrary.vue`
- Modify: `desktop/src/renderer/src/styles.css`

**Interfaces:**
- Studio emits `save`, `validate`, `publish`, `run`, and `close` events with `WorkflowDefinition` payloads.
- Canvas edits `nodes` and `edges` through stable node ids; Properties edits selected node config and input mappings using `ActionSpec` schemas.

- [ ] Implement failing behavior checks for adding an action, connecting sequential nodes, editing config, and rendering validation errors/warnings.
- [ ] Implement three-column Studio with keyboard-accessible controls, explicit start/end nodes, and condition branch handles.
- [ ] Add client-side draft normalization only; server validation remains authoritative.
- [ ] Run typecheck and build, then manually exercise create/edit/save/validate/publish flows.
- [ ] Commit `feat: add workflow studio editor`.

### Task 6: Integrate execution monitoring and regression validation

**Files:**
- Modify: `desktop/src/renderer/src/components/TaskWorkspace.vue`
- Modify: `desktop/src/renderer/src/stores/workspace.ts`
- Test: `tests/test_workflow_studio_regression.py`

- [ ] Add regression tests proving a published workflow creates a Task that uses the exact published version and that execution failures retain node ids.
- [ ] Display Workflow name/version in TaskWorkspace and link to current step when present.
- [ ] Ensure cancel/retry use existing TaskService endpoints and do not bypass the compiler.
- [ ] Run `python -m pytest tests/test_workflow_studio_regression.py tests/test_task_service.py tests/test_task_projection.py -v`.
- [ ] Run `python -m compileall -q device_tui`.
- [ ] Run `cd desktop && npm run typecheck` and `npm run build`.
- [ ] Commit `feat: connect published workflows to execution monitoring`.

### Task 7: Final architecture review and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-09-12-no-code-workflow-mvp-design.md` if implementation decisions materially changed.
- Create: `docs/workflows/no-code-workflow-mvp.md`

- [ ] Document extension points for adding an ActionSpec/executor without changing Studio core.
- [ ] Document API lifecycle and version guarantees.
- [ ] Run the complete Python test suite and desktop checks.
- [ ] Inspect git diff for credential leakage, renderer privilege expansion, and accidental changes to existing automation rules.
- [ ] Commit `docs: document workflow studio architecture`.
