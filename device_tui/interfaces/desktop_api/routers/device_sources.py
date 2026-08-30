"""Device-source selection, plugin management, and spreadsheet import routes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import monotonic
from uuid import uuid4
from pathlib import Path

from fastapi import APIRouter, Depends

from device_tui.application import (
    ApplicationConflictError,
    ApplicationError,
    ResourceNotFoundError,
)
from device_tui.device_sources.import_parser import DeviceImportError, parse_device_import
from device_tui.device_sources.plugins import DeviceSourcePluginError
from device_tui.device_sources.service import DeviceSourceServiceError
from device_tui.domain.devices.repository import RepositoryError

from ..dependencies import authorize, get_context
from ..models import (
    DeviceImportCommitRequest,
    DeviceImportCommitResponse,
    DeviceImportIssueModel,
    DeviceImportPreviewModel,
    DeviceImportPreviewRequest,
    DeviceSourcePluginListResponse,
    DeviceSourcePluginTestResponse,
    DeviceSourcePluginUpdateRequest,
    DeviceSourceStatusModel,
    DeviceSourceSwitchRequest,
)
from ..serializers import (
    attempt_internal_auto_login,
    device_source_plugin_model,
    device_source_status_model,
)

IMPORT_PREVIEW_TTL_SECONDS = 10 * 60
router = APIRouter(prefix="/api/v1", tags=["device-sources"], dependencies=[Depends(authorize)])


@router.get("/device-source", response_model=DeviceSourceStatusModel)
async def device_source_status(ctx=Depends(get_context)) -> DeviceSourceStatusModel:
    return device_source_status_model(ctx.repository)


@router.get("/device-source/plugins", response_model=DeviceSourcePluginListResponse)
async def device_source_plugins(ctx=Depends(get_context)) -> DeviceSourcePluginListResponse:
    repo = ctx.repository
    return DeviceSourcePluginListResponse(
        plugins=[device_source_plugin_model(registration.descriptor.id, repo) for registration in repo.registry.registrations()],
        warnings=list(repo.registry.warnings()),
    )


@router.put("/device-source/plugins/{source_id}", response_model=DeviceSourcePluginListResponse)
async def update_device_source_plugin(
    source_id: str,
    request: DeviceSourcePluginUpdateRequest,
    ctx=Depends(get_context),
) -> DeviceSourcePluginListResponse:
    repo = ctx.repository
    desktop = ctx.desktop
    if not repo.product_profile.allow_plugin_management:
        raise ApplicationConflictError("当前产品的数据来源由开发配置固定，不能在应用内修改插件。")
    try:
        repo.registry.registration(source_id)
    except DeviceSourcePluginError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    if source_id == repo.active_source and request.enabled is False:
        raise ApplicationConflictError("当前正在使用的数据源不能禁用。")
    if source_id == repo.active_source and desktop.sessions.list_sessions() and (request.config or request.secrets):
        raise ApplicationConflictError("请先关闭全部终端会话，再修改当前数据源配置。")
    try:
        repository = repo.apply_plugin_configuration(source_id, config_updates=request.config, secret_updates=request.secrets, enabled=request.enabled)
    except DeviceSourcePluginError as exc:
        raise ApplicationError(str(exc)) from exc
    if repository is not None and source_id == repo.active_source:
        attempt_internal_auto_login(repo, desktop.settings, desktop.secrets, source_id)
    return await device_source_plugins(ctx)


@router.post("/device-source/plugins/{source_id}/test", response_model=DeviceSourcePluginTestResponse)
async def test_device_source_plugin(source_id: str, ctx=Depends(get_context)) -> DeviceSourcePluginTestResponse:
    repo = ctx.repository
    if not repo.product_profile.allow_plugin_management:
        raise ApplicationConflictError("当前产品的数据来源由开发配置固定，不能在应用内测试插件。")
    try:
        result = repo.test_plugin_configuration(source_id)
    except DeviceSourcePluginError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    return DeviceSourcePluginTestResponse(success=result.success, message=result.message, plugin=device_source_plugin_model(source_id, repo))


@router.put("/device-source", response_model=DeviceSourceStatusModel)
async def switch_device_source(request: DeviceSourceSwitchRequest, ctx=Depends(get_context)) -> DeviceSourceStatusModel:
    repo = ctx.repository
    desktop = ctx.desktop
    if request.source == repo.active_source:
        return device_source_status_model(repo)
    if desktop.sessions.list_sessions():
        raise ApplicationConflictError("请先关闭全部终端会话，再切换设备数据源。")
    try:
        descriptor = repo.activate(request.source)
        if descriptor.requires_login:
            attempt_internal_auto_login(repo, desktop.settings, desktop.secrets, request.source)
    except DeviceSourceServiceError as exc:
        raise ApplicationConflictError(str(exc)) from exc
    return device_source_status_model(repo)


@router.post("/device-source/import/preview", response_model=DeviceImportPreviewModel)
async def preview_device_import(request: DeviceImportPreviewRequest, ctx=Depends(get_context)) -> DeviceImportPreviewModel:
    repo = ctx.repository
    if not repo.product_profile.allow_import:
        raise ApplicationConflictError("当前产品不提供设备表格导入。")
    now = monotonic()
    for token, (expires_at, _preview) in list(ctx.import_previews.items()):
        if expires_at <= now:
            ctx.import_previews.pop(token, None)
    try:
        parsed = await asyncio.to_thread(parse_device_import, Path(request.path))
    except DeviceImportError as exc:
        raise ApplicationError(str(exc)) from exc
    preview_token = uuid4().hex
    ctx.import_previews[preview_token] = (now + IMPORT_PREVIEW_TTL_SECONDS, parsed)
    return DeviceImportPreviewModel(
        token=preview_token, file_name=parsed.source_path.name, sheet_name=parsed.sheet_name,
        headers=list(parsed.headers), total_rows=parsed.total_rows, valid_rows=len(parsed.devices),
        skipped_rows=parsed.skipped_rows, preview_rows=[dict(row) for row in parsed.preview_rows],
        errors=[DeviceImportIssueModel(row=issue.row, message=issue.message) for issue in parsed.errors[:100]],
        warnings=list(parsed.warnings),
    )


@router.post("/device-source/import/commit", response_model=DeviceImportCommitResponse)
async def commit_device_import(request: DeviceImportCommitRequest, ctx=Depends(get_context)) -> DeviceImportCommitResponse:
    repo = ctx.repository
    desktop = ctx.desktop
    if not repo.product_profile.allow_import:
        raise ApplicationConflictError("当前产品不提供设备表格导入。")
    if desktop.sessions.list_sessions():
        raise ApplicationConflictError("请先关闭全部终端会话，再覆盖导入设备。")
    cached = ctx.import_previews.get(request.token)
    if cached is None or cached[0] <= monotonic():
        ctx.import_previews.pop(request.token, None)
        raise ApplicationConflictError("导入预览已失效，请重新选择文件。")
    parsed = cached[1]
    try:
        metadata = await asyncio.to_thread(repo.replace_imported_devices, list(parsed.devices), source_name=parsed.source_path.name, sheet_name=parsed.sheet_name, imported_at=datetime.now(timezone.utc).isoformat())
    except (OSError, ValueError, RepositoryError, DeviceSourceServiceError) as exc:
        raise ApplicationError(f"无法保存导入设备：{exc}") from exc
    ctx.import_previews.pop(request.token, None)
    return DeviceImportCommitResponse(imported_count=metadata.row_count, source=device_source_status_model(repo))
