"""AI planning, execution, approval, and audit endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from device_tui.application.ai.agent import AgentContext, AgentIterationLimitError
from device_tui.application.ai.llm import LlmClientError
from device_tui.application.ai.agent.safety import sanitize
from device_tui.application.ai.agent.context import ContextBudgetError
from device_tui.application.ai.agent.storage import restore, snapshot
from device_tui.application.ai.knowledge import KnowledgeDocument

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


class AgentApprovalPolicyUpdate(BaseModel):
    bypass_approval: bool


class AgentConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@router.get("/agent/approval-policy")
async def get_agent_approval_policy(ctx=Depends(get_context)) -> dict:
    enabled = bool(ctx.desktop.settings.get("ai.agent.bypass_approval", False))
    ctx.ai_runtime.bypass_approval = enabled
    return {"bypass_approval": enabled}


@router.put("/agent/approval-policy")
async def update_agent_approval_policy(request: AgentApprovalPolicyUpdate, ctx=Depends(get_context)) -> dict:
    ctx.desktop.settings.set("ai.agent.bypass_approval", request.bypass_approval)
    ctx.ai_runtime.bypass_approval = request.bypass_approval
    return {"bypass_approval": request.bypass_approval}


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
    context = _conversation(ctx, request.conversation_id)
    if context is None:
        context = AgentContext(conversation_id=request.conversation_id)
        _cache_conversation(ctx, context)
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
    except (AgentIterationLimitError, ContextBudgetError) as exc:
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


@router.get("/knowledge/search")
async def knowledge_search(query: str = Query(min_length=1, max_length=500), vendor: str = Query(default="", max_length=100), model: str = Query(default="", max_length=100), software_version: str = Query(default="", max_length=100), limit: int = Query(default=5, ge=1, le=10), ctx=Depends(get_context)) -> dict:
    try:
        return {"documents": ctx.ai_knowledge.search(query, vendor=vendor, model=model, software_version=software_version, limit=limit)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/knowledge/{document_id}")
async def knowledge_put(document_id: str, request: KnowledgeDocument, ctx=Depends(get_context)) -> dict:
    try:
        return {"document": ctx.ai_knowledge.put(document_id, request)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/{document_id}")
async def knowledge_get(document_id: str, ctx=Depends(get_context)) -> dict:
    try:
        return {"document": ctx.ai_knowledge.get(document_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/knowledge/{document_id}")
async def knowledge_delete(document_id: str, ctx=Depends(get_context)) -> dict:
    try:
        ctx.ai_knowledge.delete(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": True}


@router.get("/agent/conversations/{conversation_id}")
async def agent_state(conversation_id: str, after: int = Query(default=0, ge=0), ctx=Depends(get_context)) -> dict:
    context = _conversation(ctx, conversation_id)
    return {**ctx.ai_runtime.state(conversation_id, after), "busy": conversation_id in ctx.ai_busy_conversations, "context_available": context is not None, "history": context.messages if context else []}


@router.get("/agent/conversations")
async def agent_conversations(ctx=Depends(get_context)) -> dict:
    return {"conversations": ctx.ai_snapshot_store.list() if ctx.ai_snapshot_store else []}


@router.put("/agent/conversations/{conversation_id}")
async def rename_agent_conversation(conversation_id: str, request: AgentConversationRename, ctx=Depends(get_context)) -> dict:
    context = _conversation(ctx, conversation_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Unknown conversation")
    context.title = sanitize(request.title.strip())[:120]
    if not context.title:
        raise HTTPException(status_code=422, detail="Conversation title is required")
    approvals = ctx.ai_runtime.state(conversation_id)["approvals"][-30:]
    ctx.ai_snapshot_store.put(conversation_id, snapshot(context, approvals))
    return {"conversation": {"conversation_id": conversation_id, "title": context.title}}


@router.delete("/agent/conversations/{conversation_id}")
async def delete_agent_conversation(conversation_id: str, ctx=Depends(get_context)) -> dict:
    if conversation_id in ctx.ai_busy_conversations:
        raise HTTPException(status_code=409, detail="Cannot delete a conversation while its Agent turn is running")
    context = _conversation(ctx, conversation_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Unknown conversation")
    ctx.ai_conversations.pop(conversation_id, None)
    ctx.ai_runtime.forget_conversation(conversation_id)
    if ctx.ai_snapshot_store:
        ctx.ai_snapshot_store.delete(conversation_id)
    return {"deleted": True}


@router.get("/agent/conversations/{conversation_id}/trace")
async def agent_trace(conversation_id: str, ctx=Depends(get_context)) -> dict:
    context = _conversation(ctx, conversation_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Unknown conversation")
    return sanitize({"conversation_id": conversation_id, "runs": context.traces[-30:]})


def _conversation(ctx, conversation_id: str) -> AgentContext | None:
    context = ctx.ai_conversations.get(conversation_id)
    if context is None and ctx.ai_snapshot_store is not None:
        saved = ctx.ai_snapshot_store.get(conversation_id)
        if saved:
            context = restore(conversation_id, saved)
            ctx.ai_runtime.restore_approvals(conversation_id, saved.get("approvals", []))
            _cache_conversation(ctx, context)
    return context


def _cache_conversation(ctx, context: AgentContext) -> None:
    # Do not evict live approval/session state and later confuse a cache miss
    # with a backend restart. Persisted history remains separately bounded.
    if context.conversation_id not in ctx.ai_conversations and len(ctx.ai_conversations) >= 200:
        raise HTTPException(status_code=429, detail="Agent conversation capacity reached; restart the backend to reload persisted history")
    ctx.ai_conversations[context.conversation_id] = context


@router.post("/agent/conversations/{conversation_id}/approvals/{approval_id}/{decision}")
async def agent_resolve_approval(conversation_id: str, approval_id: str, decision: str, ctx=Depends(get_context)) -> dict:
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="decision must be approve or reject")
    if conversation_id in ctx.ai_busy_conversations:
        raise HTTPException(status_code=409, detail="Wait for the active Agent turn to finish")
    context = _conversation(ctx, conversation_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Unknown conversation")
    ctx.ai_busy_conversations.add(conversation_id)
    try:
        return {"approval": await ctx.ai_runtime.resolve(approval_id, context, approve=decision == "approve")}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        try:
            if ctx.ai_snapshot_store:
                ctx.ai_snapshot_store.put(conversation_id, snapshot(context, ctx.ai_runtime.state(conversation_id)["approvals"][-30:]))
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
