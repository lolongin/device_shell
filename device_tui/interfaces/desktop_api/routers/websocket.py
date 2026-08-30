"""Authenticated event and terminal WebSocket endpoints."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..context import BackendContext
from ..session_hub import TerminalEvent

router = APIRouter(tags=["websocket"])

TERMINAL_SOCKET_BATCH_EVENTS = 128
TERMINAL_SOCKET_BATCH_CHARS = 64 * 1024


def _coalesce_terminal_events(
    events: list[TerminalEvent],
    *,
    max_events: int = TERMINAL_SOCKET_BATCH_EVENTS,
    max_chars: int = TERMINAL_SOCKET_BATCH_CHARS,
) -> list[TerminalEvent]:
    """Merge contiguous output events without crossing status or gap boundaries."""
    result: list[TerminalEvent] = []
    pending: list[TerminalEvent] = []
    pending_chars = 0

    def flush() -> None:
        nonlocal pending_chars
        if not pending:
            return
        if len(pending) == 1:
            result.append(pending[0])
        else:
            first = pending[0]
            last = pending[-1]
            result.append(TerminalEvent(
                type="terminal.output",
                session_id=first.session_id,
                sequence=last.sequence,
                data="".join(event.data for event in pending),
                generation=first.generation,
                metadata=dict(first.metadata),
            ))
        pending.clear()
        pending_chars = 0

    for event in events:
        can_merge = (
            event.type == "terminal.output"
            and (
                not pending
                or (
                    event.session_id == pending[-1].session_id
                    and event.generation == pending[-1].generation
                    and event.metadata == pending[-1].metadata
                    and event.sequence == pending[-1].sequence + 1
                )
            )
        )
        would_exceed = pending and (
            len(pending) >= max_events
            or pending_chars + len(event.data) > max_chars
        )
        if not can_merge or would_exceed:
            flush()
        if event.type == "terminal.output":
            pending.append(event)
            pending_chars += len(event.data)
        else:
            result.append(event)
    flush()
    return result


def _authorized(ctx: BackendContext, access: str, ticket: str, scope: str, resource_id: str = "") -> bool:
    return bool(ctx.access_token and access == ctx.access_token) or ctx.ticket_store.consume(
        ticket, scope, resource_id
    )


@router.websocket("/ws/v1/events")
async def event_socket(
    websocket: WebSocket,
    access: str = Query(default=""),
    ticket: str = Query(default=""),
    after: int = Query(default=0, ge=0),
) -> None:
    ctx: BackendContext = websocket.app.state.context
    if not _authorized(ctx, access, ticket, "events"):
        await websocket.close(code=4401, reason="Invalid desktop token")
        return
    queue, replay = ctx.desktop.events.subscribe(after_sequence=after)
    await websocket.accept()
    try:
        for event in replay:
            await websocket.send_json(event.to_payload())
        while True:
            event = await queue.get()
            await websocket.send_json(event.to_payload())
    except WebSocketDisconnect:
        pass
    finally:
        ctx.desktop.events.unsubscribe(queue)


@router.websocket("/ws/v1/terminals/{session_id}")
async def terminal_socket(
    websocket: WebSocket,
    session_id: str,
    access: str = Query(default=""),
    ticket: str = Query(default=""),
    after: int = Query(default=0, ge=0),
) -> None:
    ctx: BackendContext = websocket.app.state.context
    if not _authorized(ctx, access, ticket, "terminal", session_id):
        await websocket.close(code=4401, reason="Invalid desktop token")
        return
    try:
        queue, replay = ctx.hub.subscribe(session_id, after_sequence=after)
    except KeyError:
        await websocket.close(code=4404, reason="Unknown session")
        return
    await websocket.accept()
    for event in _coalesce_terminal_events(replay):
        await websocket.send_json(event.to_payload())

    async def send_events() -> None:
        while True:
            events: list[TerminalEvent] = [await queue.get()]
            for _ in range(TERMINAL_SOCKET_BATCH_EVENTS - 1):
                try:
                    events.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            for event in _coalesce_terminal_events(events):
                await websocket.send_json(event.to_payload())

    async def receive_commands() -> None:
        while True:
            message = await websocket.receive_json()
            kind = str(message.get("type") or "")
            try:
                if kind == "terminal.input":
                    await ctx.hub.write(session_id, str(message.get("data") or ""))
                elif kind == "terminal.resize":
                    await ctx.hub.resize(
                        session_id,
                        int(message.get("cols") or 80),
                        int(message.get("rows") or 24),
                    )
                elif kind == "terminal.reconnect":
                    await ctx.hub.reconnect(session_id)
            except KeyError:
                await websocket.close(code=4404, reason="Session closed")
                return

    sender = asyncio.create_task(send_events())
    receiver = asyncio.create_task(receive_commands())
    try:
        done, pending = await asyncio.wait(
            {sender, receiver},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            with suppress(WebSocketDisconnect):
                task.result()
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        receiver.cancel()
        ctx.hub.unsubscribe(session_id, queue)
