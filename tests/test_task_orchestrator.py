from __future__ import annotations

import asyncio
import time

from device_tui.framework import (
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


class FlakyHandler:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, action, run, emit):
        self.calls += 1
        if self.calls == 1:
            return ActionResult(ActionStatus.FAILED, error={"code": "temporary", "message": "try again"})
        return ActionResult(ActionStatus.SUCCEEDED, facts={"value": "recovered"})


class CountingHandler:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, action, run, emit):
        self.calls += 1
        return ActionResult(ActionStatus.SUCCEEDED, facts={"value": self.calls})


class SlowHandler:
    def __init__(self) -> None:
        self.started: list[str] = []

    async def execute(self, action, run, emit):
        self.started.append(str(action.params.get("value")))
        await asyncio.sleep(0.03)
        return ActionResult(ActionStatus.SUCCEEDED, facts={"value": action.params.get("value")})


class ParallelFailureHandler:
    async def execute(self, action, run, emit):
        if action.params.get("value") == "bad":
            return ActionResult(ActionStatus.FAILED, error={"code": "parallel_failed", "message": "检查失败"})
        await asyncio.sleep(0.01)
        return ActionResult(ActionStatus.SUCCEEDED, facts={"value": action.params.get("value")})


class ParallelFlakyHandler:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, action, run, emit):
        self.calls += 1
        if self.calls == 1:
            return ActionResult(ActionStatus.FAILED, error={"code": "temporary", "message": "请重试"})
        return ActionResult(ActionStatus.SUCCEEDED, facts={"value": "ok"})


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


def test_task_orchestrator_retries_failed_node_with_retry_policy():
    actions = ActionRegistry()
    handler = FlakyHandler()
    actions.register(handler, item_id="test.action")
    orchestrator = TaskOrchestrator(WorkflowRuntime(actions=actions), Builder())
    plan = TaskPlan("retry-plan", nodes=(WorkflowNode("step", "test.action", retry_policy={"max_attempts": 2}),))
    task = orchestrator.start(plan, device_id="d1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status == TaskRunStatus.SUCCEEDED
    assert handler.calls == 2
    assert result.outputs["step"]["run"]["value"] == "recovered"


def test_task_orchestrator_applies_retry_backoff_between_attempts():
    class TimestampFlakyHandler:
        def __init__(self) -> None:
            self.calls = 0
            self.timestamps: list[float] = []

        async def execute(self, action, run, emit):
            self.calls += 1
            self.timestamps.append(time.perf_counter())
            if self.calls == 1:
                return ActionResult(ActionStatus.FAILED, error={"code": "temporary", "message": "try again"})
            return ActionResult(ActionStatus.SUCCEEDED, facts={"value": "recovered"})

    actions = ActionRegistry()
    handler = TimestampFlakyHandler()
    actions.register(handler, item_id="test.action")
    orchestrator = TaskOrchestrator(
        WorkflowRuntime(actions=actions),
        Builder(),
        sleep=asyncio.sleep,
    )
    plan = TaskPlan(
        "retry-backoff-plan",
        nodes=(WorkflowNode("step", "test.action", retry_policy={"max_attempts": 2, "backoff_seconds": 0.02}),),
    )
    task = orchestrator.start(plan, device_id="d1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status == TaskRunStatus.SUCCEEDED
    assert len(handler.timestamps) == 2
    assert handler.timestamps[1] - handler.timestamps[0] >= 0.019


def test_task_orchestrator_repeats_successful_node_with_iteration_context():
    actions = ActionRegistry()
    handler = CountingHandler()
    actions.register(handler, item_id="test.action")
    orchestrator = TaskOrchestrator(WorkflowRuntime(actions=actions), Builder())
    plan = TaskPlan("repeat-plan", nodes=(WorkflowNode("step", "test.action", repeat_policy={"max_iterations": 3}),))
    task = orchestrator.start(plan, device_id="d1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status == TaskRunStatus.SUCCEEDED
    assert handler.calls == 3
    assert result.outputs["step"]["repeat_iterations"] == 3


def test_task_orchestrator_executes_independent_parallel_group_concurrently():
    actions = ActionRegistry()
    handler = SlowHandler()
    actions.register(handler, item_id="test.action")
    orchestrator = TaskOrchestrator(WorkflowRuntime(actions=actions), Builder())
    plan = TaskPlan(
        "parallel-plan",
        nodes=(
            WorkflowNode("first", "test.action", input_mapping={"value": "first"}),
            WorkflowNode("a", "test.action", depends_on=("first",), input_mapping={"value": "a"}, parallel_group="checks"),
            WorkflowNode("b", "test.action", depends_on=("first",), input_mapping={"value": "b"}, parallel_group="checks"),
        ),
    )
    task = orchestrator.start(plan, device_id="d1")
    started = time.perf_counter()
    result = asyncio.run(orchestrator.execute(task.id, plan))
    elapsed = time.perf_counter() - started
    assert result.status == TaskRunStatus.SUCCEEDED
    assert set(handler.started) == {"first", "a", "b"}
    assert elapsed < 0.09
    assert "parallel_batch" not in result.context


def test_parallel_group_failure_is_aggregated_to_parent_task():
    actions = ActionRegistry()
    actions.register(ParallelFailureHandler(), item_id="test.action")
    orchestrator = TaskOrchestrator(WorkflowRuntime(actions=actions), Builder())
    plan = TaskPlan("parallel-failure", nodes=(
        WorkflowNode("a", "test.action", input_mapping={"value": "bad"}, parallel_group="checks"),
        WorkflowNode("b", "test.action", input_mapping={"value": "ok"}, parallel_group="checks"),
    ))
    task = orchestrator.start(plan, device_id="d1")
    result = asyncio.run(orchestrator.execute(task.id, plan))
    assert result.status == TaskRunStatus.FAILED
    assert result.error["code"] == "parallel_failed"


def test_parallel_node_keeps_retry_policy():
    actions = ActionRegistry()
    handler = ParallelFlakyHandler()
    actions.register(handler, item_id="test.action")
    orchestrator = TaskOrchestrator(WorkflowRuntime(actions=actions), Builder())
    plan = TaskPlan("parallel-retry", nodes=(
        WorkflowNode("a", "test.action", retry_policy={"max_attempts": 2}, parallel_group="checks"),
        WorkflowNode("b", "test.action", parallel_group="checks"),
    ))
    task = orchestrator.start(plan, device_id="d1")
    result = asyncio.run(orchestrator.execute(task.id, plan))
    assert result.status == TaskRunStatus.SUCCEEDED
    assert handler.calls == 3


def test_task_orchestrator_runs_only_the_matching_condition_branch() -> None:
    actions = ActionRegistry()
    actions.register(Handler(), item_id="test.action")
    orchestrator = TaskOrchestrator(WorkflowRuntime(actions=actions), Builder())
    condition = {
        "rules": [{"field": "value", "operator": "小于", "value": "8.200"}],
        "logical_operator": "AND",
        "values_from": "info",
    }
    plan = TaskPlan(
        id="conditional-plan",
        nodes=(
            WorkflowNode("info", "test.action", input_mapping={"value": "8.100"}),
            WorkflowNode("upload", "test.action", depends_on=("info",), run_if={**condition, "expected": True}),
            WorkflowNode("record", "test.action", depends_on=("info",), run_if={**condition, "expected": False}),
        ),
    )
    task = orchestrator.start(plan, device_id="d1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status == TaskRunStatus.SUCCEEDED
    assert set(result.node_runs) == {"info", "upload"}
    assert result.outputs["record"]["status"] == "skipped"
    assert result.outputs["record"]["reason"] == "condition_false"


def test_task_orchestrator_runs_only_the_matching_expression_branch() -> None:
    actions = ActionRegistry()
    actions.register(Handler(), item_id="test.action")
    orchestrator = TaskOrchestrator(WorkflowRuntime(actions=actions), Builder())
    condition = {"expression": "inputs.enabled and threshold >= 2", "expected": True}
    plan = TaskPlan(
        id="expression-conditional-plan",
        nodes=(
            WorkflowNode("run", "test.action", run_if=condition),
            WorkflowNode("skip", "test.action", run_if={**condition, "expected": False}),
        ),
    )
    task = orchestrator.start(
        plan,
        device_id="d1",
        inputs={"enabled": True, "threshold": 2},
    )

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status == TaskRunStatus.SUCCEEDED
    assert set(result.node_runs) == {"run"}
    assert result.outputs["skip"] == {"status": "skipped", "reason": "condition_false"}


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


def test_task_plan_rejects_dependent_nodes_in_parallel_group() -> None:
    plan = TaskPlan(
        id="parallel-group",
        nodes=(
            WorkflowNode("a", "one", parallel_group="checks"),
            WorkflowNode("b", "two", depends_on=("a",), parallel_group="checks"),
        ),
    )
    try:
        plan.validate()
    except ValueError as exc:
        assert "parallel group" in str(exc)
    else:
        raise AssertionError("dependent parallel nodes were accepted")


def test_task_plan_exposes_dependency_safe_execution_batches() -> None:
    plan = TaskPlan(
        id="batches",
        nodes=(
            WorkflowNode("first", "one"),
            WorkflowNode("check_a", "two", depends_on=("first",), parallel_group="checks"),
            WorkflowNode("check_b", "three", depends_on=("first",), parallel_group="checks"),
            WorkflowNode("last", "four", depends_on=("check_a", "check_b")),
        ),
    )
    batches = plan.execution_batches()
    assert [[node.id for node in batch] for batch in batches] == [
        ["first"], ["check_a", "check_b"], ["last"]
    ]


class _ExistingChildRuntime:
    def __init__(self, child: WorkflowRun) -> None:
        self.runs = type("Runs", (), {"get": lambda _self, _run_id: child})()


class _ResumableChildRuntime(_ExistingChildRuntime):
    async def run_until_blocked(self, _run_id: str) -> WorkflowRun:
        return WorkflowRun("child-1", "wf", "1", "d1", status=RunStatus.SUCCEEDED, outputs={"value": "resumed"})


class _PartialParallelRuntime:
    def __init__(self) -> None:
        self.runs = type("Runs", (), {"get": lambda self, run_id: WorkflowRun(run_id, "wf", "1", "d1", status=RunStatus.SUCCEEDED, outputs={"value": "kept"})})()

    async def run_until_blocked(self, _run_id: str) -> WorkflowRun:
        return WorkflowRun(_run_id, "wf", "1", "d1", status=RunStatus.SUCCEEDED, outputs={"value": "new"})

    def start(self, definition, *, device_id, context, run_id=None):
        return WorkflowRun("new-child", definition.id, definition.version, device_id, status=RunStatus.SUCCEEDED)


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


def test_parallel_resume_reuses_persisted_child_and_runs_missing_node() -> None:
    store = MemoryTaskRunStore()
    store.save(TaskRun("task-1", "parallel", "d1", status=TaskRunStatus.WAITING_CHILD, node_runs={"a": "child-a"}, outputs={"a": {"value": "kept"}}))
    runtime = _PartialParallelRuntime()
    orchestrator = TaskOrchestrator(runtime, Builder(), store=store)
    plan = TaskPlan("parallel", nodes=(
        WorkflowNode("a", "wf", parallel_group="checks"),
        WorkflowNode("b", "wf", parallel_group="checks"),
    ))
    result = asyncio.run(orchestrator.execute("task-1", plan))
    assert result.status == TaskRunStatus.SUCCEEDED
    assert result.outputs["a"]["value"] == "kept"
    assert result.outputs["b"]["value"] == "new"


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


def test_task_orchestrator_resume_from_step_clears_step_and_downstream_state():
    store = MemoryTaskRunStore()
    store.save(TaskRun("task-1", "plan-1", "d1", status=TaskRunStatus.FAILED,
                       node_runs={"one": "run-1", "two": "run-2", "three": "run-3"},
                       outputs={"one": {"ok": True}, "two": {"ok": True}, "three": {"ok": True}}))
    plan = TaskPlan("plan-1", nodes=(
        WorkflowNode("one", "wf"),
        WorkflowNode("two", "wf", depends_on=("one",)),
        WorkflowNode("three", "wf", depends_on=("two",)),
    ))
    orchestrator = TaskOrchestrator(_ExistingChildRuntime(WorkflowRun("child", "wf", "1", "d1")), Builder(), store=store)

    resumed = orchestrator.resume("task-1", step_id="two", plan=plan)

    assert resumed.status == TaskRunStatus.RUNNING
    assert resumed.node_runs == {"one": "run-1"}
    assert resumed.outputs == {"one": {"ok": True}}


def test_task_orchestrator_fences_persisted_inflight_runs_after_restart() -> None:
    store = MemoryTaskRunStore()
    running = TaskRun("task-running", "plan-1", "d1", status=TaskRunStatus.RUNNING)
    waiting = TaskRun("task-waiting", "plan-1", "d1", status=TaskRunStatus.WAITING_CHILD)
    done = TaskRun("task-done", "plan-1", "d1", status=TaskRunStatus.SUCCEEDED)
    for item in (running, waiting, done):
        store.save(item)

    orchestrator = TaskOrchestrator(_ExistingChildRuntime(WorkflowRun("child", "wf", "1", "d1")), Builder(), store=store)

    assert orchestrator.get("task-running").status == TaskRunStatus.WAITING_RECONCILE
    assert orchestrator.get("task-waiting").status == TaskRunStatus.WAITING_RECONCILE
    assert orchestrator.get("task-done").status == TaskRunStatus.SUCCEEDED
    assert orchestrator.get("task-running").context["framework.recovery"]["reason"] == "process_restart"
