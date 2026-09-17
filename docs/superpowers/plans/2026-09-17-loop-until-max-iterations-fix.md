# Loop Until Maximum Iterations Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a `loop.until` node configured to stop at the maximum count execute its child action exactly `max_iterations` times.

**Architecture:** Keep the backend loop contract unchanged and correct the renderer's default persisted condition so its visible stop mode matches runtime behavior. Protect the contract with one execution-level Python test and one focused renderer component test.

**Tech Stack:** Vue 3, TypeScript, Python 3.10+, pytest

**Spec:** `docs/superpowers/specs/2026-09-17-loop-until-max-iterations-design.md`

## Global Constraints

- Python remains a headless backend with no PySide/PyQt dependency.
- Do not modify other `loop.until` stop modes.
- Preserve unrelated working-tree changes.

---

### Task 1: Lock the maximum-count runtime contract

**Files:**
- Modify: `tests/test_workflow_utility_nodes.py`

**Interfaces:**
- Consumes: `UntilActivityHandler.execute(invocation, context, report) -> ActivityResult`
- Produces: Regression coverage for a false condition and `max_iterations=20`.

- [ ] **Step 1: Write the failing execution test**

Add a child runner that appends each call to a list, then execute `UntilActivityHandler` with `condition: "False"`, `max_iterations: 20`, and `interval_seconds: 0`. Assert the call list has 20 entries, `result.outputs["iterations"] == 20`, and `result.outputs["matched"] is False`.

```python
def test_until_activity_runs_until_max_iterations_when_condition_is_false() -> None:
    calls: list[int] = []

    async def child_runner(action_id, inputs, context, report):
        calls.append(len(calls) + 1)
        return {"status": "succeeded", "output": str(len(calls))}

    invocation = ActivityInvocation(
        "loop.until",
        "inv-1",
        "run-1",
        inputs={
            "action_id": "device.command",
            "condition": "False",
            "max_iterations": 20,
            "interval_seconds": 0,
        },
    )
    context = ActivityContext(
        WorkflowRun("run-1", "wf", "1", "device-1"), invocation
    )

    result = asyncio.run(UntilActivityHandler(child_runner).execute(invocation, context, lambda _event: None))

    assert len(calls) == 20
    assert result.outputs["iterations"] == 20
    assert result.outputs["matched"] is False
```

- [ ] **Step 2: Run the execution test**

Run: `python -m pytest tests/test_workflow_utility_nodes.py::test_until_activity_runs_until_max_iterations_when_condition_is_false -q`
Expected: PASS, confirming the existing backend contract. This is a characterization test; the renderer regression in Task 2 supplies the RED phase for the bug.

- [ ] **Step 3: Commit the runtime regression test**

```powershell
git add -- tests/test_workflow_utility_nodes.py
git commit -m "Test loop until maximum iterations"
```

### Task 2: Align the renderer default with the visible stop mode

**Files:**
- Modify: `tests/test_workflow_studio_ui.py`
- Modify: `desktop/src/renderer/src/components/WorkflowLibrary.vue`

**Interfaces:**
- Consumes: `defaultConfig(actionId: string): Record<string, unknown>` and `loopUntilStopMode`.
- Produces: New `loop.until` nodes whose visible maximum-count mode persists `condition: "False"`.

- [ ] **Step 1: Write the failing renderer regression test**

Add a focused source contract test that identifies the `loop.until` default configuration and requires an always-false condition.

```python
def test_loop_until_default_maximum_mode_uses_false_condition() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    default_line = next(
        line for line in source.splitlines()
        if "if (actionId === 'loop.until') return" in line
    )

    assert "condition: \"False\"" in default_line
```

- [ ] **Step 2: Run the renderer regression test and verify RED**

Run: `python -m pytest tests/test_workflow_studio_ui.py::test_loop_until_default_maximum_mode_uses_false_condition -q`
Expected: FAIL because the current default line contains `condition: "True"`.

- [ ] **Step 3: Apply the minimal renderer fix**

Change only the `loop.until` default condition in `defaultConfig`:

```typescript
if (actionId === 'loop.until') return { action_id: 'device.command', action_inputs: { command: 'display version' }, condition: "False", max_iterations: 10, interval_seconds: 2 }
```

Keep the `loopUntilStopMode` setter's `max_iterations` branch writing `False`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_workflow_studio_ui.py::test_loop_until_default_maximum_mode_uses_false_condition tests/test_workflow_utility_nodes.py::test_until_activity_runs_until_max_iterations_when_condition_is_false -q`
Expected: 2 passed.

- [ ] **Step 5: Run relevant regression suites**

Run: `python -m pytest tests/test_workflow_studio_ui.py tests/test_workflow_utility_nodes.py tests/test_workflow_studio_validation.py -q`
Expected: all tests pass.

- [ ] **Step 6: Verify the desktop application**

Run: `cd desktop; npm run typecheck; npm run build`
Expected: both commands exit with code 0.

- [ ] **Step 7: Commit the minimal fix**

```powershell
git add -- tests/test_workflow_studio_ui.py desktop/src/renderer/src/components/WorkflowLibrary.vue
git commit -m "Fix loop until maximum iterations"
```
