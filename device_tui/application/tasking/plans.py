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
from .catalog import WorkflowCatalog, WorkflowCatalogError, WorkflowTarget, build_default_workflow_catalog
from device_tui.framework.orchestrator import TaskPlan, WorkflowNode


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
    # Framework-native executable plan. ``workflow`` remains populated for
    # clients that still consume the legacy TaskRecord shape.
    task_plan: TaskPlan | None = None
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


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    action: str
    kind: str = "device"
    required_params: tuple[str, ...] = ()
    param_types: dict[str, tuple[type, ...]] = field(default_factory=dict)
    description: str = ""
    workflow_id: str = ""
    risk: str = ""
    confirmation_required: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "kind": self.kind,
            "required_params": list(self.required_params),
            "param_types": {
                name: [item.__name__ for item in accepted]
                for name, accepted in self.param_types.items()
            },
            "description": self.description,
            "workflow_id": self.workflow_id,
            "risk": self.risk,
            "confirmation_required": self.confirmation_required,
        }


class CapabilityRegistry:
    """Allow-listed capabilities available to Agent-authored plans."""

    def __init__(self, specs: Mapping[str, CapabilitySpec] | None = None) -> None:
        self._specs = dict(specs or {})

    def register(self, name: str, spec: CapabilitySpec) -> None:
        normalized = name.strip()
        if not normalized or normalized in self._specs:
            raise ValueError(f"capability already registered: {name}")
        self._specs[normalized] = spec

    def contains(self, name: str) -> bool:
        return name in self._specs

    def get(self, name: str) -> CapabilitySpec:
        return self._specs[name]

    def action_map(self) -> dict[str, tuple[str, str]]:
        return {name: (spec.action, spec.kind) for name, spec in self._specs.items()}

    def public_specs(self) -> dict[str, dict[str, Any]]:
        return {name: spec.public_dict() for name, spec in self._specs.items()}


DEFAULT_CAPABILITY_SPECS = {
    "session.open": CapabilitySpec("wait_online", description="Open or reuse a device session."),
    "device.wait_online": CapabilitySpec("wait_online", description="Wait until the device session is online."),
    "device.version_check": CapabilitySpec("verify_version", description="Run a version query and optionally verify expected_version."),
    "terminal.command": CapabilitySpec("command", required_params=("command",), param_types={"command": (str,)}, description="Run one allow-listed terminal command."),
    "terminal.batch": CapabilitySpec("batch", required_params=("commands",), param_types={"commands": (list, tuple)}, description="Run an ordered terminal command batch."),
    "device.reboot": CapabilitySpec("reboot", description="Reboot the device after confirmation.", risk="high", confirmation_required=True),
    "device.power_off": CapabilitySpec("power_off", description="Power off the device after confirmation.", risk="high", confirmation_required=True),
    "file.upload": CapabilitySpec("upload", required_params=("source_path", "destination_path"), param_types={"source_path": (str,), "destination_path": (str,)}, description="Upload a file through the managed transfer service.", risk="medium", confirmation_required=True),
    "file.download": CapabilitySpec("download", required_params=("source_path", "destination_path"), param_types={"source_path": (str,), "destination_path": (str,)}, description="Download a file through the managed transfer service."),
    "device.upgrade": CapabilitySpec("device_upgrade", required_params=("package_path",), param_types={"package_path": (str,)}, description="Compile the canonical driver-backed device upgrade workflow.", workflow_id="device_upgrade", risk="high", confirmation_required=True),
    "operation.wait": CapabilitySpec("operation_wait", required_params=("operation_id",), param_types={"operation_id": (str,)}, description="Wait for a registered operation and capture its evidence."),
}


class WorkflowPlanCompiler:
    """Validate Agent plans and compile allow-listed capabilities."""

    MAX_STEPS = 50
    MAX_REPLANS = 3
    CAPABILITY_SPECS = DEFAULT_CAPABILITY_SPECS
    CAPABILITIES = {name: (spec.action, spec.kind) for name, spec in CAPABILITY_SPECS.items()}

    def __init__(
        self,
        catalog: WorkflowCatalog | None = None,
        capabilities: CapabilityRegistry | None = None,
    ) -> None:
        self._catalog = catalog or build_default_workflow_catalog()
        self._capabilities = capabilities or CapabilityRegistry(self.CAPABILITY_SPECS)
        for descriptor in self._catalog.list():
            if not descriptor.capability or self._capabilities.contains(descriptor.capability):
                continue
            parameter_types = {
                parameter.name: {
                    "string": (str,),
                    "integer": (int,),
                    "boolean": (bool,),
                    "array": (list, tuple),
                }.get(parameter.type, (object,))
                for parameter in descriptor.parameters
            }
            self._capabilities.register(
                descriptor.capability,
                CapabilitySpec(
                    descriptor.capability_action or descriptor.id,
                    required_params=tuple(item.name for item in descriptor.parameters if item.required),
                    param_types=parameter_types,
                    description=descriptor.description,
                    workflow_id=descriptor.id,
                    risk=descriptor.risk,
                    confirmation_required=descriptor.confirmation_required,
                ),
            )

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
            if not self._capabilities.contains(step.capability):
                errors.append({"code": "capability_not_allowed", "path": f"steps.{step.id}.capability", "message": f"unsupported capability: {step.capability}"})
            else:
                errors.extend(self._validate_params(step))
            for dependency in step.depends_on:
                if dependency not in {item.id for item in plan.steps}:
                    errors.append({"code": "unknown_dependency", "path": f"steps.{step.id}.depends_on", "message": f"unknown dependency: {dependency}"})
            retry_max = int(step.retry_policy.get("max_attempts", step.retry_policy.get("max", 1)) or 1)
            if retry_max < 1 or retry_max > 5:
                errors.append({"code": "retry_budget_exceeded", "path": f"steps.{step.id}.retry_policy", "message": "retry attempts must be between 1 and 5"})
            command = self._command(step)
            risk = self._step_risk(step)
            spec = self._capabilities.get(step.capability) if self._capabilities.contains(step.capability) else None
            if spec is not None and spec.workflow_id == "device_upgrade":
                errors.append({
                    "code": "workflow_task_only",
                    "path": f"steps.{step.id}.capability",
                    "message": "device.upgrade must be started as a named Workflow Task, not embedded in an Agent plan.",
                })
                continue
            confirmation = bool(spec and spec.confirmation_required) or risk >= _risk_medium()
            if confirmation:
                required.append(Action(name=spec.action if spec else step.capability, risk=risk.name.lower(), confirmation_required=True, target_step=step.id))
                warnings.append(f"step {step.id} requires confirmation ({risk.name.lower()})")
        if not self._acyclic(plan.steps):
            errors.append({"code": "workflow_cycle", "path": "steps", "message": "workflow dependencies contain a cycle"})
        max_replans = int(plan.budget.get("max_replans", 0) or 0)
        if max_replans > self.MAX_REPLANS:
            errors.append({"code": "replan_budget_exceeded", "path": "budget.max_replans", "message": f"max_replans cannot exceed {self.MAX_REPLANS}"})
        if errors:
            return PlanValidationResult("rejected", plan, plan.content_hash(), errors=tuple(errors), warnings=tuple(warnings), required_actions=tuple(required))
        workflow = self.compile(plan)
        task_plan = self.compile_task_plan(plan)
        status = "requires_confirmation" if required else "validated"
        return PlanValidationResult(status, plan, plan.content_hash(), workflow=workflow, task_plan=task_plan, warnings=tuple(warnings), required_actions=tuple(required))

    def compile(self, plan: WorkflowPlan) -> WorkflowDefinition:
        steps: list[WorkflowStep] = []
        named_workflows: dict[str, WorkflowDefinition] = {}
        dependency_tails: dict[str, tuple[str, ...]] = {}
        for item in plan.steps:
            spec = self._capabilities.get(item.capability)
            if spec.workflow_id:
                workflow = self._catalog.build(
                    spec.workflow_id,
                    WorkflowTarget(
                        device_id=str(plan.target.get("device_id") or ""),
                        session_id=str(plan.target.get("session_id") or ""),
                        protocol=str(plan.target.get("protocol") or "auto"),
                    ),
                    item.params,
                )
                named_workflows[item.id] = workflow
                dependency_tails[item.id] = tuple(
                    f"{item.id}.{step_id}" for step_id in self._terminal_step_ids(workflow)
                )
            else:
                dependency_tails[item.id] = (item.id,)
        for item in plan.steps:
            dependencies = tuple(
                tail
                for dependency in item.depends_on
                for tail in dependency_tails.get(dependency, (dependency,))
            )
            if item.id in named_workflows:
                steps.extend(self._compile_named_workflow(item, named_workflows[item.id], dependencies))
                continue
            spec = self._capabilities.get(item.capability)
            action_name, kind = spec.action, spec.kind
            params = dict(item.params)
            if item.capability == "terminal.command":
                params = {**params, "command": str(params.get("command") or "")}
            if item.capability == "terminal.batch":
                params = {**params, "commands": list(params.get("commands") or [])}
            command = self._command(item)
            risk = self._step_risk(item)
            action = Action(
                name=action_name,
                parameters=dict(params),
                target_step=item.id,
                risk=risk.name.lower(),
                confirmation_required=spec.confirmation_required or risk >= _risk_medium(),
            )
            steps.append(WorkflowStep(item.id, kind=kind, action=action, depends_on=dependencies, params=params, retry_policy=dict(item.retry_policy), metadata={**item.metadata, "capability": item.capability}))
        return WorkflowDefinition(
            id=plan.plan_id or "agent-plan",
            version=str(plan.revision),
            name=plan.objective[:120],
            description=plan.objective,
            steps=tuple(steps),
            max_steps=self.MAX_STEPS,
            metadata={"plan_hash": plan.content_hash(), "plan_id": plan.plan_id, "parent_task_id": plan.parent_task_id, "success_criteria": list(plan.success_criteria), "budget": dict(plan.budget)},
        )

    def compile_task_plan(self, plan: WorkflowPlan) -> TaskPlan:
        """Compile an allow-listed proposal into the Framework Task boundary."""
        nodes: list[WorkflowNode] = []
        for item in plan.steps:
            spec = self._capabilities.get(item.capability)
            if spec.workflow_id == "device_upgrade":
                raise PlanValidationError(
                    "workflow_task_only",
                    "device.upgrade must be started as a named Workflow Task.",
                    path=f"steps.{item.id}.capability",
                )
            workflow_id = self._framework_workflow_id(item.capability, spec)
            params = dict(item.params)
            if item.capability in {"file.upload", "file.download"}:
                params["direction"] = "upload" if item.capability == "file.upload" else "download"
            if item.capability == "terminal.command":
                params["command"] = str(params.get("command") or "")
            if item.capability == "terminal.batch":
                params["commands"] = list(params.get("commands") or [])
            nodes.append(WorkflowNode(
                id=item.id,
                workflow_id=workflow_id,
                depends_on=tuple(item.depends_on),
                input_mapping=params,
            ))
        task_plan = TaskPlan(
            id=plan.plan_id or "agent-plan",
            version=str(plan.revision),
            nodes=tuple(nodes),
        )
        task_plan.validate()
        return task_plan

    @staticmethod
    def _framework_workflow_id(capability: str, spec: CapabilitySpec) -> str:
        if spec.workflow_id and spec.workflow_id != "device_upgrade":
            return spec.workflow_id
        return {
            "session.open": "device.wait_online",
            "device.wait_online": "device.wait_online",
            "device.version_check": "device.verify_version",
            "terminal.command": "terminal.command",
            "terminal.batch": "terminal.batch",
            "device.reboot": "device.reboot",
            "device.power_off": "device.power_off",
            "file.upload": "file.transfer",
            "file.download": "file.transfer",
            "operation.wait": "operation.wait",
        }.get(capability, spec.action)

    @staticmethod
    def _compile_named_workflow(
        item: PlanStep,
        workflow: WorkflowDefinition,
        dependencies: tuple[str, ...],
    ) -> tuple[WorkflowStep, ...]:
        compiled: list[WorkflowStep] = []
        for step in workflow.steps:
            step_id = f"{item.id}.{step.id}"
            internal_dependencies = tuple(f"{item.id}.{dep}" for dep in step.depends_on)
            compiled.append(WorkflowStep(
                id=step_id,
                kind=step.kind,
                action=step.action,
                depends_on=dependencies if not step.depends_on else internal_dependencies,
                params=dict(step.params),
                retry_policy=dict(step.retry_policy),
                metadata={**item.metadata, **step.metadata, "capability": item.capability, "plan_step_id": item.id},
            ))
        return tuple(compiled)

    @staticmethod
    def _terminal_step_ids(workflow: WorkflowDefinition) -> tuple[str, ...]:
        depended_on = {dependency for step in workflow.steps for dependency in step.depends_on}
        return tuple(step.id for step in workflow.steps if step.id not in depended_on)

    @classmethod
    def capability_specs(cls) -> dict[str, dict[str, Any]]:
        return {name: spec.public_dict() for name, spec in cls.CAPABILITY_SPECS.items()}

    def registered_capability_specs(self) -> dict[str, dict[str, Any]]:
        return self._capabilities.public_specs()

    def _validate_params(self, step: PlanStep) -> list[dict[str, str]]:
        spec = self._capabilities.get(step.capability)
        errors: list[dict[str, str]] = []
        for name in spec.required_params:
            value = step.params.get(name)
            missing = value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, tuple)) and not value)
            if missing:
                errors.append({"code": "parameter_required", "path": f"steps.{step.id}.params.{name}", "message": f"{name} is required for {step.capability}"})
        for name, accepted in spec.param_types.items():
            value = step.params.get(name)
            if value is not None and not isinstance(value, accepted):
                expected = " or ".join(item.__name__ for item in accepted)
                errors.append({"code": "parameter_type_invalid", "path": f"steps.{step.id}.params.{name}", "message": f"{name} must be {expected}"})
        if step.capability == "terminal.batch":
            commands = step.params.get("commands")
            if isinstance(commands, (list, tuple)) and any(not isinstance(item, str) or not item.strip() for item in commands):
                errors.append({"code": "parameter_value_invalid", "path": f"steps.{step.id}.params.commands", "message": "commands must contain non-empty strings"})
        if spec.workflow_id:
            try:
                self._catalog.normalize_parameters(spec.workflow_id, step.params)
            except WorkflowCatalogError as exc:
                errors.append({"code": "parameter_value_invalid", "path": f"steps.{step.id}.params", "message": str(exc)})
        return errors

    def _step_risk(self, step: PlanStep) -> Any:
        if not self._capabilities.contains(step.capability):
            return _classify(self._command(step))
        spec = self._capabilities.get(step.capability)
        if spec.risk == "high":
            return _risk_high()
        if spec.risk == "medium":
            return _risk_medium()
        return _classify(self._command(step))

    @staticmethod
    def _command(step: PlanStep) -> str:
        if step.capability == "terminal.command":
            return str(step.params.get("command") or "")
        if step.capability == "terminal.batch":
            return "\n".join(str(item) for item in step.params.get("commands", ()) if str(item).strip())
        if step.capability == "device.reboot":
            return "reboot"
        if step.capability == "device.power_off":
            return "power_off"
        if step.capability == "device.upgrade":
            return str(step.params.get("package_path") or step.params.get("package") or "package_upgrade")
        if step.capability == "device.version_check":
            return str(step.params.get("command") or "display version")
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
