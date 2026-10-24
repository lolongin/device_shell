# MCP AI task orchestration

The local MCP server exposes the desktop backend's device and workflow services.
AI clients can discover targets, validate structured plans, start tasks, wait for
changes across tasks, and handle supported recovery decisions. Electron remains
the only desktop UI; execution and credentials stay in the Python backend.

## Discover targets and capabilities

Start with `app.capabilities`, `device.list`, and `workflow.list`. The latter
returns `capabilities`, `capability_specs`, and the current `plan_limits`; use
these definitions instead of inventing capability names or parameters.

`device.list` accepts intersected filters:

```json
{"query":"lab", "protocol":"ssh", "status":"online", "limit":50, "offset":0}
```

`query` searches identity, type, endpoints, and location without case sensitivity.
`owner`, `status`, and `protocol` match without case sensitivity. `device_ids`
restricts the result to explicit targets; an empty array matches no devices.
Omit `limit` to retain the full-list behavior, or use 1–1000 and follow
`data.next_offset` until it is null. `data.total` is the count after filtering.

## Validate and execute a plan

Call `workflow.plan.validate` with a structured `plan` argument:

```json
{
  "plan": {
    "objective": "Read the device version",
    "target": {"device_id": "DEVICE_ID"},
    "steps": [
      {
        "id": "version",
        "capability": "terminal.command",
        "params": {"command": "display version"}
      }
    ]
  }
}
```

The MCP schema describes plan, step, and decision fields directly to the client.
Extension fields remain supported. Omitted optional fields are passed through
without inserting client-side defaults.

Inspect `data.status`, `data.errors`, and `data.required_actions`. When validation
and policy allow execution, call `workflow.run` with the returned `plan_id` and
`plan_hash`. Follow the existing approval flow for plans that require approval;
AI must obtain actual user authorization before representing a user approval.
Changing a plan requires validation again.

Keep the returned `data.task.id`. Dependencies describe ordering constraints;
they do not promise parallel execution. For independent command batches across
sessions, use `terminal.parallel`. For reusable scripts and multi-device
workflows, discover the contract with `workflow.authoring.describe` and use the
existing `workflow.script.*` and `workflow.definition.*` tools, including dry-run
and confirmation parameters where applicable.

## Observe one task or a fleet

`task.get` retains `data.task` and adds `decision`, `cursor`, `terminal`,
`requires_attention`, and `next_action`. `task.wait` observes up to 32 TaskRecord
IDs per call and waits at most 20 seconds:

```json
{
  "task_ids": ["TASK_A", "TASK_B"],
  "after_cursors": {"TASK_A": "PREVIOUS_CURSOR_A", "TASK_B": "PREVIOUS_CURSOR_B"},
  "timeout_seconds": 20
}
```

For the first snapshot, omit `after_cursors`. Each item in `data.observations`
contains the same observation fields as `task.get`. Save its cursor keyed by
`task.id` for the next call. Cursors are opaque hashes of task and decision
content, so progress-only changes also wake the wait. `changed_task_ids` lists
changed observations. `reason` is `snapshot`, `changed`, `attention`, `terminal`,
or `timeout`.

Remove terminal tasks from subsequent waits. Handle tasks requiring attention
before waiting on them again: terminal or attention states return immediately,
even with a matching cursor. A timeout does not cancel the tasks. Reusing an
idempotency key on observation requests does not cache stale state.

TaskRecord IDs used here differ from framework TaskRun IDs. Inspect TaskRun
executions through `task.framework.get`; do not pass them to `task.wait`.

## Recover deliberately

Use `next_action` and `decision.get` to inspect the pending checkpoint and
`available_actions`. Only submit an action allowed by the current decision:

```json
{
  "task_id": "TASK_A",
  "action": {"name": "retry", "expected_revision": 3},
  "reason": "The transient connection failure has been resolved"
}
```

`decision.apply` and the legacy MCP task-decision handler submit agent decisions.
They reject contexts whose `decision_modes` exclude `agent`. User-only decisions
need user input. Pass the observed `checkpoint_revision` as `expected_revision`
at the top level or inside `action`; if both are supplied they must match.
A stale revision returns a conflict (HTTP 409). Read the new context and reassess
the action before retrying. For older callers omitting a revision, the facade
captures the current checkpoint revision and forwards it to backend validation.

Use `task.resume` for a paused task when appropriate, or `task.replan` to validate
a replacement plan linked to its parent. Inspect evidence before retrying device
writes: a lost response does not prove that a command had no effect.

## Validation and boundaries

Automated tests cover filtered discovery, MCP schema serialization, multi-task
waits, progress cursors, cancellation, decision authority and revision conflicts,
and a simulated-device plan from validation through command output. Real-device
behavior still depends on transport availability and the device's command set.
This change adds bounded observation; it does not add a persistent fleet scheduler
or guarantee that active tasks survive a backend restart.
