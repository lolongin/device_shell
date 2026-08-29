from __future__ import annotations

import asyncio

from device_tui.application.workflows import (
    ActionRegistry,
    ActionResult,
    ActionSpec,
    ActionStatus,
    MemoryTaskRunStore,
    StateNode,
    TaskOrchestrator,
    TaskPlan,
    TaskRun,
    TaskRunStatus,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowRuntime,
    WorkflowRun,
    RunStatus,
)


class Handler:
    async def execute(self, action, run, emit):
        return ActionResult(ActionStatus.SUCCEEDED, facts={
            "value": action.params.get("value", "ok"),
            "context": dict(run.context),
        })


class Builder:
    def build(self, workflow_id, inputs):
        return WorkflowDefinition(
            id=workflow_id,
            version="1",
            start_state="run",
            states=(
                StateNode(
                    "run",
                    ActionSpec("run", "test.action", params={"value": inputs.get("value", "ok")}),
                    next_state="done",
                ),
                StateNode("done", terminal=True),
            ),
        )


def test_task_orchestrator_composes_workflows_and_maps_outputs() -> None:
    actions = ActionRegistry()
    actions.register(Handler(), item_id="test.action")
    orchestrator = TaskOrchestrator(WorkflowRuntime(actions=actions), Builder())
    plan = TaskPlan(
        id="build-and-test",
        nodes=(
            WorkflowNode("build", "artifact.build", input_mapping={"value": "${value}"}),
            WorkflowNode(
                "test", "script.run", depends_on=("build",),
                input_mapping={"value": "${build.run.value}"},
            ),
        ),
    )
    task = orchestrator.start(plan, device_id="d1", inputs={"value": "image.cc"})

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status == TaskRunStatus.SUCCEEDED
    assert set(result.node_runs) == {"build", "test"}
    assert result.outputs["test"]["run"]["value"] == "image.cc"


def test_task_orchestrator_passes_persisted_context_to_child_workflow() -> None:
    actions = ActionRegistry()
    actions.register(Handler(), item_id="test.action")
    orchestrator = TaskOrchestrator(WorkflowRuntime(actions=actions), Builder())
    plan = TaskPlan("context-plan", nodes=(WorkflowNode("step", "wf"),))
    task = orchestrator.start(
        plan,
        device_id="d1",
        context={"target": {"session_id": "sess-1", "protocol": "ssh"}},
    )

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status == TaskRunStatus.SUCCEEDED
    assert result.outputs["step"]["run"]["context"]["target"]["session_id"] == "sess-1"


def test_task_plan_rejects_dependency_cycles() -> None:
    plan = TaskPlan(
        id="cycle",
        nodes=(
            WorkflowNode("a", "one", depends_on=("b",)),
            WorkflowNode("b", "two", depends_on=("a",)),
        ),
    )

    try:
        plan.validate()
    except ValueError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("cyclic task plan was accepted")


class _ExistingChildRuntime:
    def __init__(self, child: WorkflowRun) -> None:
        self.runs = type("Runs", (), {"get": lambda _self, _run_id: child})()


class _ResumableChildRuntime(_ExistingChildRuntime):
    async def run_until_blocked(self, _run_id: str) -> WorkflowRun:
        return WorkflowRun("child-1", "wf", "1", "d1", status=RunStatus.SUCCEEDED, outputs={"value": "resumed"})


def test_task_orchestrator_drives_existing_running_child_on_resume() -> None:
    store = MemoryTaskRunStore()
    store.save(TaskRun("task-1", "plan-1", "d1", status=TaskRunStatus.WAITING_CHILD, node_runs={"step": "child-1"}))
    plan = TaskPlan("plan-1", nodes=(WorkflowNode("step", "wf"),))
    orchestrator = TaskOrchestrator(
        _ResumableChildRuntime(WorkflowRun("child-1", "wf", "1", "d1", status=RunStatus.RUNNING)),
        Builder(),
        store=store,
    )

    result = asyncio.run(orchestrator.execute("task-1", plan))

    assert result.status == TaskRunStatus.SUCCEEDED
    assert result.outputs["step"]["value"] == "resumed"


def test_task_orchestrator_preserves_child_decision_state_on_resume() -> None:
    child = WorkflowRun("child-1", "wf", "1", "d1", status=RunStatus.WAITING_DECISION)
    store = MemoryTaskRunStore()
    task = TaskRun(
        "task-1", "plan-1", "d1", status=TaskRunStatus.WAITING_CHILD,
        node_runs={"step": "child-1"},
    )
    store.save(task)
    plan = TaskPlan("plan-1", nodes=(WorkflowNode("step", "wf"),))
    orchestrator = TaskOrchestrator(_ExistingChildRuntime(child), Builder(), store=store)

    result = asyncio.run(orchestrator.execute("task-1", plan))

    assert result.status == TaskRunStatus.WAITING_DECISION


def test_task_orchestrator_rejects_executing_against_another_plan() -> None:
    actions = ActionRegistry()
    actions.register(Handler(), item_id="test.action")
    orchestrator = TaskOrchestrator(WorkflowRuntime(actions=actions), Builder())
    task = orchestrator.start(TaskPlan("plan-1", nodes=(WorkflowNode("step", "wf"),)), device_id="d1")

    try:
        asyncio.run(orchestrator.execute(task.id, TaskPlan("plan-2", nodes=(WorkflowNode("step", "wf"),))))
    except ValueError as exc:
        assert "plan mismatch" in str(exc)
    else:
        raise AssertionError("plan mismatch was accepted")


class _ControlRuntime:
    def __init__(self) -> None:
        self.child = WorkflowRun("child-1", "wf", "1", "d1", status=RunStatus.RUNNING)
        self.runs = type("Runs", (), {"get": lambda _self, _run_id: self.child})()
        self.paused: list[str] = []
        self.resumed: list[str] = []
        self.cancelled: list[str] = []

    def pause(self, run_id):
        self.paused.append(run_id)
        self.child = WorkflowRun("child-1", "wf", "1", "d1", status=RunStatus.PAUSED)
        return self.child

    def resume(self, run_id, *, context=None):
        self.resumed.append(run_id)
        self.child = WorkflowRun("child-1", "wf", "1", "d1", status=RunStatus.RUNNING)
        return self.child

    def cancel(self, run_id):
        self.cancelled.append(run_id)
        self.child = WorkflowRun("child-1", "wf", "1", "d1", status=RunStatus.CANCELLED)
        return self.child


def test_task_orchestrator_controls_active_child_at_task_boundary() -> None:
    runtime = _ControlRuntime()
    store = MemoryTaskRunStore()
    store.save(TaskRun("task-1", "plan-1", "d1", status=TaskRunStatus.RUNNING, node_runs={"step": "child-1"}))
    orchestrator = TaskOrchestrator(runtime, Builder(), store=store)

    paused = orchestrator.pause("task-1")
    assert paused.status == TaskRunStatus.WAITING_RECONCILE
    assert runtime.paused == ["child-1"]

    resumed = orchestrator.resume("task-1", context={"operator": "user"})
    assert resumed.status == TaskRunStatus.RUNNING
    assert resumed.context["operator"] == "user"
    assert runtime.resumed == ["child-1"]

    cancelled = orchestrator.cancel("task-1")
    assert cancelled.status == TaskRunStatus.CANCELLED
    assert runtime.cancelled == ["child-1"]
