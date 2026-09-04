"""External CLI-backed VRP package build routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from device_tui.package_builders import VrpBuildRequest

from ..dependencies import authorize, get_context
from ..models import (
    PackageBuilderListResponse,
    PackageBuilderModel,
    PackageBuildRequest,
)
from .operations import operation_model

router = APIRouter(prefix="/api/v1", tags=["package-builds"], dependencies=[Depends(authorize)])


@router.get("/package-builders", response_model=PackageBuilderListResponse)
async def package_builders(ctx=Depends(get_context)) -> PackageBuilderListResponse:
    return PackageBuilderListResponse(
        builders=[PackageBuilderModel(**item) for item in ctx.desktop.package_builds.builders()]
    )


@router.post("/package-builds")
async def package_build(request: PackageBuildRequest, ctx=Depends(get_context)) -> dict[str, object]:
    operation = ctx.desktop.package_builds.start(
        VrpBuildRequest(
            mrid=request.mrid,
            package_type=request.package_type,
            model=request.model,
            vrp_version=request.vrp_version,
            source_revision=request.source_revision,
            output_name=request.output_name,
            options=request.options,
        ),
        builder_id=request.builder_id,
    )
    return {"operation": operation_model(operation)}


@router.get("/package-builds/{operation_id}")
async def package_build_get(operation_id: str, ctx=Depends(get_context)) -> dict[str, object]:
    return {"operation": operation_model(ctx.desktop.package_builds.get(operation_id))}


@router.post("/package-builds/{operation_id}/cancel")
async def package_build_cancel(operation_id: str, ctx=Depends(get_context)) -> dict[str, object]:
    return {"operation": operation_model(ctx.desktop.package_builds.cancel(operation_id))}


__all__ = ["router"]
