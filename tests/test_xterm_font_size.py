from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.widgets.xterm_web_widget import XtermWebWidget


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_set_font_size_queues_js_and_reenables_on_ready(app: QApplication) -> None:
    _ = app
    widget = XtermWebWidget()
    ran: list[str] = []
    widget._run_js = lambda script: ran.append(script)  # type: ignore[method-assign]

    widget.set_font_size(18)

    assert widget._font_size == 18
    assert any("deviceTerminal.setFontSize(18)" in script for script in ran)

    # Simulate readiness after the pending size is set
    ran.clear()
    widget._ready = True
    widget._handle_ready()
    assert any("deviceTerminal.setFontSize(18)" in script for script in ran)

    widget.close()
