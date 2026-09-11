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
from device_tui.application.workflow_studio import (
    WorkflowDraft,
    build_action_catalog,
    validate_workflow,
)
from device_tui.application.errors import ResourceNotFoundError, UnsupportedOperationError

from ..dependencies import authorize, get_context

router = APIRouter(prefix="/api/v1/workflow-definitions", tags=["workflow-definitions"], dependencies=[Depends(authorize)])


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
        version = ctx.desktop.workflow_definitions.get(workflow_id, version_number or 1)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    steps: list[WorkflowStep] = []
    for node in version.nodes:
        action_map = {
            "device.command": "command",
            "device.reboot": "reboot",
            "utility.wait": "wait_online",
        }
        name = action_map.get(node.action_id)
        if name is None:
            raise UnsupportedOperationError(f"workflow action cannot run yet: {node.action_id}")
        steps.append(WorkflowStep(node.id, kind="tool", action=Action(name, parameters=dict(node.config)), depends_on=tuple(edge.source for edge in version.edges if edge.target == node.id), params=dict(node.input_mapping)))
    workflow = TaskWorkflowDefinition(id=workflow_id, version=str(version.version), name=version.name, steps=tuple(steps), metadata={"workflow_id": workflow_id, "workflow_version": str(version.version)})
    record = ctx.desktop.task_service.create(TaskCreate(workflow=workflow, target=DeviceTarget(device_id=device_id, session_id=str(payload.get("session_id") or ""), protocol=str(payload.get("protocol") or "auto")), source="desktop-workflow-studio", context=dict(payload.get("inputs") or {})))
    return {"task": record.to_dict()}
