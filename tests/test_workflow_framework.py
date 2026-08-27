from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from device_tui.application.workflows import (
    ActionResult,
    ActionSpec,
    ActionStatus,
    DecisionSubmission,
    Event,
    Expectation,
    Option,
    ReconcileClassification,
    ReconcilePolicy,
    ReconcileResult,
    StateNode,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRuntime,
    build_default_adapter_registry,
    build_default_workflow_registry,
    compile_workflow,
)
from device_tui.application.workflows.plugins import ActionRegistry, ReconcileRegistry
from device_tui.application.workflows.watchdog import Watchdog
from device_tui.application.workflows.models import ActionAttempt, DeviceStateSnapshot
from device_tui.application.workflows.device_bridge import DeviceExecutionActionHandler, DeviceReconcileProvider
from device_tui.application.upgrades.commands import HuaweiVrpCommandSet
from device_tui.application.tasking import DeviceExecutionTool


class Handler:
    def __init__(self, events: tuple[Event, ...], status: ActionStatus = ActionStatus.SUCCEEDED) -> None:
        self.events = events
        self.status = status
        self.calls = 0

    async def execute(self, action, run, emit):
        self.calls += 1
        return ActionResult(self.status, self.events, {"calls": self.calls})


class Reconciler:
    id = "test.reconcile"

    def __init__(self, classification: ReconcileClassification) -> None:
        self.classification = classification
        self.calls = 0

    async def reconcile(self, action, run, reason, emit):
        self.calls += 1
        return ReconcileResult(self.classification, {"reason": reason}, ({"probe": "read-only"},))


def test_provider_is_generic_and_huawei_is_only_a_registered_workflow() -> None:
    workflow = build_default_workflow_registry().build(
        "network.package_upgrade",
        {"package_ref": "flash:/image.cc", "expected_version": "V8"},
    )
    assert workflow.id == "network.package_upgrade"
    assert workflow.start_state == "precheck"
    assert {item.id for item in workflow.states} >= {"transfer", "reboot", "verify_version", "rollback"}
    assert workflow.states[1].action is not None
    assert workflow.states[1].action.operation == "huawei.storage.cleanup"


def test_huawei_adapter_parses_semantic_events_and_capabilities() -> None:
    adapter = build_default_adapter_registry().resolve({"vendor": "Huawei", "platform": "VRP"}, {"huawei.vrp"})
    events = adapter.parse_output(
        "ftp>\nTransfer started\nTransfer completed\nStartup configured\nReboot started",
        run_id="r1",
        action_id="a1",
    )
    assert {event.type for event in events} >= {
        "huawei.ftp.ready",
        "huawei.transfer.started",
        "huawei.transfer.completed",
        "huawei.startup.configured",
        "huawei.reboot.started",
    }


def test_wait_online_emits_cli_ready_only_after_the_readiness_probe_succeeds() -> None:
    action = ActionSpec("wait_online", "device.wait_online")
    run = WorkflowRun("r1", "test", "1", "d1")

    not_ready = DeviceExecutionActionHandler._semantic_events(
        action,
        run,
        {"transport_status": "connected", "cli_status": "not_ready"},
        "",
    )
    ready = DeviceExecutionActionHandler._semantic_events(
        action,
        run,
        {"transport_status": "connected", "cli_status": "ready"},
        "VRP V8\n<Huawei> ",
    )

    assert not not_ready
    assert [event.type for event in ready] == ["huawei.cli.ready"]


def test_online_reconcile_requires_cli_probe_not_only_connected_transport() -> None:
    async def scenario() -> None:
        class Control:
            def __init__(self, *, cli_ready: bool) -> None:
                self.cli_ready = cli_ready

            async def open_session(self, target, **kwargs):
                del target, kwargs
                return SimpleNamespace(session_id="s1", status="connected")

            async def execute(self, target, request, *, context):
                del target, request, context
                if not self.cli_ready:
                    return SimpleNamespace(
                        execution_id="probe-1",
                        status="timed_out",
                        error_code="cli_prompt_timeout",
                        output="Username: ",
                    )
                return SimpleNamespace(
                    execution_id="probe-1",
                    status="completed",
                    error_code="",
                    output="VRP V8\n<Huawei> ",
                )

        action = ActionSpec("wait_online", "device.wait_online")
        run = WorkflowRun("r1", "test", "1", "d1")

        ready_control = Control(cli_ready=True)
        not_ready_control = Control(cli_ready=False)
        ready = await DeviceReconcileProvider(
            "huawei.reconcile.online", DeviceExecutionTool(ready_control), ready_control,
        ).reconcile(action, run, "timeout", lambda event: event)
        not_ready = await DeviceReconcileProvider(
            "huawei.reconcile.online", DeviceExecutionTool(not_ready_control), not_ready_control,
        ).reconcile(action, run, "timeout", lambda event: event)

        assert ready.classification == ReconcileClassification.SUCCESS
        assert ready.facts["transport_status"] == "connected"
        assert ready.facts["cli_status"] == "ready"
        assert not_ready.classification == ReconcileClassification.INDETERMINATE
        assert not_ready.facts["transport_status"] == "connected"
        assert not_ready.facts["cli_status"] == "not_ready"

    asyncio.run(scenario())


def test_dsl_rejects_unknown_state_reference() -> None:
    with pytest.raises(ValueError, match="unknown state"):
        compile_workflow({"id": "test", "start_state": "one", "states": [{"id": "one", "next": "missing"}]})


def test_runtime_advances_only_when_expectations_are_observed() -> None:
    async def scenario() -> None:
        events = (Event("ready", "", "run-action"),)
        handler = Handler(events)
        actions = ActionRegistry()
        actions.register(handler, item_id="test.action")
        definition = WorkflowDefinition(
            "test.workflow", "1", "one",
            (StateNode("one", ActionSpec("one", "test.action", expectations=(Expectation("ready"),)), next_state="done"), StateNode("done", terminal=True)),
        )
        runtime = WorkflowRuntime(actions=actions)
        run = runtime.start(definition, device_id="d1")
        result = await runtime.tick(run.id)
        assert result.current_state == "done"
        assert result.status == "succeeded"
        assert runtime.events.list(run.id)[-1].type == "ready"

    asyncio.run(scenario())


def test_runtime_run_until_blocked_drives_and_reports_one_run() -> None:
    async def scenario() -> None:
        handler = Handler((Event("ready", "", "run-action"),))
        actions = ActionRegistry()
        actions.register(handler, item_id="test.action")
        definition = WorkflowDefinition(
            "test.runner", "1", "one",
            (
                StateNode("one", ActionSpec("one", "test.action", expectations=(Expectation("ready"),)), next_state="done"),
                StateNode("done", terminal=True),
            ),
        )
        runtime = WorkflowRuntime(actions=actions)
        run = runtime.start(definition, device_id="d1")
        updates: list[str] = []

        result = await runtime.run_until_blocked(
            run.id,
            on_update=lambda current: updates.append(str(current.status)),
        )

        assert result.status == "succeeded"
        assert handler.calls == 1
        assert updates[0] == "running"
        assert updates[-1] == "succeeded"

    asyncio.run(scenario())


def test_unknown_action_state_reconciles_before_decision() -> None:
    async def scenario() -> None:
        handler = Handler((), ActionStatus.FAILED)
        reconciler = Reconciler(ReconcileClassification.INDETERMINATE)
        actions = ActionRegistry()
        actions.register(handler, item_id="test.action")
        reconciliations = ReconcileRegistry()
        reconciliations.register(reconciler)
        definition = WorkflowDefinition(
            "test.workflow", "1", "one",
            (
                StateNode(
                    "one",
                    ActionSpec(
                        "one", "test.action", reconcile=ReconcilePolicy(provider="test.reconcile", probes=("read-only",)),
                    ),
                    decision_options=(Option("abort", "abort", "Abort", requires_reason=True),),
                ),
            ),
        )
        runtime = WorkflowRuntime(actions=actions, reconciliations=reconciliations)
        run = runtime.start(definition, device_id="d1")
        result = await runtime.tick(run.id)
        assert reconciler.calls == 1
        assert result.status == "waiting_decision"
        assert result.decision_point is not None
        assert result.decision_point.reason_code == "reconcile.indeterminate"

    asyncio.run(scenario())


def test_decision_engine_rejects_unknown_option_stale_revision_and_wrong_actor() -> None:
    async def scenario() -> None:
        handler = Handler((), ActionStatus.FAILED)
        actions = ActionRegistry()
        actions.register(handler, item_id="test.action")
        definition = WorkflowDefinition(
            "test.workflow", "1", "one",
            (StateNode("one", ActionSpec("one", "test.action"), decision_options=(Option("abort", "abort", "Abort", allowed_actors=("human",), requires_reason=True),)),),
        )
        runtime = WorkflowRuntime(actions=actions)
        run = await runtime.tick(runtime.start(definition, device_id="d1").id)
        assert run.decision_point is not None
        with pytest.raises(ValueError, match="option is not available"):
            runtime.apply_decision(run.id, DecisionSubmission(run.decision_point.id, run.revision, "invented", "human", "u"))
        with pytest.raises(ValueError, match="actor is not allowed"):
            runtime.apply_decision(run.id, DecisionSubmission(run.decision_point.id, run.revision, "abort", "agent", "a", reason="x"))
        with pytest.raises(ValueError, match="reason is required"):
            runtime.apply_decision(run.id, DecisionSubmission(run.decision_point.id, run.revision, "abort", "human", "u"))
        with pytest.raises(ValueError, match="stale"):
            runtime.apply_decision(run.id, DecisionSubmission(run.decision_point.id, run.revision - 1, "abort", "human", "u", reason="x"))

    asyncio.run(scenario())


def test_reconnect_decision_records_a_constrained_framework_directive() -> None:
    async def scenario() -> None:
        handler = Handler((), ActionStatus.FAILED)
        actions = ActionRegistry()
        actions.register(handler, item_id="test.action")
        definition = WorkflowDefinition(
            "test.reconnect", "1", "wait_online",
            (
                StateNode(
                    "wait_online",
                    ActionSpec("wait_online", "test.action"),
                    decision_options=(Option("reconnect", "reconnect", "Reconnect management session"),),
                ),
            ),
        )
        runtime = WorkflowRuntime(actions=actions)
        blocked = await runtime.tick(runtime.start(definition, device_id="d1").id)
        assert blocked.decision_point is not None

        resumed = runtime.apply_decision(
            blocked.id,
            DecisionSubmission(
                blocked.decision_point.id,
                blocked.revision,
                "reconnect",
                "human",
                "operator-1",
            ),
        )

        assert resumed.status == "running"
        assert resumed.context["framework.reconnect"]["state"] == "wait_online"

    asyncio.run(scenario())


def test_watchdog_uses_semantic_progress_and_action_deadline() -> None:
    now = datetime.now(timezone.utc)
    attempt = ActionAttempt(
        id="a", action_id="transfer", attempt=1,
        started_at=(now - timedelta(seconds=121)).isoformat(),
        last_progress_at=(now - timedelta(seconds=100)).isoformat(),
    )
    incident = Watchdog().evaluate(
        ActionSpec("transfer", "file.transfer", timeout_seconds=120, expectations=(Expectation("transfer.completed", idle_timeout_seconds=90, progress=True),)),
        attempt,
        satisfied_events=set(),
        device_state=DeviceStateSnapshot(reachability="pingable"),
        now=now,
    )
    assert incident is not None
    assert incident.code == "action_timeout"


def test_runtime_enforces_action_timeout_before_reconcile_or_decision() -> None:
    async def scenario() -> None:
        class HangingHandler:
            async def execute(self, action, run, emit):
                del action, run, emit
                await asyncio.sleep(0.05)

        actions = ActionRegistry()
        actions.register(HangingHandler(), item_id="test.action")
        definition = WorkflowDefinition(
            "test.timeout", "1", "one",
            (
                StateNode(
                    "one",
                    ActionSpec("one", "test.action", timeout_seconds=0.01),
                    decision_options=(Option("abort", "abort", "Abort", requires_reason=True),),
                ),
            ),
        )
        runtime = WorkflowRuntime(actions=actions)
        result = await runtime.tick(runtime.start(definition, device_id="d1").id)
        assert result.status == "waiting_decision"
        assert result.decision_point is not None
        assert result.decision_point.reason_code == "action_timeout"

    asyncio.run(scenario())


def test_runtime_enforces_individual_expectation_deadline_while_action_runs() -> None:
    async def scenario() -> None:
        class SlowHandler:
            async def execute(self, action, run, emit):
                del action, run, emit
                await asyncio.sleep(0.05)
                return ActionResult(ActionStatus.SUCCEEDED)

        actions = ActionRegistry()
        actions.register(SlowHandler(), item_id="test.action")
        definition = WorkflowDefinition(
            "test.expectation-timeout", "1", "one",
            (
                StateNode(
                    "one",
                    ActionSpec("one", "test.action", timeout_seconds=1, expectations=(Expectation("sent", timeout_seconds=0.01),)),
                    decision_options=(Option("abort", "abort", "Abort"),),
                ),
            ),
        )
        runtime = WorkflowRuntime(actions=actions)
        result = await runtime.tick(runtime.start(definition, device_id="d1").id)

        assert result.status == "waiting_decision"
        assert result.decision_point is not None
        assert result.decision_point.reason_code == "expectation_timeout"

    asyncio.run(scenario())


def test_supervisor_ignores_deadline_for_an_already_observed_expectation() -> None:
    async def scenario() -> None:
        class MilestoneHandler:
            async def execute(self, action, run, emit):
                del action, run
                emit(Event("sent", "", progress=True))
                await asyncio.sleep(0.03)
                emit(Event("completed", "", progress=True))
                return ActionResult(ActionStatus.SUCCEEDED)

        actions = ActionRegistry()
        actions.register(MilestoneHandler(), item_id="test.action")
        definition = WorkflowDefinition(
            "test.expectation-satisfied", "1", "one",
            (
                StateNode(
                    "one",
                    ActionSpec(
                        "one",
                        "test.action",
                        timeout_seconds=1,
                        expectations=(Expectation("sent", timeout_seconds=0.01), Expectation("completed", timeout_seconds=0.1)),
                    ),
                    next_state="done",
                ),
                StateNode("done", terminal=True),
            ),
        )
        runtime = WorkflowRuntime(actions=actions)
        result = await runtime.tick(runtime.start(definition, device_id="d1").id)
        assert result.status == "succeeded"

    asyncio.run(scenario())


def test_action_facts_and_progress_are_both_checkpointed() -> None:
    async def scenario() -> None:
        class ProgressHandler:
            async def execute(self, action, run, emit):
                del action, run
                emit(Event("ready", "", progress=True))
                return ActionResult(ActionStatus.SUCCEEDED, facts={"startup": {"current_system": "old.cc"}})

        actions = ActionRegistry()
        actions.register(ProgressHandler(), item_id="test.action")
        definition = WorkflowDefinition(
            "test.facts-progress", "1", "one",
            (
                StateNode(
                    "one",
                    ActionSpec("one", "test.action", expectations=(Expectation("ready"),)),
                    next_state="done",
                ),
                StateNode("done", terminal=True),
            ),
        )
        runtime = WorkflowRuntime(actions=actions)
        run = runtime.start(definition, device_id="d1")
        result = await runtime.tick(run.id)

        assert result.status == "succeeded"
        assert result.context["action.one.facts"]["startup"]["current_system"] == "old.cc"
        assert result.progress.last_event_type == "ready"
        assert result.progress.last_progress_at

    asyncio.run(scenario())


def test_interrupted_action_reconciles_before_it_can_be_reexecuted() -> None:
    async def scenario() -> None:
        handler = Handler((Event("ready", "", "run-action"),))
        reconciler = Reconciler(ReconcileClassification.SUCCESS)
        actions = ActionRegistry()
        actions.register(handler, item_id="test.action")
        reconciliations = ReconcileRegistry()
        reconciliations.register(reconciler)
        definition = WorkflowDefinition(
            "test.restart", "1", "one",
            (
                StateNode(
                    "one",
                    ActionSpec("one", "test.action", expectations=(Expectation("ready"),), reconcile=ReconcilePolicy(provider="test.reconcile", probes=("read-only",))),
                    next_state="done",
                ),
                StateNode("done", terminal=True),
            ),
        )
        runtime = WorkflowRuntime(actions=actions, reconciliations=reconciliations)
        run = runtime.start(definition, device_id="d1")
        runtime.runs.save(replace(run, attempts=(ActionAttempt("attempt-1", "one", 1, status=ActionStatus.RUNNING),)))

        paused = runtime.mark_interrupted(run.id)
        assert paused.status == "paused"
        resumed = runtime.resume(run.id)
        assert resumed.status == "recovering"
        result = await runtime.tick(run.id)

        assert result.status == "succeeded"
        assert reconciler.calls == 1
        assert handler.calls == 0
        assert runtime.events.list(run.id)[-1].type == "workflow.recovery.confirmed_success"

    asyncio.run(scenario())


def test_interrupted_not_started_action_is_retried_only_after_reconcile() -> None:
    async def scenario() -> None:
        handler = Handler((Event("ready", "", "run-action"),))
        reconciler = Reconciler(ReconcileClassification.NOT_STARTED)
        actions = ActionRegistry()
        actions.register(handler, item_id="test.action")
        reconciliations = ReconcileRegistry()
        reconciliations.register(reconciler)
        definition = WorkflowDefinition(
            "test.restart-retry", "1", "one",
            (
                StateNode(
                    "one",
                    ActionSpec("one", "test.action", expectations=(Expectation("ready"),), reconcile=ReconcilePolicy(provider="test.reconcile", probes=("read-only",))),
                    next_state="done",
                ),
                StateNode("done", terminal=True),
            ),
        )
        runtime = WorkflowRuntime(actions=actions, reconciliations=reconciliations)
        run = runtime.start(definition, device_id="d1")
        runtime.mark_interrupted(run.id)
        runtime.resume(run.id)

        after_reconcile = await runtime.tick(run.id)
        assert after_reconcile.status == "running"
        assert handler.calls == 0
        result = await runtime.tick(run.id)
        assert result.status == "succeeded"
        assert handler.calls == 1

    asyncio.run(scenario())


def test_interrupted_in_progress_action_is_monitored_without_reexecution() -> None:
    async def scenario() -> None:
        class SequenceReconciler:
            id = "test.reconcile"

            def __init__(self) -> None:
                self.outcomes = [ReconcileClassification.IN_PROGRESS, ReconcileClassification.SUCCESS]
                self.calls = 0

            async def reconcile(self, action, run, reason, emit):
                del action, run, reason, emit
                outcome = self.outcomes[self.calls]
                self.calls += 1
                return ReconcileResult(outcome)

        handler = Handler((Event("ready", "", "run-action"),))
        reconciler = SequenceReconciler()
        actions = ActionRegistry()
        actions.register(handler, item_id="test.action")
        reconciliations = ReconcileRegistry()
        reconciliations.register(reconciler)
        definition = WorkflowDefinition(
            "test.restart-monitor", "1", "one",
            (
                StateNode(
                    "one",
                    ActionSpec("one", "test.action", expectations=(Expectation("ready"),), reconcile=ReconcilePolicy(provider="test.reconcile", probes=("read-only",))),
                    next_state="done",
                ),
                StateNode("done", terminal=True),
            ),
        )
        runtime = WorkflowRuntime(actions=actions, reconciliations=reconciliations, recovery_poll_seconds=0.01)
        run = runtime.start(definition, device_id="d1")
        runtime.mark_interrupted(run.id)
        runtime.resume(run.id)
        result = await runtime.run_until_blocked(run.id)

        assert result.status == "succeeded"
        assert reconciler.calls == 2
        assert handler.calls == 0

    asyncio.run(scenario())


def test_framework_runtime_uses_device_lease_without_persisting_token() -> None:
    class Lease:
        token = "secret-lease-token"

    class Leases:
        def __init__(self) -> None:
            self.acquired = []
            self.released = []

        def acquire(self, device_id, owner_id):
            self.acquired.append((device_id, owner_id))
            return Lease()

        def release(self, device_id, token):
            self.released.append((device_id, token))
            return True

    async def scenario() -> None:
        handler = Handler((Event("ready", "", "run-action"),))
        actions = ActionRegistry()
        actions.register(handler, item_id="test.action")
        leases = Leases()
        definition = WorkflowDefinition(
            "test.lease", "1", "one",
            (StateNode("one", ActionSpec("one", "test.action", expectations=(Expectation("ready"),)), next_state="done"), StateNode("done", terminal=True)),
        )
        runtime = WorkflowRuntime(actions=actions, leases=leases)
        run = runtime.start(definition, device_id="d1")
        assert "lease_token" not in run.context
        run = await runtime.tick(run.id)
        run = await runtime.tick(run.id)
        assert run.status == "succeeded"
        assert leases.released == [("d1", "secret-lease-token")]

    asyncio.run(scenario())


def test_framework_bridge_uses_command_set_for_reboot_and_transfer_profile() -> None:
    async def scenario() -> None:
        handler = DeviceExecutionActionHandler(object(), ActionRegistry())
        run = WorkflowRun("run-1", "test", "1", "device-1", context={"target": {}})

        reboot = await handler._legacy_step(ActionSpec("reboot", "device.reboot"), run)
        transfer = await handler._legacy_step(
            ActionSpec("transfer", "file.transfer", params={"source": "images/target.cc"}),
            run,
        )

        command_set = HuaweiVrpCommandSet()
        assert reboot.params["steps"] == list(command_set.reboot_plan().steps)
        assert transfer.params["interaction_profile"] == asdict(command_set.transfer_profile("ftp"))

    asyncio.run(scenario())


def test_framework_bridge_does_not_emit_verification_success_on_mismatch() -> None:
    class Execution:
        async def execute(self, target, step, *, context):
            del target, step, context
            return {"status": "completed", "output": "Version: old"}

    async def scenario() -> None:
        handler = DeviceExecutionActionHandler(Execution(), ActionRegistry())
        action = ActionSpec(
            "verify_version",
            "device.verify",
            params={"fact": "running_version", "expected": "V8"},
        )
        run = WorkflowRun("run-1", "test", "1", "device-1", context={"target": {}})
        emitted: list[Event] = []

        result = await handler.execute(action, run, emitted.append)

        assert result.status == ActionStatus.FAILED
        assert "huawei.version.match" not in {event.type for event in emitted}

    asyncio.run(scenario())


def test_reboot_reconcile_requires_execution_evidence_before_retrying() -> None:
    async def scenario() -> None:
        provider = DeviceReconcileProvider("huawei.reconcile.reboot", object(), object())
        action = ActionSpec("reboot", "device.reboot")

        not_started = WorkflowRun(
            "run-1", "test", "1", "device-1",
            context={"action.reboot.facts": {"reboot": {"command_sent": False}}},
        )
        result = await provider.reconcile(action, not_started, "timeout", lambda event: event)
        assert result.classification == ReconcileClassification.NOT_STARTED

        disconnected = WorkflowRun(
            "run-2", "test", "1", "device-1",
            context={"action.reboot.facts": {"reboot": {"command_sent": True, "disconnect_observed": True}}},
        )
        result = await provider.reconcile(action, disconnected, "timeout", lambda event: event)
        assert result.classification == ReconcileClassification.SUCCESS

        ambiguous = WorkflowRun(
            "run-3", "test", "1", "device-1",
            context={"action.reboot.facts": {"reboot": {"command_sent": True, "disconnect_observed": False}}},
        )
        result = await provider.reconcile(action, ambiguous, "timeout", lambda event: event)
        assert result.classification == ReconcileClassification.INDETERMINATE

    asyncio.run(scenario())
