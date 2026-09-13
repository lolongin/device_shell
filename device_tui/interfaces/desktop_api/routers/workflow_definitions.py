"""No-code workflow definition lifecycle endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping
from uuid import uuid4

from fastapi import APIRouter, Depends

from device_tui.application import DeviceTarget, TaskCreate
from device_tui.application.tasking.protocol import (
    Action,
    WorkflowDefinition as TaskWorkflowDefinition,
    WorkflowStep,
)
from device_tui.framework import TaskPlan, WorkflowNode
from device_tui.application.workflow_studio import (
    WorkflowDraft,
    build_action_catalog,
    evaluate_expression,
    validate_workflow,
    validate_workflow_inputs,
)
from device_tui.application.errors import ResourceNotFoundError, UnsupportedOperationError

from ..dependencies import authorize, get_context

router = APIRouter(prefix="/api/v1/workflow-definitions", tags=["workflow-definitions"], dependencies=[Depends(authorize)])


_ACTION_WORKFLOW_IDS = {
    "device.command": "terminal.command",
    "device.reboot": "device.reboot",
    "utility.wait": "utility.wait",
    "utility.confirm": "utility.confirm",
    "file.upload": "file.transfer",
    "file.download": "file.transfer",
    "device.select": "device.select",
    "device.connect": "device.wait_online",
    "device.info": "device.info",
    "result.save": "result.save",
    "device.ssh": "device.wait_online",
    "device.telnet": "device.wait_online",
    "variable.set": "variable.set",
    "expression.evaluate": "expression.evaluate",
    "loop.for_each": "loop.for_each",
}

_LOOP_DISALLOWED_ACTIONS = frozenset({"loop.for_each", "utility.condition", "utility.confirm"})
_HIGH_RISK_WORKFLOW_IDS = frozenset({"device.reboot", "file.transfer"})


def _compile_task_plan(version: Any, device_id: str) -> TaskPlan:
    """Compile the Studio graph into allow-listed Framework activities.

    Condition nodes are compile-time control flow. Their visual rules are
    attached to branch nodes as ``run_if`` metadata, so the generic task
    orchestrator can skip the inactive branch without executing both sides.
    """
    node_ids = {node.id for node in version.nodes}
    condition_nodes = {node.id: node for node in version.nodes if node.action_id == "utility.condition"}
    condition_specs: dict[str, dict[str, Any]] = {}
    condition_dependencies: dict[str, tuple[str, ...]] = {}
    for condition_id, condition in condition_nodes.items():
        rules = condition.config.get("rules")
        expression = str(condition.config.get("expression") or "").strip()
        if (not isinstance(rules, (list, tuple)) or not any(isinstance(rule, Mapping) for rule in rules)) and not expression:
            raise UnsupportedOperationError("visual rules are required for condition branches")
        incoming = tuple(
            edge.source
            for edge in version.edges
            if edge.target == condition_id and edge.source not in condition_nodes
        )
        if any(source not in node_ids for source in incoming):
            raise UnsupportedOperationError(f"condition {condition_id} depends on an unknown node")
        condition_dependencies[condition_id] = incoming
        outgoing = [edge for edge in version.edges if edge.source == condition_id]
        if not outgoing:
            raise UnsupportedOperationError("visual rules or condition branches are required")
        condition_specs[condition_id] = {
            "rules": [dict(rule) for rule in (rules or ()) if isinstance(rule, Mapping)],
            "logical_operator": str(condition.config.get("logical_operator") or "AND"),
            "values_from": incoming[0] if len(incoming) == 1 else "",
        }
        if expression:
            condition_specs[condition_id]["expression"] = expression

    def branch_value(edge: Any) -> bool:
        raw = str(edge.condition or edge.source_handle or "").strip().casefold()
        if raw in {"true", "then", "yes", "1", "真", "是"}:
            return True
        if raw in {"false", "else", "no", "0", "假", "否"}:
            return False
        raise UnsupportedOperationError(
            f"condition edge {edge.source}->{edge.target} must identify a true or false branch"
        )

    direct_contexts: dict[str, list[dict[str, Any]]] = {}
    for edge in version.edges:
        if edge.source in condition_specs:
            context = dict(condition_specs[edge.source])
            context["expected"] = branch_value(edge)
            direct_contexts.setdefault(edge.target, []).append(context)

    incoming_regular: dict[str, tuple[str, ...]] = {
        node.id: tuple(
            edge.source
            for edge in version.edges
            if edge.target == node.id and edge.source not in condition_nodes
        )
        for node in version.nodes
        if node.id not in condition_nodes
    }

    def context_for(node_id: str, stack: set[str] | None = None) -> dict[str, Any] | None:
        stack = set(stack or ())
        if node_id in stack:
            raise UnsupportedOperationError("workflow contains a dependency cycle")
        candidates = list(direct_contexts.get(node_id, ()))
        stack.add(node_id)
        for source in incoming_regular.get(node_id, ()):
            inherited = context_for(source, stack)
            if inherited is not None:
                candidates.append(inherited)
        if not candidates:
            return None
        first = candidates[0]
        if any(candidate != first for candidate in candidates[1:]):
            raise UnsupportedOperationError(f"node {node_id} merges incompatible condition branches")
        return first

    task_nodes: list[WorkflowNode] = []
    for node in version.nodes:
        if node.id in condition_nodes:
            continue
        workflow_id = _ACTION_WORKFLOW_IDS.get(node.action_id)
        if workflow_id is None:
            raise UnsupportedOperationError(f"workflow action cannot run yet: {node.action_id}")
        params = dict(node.config)
        if node.action_id in {"device.select", "device.ssh", "device.telnet"}:
            configured_device = str(params.get("device_id") or "").strip()
            if configured_device and configured_device != device_id:
                raise UnsupportedOperationError(
                    f"node {node.id} selects device {configured_device}, but task target is {device_id}"
                )
            if node.action_id == "device.ssh":
                params["recovery_protocol"] = "ssh"
            elif node.action_id == "device.telnet":
                params["recovery_protocol"] = "telnet"
            if node.action_id != "device.select":
                params.pop("device_id", None)
        elif node.action_id in {"file.upload", "file.download"}:
            params["direction"] = "upload" if node.action_id == "file.upload" else "download"
            params["source_path"] = params.pop("source_path", params.get("source", ""))
            params["destination_path"] = params.pop("destination_path", params.get("destination", ""))
        elif node.action_id == "expression.evaluate":
            params.setdefault("values", {"inputs": "${inputs}", "outputs": "${outputs}"})
        elif node.action_id == "loop.for_each":
            child_action = str(params.get("action_id") or "").strip()
            child_workflow_id = _ACTION_WORKFLOW_IDS.get(child_action)
            if child_workflow_id is None or child_action in _LOOP_DISALLOWED_ACTIONS:
                raise UnsupportedOperationError(f"loop child action cannot run yet: {child_action}")
            params["action_id"] = child_workflow_id
        params.update(node.input_mapping)
        retry_attempts = params.pop("retry_attempts", None)
        retry_backoff_seconds = params.pop("retry_backoff_seconds", None)
        retry_policy = params.pop("retry_policy", {})
        repeat_count = params.pop("repeat_count", None)
        repeat_policy = params.pop("repeat_policy", {})
        parallel_group = str(params.pop("parallel_group", "") or "").strip() or None
        if retry_attempts not in (None, ""):
            try:
                retry_policy = {**dict(retry_policy or {}), "max_attempts": max(1, min(5, int(retry_attempts)))}
            except (TypeError, ValueError) as exc:
                raise UnsupportedOperationError(f"node {node.id} retry_attempts must be a number") from exc
        if retry_backoff_seconds not in (None, ""):
            try:
                retry_policy = {**dict(retry_policy or {}), "backoff_seconds": max(0.0, min(60.0, float(retry_backoff_seconds)))}
            except (TypeError, ValueError) as exc:
                raise UnsupportedOperationError(f"node {node.id} retry_backoff_seconds must be a number") from exc
        if repeat_count not in (None, ""):
            try:
                repeat_policy = {**dict(repeat_policy or {}), "max_iterations": max(1, min(20, int(repeat_count)))}
            except (TypeError, ValueError) as exc:
                raise UnsupportedOperationError(f"node {node.id} repeat_count must be a number") from exc
        dependencies_list: list[str] = []
        for edge in version.edges:
            if edge.target != node.id:
                continue
            if edge.source in condition_dependencies:
                dependencies_list.extend(condition_dependencies[edge.source])
            else:
                dependencies_list.append(edge.source)
        dependencies = tuple(dict.fromkeys(dependencies_list))
        if any(dep not in node_ids for dep in dependencies):
            raise UnsupportedOperationError(f"node {node.id} depends on an unknown node")
        if node.action_id == "result.save" and dependencies:
            params.setdefault("value", f"${{{dependencies[-1]}}}")
        task_nodes.append(
            WorkflowNode(
                node.id,
                workflow_id,
                depends_on=dependencies,
                input_mapping=params,
                run_if=context_for(node.id),
                retry_policy=retry_policy,
                repeat_policy=repeat_policy,
                parallel_group=parallel_group,
            )
        )
    workflow_id = str(getattr(version, "workflow_id", "") or getattr(version, "id", ""))
    # Framework TaskRecord uses a numeric plan revision. Draft test runs have
    # no published version, so use revision 0 while retaining the draft
    # semantics at the API boundary.
    execution_version = str(version.version) if str(version.version).isdigit() else "0"
    plan = TaskPlan(id=f"workflow-task:{workflow_id}:{execution_version}", version=execution_version, nodes=tuple(task_nodes))
    try:
        plan.validate()
    except ValueError as exc:
        raise UnsupportedOperationError(str(exc)) from exc
    return plan


def _draft_payload(draft: WorkflowDraft) -> dict[str, Any]:
    return draft.to_dict()


def _select_plan_from_step(plan: TaskPlan, step_id: str) -> TaskPlan:
    """Keep the selected step and its prerequisites for single-step testing."""
    wanted = {step_id}
    by_id = {node.id: node for node in plan.nodes}
    pending = [step_id]
    while pending:
        current = pending.pop()
        node = by_id.get(current)
        if node is None:
            raise UnsupportedOperationError(f"unknown workflow step: {step_id}")
        for dependency in node.depends_on:
            if dependency not in wanted:
                wanted.add(dependency)
                pending.append(dependency)
    return TaskPlan(id=f"{plan.id}:step:{step_id}", version=plan.version, nodes=tuple(node for node in plan.nodes if node.id in wanted))


@router.get("")
async def list_workflow_definitions(ctx=Depends(get_context)) -> dict[str, object]:
    return {"workflows": [_draft_payload(item) for item in ctx.desktop.workflow_definitions.list()]}


@router.post("")
async def create_workflow_definition(payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    data = dict(payload)
    data["id"] = str(data.get("id") or f"workflow_{uuid4().hex[:12]}")
    draft = WorkflowDraft.from_dict(data)
    if not draft.name.strip():
        raise UnsupportedOperationError("workflow name is required")
    try:
        saved = ctx.desktop.workflow_definitions.create(draft)
    except (KeyError, ValueError) as exc:
        raise UnsupportedOperationError(str(exc)) from exc
    return {"workflow": _draft_payload(saved)}


@router.get("/actions")
async def list_workflow_actions() -> dict[str, object]:
    """Expose the allow-listed Studio actions to renderer clients."""
    return {
        "actions": [
            {
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "input_schema": item.input_schema,
                "output_schema": item.output_schema,
                "risk": item.risk,
                "executor_id": item.executor_id,
            }
            for item in build_action_catalog().list()
        ]
    }


@router.get("/{workflow_id}")
async def get_workflow_definition(workflow_id: str, ctx=Depends(get_context)) -> dict[str, object]:
    try:
        draft = ctx.desktop.workflow_definitions.get(workflow_id)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    return {"workflow": draft.to_dict()}


@router.put("/{workflow_id}")
async def save_workflow_definition(workflow_id: str, payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    data = dict(payload)
    data["id"] = workflow_id
    draft = WorkflowDraft.from_dict(data)
    try:
        saved = ctx.desktop.workflow_definitions.save(draft)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    return {"workflow": saved.to_dict()}


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow_definition(workflow_id: str, ctx=Depends(get_context)) -> None:
    try:
        ctx.desktop.workflow_definitions.delete(workflow_id)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc


@router.post("/{workflow_id}/validate")
async def validate_workflow_definition(workflow_id: str, payload: Mapping[str, Any] | None = None, ctx=Depends(get_context)) -> dict[str, object]:
    try:
        draft = WorkflowDraft.from_dict({**ctx.desktop.workflow_definitions.get(workflow_id).to_dict(), **dict(payload or {})})
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    result = validate_workflow(draft, build_action_catalog())
    return {"valid": result.valid, "errors": [asdict(item) for item in result.errors], "warnings": [asdict(item) for item in result.warnings]}


@router.post("/{workflow_id}/publish")
async def publish_workflow_definition(workflow_id: str, ctx=Depends(get_context)) -> dict[str, object]:
    try:
        draft = ctx.desktop.workflow_definitions.get(workflow_id)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    result = validate_workflow(draft, build_action_catalog())
    if not result.valid:
        return {"published": False, "valid": False, "errors": [asdict(item) for item in result.errors], "warnings": [asdict(item) for item in result.warnings]}
    version = ctx.desktop.workflow_definitions.publish(workflow_id)
    return {"published": True, "valid": True, "workflow": version.to_dict(), "warnings": [asdict(item) for item in result.warnings]}


@router.post("/{workflow_id}/run")
async def run_workflow_definition(workflow_id: str, payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    raw_devices = payload.get("device_ids")
    device_ids = [str(item).strip() for item in raw_devices if str(item).strip()] if isinstance(raw_devices, (list, tuple)) else []
    if not device_ids:
        device_id = str(payload.get("device_id") or "").strip()
        if device_id:
            device_ids = [device_id]
    if not device_ids:
        raise UnsupportedOperationError("device_id is required")
    session_ids = payload.get("session_ids")
    session_by_device = {
        str(device_id): str(session_id).strip()
        for device_id, session_id in (session_ids.items() if isinstance(session_ids, Mapping) else ())
    }
    unknown_session_devices = set(session_by_device) - set(device_ids)
    if unknown_session_devices:
        raise UnsupportedOperationError(
            "session_ids contains devices outside device_ids",
            details={"devices": sorted(unknown_session_devices)},
        )
    version_number = payload.get("version")
    try:
        if version_number is not None:
            version = ctx.desktop.workflow_definitions.get(workflow_id, version_number)
        elif bool(payload.get("draft")):
            version = ctx.desktop.workflow_definitions.get(workflow_id, "draft")
        else:
            list_versions = getattr(ctx.desktop.workflow_definitions, "list_versions", None)
            versions = list_versions(workflow_id) if callable(list_versions) else []
            if not versions:
                raise UnsupportedOperationError("a published workflow version or explicit draft run is required")
            version = versions[-1]
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    step_id = str(payload.get("step_id") or "").strip()
    supplied_inputs = dict(payload.get("inputs") or {})
    inputs = {
        item.name: item.default
        for item in getattr(version, "inputs", ())
        if item.default is not None
    }
    inputs.update(supplied_inputs)
    input_issues = validate_workflow_inputs(version, inputs)  # type: ignore[arg-type]
    if input_issues:
        raise UnsupportedOperationError("workflow inputs are invalid", details={"errors": [asdict(item) for item in input_issues]})
    plans = {device_id: _compile_task_plan(version, device_id) for device_id in device_ids}
    if step_id:
        plans = {device_id: _select_plan_from_step(plan, step_id) for device_id, plan in plans.items()}
    plan = plans[device_ids[0]]
    if bool(payload.get("dry_run")):
        return {
            "dry_run": True,
            "preview": {
                "workflow_id": workflow_id,
                "workflow_version": str(version.version),
                "step_count": len(plan.nodes),
                "target_count": len(device_ids),
                "steps": [{"id": node.id, "action": node.workflow_id, "depends_on": list(node.depends_on)} for node in plan.nodes],
                "target_devices": device_ids,
            },
        }
    has_high_risk_action = any(
        node.workflow_id in _HIGH_RISK_WORKFLOW_IDS
        or str(node.input_mapping.get("action_id") or "") in _HIGH_RISK_WORKFLOW_IDS
        for plan in plans.values()
        for node in plan.nodes
    )
    if has_high_risk_action and not bool(payload.get("confirmed_risks")):
        raise UnsupportedOperationError(
            "high-risk workflow run requires confirmation",
            details={"code": "risk_confirmation_required"},
        )
    if str(getattr(version, "version", "draft")) != "draft":
        mark_referenced = getattr(ctx.desktop.workflow_definitions, "mark_referenced", None)
        if callable(mark_referenced):
            mark_referenced(workflow_id, version.version)
    steps = [WorkflowStep(node.id, kind="tool", action=Action(node.workflow_id, parameters=dict(node.input_mapping)), depends_on=node.depends_on, params=dict(node.input_mapping), retry_policy=dict(node.retry_policy)) for node in plan.nodes]
    execution_version = str(version.version) if str(version.version).isdigit() else "0"
    workflow = TaskWorkflowDefinition(id=workflow_id, version=execution_version, name=version.name, steps=tuple(steps), metadata={"workflow_id": workflow_id, "workflow_version": str(version.version)})
    workflow_metadata = {**workflow.metadata, "framework_inputs": inputs}
    workflow = TaskWorkflowDefinition(id=workflow.id, version=workflow.version, name=workflow.name, steps=workflow.steps, metadata=workflow_metadata)
    records = [
            ctx.desktop.task_service.create(TaskCreate(workflow=workflow, framework_plan=plans[target_id], target=DeviceTarget(device_id=target_id, session_id=session_by_device.get(target_id, str(payload.get("session_id") or "")), protocol=str(payload.get("protocol") or "auto")), source="desktop-workflow-studio", context=inputs))
        for target_id in device_ids
    ]
    task_payload = records[0].to_dict()
    task_payload["context"] = dict(inputs)
    return {"task": task_payload, "tasks": [record.to_dict() for record in records], "target_count": len(records)}
