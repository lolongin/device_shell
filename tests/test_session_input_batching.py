from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from src.app import session_ops as session_ops_module
from src.app.session_ops import SessionOpsMixin


class _FakeSession:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


class _SessionHarness(SessionOpsMixin):
    def __init__(self) -> None:
        self.session = _FakeSession()
        self.state = SimpleNamespace(
            kind="linux",
            session=self.session,
            pending_input_text="",
            input_flush_scheduled=False,
            suppress_auto_response_until_input=True,
            user_input_seen=False,
        )
        self.session_tabs_by_id = {"tab": self.state}
        self.logged: list[str] = []
        self.coroutines: list[Any] = []

    def log_session_input(self, _state: object, text: str) -> None:
        self.logged.append(text)

    def run_coro(self, coro: Any, on_success: object | None = None, on_error: object | None = None) -> None:
        _ = on_success, on_error
        self.coroutines.append(coro)

    def write_session_log_line(self, *_args: object) -> None:
        pass

    def show_error(self, _message: str) -> None:
        pass

    def handle_background_error(self, exc: Exception) -> None:
        raise exc

    def refresh_auto_response_rule_buttons(self) -> None:
        pass


def test_session_input_is_batched_until_next_ui_tick(monkeypatch: object) -> None:
    callbacks: list[Any] = []

    class FakeTimer:
        @staticmethod
        def singleShot(_interval: int, callback: Any) -> None:  # noqa: N802
            callbacks.append(callback)

    monkeypatch.setattr(session_ops_module, "QTimer", FakeTimer)
    harness = _SessionHarness()

    harness.send_session_text("tab", "a")
    harness.send_session_text("tab", "b")

    assert callbacks == [callbacks[0]]
    assert harness.logged == ["a", "b"]
    assert harness.state.pending_input_text == "ab"
    assert harness.coroutines == []

    callbacks[0]()
    assert harness.state.pending_input_text == ""
    assert harness.state.input_flush_scheduled is False
    assert len(harness.coroutines) == 1

    asyncio.run(harness.coroutines[0])
    assert harness.session.sent == ["ab"]
