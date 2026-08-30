"""Automation rules and quick-send controls."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from device_tui.application import ResourceNotFoundError

from ..dependencies import authorize, get_context
from ..models import (
    AutomationDispatchResponse,
    AutomationPreviewRequest,
    AutomationPreviewResponse,
    AutomationRuleEnabledRequest,
    AutomationRuleTriggerRequest,
    AutomationRuleUpsertRequest,
    AutomationWorkspaceResponse,
    QuickSendButtonUpsertRequest,
    QuickSendDispatchRequest,
    QuickSendDispatchResponse,
)
from ..serializers import automation_workspace

router = APIRouter(prefix="/api/v1", tags=["automation"], dependencies=[Depends(authorize)])


@router.get("/automation/workspace", response_model=AutomationWorkspaceResponse)
async def get_automation_workspace(ctx=Depends(get_context)) -> AutomationWorkspaceResponse:
    return automation_workspace(ctx.desktop)


@router.post("/automation/preview", response_model=AutomationPreviewResponse)
async def preview_automation_rule(request: AutomationPreviewRequest, ctx=Depends(get_context)) -> AutomationPreviewResponse:
    desktop = ctx.desktop
    result = desktop.automation.preview_rule(desktop.automation.deserialize_rule(request.rule), session_id=request.session_id, sample_output=request.sample_output, max_steps=request.max_steps)
    return AutomationPreviewResponse(**result)


@router.post("/automation/rules", response_model=AutomationWorkspaceResponse)
async def create_automation_rule(request: AutomationRuleUpsertRequest, ctx=Depends(get_context)) -> AutomationWorkspaceResponse:
    desktop = ctx.desktop
    desktop.automation.create_rule(desktop.automation.deserialize_rule(request.rule))
    return automation_workspace(desktop)


@router.put("/automation/rules/{rule_id}", response_model=AutomationWorkspaceResponse)
async def update_automation_rule(rule_id: str, request: AutomationRuleUpsertRequest, ctx=Depends(get_context)) -> AutomationWorkspaceResponse:
    desktop = ctx.desktop
    desktop.automation.update_rule(rule_id, desktop.automation.deserialize_rule(request.rule))
    return automation_workspace(desktop)


@router.post("/automation/rules/{rule_id}/clone", response_model=AutomationWorkspaceResponse)
async def clone_automation_rule(rule_id: str, ctx=Depends(get_context)) -> AutomationWorkspaceResponse:
    desktop = ctx.desktop
    desktop.automation.clone_rule(rule_id)
    return automation_workspace(desktop)


@router.put("/automation/rules/{rule_id}/enabled", response_model=AutomationWorkspaceResponse)
async def set_automation_rule_enabled(rule_id: str, request: AutomationRuleEnabledRequest, ctx=Depends(get_context)) -> AutomationWorkspaceResponse:
    desktop = ctx.desktop
    desktop.automation.set_enabled(rule_id, request.enabled)
    return automation_workspace(desktop)


@router.delete("/automation/rules/{rule_id}", status_code=204)
async def delete_automation_rule(rule_id: str, ctx=Depends(get_context)) -> None:
    ctx.desktop.automation.delete_rule(rule_id)


@router.post("/automation/rules/{rule_id}/trigger", response_model=AutomationDispatchResponse)
async def trigger_automation_rule(rule_id: str, request: AutomationRuleTriggerRequest, ctx=Depends(get_context)) -> AutomationDispatchResponse:
    ctx.desktop.automation.trigger_rule(rule_id, request.session_id)
    return AutomationDispatchResponse(rule_id=rule_id, session_id=request.session_id, status="started")


@router.post("/automation/sessions/{session_id}/cancel", response_model=AutomationDispatchResponse)
async def cancel_session_automation(session_id: str, ctx=Depends(get_context)) -> AutomationDispatchResponse:
    desktop = ctx.desktop
    if not any(session.id == session_id for session in desktop.sessions.list_sessions()):
        raise ResourceNotFoundError(f"Unknown session: {session_id}", details={"resource": "session", "session_id": session_id})
    desktop.automation.cancel_session(session_id, reason="user_cancelled")
    return AutomationDispatchResponse(rule_id="", session_id=session_id, status="cancelled")


@router.post("/automation/quick-send-buttons", response_model=AutomationWorkspaceResponse)
async def create_quick_send_button(request: QuickSendButtonUpsertRequest, ctx=Depends(get_context)) -> AutomationWorkspaceResponse:
    desktop = ctx.desktop
    desktop.automation.create_quick_send_button(**request.model_dump())
    return automation_workspace(desktop)


@router.put("/automation/quick-send-buttons/{button_id}", response_model=AutomationWorkspaceResponse)
async def update_quick_send_button(button_id: str, request: QuickSendButtonUpsertRequest, ctx=Depends(get_context)) -> AutomationWorkspaceResponse:
    desktop = ctx.desktop
    desktop.automation.update_quick_send_button(button_id, **request.model_dump())
    return automation_workspace(desktop)


@router.delete("/automation/quick-send-buttons/{button_id}", status_code=204)
async def delete_quick_send_button(button_id: str, ctx=Depends(get_context)) -> None:
    ctx.desktop.automation.delete_quick_send_button(button_id)


@router.post("/automation/quick-send-buttons/{button_id}/send", response_model=QuickSendDispatchResponse)
async def send_quick_send_button(button_id: str, request: QuickSendDispatchRequest, ctx=Depends(get_context)) -> QuickSendDispatchResponse:
    await ctx.desktop.automation.send_quick_send_button(button_id, request.session_id)
    return QuickSendDispatchResponse(button_id=button_id, session_id=request.session_id, status="sent")
