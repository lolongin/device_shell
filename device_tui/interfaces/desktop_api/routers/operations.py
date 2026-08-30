"""Long-running operation and package-upgrade API routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from ..dependencies import authorize, get_context
from ..models import (
    OperationListResponse,
    OperationModel,
    OperationResponse,
    PackageUpgradeManualPlanRequest,
    PackageUpgradeManualPlanResponse,
    PackageUpgradeManualScriptSendRequest,
    PackageUpgradeManualScriptSendResponse,
    SessionLogResponse,
)

router = APIRouter(prefix="/api/v1", tags=["operations"], dependencies=[Depends(authorize)])


def operation_model(record: object) -> OperationModel:
    payload = asdict(record)
    if "operation_id" in payload and "id" not in payload:
        payload["id"] = payload.pop("operation_id")
    payload.setdefault("direction", "")
    payload.setdefault("bytes_transferred", 0)
    payload.setdefault("total_bytes", 0)
    payload.setdefault("bytes_per_second", 0)
    payload.setdefault("eta_seconds", None)
    payload.setdefault("queue_position", None)
    payload.setdefault("retry_of", None)
    payload.setdefault("cancellable", True)
    payload.setdefault("revision", 0)
    payload.setdefault("created_at", "")
    payload.setdefault("updated_at", "")
    return OperationModel(**payload)


@router.get("/operations", response_model=OperationListResponse)
async def list_operations(kind: str = Query(default="", max_length=160), limit: int = Query(default=200, ge=1, le=1_000), ctx=Depends(get_context)) -> OperationListResponse:
    return OperationListResponse(operations=[operation_model(record) for record in ctx.desktop.control.list_operations(kind=kind, limit=limit)])


@router.get("/operations/{operation_id}", response_model=OperationResponse)
async def get_operation(operation_id: str, ctx=Depends(get_context)) -> OperationResponse:
    return OperationResponse(operation=operation_model(ctx.desktop.control.get_operation(operation_id)))


@router.post("/operations/{operation_id}/cancel", response_model=OperationResponse)
async def cancel_operation(operation_id: str, ctx=Depends(get_context)) -> OperationResponse:
    return OperationResponse(operation=operation_model(ctx.desktop.control.cancel_operation(operation_id)))


@router.get("/package-upgrades/manual/{session_id}/terminal", response_model=SessionLogResponse)
async def package_upgrade_manual_terminal(session_id: str, ctx=Depends(get_context)) -> SessionLogResponse:
    content, truncated = ctx.desktop.upgrades.manual_terminal_snapshot(session_id)
    return SessionLogResponse(session_id=session_id, content=content, truncated=truncated)


@router.post("/package-upgrades/manual/plan", response_model=PackageUpgradeManualPlanResponse)
async def package_upgrade_manual_plan(request: PackageUpgradeManualPlanRequest, ctx=Depends(get_context)) -> PackageUpgradeManualPlanResponse:
    plan = await ctx.desktop.upgrades.generate_manual_plan(session_id=request.session_id, package_path=request.package_path, startup_output=request.startup_output, master_dir_output=request.master_dir_output, slave_dir_output=request.slave_dir_output, include_slave=request.include_slave, auto_delete_old_packages=request.auto_delete_old_packages, reboot_after_setting=request.reboot_after_setting, master_storage=request.master_storage, slave_storage=request.slave_storage)
    return PackageUpgradeManualPlanResponse(script=plan.script, package_name=plan.package_name, cleanup_paths=plan.cleanup_paths, notes=plan.notes, password_placeholder=plan.password_placeholder)


@router.post("/package-upgrades/manual/send", response_model=PackageUpgradeManualScriptSendResponse)
async def package_upgrade_manual_send(request: PackageUpgradeManualScriptSendRequest, ctx=Depends(get_context)) -> PackageUpgradeManualScriptSendResponse:
    command_count = await ctx.desktop.upgrades.send_manual_script(session_id=request.session_id, script=request.script, interval_ms=request.interval_ms)
    return PackageUpgradeManualScriptSendResponse(session_id=request.session_id, command_count=command_count)
