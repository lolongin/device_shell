"""Saved connection profiles and profile groups."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from device_tui.application import ApplicationConflictError

from ..dependencies import authorize, get_context
from ..models import (
    ConnectionProfileGroupCreateRequest,
    ConnectionProfileGroupListResponse,
    ConnectionProfileListResponse,
    ConnectionProfileSummary,
    ConnectionProfileUpsertRequest,
    ProfileCredentialUpdateRequest,
)
from ..serializers import profile_draft, profile_summary

router = APIRouter(prefix="/api/v1", tags=["profiles"], dependencies=[Depends(authorize)])


@router.get("/connection-profiles", response_model=ConnectionProfileListResponse)
async def connection_profiles(profile_type: str = Query(default="", alias="type"), ctx=Depends(get_context)) -> ConnectionProfileListResponse:
    normalized_type = profile_type if profile_type in {"temporary", "server"} else None
    profiles = ctx.desktop.profiles.list_profiles(normalized_type)
    return ConnectionProfileListResponse(profiles=[profile_summary(ctx.desktop, profile) for profile in profiles], groups=ctx.desktop.profiles.list_groups())


@router.post("/connection-profile-groups", response_model=ConnectionProfileGroupListResponse)
async def create_connection_profile_group(request: ConnectionProfileGroupCreateRequest, ctx=Depends(get_context)) -> ConnectionProfileGroupListResponse:
    ctx.desktop.profiles.create_group(request.name)
    return ConnectionProfileGroupListResponse(groups=ctx.desktop.profiles.list_groups())


@router.post("/connection-profiles", response_model=ConnectionProfileSummary)
async def create_connection_profile(request: ConnectionProfileUpsertRequest, ctx=Depends(get_context)) -> ConnectionProfileSummary:
    return profile_summary(ctx.desktop, ctx.desktop.profiles.save(profile_draft(request), allow_duplicate=request.allow_duplicate))


@router.put("/connection-profiles/{profile_id}", response_model=ConnectionProfileSummary)
async def update_connection_profile(profile_id: str, request: ConnectionProfileUpsertRequest, ctx=Depends(get_context)) -> ConnectionProfileSummary:
    ctx.desktop.profiles.get_profile(profile_id)
    return profile_summary(ctx.desktop, ctx.desktop.profiles.save(profile_draft(request, profile_id), allow_duplicate=request.allow_duplicate))


@router.delete("/connection-profiles/{profile_id}", status_code=204)
async def delete_connection_profile(profile_id: str, ctx=Depends(get_context)) -> None:
    desktop = ctx.desktop
    profile = desktop.profiles.get_profile(profile_id)
    if profile.profile_type == "temporary" and any(session.device_id == profile_id for session in desktop.sessions.list_sessions()):
        raise ApplicationConflictError("Close the temporary connection's terminal sessions before deleting it.", details={"profile_id": profile_id})
    desktop.profiles.delete(profile_id)


@router.put("/connection-profiles/{profile_id}/credentials/{protocol}", response_model=ConnectionProfileSummary)
async def save_connection_profile_credential(profile_id: str, protocol: str, request: ProfileCredentialUpdateRequest, ctx=Depends(get_context)) -> ConnectionProfileSummary:
    ctx.desktop.profiles.set_password(profile_id, protocol, request.password)
    return profile_summary(ctx.desktop, ctx.desktop.profiles.get_profile(profile_id))


@router.delete("/connection-profiles/{profile_id}/credentials/{protocol}", response_model=ConnectionProfileSummary)
async def delete_connection_profile_credential(profile_id: str, protocol: str, ctx=Depends(get_context)) -> ConnectionProfileSummary:
    ctx.desktop.profiles.set_password(profile_id, protocol, "")
    return profile_summary(ctx.desktop, ctx.desktop.profiles.get_profile(profile_id))
