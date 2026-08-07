from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from src.widgets.sidebar_splitter import SidebarSplitter


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_handle_index_matches_widget_position(app: QApplication) -> None:
    """SidebarSplitterHandle.handle_index() must return the handle's position in
    the splitter. Regression: it called the non-existent QSplitter.handleIndex(),
    raising AttributeError on every left-click drag, which broke all splitter
    boundary dragging (session-manager panel width could not be adjusted)."""
    _ = app
    splitter = SidebarSplitter(Qt.Horizontal)
    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())
    splitter.show()
    app.processEvents()

    for expected_index in range(splitter.count()):
        handle = splitter.handle(expected_index)
        assert handle.handle_index() == expected_index

    splitter.close()


def test_mouse_press_on_handle_emits_drag_started(app: QApplication) -> None:
    """A left-click press on a splitter handle must emit drag_started with the
    correct index. Regression: the press handler raised AttributeError, so no
    drag was ever started."""
    _ = app
    splitter = SidebarSplitter(Qt.Horizontal)
    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())
    splitter.addWidget(QWidget())
    splitter.show()
    app.processEvents()

    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QSignalSpy

    handle = splitter.handle(2)
    spy = QSignalSpy(splitter.drag_started)
    center = handle.rect().center()
    global_center = handle.mapToGlobal(center)
    press = QMouseEvent(
        QEvent.MouseButtonPress,
        center,
        global_center,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(handle, press)
    app.processEvents()

    assert spy.count() == 1
    assert spy.at(0)[0] == 2

    splitter.close()
