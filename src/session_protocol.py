from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol


SessionTarget = Literal["linux", "device"]
OutputEmitter = Callable[[str], None]
StatusEmitter = Callable[[str], None]


class SessionError(Exception):
    """Base exception raised by command session implementations."""


class SessionUnavailableError(SessionError):
    """Raised when a session backend is not available in the current environment."""


class CommandSession(Protocol):
    async def connect(self, *args: object, **kwargs: object) -> None:
        ...

    async def disconnect(self, message: str = "Disconnected.") -> None:
        ...

    async def send_text(self, text: str) -> None:
        ...

    async def send_command(self, command: str) -> None:
        ...

    @property
    def is_connected(self) -> bool:
        ...


@dataclass(slots=True)
class SessionCallbacks:
    on_output: OutputEmitter
    on_status: StatusEmitter
