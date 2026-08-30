"""Session log settings and inspection routes."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from ..dependencies import authorize, get_context
from ..models import SessionLogActionResponse, SessionLogResponse, SessionLogSettingsModel, SessionLogSettingsUpdateRequest
from ..serializers import session_log_settings

SESSION_LOG_DIRECTORY_SETTING = "session_logs.directory"
SESSION_LOG_MAX_BYTES_SETTING = "session_logs.max_bytes"
SESSION_LOG_BACKUPS_SETTING = "session_logs.backup_count"

router = APIRouter(prefix="/api/v1", tags=["session-logs"], dependencies=[Depends(authorize)])


@router.get("/settings/session-logs", response_model=SessionLogSettingsModel)
async def get_session_log_settings(ctx=Depends(get_context)) -> SessionLogSettingsModel:
    return session_log_settings(ctx.hub)


@router.put("/settings/session-logs", response_model=SessionLogSettingsModel)
async def update_session_log_settings(request: SessionLogSettingsUpdateRequest, ctx=Depends(get_context)) -> SessionLogSettingsModel:
    directory = Path(request.directory).expanduser()
    if not directory.is_absolute():
        raise HTTPException(status_code=422, detail="日志目录必须是绝对路径。")
    current = ctx.hub.log_configuration()
    if current is None:
        raise HTTPException(status_code=409, detail="当前会话日志不是文件日志，无法更改设置。")
    try:
        result = await asyncio.to_thread(ctx.hub.reconfigure_logging, directory, max_bytes=request.rotate_size_mb * 1024 * 1024, backup_count=int(current["backup_count"]))
    except (OSError, RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=400, detail=f"日志设置应用失败: {exc}") from exc
    ctx.desktop.settings.set(SESSION_LOG_DIRECTORY_SETTING, str(result["root"]))
    ctx.desktop.settings.set(SESSION_LOG_MAX_BYTES_SETTING, int(result["max_bytes"]))
    ctx.desktop.settings.set(SESSION_LOG_BACKUPS_SETTING, int(result["backup_count"]))
    if ctx.log_policy is not None:
        ctx.log_policy["session_log_max_bytes"] = int(result["max_bytes"])
        ctx.log_policy["session_log_backups"] = int(result["backup_count"])
    return session_log_settings(ctx.hub, moved_count=int(result.get("moved_count", 0)))


@router.get("/sessions/{session_id}/log", response_model=SessionLogResponse)
async def session_log(session_id: str, max_chars: int = Query(default=200_000, ge=1_024, le=2_000_000), ctx=Depends(get_context)) -> SessionLogResponse:
    record = ctx.desktop.sessions.read_log(session_id, max_chars)
    return SessionLogResponse(session_id=record.session_id, content=record.content, truncated=record.truncated)


@router.get("/sessions/{session_id}/log-path", response_model=SessionLogActionResponse)
async def session_log_path(session_id: str, ctx=Depends(get_context)) -> SessionLogActionResponse:
    try:
        path = ctx.hub.log_path(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SessionLogActionResponse(session_id=session_id, path=str(path))


@router.post("/sessions/{session_id}/log/new", response_model=SessionLogActionResponse)
async def create_session_log(session_id: str, ctx=Depends(get_context)) -> SessionLogActionResponse:
    try:
        archived_path = await asyncio.to_thread(ctx.hub.start_new_log, session_id)
        path = ctx.hub.log_path(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    except (OSError, RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=400, detail=f"新建会话日志失败: {exc}") from exc
    return SessionLogActionResponse(session_id=session_id, path=str(path), archived_path=archived_path)
