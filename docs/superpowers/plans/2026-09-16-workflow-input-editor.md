# Workflow Input Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make manually created workflows expose the same editable workflow inputs and runtime parameter area as imported workflows.

**Architecture:** Keep `WorkflowInput` data in the existing `selected.inputs` array. Add small editor handlers in `WorkflowLibrary.vue`; reuse existing save, validation, runtime-input initialization, import, and export paths.

**Tech Stack:** Vue 3 `<script setup>`, TypeScript, existing Workflow Studio styles and API.

**Spec:** User-approved design in conversation: add, edit, and delete workflow inputs with name, type, required, default, and description fields; show runtime parameters when inputs exist.

## Global Constraints

- Preserve the existing portable `device-tui.workflow` schema.
- Keep changes scoped to the Workflow Studio renderer unless tests expose a contract issue.
- Run `npm run typecheck` and focused Python tests after implementation.

---

### Task 1: Add Workflow Input Editing

**Files:**
- Modify: `desktop/src/renderer/src/components/WorkflowLibrary.vue`

**Interfaces:**
- Consumes: existing `WorkflowInput`, `selected`, `save`, and validation state.
- Produces: handlers for adding, updating, and removing `selected.inputs` entries; an editor section visible for the selected workflow.

- [x] **Step 1: Add handlers**

Implement `addWorkflowInput`, `removeWorkflowInput`, and `updateWorkflowInputDefinition` using immutable array replacement and unique names such as `input_1`.

- [x] **Step 2: Render editor controls**

Render a compact `workflow-input-editor` section before runtime values, with controls for name, type, required, default, description, add, and delete.

- [x] **Step 3: Verify renderer behavior**

Run `npm run typecheck` from `desktop` and confirm no TypeScript/Vue errors.

### Task 2: Regression Verification

**Files:**
- Test: existing Workflow Studio and portable workflow tests.

- [x] **Step 1: Run focused backend tests**

Run `python -m pytest tests/test_workflow_portable.py tests/test_workflow_studio_api.py -q`.

- [x] **Step 2: Run production build**

Run `npm run build` from `desktop`.
