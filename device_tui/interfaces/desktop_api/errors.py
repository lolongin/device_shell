"""Exception-to-HTTP translation for the desktop API."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from device_tui.application import (
    ApplicationConflictError,
    ApplicationError,
    ResourceNotFoundError,
    UnsupportedOperationError,
)
from device_tui.framework.errors import ResourceConflictError
from device_tui.interfaces.mcp.core import AppControlError

from .models import ErrorResponse


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        _request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        status_code = 400
        if isinstance(exc, ResourceNotFoundError):
            status_code = 404
        elif isinstance(exc, ApplicationConflictError):
            status_code = 409
        elif isinstance(exc, UnsupportedOperationError):
            status_code = 400
        payload = ErrorResponse(
            detail=exc.message,
            error={
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        )
        return JSONResponse(status_code=status_code, content=payload.model_dump())

    @app.exception_handler(ResourceConflictError)
    async def framework_resource_error_handler(
        _request: Request,
        exc: ResourceConflictError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                detail=exc.message,
                error={"code": exc.code, "message": exc.message, "details": exc.details},
            ).model_dump(),
        )

    @app.exception_handler(AppControlError)
    async def app_control_error_handler(
        _request: Request,
        exc: AppControlError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "api_version": 1,
                "detail": str(exc),
                "error": {"code": exc.code, "message": str(exc), "details": exc.details},
            },
        )
