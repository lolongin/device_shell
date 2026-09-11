# Task 1 Report

## Status

Complete.

## Commit

`0d5740d64d0e6ca1a7bffc0b3a93785db82450b0` (`feat: add generic workflow studio contracts`)

## Changes

- Added framework-independent workflow draft/version, node, edge, and input dataclasses with deterministic dictionary serialization.
- Added ActionSpec and ActionCatalog with the P0 device, connection, transfer, control, and condition actions.
- Added structured workflow validation for unknown actions, required configuration, invalid edges/conditions, disconnected nodes, cycles, variable references, and high-risk warnings.
- Exported the workflow studio contracts from `device_tui.application.workflow_studio`.
- Added focused round-trip and validation tests.

## Tests

Command: `python -m pytest tests/test_workflow_studio_models.py tests/test_workflow_studio_validation.py -q`

Output: `6 passed in 0.06s`

Also ran: `python -m compileall -q device_tui/application/workflow_studio` (pass).

## Reviewer follow-up

Strengthened validation for duplicate node/input names, a single-root workflow policy, blank or null required values, non-string edge conditions, nested variable references, edge-condition references, and forward references to non-upstream node outputs.

Follow-up command: `python -m pytest tests/test_workflow_studio_models.py tests/test_workflow_studio_validation.py -q`

Follow-up output: `9 passed in 0.07s`

## Concerns

- The catalog is intentionally a schema/executor metadata boundary; execution mapping remains for the compiler task.
- Variable validation currently allows workflow input names, `device`, `inputs`, and node IDs as roots; richer output-path semantics should be tightened by the compiler when output schemas are available.
- Dataclasses use immutable containers for top-level collections, while nested dictionaries remain copied on serialization rather than deeply frozen.


Edge conditions now allow source output references; focused suite 10 passed.
