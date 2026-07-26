from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.app.command_record_ops import CommandRecordOpsMixin
from src.widgets.terminal_canvas import TerminalCanvasWidget
from src.widgets.terminal_widget import InteractiveTerminal
from src.widgets.xterm_web_widget import XtermWebWidget


class _TerminalSpy:
    def __init__(self, events: list[object]) -> None:
        self._events = events

    def scroll_to_live_input(self) -> None:
        self._events.append("scroll")


class _CommandInput:
    def __init__(self, command: str) -> None:
        self._command = command

    def selected_or_current_command_text(self) -> str:
        return self._command


class _CommandHarness(CommandRecordOpsMixin):
    def __init__(self, *, command: str = "display version") -> None:
        self.events: list[object] = []
        self.terminal = _TerminalSpy(self.events)
        self.state = SimpleNamespace(
            tab_id="terminal-1",
            terminal=self.terminal,
            session=SimpleNamespace(is_connected=True),
        )
        self.session_tabs_by_id = {self.state.tab_id: self.state}
        self.command_record_input = _CommandInput(command)

    def current_session_state(self) -> object:
        return self.state

    def send_session_text(self, tab_id: str, text: str) -> None:
        self.events.append(("send", tab_id, text))

    def focus_current_terminal(self, *, force: bool = False) -> None:
        self.events.append(("focus", force))

    def _save_current_command_content(self) -> None:
        self.events.append("save")

    def remember_command_history(self, command: str, state: object | None = None) -> None:
        del state
        self.events.append(("history", command))

    def schedule_desktop_state_save(self) -> None:
        self.events.append("schedule-save")

    def set_status_message(self, message: str) -> None:
        self.events.append(("status", message))


def test_single_terminal_send_scrolls_to_live_input_before_sending() -> None:
    harness = _CommandHarness()

    harness.send_command_text_to_current_session("display version")

    assert harness.events == [
        "scroll",
        ("send", "terminal-1", "display version\r"),
        ("focus", True),
    ]


def test_broadcast_send_does_not_change_current_terminal_scroll_position() -> None:
    harness = _CommandHarness()

    harness.broadcast_command_record_input()

    assert "scroll" not in harness.events
    assert ("send", "terminal-1", "display version\r") in harness.events


def test_all_terminal_renderers_expose_live_input_scrolling() -> None:
    assert callable(InteractiveTerminal.scroll_to_live_input)
    assert callable(TerminalCanvasWidget.scroll_to_live_input)
    assert callable(XtermWebWidget.scroll_to_live_input)


def test_xterm_live_input_action_clears_selection_and_scrolls_to_bottom() -> None:
    page = (
        Path(__file__).resolve().parents[1] / "src" / "web" / "xterm_terminal.html"
    ).read_text(encoding="utf-8")

    assert "scrollToLiveInput()" in page
    assert "term.clearSelection();" in page
    assert "term.scrollToBottom();" in page
