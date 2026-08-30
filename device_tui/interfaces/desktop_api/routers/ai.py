"""AI planning, execution, approval, and audit endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ..dependencies import authorize, get_context
from ..models import (
    AiApprovalListResponse,
    AiApprovalResponse,
    AiAuditResponse,
    AiBatchRequest,
    AiCommandRequest,
    AiPlanRequest,
    AiPlanResponse,
    AiResultResponse,
)

router = APIRouter(prefix="/api/v1/ai", tags=["ai"], dependencies=[Depends(authorize)])


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
        session_id=request.session_id,
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
        session_id=request.session_id,
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
