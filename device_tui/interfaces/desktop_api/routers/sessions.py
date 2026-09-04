"""Terminal session lifecycle routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from device_tui.application import ConnectionTarget, ControlContext, DeviceTarget, ResourceNotFoundError, SessionCredential

from ..dependencies import authorize, get_context
from ..models import (
    DeviceCredentialRequest,
    DeviceCredentialResponse,
    DirectCredentialSessionRequest,
    OneTimeCredentialSessionRequest,
    SessionCreateRequest,
    SessionListResponse,
    SessionSummary,
)
from ..serializers import session_summary

router = APIRouter(prefix="/api/v1", tags=["sessions"], dependencies=[Depends(authorize)])


@router.get("/sessions", response_model=SessionListResponse)
async def sessions(ctx=Depends(get_context)) -> SessionListResponse:
    return SessionListResponse(sessions=[session_summary(item) for item in ctx.desktop.sessions.list_sessions()])


@router.post("/sessions", response_model=SessionSummary)
async def create_session(request: SessionCreateRequest, ctx=Depends(get_context)) -> SessionSummary:
    view = await ctx.desktop.control.open_session(DeviceTarget(device_id=request.device_id, protocol=request.kind), reuse=False, title=request.title, term_size=(request.cols, request.rows), context=ControlContext(source="electron"))
    return session_summary(next(item for item in ctx.desktop.sessions.list_sessions() if item.id == view.session_id))


@router.post("/sessions/with-credential", response_model=SessionSummary)
async def create_session_with_one_time_credential(request: OneTimeCredentialSessionRequest, ctx=Depends(get_context)) -> SessionSummary:
    target = ctx.desktop.profiles.resolve_target_with_password(request.profile_id, request.kind, request.password)
    view = await ctx.desktop.control.open_connection(target, reuse=False, title=request.title, term_size=(request.cols, request.rows), context=ControlContext(source="electron"))
    return session_summary(next(item for item in ctx.desktop.sessions.list_sessions() if item.id == view.session_id))


@router.post("/sessions/direct", response_model=SessionSummary)
async def create_direct_credential_session(request: DirectCredentialSessionRequest, ctx=Depends(get_context)) -> SessionSummary:
    desktop = ctx.desktop
    if request.password:
        credentials = (SessionCredential(request.username.strip(), request.password),)
    else:
        base_target = desktop.credentials.resolve(request.device_id, request.kind)
        credentials = tuple(SessionCredential(request.username.strip() or credential.username, credential.password) for credential in base_target.credentials)
    target = ConnectionTarget(device_id=request.device_id, protocol=request.kind, host=request.host.strip(), port=request.port, credentials=credentials)
    view = await desktop.control.open_connection(target, reuse=False, title=request.title, term_size=(request.cols, request.rows), context=ControlContext(source="electron"))
    return session_summary(next(item for item in desktop.sessions.list_sessions() if item.id == view.session_id))


@router.post("/session-credentials", response_model=DeviceCredentialResponse)
async def device_session_credentials(
    request: DeviceCredentialRequest,
    ctx=Depends(get_context),
) -> DeviceCredentialResponse:
    """Supply defaults to the isolated Electron credential prompt only."""
    target = ctx.desktop.credentials.resolve(request.device_id, request.kind)
    if not target.credentials:
        return DeviceCredentialResponse()
    # SSH may have fallback candidates (root/root and root/huawei).  The
    # device-specific candidate is last; Telnet and serial have one default.
    credential = target.credentials[-1] if request.kind == "ssh" else target.credentials[0]
    return DeviceCredentialResponse(
        username=credential.username,
        password=credential.password,
    )


async def _session_action(session_id: str, ctx, action: str) -> SessionSummary:
    desktop = ctx.desktop
    desktop.task_service.cancel_session(session_id)
    desktop.transfers.cancel_session(session_id)
    record = next((item for item in desktop.sessions.list_sessions() if item.id == session_id), None)
    if record is None:
        raise ResourceNotFoundError(f"Unknown session: {session_id}", details={"session_id": session_id})
    view = await getattr(desktop.control, action)(DeviceTarget(device_id=record.device_id, session_id=session_id), context=ControlContext(source="electron"))
    return session_summary(next(item for item in desktop.sessions.list_sessions() if item.id == view.session_id))


@router.post("/sessions/{session_id}/reconnect", response_model=SessionSummary)
async def reconnect_session(session_id: str, ctx=Depends(get_context)) -> SessionSummary:
    return await _session_action(session_id, ctx, "reconnect_session")


@router.post("/sessions/{session_id}/disconnect", response_model=SessionSummary)
async def disconnect_session(session_id: str, ctx=Depends(get_context)) -> SessionSummary:
    return await _session_action(session_id, ctx, "disconnect_session")


@router.delete("/sessions/{session_id}", status_code=204)
async def close_session(session_id: str, ctx=Depends(get_context)) -> None:
    desktop = ctx.desktop
    desktop.automation.cancel_session(session_id, reason="session_closed")
    desktop.task_service.cancel_session(session_id)
    desktop.transfers.cancel_session(session_id)
    record = next((item for item in desktop.sessions.list_sessions() if item.id == session_id), None)
    if record is None:
        raise ResourceNotFoundError(f"Unknown session: {session_id}", details={"session_id": session_id})
    await desktop.control.close_session(DeviceTarget(device_id=record.device_id, session_id=session_id), context=ControlContext(source="electron"))
