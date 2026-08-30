"""Health and diagnostics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..dependencies import authorize, get_context
from ..models import DiagnosticsResponse, HealthResponse
from ..serializers import persistence_diagnostics

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/diagnostics",
    response_model=DiagnosticsResponse,
    dependencies=[Depends(authorize)],
)
async def diagnostics(ctx=Depends(get_context)) -> DiagnosticsResponse:
    return DiagnosticsResponse(
        persistence=persistence_diagnostics(ctx.persistence_status),
        legacy_imports={
            "profiles": dict(ctx.legacy_import or {}),
            "commands": dict(ctx.legacy_command_import or {}),
            "automation": dict(ctx.legacy_automation_import or {}),
            "transfers": dict(ctx.legacy_transfer_import or {}),
        },
        log_policy=dict(ctx.log_policy or {}),
    )
