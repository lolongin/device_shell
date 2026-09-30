"""Small seams used by the managed transfer application service."""

from __future__ import annotations

from typing import Callable, Protocol

from device_tui.application.terminal.orchestration import TerminalExecutionPlan

from .errors import UnsupportedOperationError
from .transfer_models import PreparedTransferSource


class TransferStore(Protocol):
    def get_meta(self, key: str) -> str | None: ...

    def set_meta(self, key: str, value: str) -> None: ...


class MemoryTransferStore:
    def __init__(self) -> None:
        self._meta: dict[str, str] = {}

    def get_meta(self, key: str) -> str | None:
        return self._meta.get(key)

    def set_meta(self, key: str, value: str) -> None:
        self._meta[key] = value


class TerminalPlanExecutor(Protocol):
    def acquire(
        self,
        session_id: str,
        owner_id: str,
        *,
        on_cancel: Callable[[], None],
    ) -> None: ...

    def release(self, session_id: str, owner_id: str) -> None: ...

    async def run(
        self,
        *,
        session_id: str,
        device_id: str,
        plan: TerminalExecutionPlan,
        owner_id: str,
        execution_id: str | None = None,
        return_on_interaction: bool = False,
    ) -> dict[str, object]: ...

    def get_execution(self, execution_id: str) -> dict[str, object]: ...

    def cancel_execution(self, execution_id: str) -> dict[str, object]: ...

    def cancel_active(self, session_id: str) -> str: ...

    def configure_managed_transfer(
        self,
        session_id: str,
        *,
        username: str,
        password: str,
        source_path: str,
        source_size: int,
        destination_path: str,
    ) -> None: ...


class UnavailableTerminalPlanExecutor:
    def acquire(self, *_args: object, **_kwargs: object) -> None:
        raise UnsupportedOperationError("Terminal operations are unavailable.")

    def release(self, *_args: object, **_kwargs: object) -> None:
        return

    async def run(self, **_kwargs: object) -> dict[str, object]:
        raise UnsupportedOperationError("Terminal operations are unavailable.")

    def get_execution(self, _execution_id: str) -> dict[str, object]:
        raise UnsupportedOperationError("Terminal operations are unavailable.")

    def cancel_execution(self, _execution_id: str) -> dict[str, object]:
        raise UnsupportedOperationError("Terminal operations are unavailable.")

    def cancel_active(self, _session_id: str) -> str:
        return ""

    def configure_managed_transfer(self, *_args: object, **_kwargs: object) -> None:
        return
