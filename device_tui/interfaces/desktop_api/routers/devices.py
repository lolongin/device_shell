"""Device inventory and device-level actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from device_tui.application import ApplicationError, ControlContext
from device_tui.domain.devices.repository import RepositoryError

from ..dependencies import authorize, get_context
from ..models import DeviceActionResponse, DeviceListResponse
from ..serializers import device_action_response, device_field_schema, device_summary

router = APIRouter(prefix="/api/v1", tags=["devices"], dependencies=[Depends(authorize)])


@router.get("/devices", response_model=DeviceListResponse)
async def devices(ctx=Depends(get_context)) -> DeviceListResponse:
    repo = ctx.repository
    descriptor = repo.registry.descriptor(repo.active_source)
    if descriptor.requires_login:
        try:
            auth_status = repo.internal_auth_status()
        except RepositoryError as exc:
            raise ApplicationError(str(exc)) from exc
        if not auth_status.authenticated:
            return DeviceListResponse(current_user=auth_status.username, owned_device_ids=[], devices=[], field_schema=device_field_schema(repo))
    inventory = ctx.desktop.devices.list_inventory()
    return DeviceListResponse(current_user=inventory.current_user, owned_device_ids=list(inventory.owned_device_ids), devices=[device_summary(device) for device in inventory.devices], field_schema=device_field_schema(repo))


@router.post("/devices/{device_id}/claim", response_model=DeviceActionResponse)
async def claim_device(device_id: str, ctx=Depends(get_context)) -> DeviceActionResponse:
    return device_action_response(ctx.desktop.devices.claim(device_id), ctx.repository)


@router.post("/devices/{device_id}/release", response_model=DeviceActionResponse)
async def release_device(device_id: str, ctx=Depends(get_context)) -> DeviceActionResponse:
    return device_action_response(ctx.desktop.devices.release(device_id), ctx.repository)


@router.post("/devices/{device_id}/toggle", response_model=DeviceActionResponse)
async def toggle_device(device_id: str, ctx=Depends(get_context)) -> DeviceActionResponse:
    return device_action_response(ctx.desktop.devices.toggle(device_id), ctx.repository)


@router.post("/devices/{device_id}/power-off", response_model=DeviceActionResponse)
async def power_off_device(device_id: str, ctx=Depends(get_context)) -> DeviceActionResponse:
    return device_action_response(ctx.desktop.control.power_off(device_id, context=ControlContext(source="electron")), ctx.repository)
