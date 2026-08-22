"""Agent-authored workflow plans and the backend compiler.

``WorkflowPlan`` is deliberately an untrusted proposal.  It is validated and
compiled into a ``WorkflowDefinition`` before it can become a Task.  Keeping
the two contracts separate prevents an Agent from smuggling engine details or
an arbitrary backend method through the MCP boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Protocol

from .protocol import Action, ProtocolModel, WorkflowDefinition, WorkflowStep


class PlanValidationError(ValueError):
    """A plan cannot be accepted by the backend policy."""

    def __init__(self, code: str, message: str, *, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PlanStep(ProtocolModel):
    id: str
    capability: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    retry_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PlanStep":
        return cls(
            id=str(payload.get("id") or ""),
            capability=str(payload.get("capability") or ""),
            params=dict(payload.get("params") or {}),
            depends_on=tuple(str(item) for item in payload.get("depends_on", ()) if str(item)),
            retry_policy=dict(payload.get("retry_policy") or payload.get("retry") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class WorkflowPlan(ProtocolModel):
    plan_id: str
    objective: str
    target: dict[str, str]
    steps: tuple[PlanStep, ...]
    success_criteria: tuple[dict[str, Any], ...] = ()
    budget: dict[str, Any] = field(default_factory=dict)
    parent_task_id: str = ""
    revision: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowPlan":
        raw_steps = payload.get("steps", ())
        return cls(
            plan_id=str(payload.get("plan_id") or payload.get("id") or ""),
            objective=str(payload.get("objective") or ""),
            target={str(k): str(v) for k, v in dict(payload.get("target") or {}).items()},
            steps=tuple(PlanStep.from_dict(item) for item in raw_steps if isinstance(item, Mapping)),
            success_criteria=tuple(dict(item) for item in payload.get("success_criteria", ()) if isinstance(item, Mapping)),
            budget=dict(payload.get("budget") or {}),
            parent_task_id=str(payload.get("parent_task_id") or ""),
            revision=max(1, int(payload.get("revision") or 1)),
            metadata=dict(payload.get("metadata") or {}),
        )

    def content_hash(self) -> str:
        body = self.to_dict()
        body.pop("plan_id", None)
        return "sha256:" + hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class PlanValidationResult(ProtocolModel):
    status: str
    plan: WorkflowPlan
    plan_hash: str
    workflow: WorkflowDefinition | None = None
    errors: tuple[dict[str, str], ...] = ()
    warnings: tuple[str, ...] = ()
    required_actions: tuple[Action, ...] = ()


class PlanStore(Protocol):
    def list_plans(self, *, limit: int = 500) -> list[dict[str, Any]]: ...
    def upsert_plan(self, payload: dict[str, Any]) -> None: ...


class MemoryPlanStore:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def list_plans(self, *, limit: int = 500) -> list[dict[str, Any]]:
        count = max(0, limit)
        if count == 0:
            return []
        return list(self._items.values())[-count:][::-1]

    def upsert_plan(self, payload: dict[str, Any]) -> None:
        plan_id = str(payload.get("plan_id") or "")
        if plan_id:
            self._items[plan_id] = dict(payload)


class WorkflowPlanCompiler:
    """Validate Agent plans and compile allow-listed capabilities."""

    MAX_STEPS = 50
    MAX_REPLANS = 3
    CAPABILITIES = {
        "session.open": ("wait_online", "device"),
        "device.wait_online": ("wait_online", "device"),
        "terminal.command": ("command", "device"),
        "terminal.batch": ("batch", "device"),
        "device.reboot": ("reboot", "device"),
        "file.upload": ("upload", "device"),
    }

    def validate(self, plan: WorkflowPlan) -> PlanValidationResult:
        errors: list[dict[str, str]] = []
        warnings: list[str] = []
        required: list[Action] = []
        if not plan.objective.strip():
            errors.append({"code": "objective_required", "path": "objective", "message": "objective is required"})
        if not str(plan.target.get("device_id") or "").strip():
            errors.append({"code": "device_required", "path": "target.device_id", "message": "target.device_id is required"})
        if not plan.steps:
            errors.append({"code": "steps_required", "path": "steps", "message": "at least one step is required"})
        if len(plan.steps) > min(self.MAX_STEPS, max(1, int(plan.budget.get("max_steps", self.MAX_STEPS) or self.MAX_STEPS))):
            errors.append({"code": "too_many_steps", "path": "steps", "message": f"at most {self.MAX_STEPS} steps are allowed"})
        ids: set[str] = set()
        for step in plan.steps:
            if not step.id.strip():
                errors.append({"code": "step_id_required", "path": "steps", "message": "every step requires an id"})
            elif step.id in ids:
                errors.append({"code": "duplicate_step", "path": f"steps.{step.id}", "message": "step id must be unique"})
            ids.add(step.id)
            if step.capability not in self.CAPABILITIES:
                errors.append({"code": "capability_not_allowed", "path": f"steps.{step.id}.capability", "message": f"unsupported capability: {step.capability}"})
            for dependency in step.depends_on:
                if dependency not in {item.id for item in plan.steps}:
                    errors.append({"code": "unknown_dependency", "path": f"steps.{step.id}.depends_on", "message": f"unknown dependency: {dependency}"})
            retry_max = int(step.retry_policy.get("max_attempts", step.retry_policy.get("max", 1)) or 1)
            if retry_max < 1 or retry_max > 5:
                errors.append({"code": "retry_budget_exceeded", "path": f"steps.{step.id}.retry_policy", "message": "retry attempts must be between 1 and 5"})
            command = self._command(step)
            risk = _step_risk(step)
            confirmation = risk >= _risk_medium() or step.capability == "device.reboot"
            if confirmation:
                required.append(Action(name=self.CAPABILITIES.get(step.capability, (step.capability, ""))[0], risk=risk.name.lower(), confirmation_required=True, target_step=step.id))
                warnings.append(f"step {step.id} requires confirmation ({risk.name.lower()})")
        if not self._acyclic(plan.steps):
            errors.append({"code": "workflow_cycle", "path": "steps", "message": "workflow dependencies contain a cycle"})
        max_replans = int(plan.budget.get("max_replans", 0) or 0)
        if max_replans > self.MAX_REPLANS:
            errors.append({"code": "replan_budget_exceeded", "path": "budget.max_replans", "message": f"max_replans cannot exceed {self.MAX_REPLANS}"})
        if errors:
            return PlanValidationResult("rejected", plan, plan.content_hash(), errors=tuple(errors), warnings=tuple(warnings), required_actions=tuple(required))
        workflow = self.compile(plan)
        status = "requires_confirmation" if required else "validated"
        return PlanValidationResult(status, plan, plan.content_hash(), workflow=workflow, warnings=tuple(warnings), required_actions=tuple(required))

    def compile(self, plan: WorkflowPlan) -> WorkflowDefinition:
        steps: list[WorkflowStep] = []
        for item in plan.steps:
            action_name, kind = self.CAPABILITIES[item.capability]
            params = dict(item.params)
            if item.capability == "terminal.command":
                params = {**params, "command": str(params.get("command") or "")}
            if item.capability == "terminal.batch":
                params = {**params, "commands": list(params.get("commands") or [])}
            command = self._command(item)
            risk = _step_risk(item)
            action = Action(
                name=action_name,
                parameters=dict(params),
                target_step=item.id,
                risk=risk.name.lower(),
                confirmation_required=risk >= _risk_medium() or item.capability == "device.reboot",
            )
            steps.append(WorkflowStep(item.id, kind=kind, action=action, depends_on=item.depends_on, params=params, retry_policy=dict(item.retry_policy), metadata={**item.metadata, "capability": item.capability}))
        return WorkflowDefinition(
            id=plan.plan_id or "agent-plan",
            version=str(plan.revision),
            name=plan.objective[:120],
            description=plan.objective,
            steps=tuple(steps),
            max_steps=self.MAX_STEPS,
            metadata={"plan_hash": plan.content_hash(), "plan_id": plan.plan_id, "parent_task_id": plan.parent_task_id, "success_criteria": list(plan.success_criteria), "budget": dict(plan.budget)},
        )

    @staticmethod
    def _command(step: PlanStep) -> str:
        if step.capability == "terminal.command":
            return str(step.params.get("command") or "")
        if step.capability == "terminal.batch":
            return "\n".join(str(item) for item in step.params.get("commands", ()) if str(item).strip())
        if step.capability == "device.reboot":
            return "reboot"
        return ""

    @staticmethod
    def _acyclic(steps: tuple[PlanStep, ...]) -> bool:
        graph = {step.id: set(step.depends_on) for step in steps}
        while graph:
            ready = {node for node, deps in graph.items() if not deps or not deps & graph.keys()}
            if not ready:
                return False
            for node in ready:
                graph.pop(node, None)
        return True


def _classify(command: str) -> Any:
    """Import AI risk policy lazily to avoid the application package cycle."""
    from device_tui.application.ai.operations import RiskLevel, classify_command_risk
    if not command:
        return RiskLevel.LOW
    return classify_command_risk(command)


def _risk_high() -> Any:
    from device_tui.application.ai.operations import RiskLevel
    return RiskLevel.HIGH


def _risk_medium() -> Any:
    from device_tui.application.ai.operations import RiskLevel
    return RiskLevel.MEDIUM


def _step_risk(step: PlanStep) -> Any:
    from device_tui.application.ai.operations import RiskLevel
    if step.capability == "file.upload":
        return RiskLevel.MEDIUM
    return _classify(WorkflowPlanCompiler._command(step))
