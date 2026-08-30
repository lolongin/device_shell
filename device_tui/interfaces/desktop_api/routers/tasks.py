"""Legacy task API and framework workflow discovery endpoints."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, Query

from device_tui.application import (
    Action,
    ControlContext,
    Decision,
    DecisionActor,
    DeviceTarget,
    TaskCreate,
    UnsupportedOperationError,
    WorkflowCatalogError,
    WorkflowTarget,
)
from device_tui.application.errors import ResourceNotFoundError

from ..dependencies import authorize, get_context
from ..models import (
    TaskCreateRequest,
    TaskDeleteRequest,
    TaskDeleteResponse,
    TaskListResponse,
    TaskResponse,
    TaskResumeRequest,
)
from ..serializers import task_model

router = APIRouter(prefix="/api/v1", tags=["tasks"], dependencies=[Depends(authorize)])


@router.post("/tasks", response_model=TaskResponse)
async def task_create(request: TaskCreateRequest, ctx=Depends(get_context)) -> TaskResponse:
    desktop = ctx.desktop
    requested_protocol = request.protocol
    session_id = request.session_id
    device_id = request.device_id
    if session_id:
        session = next((item for item in desktop.sessions.list_sessions() if item.id == session_id), None)
        if session is None:
            raise ResourceNotFoundError("Unknown session", details={"session_id": session_id})
        if device_id and device_id != session.device_id:
            raise UnsupportedOperationError(
                "session_id does not belong to device_id.",
                details={"session_id": session_id, "session_device_id": session.device_id, "device_id": device_id},
            )
        if request.workflow_id == "device_upgrade" and requested_protocol == "auto":
            requested_protocol = session.kind.casefold()
        if requested_protocol != "auto" and session.kind.casefold() != requested_protocol:
            raise UnsupportedOperationError(
                "session_id does not match the requested protocol.",
                details={"session_id": session_id, "session_protocol": session.kind, "protocol": requested_protocol},
            )
        device_id = session.device_id
    elif request.workflow_id == "device_upgrade" and requested_protocol == "auto":
        requested_protocol = "telnet"
    if not device_id:
        raise UnsupportedOperationError("device_id or session_id is required")
    if not session_id:
        view = await desktop.control.open_session(
            DeviceTarget(device_id=device_id, protocol=requested_protocol),
            reuse=True,
            context=ControlContext(source=request.source),
        )
        session_id = view.session_id
    if not desktop.workflows.contains(request.workflow_id):
        raise UnsupportedOperationError(
            f"Unknown workflow_id: {request.workflow_id}. Register a WorkflowProvider or submit a WorkflowPlan."
        )
    parameters = {**dict(request.options), **dict(request.parameters)}
    if request.package:
        parameters.setdefault("package_path", request.package)
    descriptor = desktop.workflows.descriptor(request.workflow_id)
    for definition in descriptor.parameters:
        if not definition.stage_to_transfer_root:
            continue
        raw_value = parameters.get(definition.name)
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        local_path = Path(raw_value).expanduser()
        if not local_path.is_absolute():
            continue
        if request.source != "desktop":
            raise UnsupportedOperationError(
                "An absolute workflow file path is only accepted from the desktop file picker."
            )
        if definition.file_extensions and local_path.suffix.casefold() not in {
            item.casefold() for item in definition.file_extensions
        }:
            raise UnsupportedOperationError(f"请选择 {', '.join(definition.file_extensions)} 文件。")
        if not local_path.is_file():
            raise UnsupportedOperationError("请选择存在的文件。")
        transfer_root = Path(desktop.transfers.settings().root).resolve()
        transfer_root.mkdir(parents=True, exist_ok=True)
        staged_path = (transfer_root / local_path.name).resolve()
        if staged_path != local_path.resolve():
            try:
                shutil.copy2(local_path, staged_path)
            except OSError as exc:
                raise UnsupportedOperationError(f"无法将文件放入文件服务目录：{exc}") from exc
        parameters[definition.name] = staged_path.relative_to(transfer_root).as_posix()
    try:
        workflow = desktop.workflows.build(
            request.workflow_id,
            WorkflowTarget(device_id=device_id, session_id=session_id, protocol=requested_protocol),
            parameters,
            legacy_steps=tuple(item.model_dump() for item in request.steps),
        )
    except WorkflowCatalogError as exc:
        raise UnsupportedOperationError(str(exc)) from exc
    record = desktop.task_service.create(
        TaskCreate(
            workflow=workflow,
            target=DeviceTarget(device_id=device_id, session_id=session_id, protocol=requested_protocol),
            source=request.source,
            context=dict(request.context),
        )
    )
    return TaskResponse(task=task_model(record))


@router.get("/workflows")
async def workflow_catalog(ctx=Depends(get_context)) -> dict[str, object]:
    return {"workflows": [item.public_dict() for item in ctx.desktop.workflows.list()]}


@router.get("/framework/workflows")
async def framework_workflow_catalog(ctx=Depends(get_context)) -> dict[str, object]:
    return {
        "workflows": [
            {
                "id": provider.id,
                "version": provider.version,
                "capabilities": sorted(
                    ctx.desktop.framework_workflows.build(
                        provider.id,
                        {"package_ref": "<artifact>", "expected_version": "<version>"},
                    ).required_capabilities
                )
                if provider.id == "network.package_upgrade"
                else [],
            }
            for provider in ctx.desktop.framework_workflows.list()
        ]
    }


@router.post("/framework/workflows/{workflow_id}/preview")
async def framework_workflow_preview(
    workflow_id: str,
    request: dict[str, object],
    ctx=Depends(get_context),
) -> dict[str, object]:
    try:
        definition = ctx.desktop.framework_workflows.build(workflow_id, dict(request))
    except (KeyError, ValueError) as exc:
        raise UnsupportedOperationError(str(exc)) from exc
    return {"workflow": definition.to_dict()}


@router.get("/tasks", response_model=TaskListResponse)
async def task_list(
    limit: int = Query(default=200, ge=1, le=500),
    ctx=Depends(get_context),
) -> TaskListResponse:
    return TaskListResponse(tasks=[task_model(item) for item in ctx.desktop.task_service.list(limit=limit)])


@router.delete("/tasks", response_model=TaskDeleteResponse)
async def task_delete_many(
    request: TaskDeleteRequest,
    ctx=Depends(get_context),
) -> TaskDeleteResponse:
    deleted_task_ids = ctx.desktop.task_service.delete_tasks(request.task_ids)
    return TaskDeleteResponse(
        deleted_count=len(deleted_task_ids),
        deleted_task_ids=list(deleted_task_ids),
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def task_get(task_id: str, ctx=Depends(get_context)) -> TaskResponse:
    return TaskResponse(task=task_model(ctx.desktop.task_service.get(task_id)))


@router.delete("/tasks/{task_id}", status_code=204)
async def task_delete(task_id: str, ctx=Depends(get_context)) -> None:
    ctx.desktop.task_service.delete_task(task_id)


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse)
async def task_cancel(task_id: str, ctx=Depends(get_context)) -> TaskResponse:
    return TaskResponse(task=task_model(ctx.desktop.task_service.cancel(task_id)))


@router.post("/tasks/{task_id}/pause", response_model=TaskResponse)
async def task_pause(task_id: str, ctx=Depends(get_context)) -> TaskResponse:
    return TaskResponse(task=task_model(ctx.desktop.task_service.pause(task_id)))


@router.get("/tasks/{task_id}/decision")
async def task_decision_get(task_id: str, ctx=Depends(get_context)) -> dict[str, object]:
    decision = ctx.desktop.task_service.get_decision(task_id)
    return {"decision": decision.to_dict() if decision is not None else None}


@router.post("/tasks/{task_id}/resume", response_model=TaskResponse)
async def task_resume(
    task_id: str,
    request: TaskResumeRequest,
    ctx=Depends(get_context),
) -> TaskResponse:
    return TaskResponse(
        task=task_model(
            ctx.desktop.task_service.resume(
                task_id,
                context=dict(request.context),
                step_id=request.step_id,
            )
        )
    )


@router.post("/tasks/{task_id}/decision", response_model=TaskResponse)
async def task_decision(
    task_id: str,
    request: dict[str, object],
    ctx=Depends(get_context),
) -> TaskResponse:
    raw_action = request.get("action")
    if isinstance(raw_action, str):
        action = Action(
            raw_action,
            target_step=str(request.get("target_step") or ""),
            parameters=dict(request.get("parameters") or {}),
        )
    elif isinstance(raw_action, dict):
        action = Action.from_dict(raw_action)
    else:
        raise UnsupportedOperationError("Decision action is required")
    decision = Decision(
        decision_id=str(request.get("decision_id") or uuid4()),
        actor=DecisionActor(
            type=str(request.get("actor_type") or "user"),
            id=str(request.get("actor_id") or ""),
        ),
        action=action,
        reason=str(request.get("reason") or ""),
        task_id=task_id,
        expected_revision=(
            int(request["expected_revision"])
            if request.get("expected_revision") is not None
            else None
        ),
    )
    return TaskResponse(task=task_model(ctx.desktop.task_service.apply_decision(task_id, decision)))
