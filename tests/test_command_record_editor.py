from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from src.widgets.command_record import CommandRecordInput


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_command_record_editor_supports_undo_redo(app: QApplication) -> None:
    _ = app
    editor = CommandRecordInput()

    editor.setPlainText("display version")
    editor.selectAll()
    editor.insertPlainText("display ip interface brief")
    assert editor.toPlainText() == "display ip interface brief"

    editor.undo()
    assert editor.toPlainText() == "display version"
    editor.redo()
    assert editor.toPlainText() == "display ip interface brief"


def test_command_record_editor_uses_selection_for_submit_text(app: QApplication) -> None:
    _ = app
    editor = CommandRecordInput()
    editor.setPlainText("display version\ndisplay ip interface brief\ndisplay clock")

    cursor = editor.textCursor()
    cursor.setPosition(len("display version\n"))
    cursor.setPosition(
        len("display version\ndisplay ip interface brief"),
        QTextCursor.KeepAnchor,
    )
    editor.setTextCursor(cursor)

    assert editor.selected_or_current_command_text() == "display ip interface brief"


def test_command_record_editor_reserves_line_number_gutter(app: QApplication) -> None:
    _ = app
    editor = CommandRecordInput()

    initial_width = editor.line_number_area_width()
    editor.setPlainText("\n".join(f"display line {index}" for index in range(120)))

    assert editor.line_number_area_width() > initial_width
    assert editor.viewportMargins().left() == editor.line_number_area_width()
