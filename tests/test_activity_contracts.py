from __future__ import annotations

import pytest

from device_tui.application.workflows import (
    ActivityDefinition,
    ActivityInvocation,
    ActivityRegistry,
    ActivityResult,
    ActivityStatus,
    ExchangeSpec,
    GuardSpec,
    IdempotencyPolicy,
    MonitorSpec,
    VerificationSpec,
)


def test_activity_contract_models_stages_for_ftp_transfer() -> None:
    definition = ActivityDefinition(
        id="file.transfer",
        preconditions=(GuardSpec(
            id="cli_view",
            probe="session.inspect",
            predicate={"cli_view": "user"},
            on_failure="prepare",
            preparation_activity="session.enter_user_view",
        ),),
        exchanges=(
            ExchangeSpec(
                id="login",
                send="ftp ${host}",
                accepted_signals=("ftp_prompt",),
                failure_signals=("authentication_failed",),
            ),
        ),
        monitor=MonitorSpec(
            id="transfer",
            progress_signals=("transfer.progress",),
            completion_signals=("transfer.completed",),
            failure_signals=("transfer.failed",),
            idle_timeout_seconds=90,
        ),
        verification=VerificationSpec(
            id="target_file",
            verifier="file.exists_and_matches",
            input_mapping={"path": "${inputs.destination_path}"},
        ),
        idempotency=IdempotencyPolicy.CONDITIONAL,
    )

    definition.validate()
    assert definition.preconditions[0].preparation_activity == "session.enter_user_view"
    assert definition.monitor is not None
    assert definition.verification is not None


def test_activity_result_keeps_unknown_separate_from_failure() -> None:
    result = ActivityResult(
        status=ActivityStatus.UNKNOWN,
        operation_id="transfer-1",
        evidence=({"reason": "connection_lost"},),
    )

    assert result.status == ActivityStatus.UNKNOWN
    assert result.status != ActivityStatus.FAILED


def test_activity_registry_validates_versioned_definitions_and_resolves_handlers() -> None:
    registry = ActivityRegistry()
    definition = ActivityDefinition(id="script.run")
    registry.register_definition(definition)

    class Handler:
        activity_id = "script.run"

    registry.register_handler(Handler())

    assert registry.resolve_definition("script.run").id == "script.run"
    assert registry.resolve_handler("script.run").activity_id == "script.run"


def test_guard_and_exchange_reject_incomplete_contracts() -> None:
    with pytest.raises(ValueError):
        GuardSpec(id="", probe="session.inspect")
    with pytest.raises(ValueError):
        ExchangeSpec(id="login")


def test_invocation_requires_stable_ids() -> None:
    with pytest.raises(ValueError):
        ActivityInvocation(activity_id="script.run", invocation_id="", workflow_run_id="run-1")
