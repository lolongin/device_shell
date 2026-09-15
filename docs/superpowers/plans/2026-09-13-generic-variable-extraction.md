# Generic Workflow Variable Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing `variable.set` workflow node so it can save a resolved value directly or extract the first regex match from that value without adding device-specific actions.

**Architecture:** Keep reference resolution in the existing task orchestrator. Add a small pure extraction helper in the workflow utility layer, then let `VariableSetActivityHandler` apply optional extraction to the already-resolved `value` and return `matched` metadata. Extend the existing catalog, validation, compiler pass-through, and Vue editor only as needed to describe and configure the optional `extract` object.

**Tech Stack:** Python 3.10+, pytest, FastAPI workflow compiler, Vue 3 + TypeScript, existing Activity framework.

**Spec:** `docs/superpowers/specs/2026-09-13-generic-variable-extraction-design.md`

## Global Constraints

- Reuse `variable.set`; do not add vendor-, file-, or command-specific actions.
- Preserve existing `${node.field}` full-value references and variable propagation.
- Use Python standard-library regular expressions only; do not execute user scripts.
- An invalid regex fails the node; no match succeeds with `matched=false` and an empty value.
- Keep the default editor path as simple as name plus value; extraction is optional.
- Do not modify device command execution, terminal paging, or vendor adapters.
- Preserve unrelated user changes in the dirty worktree.

### Task 1: Add the pure extraction contract

**Files:**
- Create: `device_tui/application/workflow_runtime/value_extraction.py`
- Test: `tests/test_workflow_value_extraction.py`

**Interfaces:**
- Produces `extract_value(source: Any, extract: Mapping[str, Any]) -> tuple[Any, bool]` for the Activity handler.
- `mode="match"` returns the selected capture group from the first `re.search` match.
- `mode="line"` returns the complete source line containing the first match.
- An empty or non-string source is converted to text only when extraction is requested; without extraction values remain unchanged.
- Invalid regex raises `ValueError` with a stable, user-readable message.
- A missing match returns `("", False)` rather than raising.

- [ ] **Step 1: Write failing tests**

Add tests covering:

```python
def test_extracts_first_full_match():
    assert extract_value("flash:/cc\nflash:/other", {"pattern": r"flash:/\S+"}) == ("flash:/cc", True)

def test_extracts_capture_group():
    assert extract_value("Version: 8.220", {"pattern": r"Version:\s*([0-9.]+)", "group": 1}) == ("8.220", True)

def test_can_save_the_matching_line():
    assert extract_value("ok\nfound flash:/cc\nend", {"pattern": r"flash:/\S+", "mode": "line"}) == ("found flash:/cc", True)

def test_no_match_returns_empty_value():
    assert extract_value("nothing", {"pattern": "cc"}) == ("", False)

def test_invalid_pattern_is_rejected():
    with pytest.raises(ValueError, match="invalid extraction pattern"):
        extract_value("text", {"pattern": "["})
```

- [ ] **Step 2: Run the focused test file and verify failure**

Run: `python -m pytest tests/test_workflow_value_extraction.py -q`

Expected: FAIL because the helper module and function do not exist.

- [ ] **Step 3: Implement the minimal pure helper**

Use `re.compile` and `search`, default `group` to `0`, accept only `match` and `line`, and raise `ValueError` for invalid mode, invalid group, missing pattern, or invalid regex. Keep the function independent of Activity or device classes.

- [ ] **Step 4: Run the focused test file**

Run: `python -m pytest tests/test_workflow_value_extraction.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the isolated runtime helper**

```bash
git add device_tui/application/workflow_runtime/value_extraction.py tests/test_workflow_value_extraction.py
git commit -m "Add generic workflow value extraction"
```

### Task 2: Apply extraction in `variable.set`

**Files:**
- Modify: `device_tui/application/workflow_plugins/utility.py:15-27`
- Test: `tests/test_workflow_utility_nodes.py`

**Interfaces:**
- Consumes the `extract` mapping passed through `invocation.inputs`.
- Produces the existing `name` and `value` outputs plus `matched` and `source` only when extraction is configured.
- Keeps direct assignments type-preserving and keeps existing invalid-name behavior.

- [ ] **Step 1: Add failing Activity tests**

Add async tests that invoke `VariableSetActivityHandler` directly:

```python
async def test_variable_set_can_extract_a_capture_group():
    result = await handler.execute(invocation({
        "name": "cc_path",
        "value": "found flash:/cc",
        "extract": {"pattern": r"flash:/\S+"},
    }), context, report)
    assert result.status is ActivityStatus.SUCCEEDED
    assert result.outputs == {
        "name": "cc_path",
        "value": "flash:/cc",
        "matched": True,
        "source": "found flash:/cc",
    }

async def test_variable_set_reports_no_match_without_failing():
    result = await handler.execute(invocation({
        "name": "cc_path", "value": "not found", "extract": {"pattern": "flash:/"}
    }), context, report)
    assert result.status is ActivityStatus.SUCCEEDED
    assert result.outputs["value"] == ""
    assert result.outputs["matched"] is False
```

Also test invalid regex returns `ActivityStatus.FAILED` with code `variable_extract_invalid`.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `python -m pytest tests/test_workflow_utility_nodes.py -q`

Expected: FAIL because `VariableSetActivityHandler` currently ignores `extract`.

- [ ] **Step 3: Implement the handler integration**

When `extract` is a non-empty mapping, preserve the original value as `source`, call `extract_value`, and return `matched`. Catch only `ValueError` from extraction and return a deterministic failed Activity result. When `extract` is absent, preserve the current output shape and do not coerce the value.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_workflow_utility_nodes.py tests/test_workflow_value_extraction.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the Activity behavior**

```bash
git add device_tui/application/workflow_plugins/utility.py tests/test_workflow_utility_nodes.py
git commit -m "Support extraction in workflow variable assignment"
```

### Task 3: Expose and validate the optional configuration

**Files:**
- Modify: `device_tui/application/workflow_studio/catalog.py:44`
- Modify: `device_tui/application/workflow_studio/validation.py:170-171`
- Modify: `device_tui/interfaces/desktop_api/routers/workflow_definitions.py:46`
- Test: `tests/test_workflow_studio_ui.py` or the existing workflow studio API test module that covers catalog validation and plan compilation.

**Interfaces:**
- `variable.set` catalog schema adds optional `extract` object while retaining required `name`.
- Validation accepts `extract` only as an object with a non-empty string `pattern`, `mode` in `{"match", "line"}`, and a non-negative integer `group`.
- The compiler passes `extract` unchanged in `WorkflowNode.input_mapping`; no new workflow ID or executor registration is needed.

- [ ] **Step 1: Add failing catalog and validation tests**

Verify the catalog exposes `extract`, valid extraction config has no errors, and invalid pattern/mode/group produce targeted validation issues. Add a compile assertion that a `variable.set` node retains its `extract` mapping.

- [ ] **Step 2: Run the focused workflow studio tests and verify failure**

Run: `python -m pytest tests/test_workflow_studio_ui.py -q`

Expected: FAIL for the new schema and validation assertions.

- [ ] **Step 3: Implement schema and validation**

Add `extract={"type": "object"}` to the action catalog. In `validate_workflow`, compile the configured pattern with `re.compile`, report `invalid_variable_extract_pattern`, check mode and group bounds, and leave absent extraction valid. Do not add a new action mapping because `variable.set` is already compiled and registered.

- [ ] **Step 4: Run the focused workflow studio tests**

Run: `python -m pytest tests/test_workflow_studio_ui.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the workflow contract**

```bash
git add device_tui/application/workflow_studio/catalog.py device_tui/application/workflow_studio/validation.py device_tui/interfaces/desktop_api/routers/workflow_definitions.py tests/test_workflow_studio_ui.py
git commit -m "Validate generic variable extraction configuration"
```

### Task 4: Add the compact Vue configuration

**Files:**
- Modify: `desktop/src/renderer/src/components/WorkflowLibrary.vue:303-315, 919-920`
- Modify: `desktop/src/renderer/src/styles.css` only if the existing field-hint/inline form styles cannot support the new compact controls.
- Test: `tests/test_workflow_studio_ui.py`

**Interfaces:**
- Default config for `variable.set` remains `{ name: '', value: '' }`.
- The editor provides a source selector populated from existing `resultSources`, writing a full reference such as `${command_1.output}` into `config.value`.
- A checkbox or toggle reveals extraction fields only when enabled: pattern, save mode, and capture group.
- Disabling extraction removes `config.extract`; direct value assignment remains unchanged.

- [ ] **Step 1: Add failing source/UI contract assertions**

Assert the component contains a variable source selector, extraction toggle, pattern field, `match`/`line` mode options, and capture-group input while retaining the existing variable name/value fields.

- [ ] **Step 2: Run the UI contract test and verify failure**

Run: `python -m pytest tests/test_workflow_studio_ui.py -q`

Expected: FAIL because the new controls are not present.

- [ ] **Step 3: Implement the smallest editor helpers and template**

Add helpers to read and write `config.extract` and to set a selected upstream field reference. Reuse `resultSources` and the existing `${node.field}` convention. Show concise Chinese labels such as “值来源”“提取匹配”“匹配规则”“保存整行”“捕获组”，and use an inline hint rather than a large explanatory panel.

- [ ] **Step 4: Run type checking**

Run: `cd desktop; npm run typecheck`

Expected: PASS with no TypeScript or Vue template errors.

- [ ] **Step 5: Run the UI contract test**

Run: `python -m pytest tests/test_workflow_studio_ui.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the editor change**

```bash
git add desktop/src/renderer/src/components/WorkflowLibrary.vue desktop/src/renderer/src/styles.css tests/test_workflow_studio_ui.py
git commit -m "Add compact variable extraction controls"
```

### Task 5: End-to-end regression verification

**Files:**
- Modify: none unless a test exposes an actual integration defect.
- Test: existing workflow tests plus `tests/test_workflow_value_extraction.py`, `tests/test_workflow_utility_nodes.py`, and `tests/test_workflow_studio_ui.py`.

- [ ] **Step 1: Run all focused Python tests**

Run: `python -m pytest tests/test_workflow_value_extraction.py tests/test_workflow_utility_nodes.py tests/test_workflow_studio_ui.py -q`

Expected: PASS.

- [ ] **Step 2: Run the full Python suite**

Run: `python -m pytest -q`

Expected: PASS, with no regressions in workflow execution or validation.

- [ ] **Step 3: Build the desktop bundle**

Run: `cd desktop; npm run build`

Expected: PASS and production renderer bundles are generated.

- [ ] **Step 4: Inspect the final diff**

Run: `git diff HEAD~4 --stat; git status --short`

Confirm only the feature commits contain the planned files and unrelated pre-existing worktree changes remain untouched.

- [ ] **Step 5: Commit any required test-only correction**

If the verification steps require a correction, add only the affected test or feature file and use:

```bash
git add <affected-files>
git commit -m "Fix variable extraction regression"
```
