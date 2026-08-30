"""FastAPI dependencies for the desktop API."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

from .context import BackendContext


def get_context(request: Request) -> BackendContext:
    return request.app.state.context


def authorize(
    request: Request,
    authorization: str = Header(default=""),
) -> None:
    context = get_context(request)
    if context.access_token and authorization != f"Bearer {context.access_token}":
        raise HTTPException(status_code=401, detail="Invalid desktop token")
