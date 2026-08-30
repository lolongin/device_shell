"""Short-lived WebSocket ticket issuance."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from device_tui.application import ResourceNotFoundError, UnsupportedOperationError

from ..dependencies import authorize, get_context
from ..models import WebSocketTicketRequest, WebSocketTicketResponse

router = APIRouter(prefix="/api/v1", tags=["websocket"], dependencies=[Depends(authorize)])


@router.post("/ws-tickets", response_model=WebSocketTicketResponse)
async def issue_websocket_ticket(request: WebSocketTicketRequest, ctx=Depends(get_context)) -> WebSocketTicketResponse:
    if request.scope == "terminal":
        try:
            ctx.hub.get(request.resource_id)
        except KeyError as exc:
            raise ResourceNotFoundError(f"Unknown session: {request.resource_id}", details={"resource": "session", "session_id": request.resource_id}) from exc
    elif request.resource_id:
        raise UnsupportedOperationError("The events ticket does not accept a resource id.")
    ticket = ctx.ticket_store.issue(request.scope, request.resource_id)
    return WebSocketTicketResponse(ticket=ticket.value, expires_in_seconds=30)
