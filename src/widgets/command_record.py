"""Command record input widget with resize handle."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QTextCursor, QTextFormat
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QTextEdit, QWidget


class _CommandRecordLineNumberArea(QWidget):
    def __init__(self, editor: "CommandRecordInput") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self._editor.line_number_area_paint_event(event)


class CommandRecordInput(QPlainTextEdit):
    """Multi-line input for recording device commands."""

    def __init__(self) -> None:
        super().__init__()
        self._submit_handler: Callable[[str], None] | None = None
        self._suggestion_accept_handler: Callable[[], bool] | None = None
        self._enter_sends = False
        self._theme_mode = "dark"
        self.setObjectName("commandRecordEditor")
        self.setMinimumHeight(72)
        self.setMaximumHeight(16777215)
        self.setTabChangesFocus(True)
        self.setUndoRedoEnabled(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setPlaceholderText("在此输入命令...")
        self._line_number_area = _CommandRecordLineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width()
        self.highlight_current_line()

    def set_theme(self, mode: str) -> None:
        """Record the active theme so the line-number gutter and current-line
        highlight pick matching colors."""
        self._theme_mode = "light" if mode == "light" else "dark"
        self._line_number_area.update()
        self.highlight_current_line()

    def set_submit_handler(self, handler: Callable[[str], None]) -> None:
        self._submit_handler = handler

    def set_suggestion_accept_handler(self, handler: Callable[[], bool]) -> None:
        self._suggestion_accept_handler = handler

    def set_enter_sends(self, enter_sends: bool) -> None:
        self._enter_sends = enter_sends

    def current_command_line(self) -> str:
        return self.textCursor().block().text().strip()

    def selected_or_current_command_text(self) -> str:
        cursor = self.textCursor()
        if cursor.hasSelection():
            selected = cursor.selectedText().replace("\u2029", "\n")
            return selected.strip()
        return self.current_command_line()

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width()

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        contents_rect = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(contents_rect.left(), contents_rect.top(), self.line_number_area_width(), contents_rect.height())
        )

    def highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        line_bg = QColor("#e8ebef") if self._theme_mode == "light" else QColor("#111c2f")
        selection.format.setBackground(line_bg)
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def line_number_area_paint_event(self, event: object) -> None:
        light = self._theme_mode == "light"
        area_bg = QColor("#eef0f3") if light else QColor("#08101d")
        current_fg = QColor("#1c2128") if light else QColor("#f8fafc")
        normal_fg = QColor("#5a6470") if light else QColor("#718096")
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), area_bg)
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        current_block = self.textCursor().blockNumber()
        width = self._line_number_area.width() - 5
        height = self.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                is_current = block_number == current_block
                painter.setPen(current_fg if is_current else normal_fg)
                painter.drawText(0, top, width, height, Qt.AlignRight, str(block_number + 1))
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

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
                command = self.selected_or_current_command_text()
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


class HorizontalResizeHandle(QFrame):
    """Draggable horizontal resize handle."""

    def __init__(
        self,
        resize_handler: Callable[[int], None],
        parent: QWidget,
        width_provider: Callable[[], int] | None = None,
    ) -> None:
        super().__init__(parent)
        self._resize_handler = resize_handler
        self._width_provider = width_provider
        self._drag_start_x = 0
        self._drag_start_width = 0
        self.setObjectName("horizontalResizeHandle")
        self.setFixedWidth(6)
        self.setCursor(Qt.SizeHorCursor)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_start_x = self._event_global_x(event)
            parent = self.parentWidget()
            if self._width_provider is not None:
                self._drag_start_width = self._width_provider()
            else:
                self._drag_start_width = parent.width() if parent is not None else 0
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        delta = self._event_global_x(event) - self._drag_start_x
        self._resize_handler(self._drag_start_width + delta)
        event.accept()

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            event.accept()
            return
        super().mouseReleaseEvent(event)

    @staticmethod
    def _event_global_x(event: Any) -> int:
        if hasattr(event, "globalPosition"):
            return int(event.globalPosition().toPoint().x())
        return int(event.globalX())


class VerticalResizeHandle(QFrame):
    """Draggable vertical resize handle."""

    def __init__(
        self,
        resize_handler: Callable[[int], None],
        parent: QWidget,
        height_provider: Callable[[], int] | None = None,
        *,
        grow_down: bool = True,
    ) -> None:
        super().__init__(parent)
        self._resize_handler = resize_handler
        self._height_provider = height_provider
        self._grow_down = grow_down
        self._drag_start_y = 0
        self._drag_start_height = 0
        self.setObjectName("verticalResizeHandle")
        self.setFixedHeight(6)
        self.setCursor(Qt.SizeVerCursor)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_start_y = self._event_global_y(event)
            parent = self.parentWidget()
            if self._height_provider is not None:
                self._drag_start_height = self._height_provider()
            else:
                self._drag_start_height = parent.height() if parent is not None else 0
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802
        if not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        delta = self._event_global_y(event) - self._drag_start_y
        if not self._grow_down:
            delta = -delta
        self._resize_handler(self._drag_start_height + delta)
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
