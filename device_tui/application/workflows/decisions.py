"""Single decision boundary for rules, agents, and humans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .models import DecisionPoint, Option, WorkflowRun


class DecisionValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DecisionSubmission:
    decision_point_id: str
    expected_revision: int
    option_id: str
    actor_type: str
    actor_id: str
    inputs: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    idempotency_key: str = ""

class DecisionEngine:
    """Validates a constrained option; it never accepts an arbitrary command."""

    def validate(self, run: WorkflowRun, submission: DecisionSubmission) -> Option:
        point = run.decision_point
        if point is None or point.id != submission.decision_point_id:
            raise DecisionValidationError("decision point is not pending")
        if submission.expected_revision != run.revision:
            raise DecisionValidationError("decision revision is stale")
        option = next((item for item in point.options if item.id == submission.option_id), None)
        if option is None:
            raise DecisionValidationError("option is not available")
        if submission.actor_type not in option.allowed_actors:
            raise DecisionValidationError("actor is not allowed for this option")
        if option.requires_reason and not submission.reason.strip():
            raise DecisionValidationError("reason is required for this option")
        self._validate_inputs(option, submission.inputs or {})
        return option

    @staticmethod
    def _validate_inputs(option: Option, inputs: Mapping[str, Any]) -> None:
        schema = option.input_schema
        allowed = set(schema.get("properties", {}))
        unknown = set(inputs) - allowed
        if unknown:
            raise DecisionValidationError(f"unsupported decision inputs: {', '.join(sorted(unknown))}")
        for name in schema.get("required", ()):
            if name not in inputs:
                raise DecisionValidationError(f"decision input is required: {name}")
        for name, definition in schema.get("properties", {}).items():
            if name not in inputs:
                continue
            if "enum" in definition and inputs[name] not in definition["enum"]:
                raise DecisionValidationError(f"invalid value for decision input: {name}")
