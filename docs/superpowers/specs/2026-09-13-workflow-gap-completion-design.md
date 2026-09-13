# Workflow Gap Completion Design

## Goal

Close the current Workflow Studio gaps for the requested flow model: device selection and connection, IF conditions, variables, command execution, FOR iteration, WAIT, expressions, retry, reboot, human confirmation, outputs, and file transfer.

## Scope

The first delivery keeps the existing TaskPlan/WorkflowRuntime boundary and adds three framework-backed utility actions:

- `variable.set`: assign a literal or a resolved value to a named workflow variable.
- `expression.evaluate`: evaluate a bounded expression against workflow inputs and prior node outputs.
- `loop.for_each`: execute a child action once per item in a list, with the item and index available to that child.

The delivery also fixes published-version execution, compile/validation parity, node renaming, referenced-version protection, dynamic Action Catalog rendering, and workflow input validation. Retry remains a node policy with explicit retryable error classes and bounded attempts; a separate visual RETRY node is deferred because it would duplicate TaskOrchestrator policy.

## Architecture

`WorkflowDefinition` remains the source of the Studio graph. The compiler maps Studio actions to allow-listed framework activities. Utility actions execute through `ActivityExecutor` and return structured outputs. The TaskOrchestrator resolves exact `${path}` references before invoking a child workflow; expression and loop handlers receive the resolved task context through their Activity inputs.

The run API uses an explicit published version when one exists unless the caller opts into `draft: true`. Publishing validates both the Studio graph and compiler compatibility. Starting a published run marks that immutable version as referenced before creating the Task.

The renderer loads `/workflow-definitions/actions`, renders the catalog from metadata, exposes workflow inputs and utility-node configuration, and preserves edge references when a node id changes. The existing compact Studio layout remains in place for this delivery; a full canvas editor is deferred.

## Semantics

- Workflow inputs are validated for required values and primitive types before compilation.
- Variable references use exact `${inputs.name}`, `${node_id.field}`, or `${variable_name}` paths. Embedded string interpolation is rejected with a validation error.
- `expression.evaluate` supports literals, comparisons, boolean operators, arithmetic, and `inputs`/node-output paths through a restricted AST evaluator. Calls, attributes, imports, and arbitrary names are rejected.
- `loop.for_each` accepts `items` as a list or an exact variable reference, invokes one allow-listed child action per item, and returns `items`, `results`, and `count`. The child action receives `item` and `index` in its inputs.
- `utility.condition` accepts visual rules. Expression-only conditions are either compiled through `expression.evaluate` or rejected consistently at validation; this delivery chooses compilation through the bounded evaluator.
- High-risk actions appear in the run preview and require the existing confirmation step. The API also rejects a run without an explicit confirmation token when high-risk actions are present.

## Error handling

Validation returns structured issues for unknown actions, missing inputs, invalid references, unsupported expressions, invalid loop actions, cycles, and incompatible branch merges. Runtime utility failures return deterministic Activity errors. Loop failures identify the item index and child action. Published versions are immutable and cannot be deleted after a run references them.

## Testing

Add focused pytest coverage for input validation, expression safety/evaluation, loop output and failure reporting, compile/validation parity, published-version selection and reference marking, and node rename edge preservation. Extend the existing Vue source checks to verify catalog loading and utility-node forms. Run the focused workflow suite, Python compile checks, and desktop typecheck/build.
