"""AI planning, execution, approval, and audit endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from device_tui.application.ai.agent import AgentContext, AgentIterationLimitError
from device_tui.application.ai.llm import LlmClientError
from device_tui.application.ai.agent.safety import sanitize

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


class AiModelUpdate(BaseModel):
    base_url: str = Field(max_length=2048)
    model: str = Field(max_length=128)
    timeout: float = Field(ge=1, le=300)


class AiModelKeyUpdate(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)


@router.get("/model")
async def ai_model_settings(ctx=Depends(get_context)) -> dict:
    return ctx.ai_model.public()


@router.put("/model")
async def update_ai_model(request: AiModelUpdate, ctx=Depends(get_context)) -> dict:
    try:
        result = ctx.ai_model.update(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    ctx.ai_agent.set_llm(ctx.ai_model.client())
    return result


@router.put("/model-key")
async def update_ai_model_key(request: AiModelKeyUpdate, ctx=Depends(get_context)) -> dict:
    result = ctx.ai_model.set_key(request.api_key)
    ctx.ai_agent.set_llm(ctx.ai_model.client())
    return result


@router.delete("/model-key")
async def delete_ai_model_key(ctx=Depends(get_context)) -> dict:
    result = ctx.ai_model.delete_key()
    ctx.ai_agent.set_llm(ctx.ai_model.client())
    return result


@router.post("/model/test")
async def test_ai_model(ctx=Depends(get_context)) -> dict:
    if not ctx.ai_model.public()["has_api_key"]:
        raise HTTPException(status_code=400, detail="Configure an API key first")
    try:
        await ctx.ai_model.client().chat(
            messages=[{"role": "user", "content": "Reply with OK. Do not call a tool."}],
            tools=[{
                "type": "function",
                "function": {
                    "name": "connection_check",
                    "description": "Connectivity check only",
                    "parameters": {"type": "object", "properties": {}},
                },
            }],
        )
    except LlmClientError as exc:
        raise HTTPException(status_code=502, detail=sanitize(str(exc))) from exc
    return {"success": True}


async def _run_chat(request: AiChatRequest, ctx) -> AiChatResponse:
    if request.conversation_id in ctx.ai_busy_conversations:
        raise HTTPException(status_code=409, detail="This Agent conversation is already running")
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
    ctx.ai_busy_conversations.add(request.conversation_id)
    try:
        message = await ctx.ai_agent.run(request.message, context)
    except LlmClientError as exc:
        raise HTTPException(status_code=502, detail=sanitize(str(exc))) from exc
    except AgentIterationLimitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        ctx.ai_busy_conversations.discard(request.conversation_id)
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


@router.get("/agent/capabilities")
async def agent_capabilities(ctx=Depends(get_context)) -> dict:
    return {"tools": ctx.ai_runtime.definitions, "approval_mode": "user_required_for_mutations", "unavailable": ctx.ai_runtime.tools.unavailable_capabilities}


@router.get("/agent/conversations/{conversation_id}")
async def agent_state(conversation_id: str, after: int = Query(default=0, ge=0), ctx=Depends(get_context)) -> dict:
    return {**ctx.ai_runtime.state(conversation_id, after), "busy": conversation_id in ctx.ai_busy_conversations}


@router.post("/agent/conversations/{conversation_id}/approvals/{approval_id}/{decision}")
async def agent_resolve_approval(conversation_id: str, approval_id: str, decision: str, ctx=Depends(get_context)) -> dict:
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="decision must be approve or reject")
    if conversation_id in ctx.ai_busy_conversations:
        raise HTTPException(status_code=409, detail="Wait for the active Agent turn to finish")
    context = ctx.ai_conversations.get(conversation_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Unknown conversation")
    ctx.ai_busy_conversations.add(conversation_id)
    try:
        return {"approval": await ctx.ai_runtime.resolve(approval_id, context, approve=decision == "approve")}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        ctx.ai_busy_conversations.discard(conversation_id)


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
