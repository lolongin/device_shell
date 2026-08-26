from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

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
from device_tui.application.workflows.device_bridge import _ftp_login_steps
from device_tui.application.workflows.device_bridge import DeviceExecutionActionHandler


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
    assert workflow.states[1].action.operation == "file.session.login"


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


def test_framework_ftp_probe_uses_managed_secret_refs_and_returns_to_device_prompt() -> None:
    steps = _ftp_login_steps({"server_host": "192.0.2.10", "server_port": 2121})
    assert steps[1]["success"] == ["ftp_prompt"]
    responses = steps[1]["responses"]
    assert {item["secret_ref"] for item in responses} == {"file_transfer.username", "file_transfer.password"}
    assert steps[-2]["text"] == "quit"
    assert steps[-1]["success"] == ["device_prompt"]


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
