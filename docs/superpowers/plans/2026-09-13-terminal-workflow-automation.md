# Terminal Workflow Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Turn Workflow Studio into a usable terminal automation editor that supports drag-and-drop graphs, output matching, branching, bounded loops, cancellation, and live execution state.

**Architecture:** Keep `WorkflowDefinition` as the persisted graph and the existing TaskService as the task boundary. Add a focused terminal workflow runtime that consumes `SessionHub` output events, then expose runtime state through the existing task API. The Vue Flow canvas becomes the editor surface; the renderer never owns device credentials or terminal execution.

**Tech Stack:** Python 3.10+, pytest, FastAPI, Vue 3, Vue Flow, TypeScript, existing Electron IPC and session hub.

**Spec:** `docs/superpowers/specs/2026-09-13-workflow-gap-completion-design.md` plus the approved terminal-automation design from this task.

## Global Constraints

- Keep credentials and privileged operations outside the renderer.
- Reuse `SessionHub.subscribe()` and the existing task lifecycle; do not add a second terminal transport.
- Terminal matching must support incremental chunks, bounded regex, timeout, disconnect, cancellation, and output redaction inherited from the session hub.
- Structured loops must have a maximum iteration count and must not permit unbounded graph cycles.
- Preserve existing workflow JSON and current uncommitted user changes.
- Use `apply_patch` for manual edits and pytest/typecheck/build for verification.

---

### Task 1: Terminal Match and Loop Runtime

**Files:**
- Create: `device_tui/application/workflow_runtime/events.py`
- Create: `device_tui/application/workflow_runtime/matcher.py`
- Create: `device_tui/application/workflow_runtime/runner.py`
- Create: `device_tui/application/workflow_runtime/__init__.py`
- Test: `tests/test_terminal_workflow_runtime.py`

**Interfaces:**
- `TerminalMatchSpec(mode: str, pattern: str, case_sensitive: bool = False)` describes `contains`, `regex`, and `exit_code` matching.
- `TerminalMatcher.feed(text: str) -> bool` consumes chunks and preserves a bounded buffer.
- `TerminalWorkflowRunner.wait_for_output(session_hub, session_id, spec, timeout_seconds, cancel_event) -> MatchResult` consumes `TerminalEvent` values from `SessionHub.subscribe()` and always unsubscribes.
- `run_until(check, max_iterations, interval_seconds, cancel_event) -> LoopResult` provides bounded loop semantics independent of terminal transport.

- [ ] Write failing tests for split chunks, regex matching, timeout, disconnect, cancellation, and loop exhaustion.
- [ ] Run `pytest tests/test_terminal_workflow_runtime.py -q` and confirm the failures are caused by missing runtime symbols.
- [ ] Implement the matcher with a maximum 64 KiB rolling buffer and deterministic result/error codes.
- [ ] Implement subscription cleanup in `finally`, ignore replay before the wait cursor, and treat `terminal.status` values `disconnected`, `failed`, and `closed` as disconnect results.
- [ ] Implement bounded loop execution and cancellation propagation.
- [ ] Run the focused runtime tests and the existing session hub tests.

### Task 2: Workflow Node Contracts and Compiler

**Files:**
- Modify: `device_tui/application/workflow_studio/models.py`
- Modify: `device_tui/application/workflow_studio/catalog.py`
- Modify: `device_tui/application/workflow_studio/validation.py`
- Modify: `device_tui/interfaces/desktop_api/routers/workflow_definitions.py`
- Test: `tests/test_workflow_studio_validation.py`
- Test: `tests/test_workflow_studio_api.py`

**Interfaces:**
- Add catalog entries `terminal.wait` and `loop.until` with explicit input/output schemas and output ports `matched`, `timeout`, `disconnected`, `error`, `done`, and `exhausted`.
- `terminal.wait` config accepts `match_mode`, `pattern`, `case_sensitive`, `scope`, and `timeout_seconds`.
- `loop.until` config accepts `condition`, `max_iterations`, `interval_seconds`, and `on_exhausted`.

- [ ] Add failing validation tests for missing patterns, invalid modes, zero/negative limits, malformed conditional edges, and forbidden unbounded cycles.
- [ ] Run the focused validation/API tests and confirm expected failures.
- [ ] Implement catalog and validation rules using the existing action catalog.
- [ ] Compile the new nodes into explicit runtime actions while preserving existing action mappings and retry policies.
- [ ] Add API serialization for port metadata and include terminal runtime configuration in dry-run previews.
- [ ] Run all workflow studio tests.

### Task 3: Runtime Integration With Sessions and Tasks

**Files:**
- Modify: `device_tui/application/composition/workflows.py`
- Modify: `device_tui/application/tasking/task_service.py`
- Modify: `device_tui/interfaces/desktop_api/session_hub.py`
- Modify: `device_tui/interfaces/desktop_api/routers/workflow_definitions.py`
- Test: `tests/test_terminal_workflow_integration.py`

**Interfaces:**
- Add a backend-owned `WorkflowExecutionRegistry` keyed by task id, with `start`, `cancel`, `snapshot`, and `events` methods.
- Runtime events use `{task_id, node_id, state, attempt, iteration, message, output, timestamp}` and never include credentials.
- `POST /workflow-definitions/{workflow_id}/run` starts the registry execution when a terminal wait/loop node exists and returns the task id plus initial execution state.
- `POST /tasks/{task_id}/cancel` cancels the registry execution and the underlying task.

- [ ] Add failing integration tests with a fake session hub for match success, timeout branch, loop exhaustion, and cancellation cleanup.
- [ ] Run the integration test file to confirm missing registry behavior.
- [ ] Implement dependency-injected runtime wiring using the existing composition object.
- [ ] Ensure all background tasks are retained, cancelled, and awaited during shutdown.
- [ ] Publish runtime events through the existing task/event channel without changing terminal secrets handling.
- [ ] Run focused task, session, and workflow API tests.

### Task 4: Drag-and-Drop Studio Experience

**Files:**
- Modify: `desktop/src/renderer/src/components/WorkflowLibrary.vue`
- Modify: `desktop/src/renderer/src/components/WorkflowCanvas.vue`
- Modify: `desktop/src/renderer/src/components/WorkflowNode.vue`
- Create: `desktop/src/renderer/src/components/WorkflowNodePalette.vue`
- Create: `desktop/src/renderer/src/components/WorkflowPropertiesPanel.vue`
- Create: `desktop/src/renderer/src/utils/workflowGraph.ts`
- Test: `tests/test_workflow_studio_ui.py`

**Interfaces:**
- Dragging a catalog item emits `nodeAdd(actionId, canvasPosition)` and creates a node with stable id and default config.
- Handles are named `next`, `matched`, `timeout`, `disconnected`, `error`, `body`, `done`, and `exhausted` as applicable.
- Graph updates preserve all edge source/target/source_handle fields.
- Property panel edits are emitted as immutable workflow updates and displays node-specific fields for terminal wait and loop until.

- [ ] Add source-level UI tests for drag payload, multi-port handles, terminal configuration fields, loop limits, and edge preservation.
- [ ] Run the UI tests to confirm missing palette/property behavior.
- [ ] Implement the palette and drag/drop using existing Vue Flow APIs and the backend catalog.
- [ ] Replace generic single top/bottom handles with named source handles for branch nodes.
- [ ] Add live node state rendering for waiting, running, matched, timeout, disconnected, failed, and cancelled.
- [ ] Run UI tests and `cd desktop; npm run typecheck`.

### Task 5: Verification and Review

**Files:**
- No new production files.

- [ ] Run `python -m compileall -q device_tui`.
- [ ] Run `python -m pytest`.
- [ ] Run `cd desktop; npm run typecheck`.
- [ ] Run `cd desktop; npm run build`.
- [ ] Review the diff for unrelated changes, accidental credential exposure, and unbounded execution paths.
