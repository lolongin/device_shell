"""Small JSON-compatible DSL compiler for framework workflows."""

from __future__ import annotations

from typing import Any, Mapping

from .models import (
    ActionSpec,
    Expectation,
    InteractionPolicy,
    Option,
    ReconcilePolicy,
    RetryPolicy,
    StateNode,
    WorkflowDefinition,
)


class WorkflowDslError(ValueError):
    pass


def compile_workflow(document: Mapping[str, Any]) -> WorkflowDefinition:
    try:
        workflow_id = str(document["id"])
        version = str(document.get("version", "1"))
        start_state = str(document["start_state"])
    except KeyError as exc:
        raise WorkflowDslError(f"missing workflow field: {exc.args[0]}") from exc
    raw_states = document.get("states")
    if not isinstance(raw_states, list):
        raise WorkflowDslError("states must be a list")
    states = tuple(_state(item, index) for index, item in enumerate(raw_states))
    definition = WorkflowDefinition(
        id=workflow_id,
        version=version,
        start_state=start_state,
        states=states,
        required_capabilities=tuple(str(item) for item in document.get("requires", ()) if str(item)),
        input_schema=dict(document.get("inputs", {})),
        metadata=dict(document.get("metadata", {})),
    )
    try:
        definition.validate()
    except ValueError as exc:
        raise WorkflowDslError(str(exc)) from exc
    return definition


def _state(raw: Any, index: int) -> StateNode:
    if not isinstance(raw, Mapping):
        raise WorkflowDslError(f"state {index} must be an object")
    state_id = str(raw.get("id", "")).strip()
    if not state_id:
        raise WorkflowDslError(f"state {index} id is required")
    action_raw = raw.get("action")
    action = _action(action_raw, state_id) if action_raw is not None else None
    options = tuple(_option(item, index) for item in raw.get("decision_options", ()))
    return StateNode(
        id=state_id,
        action=action,
        next_state=str(raw.get("next", "")),
        transitions={str(key): str(value) for key, value in dict(raw.get("on", {})).items()},
        decision_options=options,
        terminal=bool(raw.get("terminal", False)),
    )


def _action(raw: Any, state_id: str) -> ActionSpec:
    if not isinstance(raw, Mapping):
        raise WorkflowDslError(f"action for {state_id} must be an object")
    retry_raw = dict(raw.get("retry", {}))
    reconcile_raw = dict(raw.get("reconcile", {}))
    interaction_raw = dict(raw.get("interaction", {}))
    expectations = tuple(
        Expectation(
            event_type=str(item["event"]),
            timeout_seconds=float(item.get("timeout", 30)),
            idle_timeout_seconds=float(item.get("idle_timeout", 0)),
            predicate=dict(item.get("when", {})),
            progress=bool(item.get("progress", False)),
        )
        for item in raw.get("expect", ())
        if isinstance(item, Mapping) and item.get("event")
    )
    return ActionSpec(
        id=str(raw.get("id", state_id)),
        operation=str(raw.get("operation", "")),
        params=dict(raw.get("params", {})),
        expectations=expectations,
        timeout_seconds=float(raw.get("timeout", 60)),
        retry_policy=RetryPolicy(
            max_attempts=int(retry_raw.get("max_attempts", 1)),
            retryable_classes=tuple(str(item) for item in retry_raw.get("classes", ("transient", "timeout"))),
            backoff_seconds=float(retry_raw.get("backoff", 0)),
        ),
        interaction=InteractionPolicy(
            confirmations={str(key): str(value) for key, value in dict(interaction_raw.get("confirmations", {})).items()},
            secret_refs=tuple(str(item) for item in interaction_raw.get("secret_refs", ())),
        ),
        reconcile=ReconcilePolicy(
            provider=str(reconcile_raw.get("provider", "")),
            probes=tuple(str(item) for item in reconcile_raw.get("probes", ())),
            budget_seconds=float(reconcile_raw.get("budget", 60)),
            on_classification={str(key): str(value) for key, value in dict(reconcile_raw.get("on", {})).items()},
        ),
        idempotency_key=str(raw.get("idempotency", "")),
        risk=str(raw.get("risk", "normal")),
    )


def _option(raw: Any, index: int) -> Option:
    if not isinstance(raw, Mapping):
        raise WorkflowDslError(f"decision option {index} must be an object")
    return Option(
        id=str(raw.get("id", "")),
        kind=str(raw.get("kind", "")),
        label=str(raw.get("label", raw.get("id", ""))),
        description=str(raw.get("description", "")),
        risk=str(raw.get("risk", "normal")),
        allowed_actors=tuple(str(item) for item in raw.get("allowed_actors", ("human", "agent", "rule"))),
        requires_reason=bool(raw.get("requires_reason", False)),
        input_schema=dict(raw.get("input_schema", {})),
        next_state=str(raw.get("next_state", "")),
    )
