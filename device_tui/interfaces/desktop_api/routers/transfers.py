"""File-transfer service, shared files, and managed transfer routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from device_tui.application import ControlContext, DeviceTarget, ResourceNotFoundError, UnsupportedOperationError

from ..dependencies import authorize, get_context
from ..models import (
    DeleteHistoryResponse,
    ManagedTransferStartRequest,
    OperationResponse,
    SharedFileListResponse,
    SharedFileModel,
    TransferNetworkAddressesResponse,
    TransferPasswordResponse,
    TransferQueueResumeResponse,
    TransferServiceLogResponse,
    TransferSettingsModel,
    TransferSettingsUpdateRequest,
)
from ..serializers import transfer_settings
from .operations import operation_model

router = APIRouter(prefix="/api/v1", tags=["transfers"], dependencies=[Depends(authorize)])


@router.get("/file-transfer/settings", response_model=TransferSettingsModel)
async def file_transfer_settings(ctx=Depends(get_context)) -> TransferSettingsModel:
    return transfer_settings(ctx.desktop)


@router.put("/file-transfer/settings", response_model=TransferSettingsModel)
async def update_file_transfer_settings(request: TransferSettingsUpdateRequest, ctx=Depends(get_context)) -> TransferSettingsModel:
    await ctx.desktop.transfers.reconfigure(protocol=request.protocol, host=request.host, advertised_host=request.advertised_host, port=request.port, root=request.root, username=request.username, password=request.password, writable=request.writable)
    return transfer_settings(ctx.desktop)


@router.get("/file-transfer/password", response_model=TransferPasswordResponse)
async def file_transfer_password(ctx=Depends(get_context)) -> TransferPasswordResponse:
    return TransferPasswordResponse(password=ctx.desktop.transfers.resolve_secret("file_transfer.password"))


@router.post("/file-transfer/service/start", response_model=TransferSettingsModel)
async def start_file_transfer_service(ctx=Depends(get_context)) -> TransferSettingsModel:
    await ctx.desktop.transfers.start_service(auto_stop_when_idle=False)
    return transfer_settings(ctx.desktop)


@router.post("/file-transfer/service/stop", response_model=TransferSettingsModel)
async def stop_file_transfer_service(ctx=Depends(get_context)) -> TransferSettingsModel:
    await ctx.desktop.transfers.stop_service()
    return transfer_settings(ctx.desktop)


@router.get("/file-transfer/service/log", response_model=TransferServiceLogResponse)
async def file_transfer_service_log(ctx=Depends(get_context)) -> TransferServiceLogResponse:
    entries = ctx.desktop.transfers.service_log()
    return TransferServiceLogResponse(entries=entries, content="\n".join(entries), client_command=ctx.desktop.transfers.client_command_hint())


@router.get("/file-transfer/network-addresses", response_model=TransferNetworkAddressesResponse)
async def file_transfer_network_addresses(session_id: str = Query(default="", max_length=160), ctx=Depends(get_context)) -> TransferNetworkAddressesResponse:
    addresses, recommended = ctx.desktop.transfers.network_addresses(session_id)
    return TransferNetworkAddressesResponse(addresses=addresses, recommended=recommended)


@router.delete("/file-transfer/service/log", response_model=TransferServiceLogResponse)
async def clear_file_transfer_service_log(ctx=Depends(get_context)) -> TransferServiceLogResponse:
    ctx.desktop.transfers.clear_service_log()
    return TransferServiceLogResponse(entries=[], content="", client_command=ctx.desktop.transfers.client_command_hint())


@router.get("/file-transfer/files", response_model=SharedFileListResponse)
async def shared_transfer_files(path: str = Query(default="", max_length=4_096), recursive: bool = Query(default=True), limit: int = Query(default=200, ge=1, le=1_000), query: str = Query(default="", max_length=512), sort: str = Query(default="name", pattern="^(name|size|modified)$"), order: str = Query(default="asc", pattern="^(asc|desc)$"), offset: int = Query(default=0, ge=0), ctx=Depends(get_context)) -> SharedFileListResponse:
    catalog = ctx.desktop.transfers.list_files(relative_path=path, recursive=recursive, limit=limit, query=query, sort=sort, order=order, offset=offset)
    return SharedFileListResponse(files=[SharedFileModel(**item.public_dict()) for item in catalog.files], count=len(catalog.files), truncated=catalog.truncated, total=catalog.total, next_offset=catalog.next_offset)


@router.post("/file-transfers", response_model=OperationResponse)
async def start_managed_file_transfer(request: ManagedTransferStartRequest, ctx=Depends(get_context)) -> OperationResponse:
    desktop = ctx.desktop
    session_id = request.session_id
    device_id = request.device_id
    session = None
    if session_id:
        session = next((item for item in desktop.sessions.list_sessions() if item.id == session_id), None)
        if session is None:
            raise ResourceNotFoundError(f"Unknown session: {session_id}", details={"session_id": session_id})
        if device_id and device_id != session.device_id:
            raise UnsupportedOperationError("session_id does not belong to device_id.", details={"session_id": session_id, "session_device_id": session.device_id, "device_id": device_id})
        if request.protocol != "auto" and session.kind.casefold() != request.protocol:
            raise UnsupportedOperationError("session_id does not match the requested protocol.", details={"session_id": session_id, "session_protocol": session.kind, "protocol": request.protocol})
        device_id = session.device_id
    if not device_id:
        raise UnsupportedOperationError("device_id or session_id is required")
    if not session_id:
        view = await desktop.control.open_session(DeviceTarget(device_id=device_id, protocol=request.protocol), reuse=True, context=ControlContext(source="electron"))
        session_id = view.session_id
        session = next((item for item in desktop.sessions.list_sessions() if item.id == session_id), None)
        if session is None:
            raise ResourceNotFoundError("Session disappeared after opening", details={"session_id": session_id})
    task_run, operation_id = await desktop.task_service.start_file_transfer(device_id=session.device_id, session_id=session.id, direction=request.direction, source_path=request.source_path, destination_path=request.destination_path, overwrite=request.overwrite, protocol=request.protocol, terminal_environment=request.terminal_environment, command_mode=request.command_mode, context={"source": "electron"})
    desktop.operations.update(operation_id, data={"task_run_id": task_run.id, "task_plan_id": task_run.plan_id})
    return OperationResponse(operation=operation_model(desktop.control.get_operation(operation_id)))


@router.post("/file-transfers/{operation_id}/retry", response_model=OperationResponse)
async def retry_managed_file_transfer(operation_id: str, ctx=Depends(get_context)) -> OperationResponse:
    return OperationResponse(operation=operation_model(ctx.desktop.transfers.retry(operation_id)))


@router.post("/file-transfers/queues/{session_id}/resume", response_model=TransferQueueResumeResponse)
async def resume_managed_file_transfer_queue(session_id: str, ctx=Depends(get_context)) -> TransferQueueResumeResponse:
    return TransferQueueResumeResponse(session_id=session_id, resumed_count=ctx.desktop.transfers.resume_queue(session_id))


@router.delete("/file-transfers/history", response_model=DeleteHistoryResponse)
async def clear_managed_file_transfer_history(ctx=Depends(get_context)) -> DeleteHistoryResponse:
    return DeleteHistoryResponse(deleted_count=ctx.desktop.transfers.clear_history())
