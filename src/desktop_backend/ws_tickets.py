"""Single-use, short-lived tickets for renderer WebSocket attachment."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import Literal


TicketScope = Literal["terminal", "events"]


@dataclass(frozen=True, slots=True)
class WebSocketTicket:
    value: str
    scope: TicketScope
    resource_id: str
    expires_at: float


class WebSocketTicketStore:
    def __init__(self, lifetime_seconds: float = 30.0) -> None:
        self._lifetime_seconds = max(1.0, float(lifetime_seconds))
        self._tickets: dict[str, WebSocketTicket] = {}
        self._lock = Lock()

    def issue(self, scope: TicketScope, resource_id: str = "") -> WebSocketTicket:
        now = time.monotonic()
        ticket = WebSocketTicket(
            value=secrets.token_urlsafe(32),
            scope=scope,
            resource_id=resource_id,
            expires_at=now + self._lifetime_seconds,
        )
        with self._lock:
            self._prune(now)
            self._tickets[ticket.value] = ticket
        return ticket

    def consume(self, value: str, scope: TicketScope, resource_id: str = "") -> bool:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            ticket = self._tickets.pop(value, None)
        return bool(
            ticket is not None
            and ticket.scope == scope
            and ticket.resource_id == resource_id
            and ticket.expires_at >= now
        )

    def _prune(self, now: float) -> None:
        expired = [value for value, ticket in self._tickets.items() if ticket.expires_at < now]
        for value in expired:
            self._tickets.pop(value, None)
