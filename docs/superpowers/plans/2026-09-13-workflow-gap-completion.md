# Workflow Gap Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Complete the requested Workflow Studio capabilities while preserving the existing TaskPlan/WorkflowRuntime execution boundary.

**Architecture:** Add bounded utility Activity handlers and compile them through the existing allow-list. Strengthen the workflow API/compiler contract for inputs and immutable versions. Update the Vue Studio to consume the server catalog and expose utility-node configuration while preserving graph edge integrity.

**Tech Stack:** Python 3.10+, pytest, FastAPI, Vue 3, TypeScript, existing ActivityExecutor/TaskOrchestrator.

**Spec:** `docs/superpowers/specs/2026-09-13-workflow-gap-completion-design.md`

## Global Constraints

- Keep credentials and privileged operations outside the renderer.
- Use the existing TaskPlan/WorkflowRuntime boundary; do not add a second scheduler.
- Expressions must be evaluated through a restricted AST; never call `eval`.
- Preserve existing workflow JSON compatibility and current tests.

### Task 1: Utility Semantics

**Files:**
- Create: `device_tui/application/workflow_studio/expression.py`
- Modify: `device_tui/application/workflow_plugins/utility.py`
- Modify: `device_tui/application/workflow_plugins/generic.py`
- Modify: `device_tui/application/composition/workflows.py`
- Modify: `device_tui/application/workflow_studio/catalog.py`
- Test: `tests/test_workflow_utility_nodes.py`

Implement `evaluate_expression(expression: str, values: Mapping[str, Any]) -> Any` with a restricted AST and add `ExpressionActivityHandler`, `VariableSetActivityHandler`, and `ForEachActivityHandler`. `loop.for_each` must execute a configured allow-listed child action through a callback injected by composition, returning `count`, `items`, and per-item results. Register definitions and handlers and expose schemas in the Studio catalog.

- [ ] Write failing tests for safe comparisons, rejected calls, variable assignment, loop result shape, and loop failure index.
- [ ] Run `pytest tests/test_workflow_utility_nodes.py -q` and verify the new tests fail.
- [ ] Implement the restricted evaluator and handlers with deterministic errors.
- [ ] Run the focused test file and then `pytest tests/test_workflow_studio_api.py -q`.

### Task 2: Compiler and Validation Contract

**Files:**
- Modify: `device_tui/application/workflow_studio/validation.py`
- Modify: `device_tui/interfaces/desktop_api/routers/workflow_definitions.py`
- Modify: `device_tui/application/workflow_studio/models.py`
- Test: `tests/test_workflow_studio_validation.py`
- Test: `tests/test_workflow_studio_api.py`

Validate workflow inputs for required values/types, validate utility node configuration, compile expression conditions and utility actions, and use the loop child-action contract. Add consistent errors for unsupported expressions and malformed loops.

- [ ] Add failing validation/compiler tests.
- [ ] Run them to confirm expected failures.
- [ ] Implement validation and compiler mappings.
- [ ] Run all workflow studio tests.

### Task 3: Version and Reference Safety

**Files:**
- Modify: `device_tui/interfaces/desktop_api/routers/workflow_definitions.py`
- Modify: `device_tui/application/workflow_studio/store.py`
- Modify: `device_tui/infrastructure/persistence/sqlite_workflows.py`
- Test: `tests/test_workflow_studio_api.py`
- Test: `tests/test_workflow_definition_store.py`

Make published runs explicit and immutable, mark referenced versions when a published run is created, and retain draft execution only behind an explicit draft request. Keep compatibility with stores that do not implement reference marking.

- [ ] Add failing tests for published version selection and reference marking.
- [ ] Run tests to verify failure.
- [ ] Implement the API/store changes.
- [ ] Run API and persistence tests.

### Task 4: Studio Catalog and Graph Editing Fixes

**Files:**
- Modify: `desktop/src/renderer/src/components/WorkflowLibrary.vue`
- Modify: `desktop/src/renderer/src/transport/api.ts`
- Test: `tests/test_workflow_studio_ui.py`

Load the action catalog from the backend, render utility-node forms for variables, expressions, and loops, expose workflow inputs, make blank creation actually blank, and update edge source/target ids when a node is renamed. Pass a published version during run when selected.

- [ ] Add source-level UI assertions for catalog loading, blank creation, version passing, and edge rename handling.
- [ ] Run the UI test to confirm failure.
- [ ] Implement the renderer changes.
- [ ] Run UI tests and `cd desktop; npm run typecheck`.

### Task 5: Full Verification

**Files:**
- No new production files.

- [ ] Run `python -m compileall -q device_tui`.
- [ ] Run `python -m pytest`.
- [ ] Run `cd desktop; npm run typecheck`.
- [ ] Run `cd desktop; npm run build`.
- [ ] Review the final diff for unrelated changes or secret material.
