"""Command record input widget with resize handle."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QWidget


class CommandRecordInput(QPlainTextEdit):
    """Multi-line input for recording device commands."""

    def __init__(self) -> None:
        super().__init__()
        self._submit_handler: Callable[[str], None] | None = None
        self._suggestion_accept_handler: Callable[[], bool] | None = None
        self._enter_sends = False
        self.setObjectName("commandRecordEditor")
        self.setMinimumHeight(72)
        self.setMaximumHeight(16777215)
        self.setTabChangesFocus(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setPlaceholderText("在此输入命令...")

    def set_submit_handler(self, handler: Callable[[str], None]) -> None:
        self._submit_handler = handler

    def set_suggestion_accept_handler(self, handler: Callable[[], bool]) -> None:
        self._suggestion_accept_handler = handler

    def set_enter_sends(self, enter_sends: bool) -> None:
        self._enter_sends = enter_sends

    def current_command_line(self) -> str:
        return self.textCursor().block().text().strip()

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        key = event.key()
        modifiers = event.modifiers()
        if modifiers == Qt.NoModifier:
            if key == Qt.Key_Left:
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.Left)
                self.setTextCursor(cursor)
                self.ensureCursorVisible()
                return
            if key == Qt.Key_Right:
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.Right)
                self.setTextCursor(cursor)
                self.ensureCursorVisible()
                return
            if key == Qt.Key_Home:
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.StartOfLine)
                self.setTextCursor(cursor)
                self.ensureCursorVisible()
                return
            if key == Qt.Key_End:
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.EndOfLine)
                self.setTextCursor(cursor)
                self.ensureCursorVisible()
                return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            ctrl_pressed = bool(modifiers & Qt.ControlModifier)
            should_submit = not ctrl_pressed if self._enter_sends else ctrl_pressed
            if should_submit:
                command = self.current_command_line()
                if command and self._submit_handler is not None:
                    self._submit_handler(command)
                return
            self.insertPlainText("\n")
            return
        if key == Qt.Key_Tab and modifiers == Qt.NoModifier:
            if self._suggestion_accept_handler is not None and self._suggestion_accept_handler():
                return
        super().keyPressEvent(event)


class CommandRecordResizeHandle(QFrame):
    """Draggable resize handle for the command record panel."""

    def __init__(self, resize_handler: Callable[[int], None], parent: QWidget) -> None:
        super().__init__(parent)
        self._resize_handler = resize_handler
        self._drag_start_y = 0
        self._drag_start_height = 0
        self.setObjectName("commandRecordResizeHandle")
        self.setFixedHeight(5)
        self.setCursor(Qt.SizeVerCursor)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_start_y = self._event_global_y(event)
            parent = self.parentWidget()
            self._drag_start_height = parent.height() if parent is not None else 0
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        delta = self._event_global_y(event) - self._drag_start_y
        self._resize_handler(self._drag_start_height - delta)
        event.accept()

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    @staticmethod
    def _event_global_y(event: Any) -> int:
        if hasattr(event, "globalPosition"):
            return int(event.globalPosition().toPoint().y())
        return int(event.globalY())
