"""Input behavior tests for the custom terminal canvas."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from src.widgets.terminal_canvas import TerminalCanvasWidget


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _press(widget: TerminalCanvasWidget, key: int, modifiers: Qt.KeyboardModifier = Qt.NoModifier, text: str = "") -> None:
    event = QKeyEvent(QEvent.KeyPress, key, modifiers, text)
    widget.keyPressEvent(event)


def _send_event(widget: TerminalCanvasWidget, key: int, modifiers: Qt.KeyboardModifier = Qt.NoModifier, text: str = "") -> bool:
    event = QKeyEvent(QEvent.KeyPress, key, modifiers, text)
    return widget.event(event)


def _terminal_with_sender(app: QApplication) -> tuple[TerminalCanvasWidget, list[str]]:
    _ = app
    sent: list[str] = []
    terminal = TerminalCanvasWidget()
    terminal.set_raw_sender(sent.append)
    return terminal, sent


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (Qt.Key_A, "\x01"),
        (Qt.Key_B, "\x02"),
        (Qt.Key_C, "\x03"),
        (Qt.Key_D, "\x04"),
        (Qt.Key_E, "\x05"),
        (Qt.Key_K, "\x0b"),
        (Qt.Key_L, "\x0c"),
        (Qt.Key_R, "\x12"),
        (Qt.Key_V, "\x16"),
        (Qt.Key_Z, "\x1a"),
    ],
)
def test_ctrl_letter_sends_terminal_control_character(app: QApplication, key: int, expected: str) -> None:
    terminal, sent = _terminal_with_sender(app)

    _press(terminal, key, Qt.ControlModifier)

    assert sent == [expected]


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (Qt.Key_Left, "\x1b[D"),
        (Qt.Key_Right, "\x1b[C"),
        (Qt.Key_Up, "\x1b[A"),
        (Qt.Key_Down, "\x1b[B"),
        (Qt.Key_Delete, "\x1b[3~"),
        (Qt.Key_Home, "\x1b[H"),
        (Qt.Key_End, "\x1b[F"),
        (Qt.Key_PageUp, "\x1b[5~"),
        (Qt.Key_PageDown, "\x1b[6~"),
    ],
)
def test_navigation_keys_send_escape_sequences(app: QApplication, key: int, expected: str) -> None:
    terminal, sent = _terminal_with_sender(app)

    _press(terminal, key)

    assert sent == [expected]


def test_tab_key_event_is_sent_to_terminal_instead_of_changing_focus(app: QApplication) -> None:
    terminal, sent = _terminal_with_sender(app)

    handled = _send_event(terminal, Qt.Key_Tab, Qt.NoModifier, "\t")

    assert handled is True
    assert sent == ["\t"]


def test_shift_tab_key_event_sends_backtab_sequence(app: QApplication) -> None:
    terminal, sent = _terminal_with_sender(app)

    handled = _send_event(terminal, Qt.Key_Backtab, Qt.ShiftModifier)

    assert handled is True
    assert sent == ["\x1b[Z"]


def test_enter_invokes_reconnect_handler_before_sending_return(app: QApplication) -> None:
    terminal, sent = _terminal_with_sender(app)
    reconnect_calls: list[bool] = []
    terminal.set_enter_reconnect_handler(lambda: reconnect_calls.append(True) or True)

    _press(terminal, Qt.Key_Return)

    assert reconnect_calls == [True]
    assert sent == []


def test_enter_sends_return_when_reconnect_handler_declines(app: QApplication) -> None:
    terminal, sent = _terminal_with_sender(app)
    terminal.set_enter_reconnect_handler(lambda: False)

    _press(terminal, Qt.Key_Return)

    assert sent == ["\r"]


def test_ctrl_shift_v_pastes_clipboard_instead_of_control_v(app: QApplication) -> None:
    terminal, sent = _terminal_with_sender(app)
    QApplication.clipboard().setText("paste me")

    _press(terminal, Qt.Key_V, Qt.ControlModifier | Qt.ShiftModifier)

    assert sent == ["paste me"]


def test_bracketed_paste_wraps_clipboard_when_enabled(app: QApplication) -> None:
    terminal, sent = _terminal_with_sender(app)
    terminal.set_bracketed_paste_enabled(True)
    terminal.set_confirm_multiline_paste(False)
    QApplication.clipboard().setText("line1\nline2")

    _press(terminal, Qt.Key_V, Qt.ControlModifier | Qt.ShiftModifier)

    assert sent == ["\x1b[200~line1\nline2\x1b[201~"]


def test_large_paste_is_sent_in_chunks(app: QApplication) -> None:
    terminal, sent = _terminal_with_sender(app)
    QApplication.clipboard().setText("x" * (terminal.PASTE_CHUNK_SIZE + 3))

    _press(terminal, Qt.Key_V, Qt.ControlModifier | Qt.ShiftModifier)

    assert sent == ["x" * terminal.PASTE_CHUNK_SIZE, "xxx"]


def test_ctrl_shift_c_copies_selection_instead_of_sending_interrupt(app: QApplication) -> None:
    terminal, sent = _terminal_with_sender(app)
    terminal.append_output("abcdef\n")
    terminal._flush_pending_output()
    terminal._selection_anchor = (0, 1)
    terminal._selection_cursor = (0, 3)

    _press(terminal, Qt.Key_C, Qt.ControlModifier | Qt.ShiftModifier)

    assert sent == []
    assert QApplication.clipboard().text() == "bcd"


def test_ctrl_c_copies_selection_when_text_is_selected(app: QApplication) -> None:
    terminal, sent = _terminal_with_sender(app)
    terminal.append_output("abcdef\n")
    terminal._flush_pending_output()
    terminal._selection_anchor = (0, 2)
    terminal._selection_cursor = (0, 4)

    _press(terminal, Qt.Key_C, Qt.ControlModifier)

    assert sent == []
    assert QApplication.clipboard().text() == "cde"


def test_copy_all_copies_history_and_visible_screen(app: QApplication) -> None:
    terminal, _sent = _terminal_with_sender(app)
    terminal.resize(900, 160)
    terminal.append_output("".join(f"line{i}\n" for i in range(20)))
    terminal._flush_pending_output()

    terminal.copy_all()

    clipboard_text = QApplication.clipboard().text()
    assert "line0" in clipboard_text
    assert "line19" in clipboard_text


def test_clear_terminal_resets_visible_text(app: QApplication) -> None:
    terminal, _sent = _terminal_with_sender(app)
    terminal.append_output("abc\n")
    terminal._flush_pending_output()

    terminal.clear_terminal()

    assert terminal.visible_text() == ""
    assert terminal.all_text() == ""


def test_select_word_at_cell(app: QApplication) -> None:
    terminal, _sent = _terminal_with_sender(app)
    terminal.append_output("show interface GigabitEthernet0/0/1\n")
    terminal._flush_pending_output()

    terminal._select_word_at((0, 18))

    assert terminal.selected_text() == "GigabitEthernet0/0/1"


def test_select_line_at_cell(app: QApplication) -> None:
    terminal, _sent = _terminal_with_sender(app)
    terminal.append_output("display current-configuration\n")
    terminal._flush_pending_output()

    terminal._select_line_at((0, 3))

    assert terminal.selected_text() == "display current-configuration"


def test_multiline_paste_detection() -> None:
    assert TerminalCanvasWidget._is_multiline_paste("line1\nline2")
    assert not TerminalCanvasWidget._is_multiline_paste("line1\n")


def test_hot_paths_do_not_materialize_full_history(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    terminal, _sent = _terminal_with_sender(app)
    terminal.resize(1000, 500)
    terminal.append_output("".join("line%d\n" % index for index in range(7000)))
    for _index in range(20):
        if not terminal._pending_output_chunks:
            break
        terminal._flush_pending_output()
    assert terminal._history_top_length() == terminal.DEFAULT_HISTORY

    def fail_full_history_walk() -> list[object]:
        pytest.fail("hot terminal path materialized the full scrollback history")

    monkeypatch.setattr(terminal, "_all_terminal_lines", fail_full_history_walk)

    terminal.append_output("tail\n")
    terminal._flush_pending_output()
    terminal._scroll_by(12)
    assert "line" in terminal.visible_text()

    first_visible = terminal._first_visible_line_index()
    terminal._selection_anchor = (first_visible, 0)
    terminal._selection_cursor = (first_visible + 1, 4)
    assert terminal.selected_text()

    image = terminal.grab()
    assert image.size().width() > 0


def test_plain_terminal_row_is_drawn_as_one_text_run(app: QApplication) -> None:
    terminal, _sent = _terminal_with_sender(app)
    default_cell = terminal._screen.default_char
    line = {index: SimpleNamespace(data=char) for index, char in enumerate("abc")}

    class FakePainter:
        def __init__(self) -> None:
            self.text_runs: list[str] = []

        def setFont(self, _font: object) -> None:  # noqa: N802
            pass

        def setPen(self, _pen: object) -> None:  # noqa: N802
            pass

        def fillRect(self, *_args: object) -> None:  # noqa: N802
            pass

        def drawText(self, _point: object, text: str) -> None:  # noqa: N802
            self.text_runs.append(text)

        def drawLine(self, *_args: object) -> None:  # noqa: N802
            pass

    painter = FakePainter()

    terminal._paint_terminal_row(
        painter,
        line,
        row=0,
        absolute_row=0,
        columns=80,
        baseline=terminal._baseline_offset,
        cursor_col=-1,
        default_cell=default_cell,
    )

    assert painter.text_runs == ["abc"]


def test_large_paste_does_not_fill_command_record_buffer(app: QApplication) -> None:
    terminal, _sent = _terminal_with_sender(app)
    terminal._record_local_text("x" * (terminal.MAX_COMMAND_RECORD_CHARS + 1))

    assert terminal._pending_command_chars == []
