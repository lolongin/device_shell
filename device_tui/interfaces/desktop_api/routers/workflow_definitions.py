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
    validate_workflow,
)
from device_tui.application.errors import ResourceNotFoundError, UnsupportedOperationError

from ..dependencies import authorize, get_context

router = APIRouter(prefix="/api/v1/workflow-definitions", tags=["workflow-definitions"], dependencies=[Depends(authorize)])


_ACTION_WORKFLOW_IDS = {
    "device.command": "terminal.command",
    "device.reboot": "device.reboot",
    "utility.wait": "utility.wait",
    "file.upload": "file.transfer",
    "file.download": "file.transfer",
    "device.select": "device.select",
    "device.ssh": "device.wait_online",
    "device.telnet": "device.wait_online",
}


def _compile_task_plan(version: Any, device_id: str) -> TaskPlan:
    """Compile the Studio graph into allow-listed Framework activities.

    TaskPlan intentionally models dependencies only. Conditional edges and
    condition nodes need a branch-aware compiler; rejecting them here keeps a
    published graph from silently executing every branch.
    """
    if any(node.action_id == "utility.condition" for node in version.nodes):
        raise UnsupportedOperationError("utility.condition requires branch execution and is not runnable yet")
    if any(edge.condition for edge in version.edges):
        raise UnsupportedOperationError("conditional edges require branch execution and are not runnable yet")
    node_ids = {node.id for node in version.nodes}
    task_nodes: list[WorkflowNode] = []
    for node in version.nodes:
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
        params.update(node.input_mapping)
        dependencies = tuple(edge.source for edge in version.edges if edge.target == node.id)
        if any(dep not in node_ids for dep in dependencies):
            raise UnsupportedOperationError(f"node {node.id} depends on an unknown node")
        task_nodes.append(WorkflowNode(node.id, workflow_id, depends_on=dependencies, input_mapping=params))
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
    device_id = str(payload.get("device_id") or "").strip()
    if not device_id:
        raise UnsupportedOperationError("device_id is required")
    version_number = payload.get("version")
    try:
        # A test run without an explicit version executes the current draft.
        # Published runs remain immutable when the caller supplies a version.
        version = ctx.desktop.workflow_definitions.get(
            workflow_id,
            version_number if version_number is not None else "draft",
        )
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    plan = _compile_task_plan(version, device_id)
    steps = [WorkflowStep(node.id, kind="tool", action=Action(node.workflow_id, parameters=dict(node.input_mapping)), depends_on=node.depends_on, params=dict(node.input_mapping)) for node in plan.nodes]
    execution_version = str(version.version) if str(version.version).isdigit() else "0"
    workflow = TaskWorkflowDefinition(id=workflow_id, version=execution_version, name=version.name, steps=tuple(steps), metadata={"workflow_id": workflow_id, "workflow_version": str(version.version)})
    inputs = dict(payload.get("inputs") or {})
    workflow_metadata = {**workflow.metadata, "framework_inputs": inputs}
    workflow = TaskWorkflowDefinition(id=workflow.id, version=workflow.version, name=workflow.name, steps=workflow.steps, metadata=workflow_metadata)
    record = ctx.desktop.task_service.create(TaskCreate(workflow=workflow, framework_plan=plan, target=DeviceTarget(device_id=device_id, session_id=str(payload.get("session_id") or ""), protocol=str(payload.get("protocol") or "auto")), source="desktop-workflow-studio", context=inputs))
    return {"task": record.to_dict()}
