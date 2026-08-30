"""Command workspace, history, and dispatch routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from device_tui.application import ControlContext, DeviceTarget, ResourceNotFoundError, redact_command_secrets

from ..dependencies import authorize, get_context
from ..models import (
    CommandBroadcastRequest,
    CommandDispatchResponse,
    CommandGroupCreateRequest,
    CommandGroupOrderRequest,
    CommandGroupUpdateRequest,
    CommandRecordRequest,
    CommandSendRequest,
    CommandSuggestionResponse,
    CommandWorkspacePreferencesRequest,
    CommandWorkspaceResponse,
)
from ..serializers import command_workspace

router = APIRouter(prefix="/api/v1", tags=["commands"], dependencies=[Depends(authorize)])


@router.get("/commands/workspace", response_model=CommandWorkspaceResponse)
async def get_command_workspace(ctx=Depends(get_context)) -> CommandWorkspaceResponse:
    return command_workspace(ctx.desktop)


@router.post("/commands/groups", response_model=CommandWorkspaceResponse)
async def create_command_group(request: CommandGroupCreateRequest, ctx=Depends(get_context)) -> CommandWorkspaceResponse:
    ctx.desktop.commands.create_group(request.name)
    return command_workspace(ctx.desktop)


@router.put("/commands/groups/order", response_model=CommandWorkspaceResponse)
async def reorder_command_groups(request: CommandGroupOrderRequest, ctx=Depends(get_context)) -> CommandWorkspaceResponse:
    ctx.desktop.commands.reorder_groups(request.group_ids)
    return command_workspace(ctx.desktop)


@router.put("/commands/groups/{group_id}", response_model=CommandWorkspaceResponse)
async def update_command_group(group_id: str, request: CommandGroupUpdateRequest, ctx=Depends(get_context)) -> CommandWorkspaceResponse:
    ctx.desktop.commands.update_group(group_id, name=request.name, content=request.content)
    return command_workspace(ctx.desktop)


@router.delete("/commands/groups/{group_id}", response_model=CommandWorkspaceResponse)
async def delete_command_group(group_id: str, ctx=Depends(get_context)) -> CommandWorkspaceResponse:
    ctx.desktop.commands.delete_group(group_id)
    return command_workspace(ctx.desktop)


@router.put("/commands/preferences", response_model=CommandWorkspaceResponse)
async def update_command_preferences(request: CommandWorkspacePreferencesRequest, ctx=Depends(get_context)) -> CommandWorkspaceResponse:
    if request.current_group_id is not None:
        ctx.desktop.commands.set_current_group(request.current_group_id)
    if request.enter_sends is not None:
        ctx.desktop.commands.set_enter_sends(request.enter_sends)
    return command_workspace(ctx.desktop)


@router.get("/commands/suggestions", response_model=CommandSuggestionResponse)
async def command_suggestions(query: str = Query(min_length=1, max_length=10_000), session_id: str = Query(default="", max_length=160), limit: int = Query(default=5, ge=1, le=20), ctx=Depends(get_context)) -> CommandSuggestionResponse:
    device_id = ""
    session_kind = ""
    if session_id:
        session = next((item for item in ctx.desktop.sessions.list_sessions() if item.id == session_id), None)
        if session is None:
            raise ResourceNotFoundError(f"Unknown session: {session_id}", details={"resource": "session", "session_id": session_id})
        device_id = session.device_id
        session_kind = session.kind
    return CommandSuggestionResponse(suggestions=ctx.desktop.commands.suggestions(query, device_id=device_id, session_kind=session_kind, limit=limit))


@router.post("/commands/send", response_model=CommandDispatchResponse)
async def send_command(request: CommandSendRequest, ctx=Depends(get_context)) -> CommandDispatchResponse:
    session = next((item for item in ctx.desktop.sessions.list_sessions() if item.id == request.session_id), None)
    if session is None:
        raise ResourceNotFoundError(f"Unknown session: {request.session_id}", details={"session_id": request.session_id})
    await ctx.desktop.control.send_raw(DeviceTarget(device_id=session.device_id, session_id=session.id), request.command, context=ControlContext(source="electron"))
    ctx.desktop.commands.record_for_session(request.session_id, request.command)
    return CommandDispatchResponse(command=redact_command_secrets(request.command), session_ids=[session.id])


@router.post("/commands/history", status_code=204)
async def record_command(request: CommandRecordRequest, ctx=Depends(get_context)) -> None:
    ctx.desktop.commands.record_for_session(request.session_id, request.command)


@router.post("/commands/broadcast", response_model=CommandDispatchResponse)
async def broadcast_command(request: CommandBroadcastRequest, ctx=Depends(get_context)) -> CommandDispatchResponse:
    result = await ctx.desktop.control.broadcast(request.command, session_ids=request.session_ids or None, context=ControlContext(source="electron"))
    for session_id in result.session_ids:
        ctx.desktop.commands.record_for_session(session_id, request.command)
    return CommandDispatchResponse(command=redact_command_secrets(request.command), session_ids=list(result.session_ids))
