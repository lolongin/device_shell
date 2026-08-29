from __future__ import annotations

from device_tui.application.workflows import (
    MemoryWorkflowRunStore,
    RunStatus,
    StateNode,
    WorkflowDefinition,
    WorkflowRuntime,
)


def test_runtime_fences_persisted_inflight_runs_for_reconcile() -> None:
    store = MemoryWorkflowRunStore()
    definition = WorkflowDefinition(
        id="recovery.workflow",
        version="1",
        start_state="run",
        states=(StateNode("run"),),
    )
    first = WorkflowRuntime(runs=store)
    run = first.start(definition, device_id="d1", run_id="run-1")
    assert run.status == RunStatus.RUNNING

    restarted = WorkflowRuntime(runs=store)
    recovered = restarted.recover_inflight()

    assert [item.id for item in recovered] == ["run-1"]
    persisted = store.get("run-1")
    assert persisted.status == RunStatus.PAUSED
    assert persisted.context["framework.recovery"]["required"] is True
    assert persisted.context["framework.recovery"]["reason"] == "process_restart"
