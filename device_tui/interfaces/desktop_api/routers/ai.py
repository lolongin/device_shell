"""AI planning, execution, approval, and audit endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from device_tui.application.ai.agent import AgentContext, AgentIterationLimitError
from device_tui.application.ai.llm import LlmClientError
from device_tui.application.errors import UnsupportedOperationError

from ..dependencies import authorize, get_context
from ..models import (
    AiApprovalListResponse,
    AiApprovalResponse,
    AiAuditResponse,
    AiBatchRequest,
    AiChatRequest,
    AiChatResponse,
    AiCommandRequest,
    AiPlanRequest,
    AiPlanResponse,
    AiResultResponse,
)

router = APIRouter(prefix="/api/v1/ai", tags=["ai"], dependencies=[Depends(authorize)])
legacy_router = APIRouter(prefix="/api/ai", tags=["ai"], dependencies=[Depends(authorize)])


async def _run_chat(request: AiChatRequest, ctx) -> AiChatResponse:
    context = ctx.ai_conversations.get(request.conversation_id)
    if context is None:
        context = AgentContext(conversation_id=request.conversation_id)
        ctx.ai_conversations[request.conversation_id] = context
    if request.device_id:
        context.device_id = request.device_id.strip()
    if request.session_id:
        context.session_id = request.session_id.strip()
    if request.protocol != "auto":
        context.variables["protocol"] = request.protocol
    if not context.device_id and not context.session_id:
        raise UnsupportedOperationError(
            "A device_id or session_id is required for device Agent chat.",
            details={"resource": "terminal_target"},
        )
    try:
        message = await ctx.ai_agent.run(request.message, context)
    except LlmClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except AgentIterationLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AiChatResponse(
        conversation_id=context.conversation_id,
        message=message,
        device_id=context.device_id or "",
        session_id=context.session_id or "",
    )


@router.post("/chat", response_model=AiChatResponse)
async def ai_chat(request: AiChatRequest, ctx=Depends(get_context)) -> AiChatResponse:
    return await _run_chat(request, ctx)


@legacy_router.post("/chat", response_model=AiChatResponse)
async def ai_chat_legacy(request: AiChatRequest, ctx=Depends(get_context)) -> AiChatResponse:
    return await _run_chat(request, ctx)


@router.post("/plan", response_model=AiPlanResponse)
async def ai_plan(request: AiPlanRequest, ctx=Depends(get_context)) -> AiPlanResponse:
    plan = ctx.ai_service.plan(
        request.objective,
        selected_device_id=request.selected_device_id,
    )
    return AiPlanResponse(
        objective=plan.objective,
        summary=plan.summary,
        actions=list(plan.actions),
        warnings=list(plan.warnings),
    )


@router.post("/execute-command", response_model=AiResultResponse)
async def ai_execute_command(
    request: AiCommandRequest,
    ctx=Depends(get_context),
) -> AiResultResponse | JSONResponse:
    result = await ctx.ai_service.execute_command(
        request.command,
        device_id=request.device_id,
        session_id=request.session_id,
        protocol=request.protocol,
        approval_token=request.approval_token,
        source="desktop-api",
        idempotency_key=request.idempotency_key,
    )
    if result.get("status") == "needs_approval":
        return JSONResponse(status_code=409, content={"api_version": 1, **result})
    return AiResultResponse(result=result)


@router.post("/execute-batch", response_model=AiResultResponse)
async def ai_execute_batch(
    request: AiBatchRequest,
    ctx=Depends(get_context),
) -> AiResultResponse | JSONResponse:
    result = await ctx.ai_service.execute_batch(
        request.commands,
        device_id=request.device_id,
        session_id=request.session_id,
        protocol=request.protocol,
        command_timeout_seconds=request.command_timeout_seconds,
        approval_token=request.approval_token,
        source="desktop-api",
        idempotency_key=request.idempotency_key,
    )
    if result.get("status") == "needs_approval":
        return JSONResponse(status_code=409, content={"api_version": 1, **result})
    return AiResultResponse(result=result)


@router.get("/results/{result_id}", response_model=AiResultResponse)
async def ai_result(
    result_id: str,
    include_raw: bool = Query(default=False),
    ctx=Depends(get_context),
) -> AiResultResponse:
    return AiResultResponse(
        result=ctx.ai_service.get_result(result_id, include_raw=include_raw)
    )


@router.get("/approvals", response_model=AiApprovalListResponse)
async def ai_approvals(ctx=Depends(get_context)) -> AiApprovalListResponse:
    return AiApprovalListResponse(approvals=ctx.ai_service.pending_approvals())


@router.get("/approvals/{approval_id}", response_model=AiApprovalResponse)
async def ai_approval(
    approval_id: str,
    ctx=Depends(get_context),
) -> AiApprovalResponse:
    return AiApprovalResponse(approval=ctx.ai_service.approval(approval_id))


@router.post("/approvals/{approval_id}/approve", response_model=AiApprovalResponse)
async def ai_approve(
    approval_id: str,
    ctx=Depends(get_context),
) -> AiApprovalResponse:
    return AiApprovalResponse(approval=ctx.ai_service.approve(approval_id))


@router.post("/approvals/{approval_id}/reject", response_model=AiApprovalResponse)
async def ai_reject(
    approval_id: str,
    ctx=Depends(get_context),
) -> AiApprovalResponse:
    return AiApprovalResponse(approval=ctx.ai_service.reject(approval_id))


@router.get("/audit", response_model=AiAuditResponse)
async def ai_audit(
    limit: int = Query(default=100, ge=1, le=500),
    ctx=Depends(get_context),
) -> AiAuditResponse:
    return AiAuditResponse(entries=ctx.ai_service.audit_entries(limit))
