"""Device list table widget with copy support."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QTableWidget,
    QWidget,
)


class NoFocusItemDelegate(QStyledItemDelegate):
    """Delegate that hides the dotted focus rectangle on table cells."""

    def paint(self, painter: Any, option: Any, index: Any) -> None:
        clean_option = QStyleOptionViewItem(option)
        clean_option.state &= ~QStyle.State_HasFocus
        super().paint(painter, clean_option, index)


class CopyableDeviceTable(QTableWidget):
    """A table widget that copies the selected cell value on Ctrl+C."""

    def __init__(
        self,
        copy_handler: Callable[["CopyableDeviceTable"], None],
        field_copy_handler: Callable[["CopyableDeviceTable", str], None],
        parent: QWidget,
    ) -> None:
        super().__init__(0, 0, parent)
        self._copy_handler = copy_handler
        self._field_copy_handler = field_copy_handler
        self._stretch_column = 1
        self._stretch_base = 200
        self._adapt_timer: QTimer | None = None
        self.setItemDelegate(NoFocusItemDelegate(self))

    def set_stretch_column(self, column: int) -> None:
        self._stretch_column = column

    def set_stretch_base(self, width: int) -> None:
        self._stretch_base = width

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._adapt_timer is None:
            self._adapt_timer = QTimer(self)
            self._adapt_timer.setSingleShot(True)
            self._adapt_timer.timeout.connect(self._spread)
        if not self._adapt_timer.isActive():
            self._adapt_timer.start(30)

    def _spread(self) -> None:
        vp = self.viewport()
        if vp is None:
            return
        available = vp.width()
        other_total = 0
        for col in range(self.columnCount()):
            if col != self._stretch_column:
                other_total += self.columnWidth(col)
        if other_total <= 0:
            return
        desired = max(40, available - other_total)
        self.setColumnWidth(self._stretch_column, desired)

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        if event.matches(QKeySequence.Copy):
            self._copy_handler(self)
            return
        if event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier):
            key_map = {
                Qt.Key_S: "ssh_ip",
                Qt.Key_T: "telnet_ip",
                Qt.Key_U: "username",
                Qt.Key_P: "password",
            }
            field = key_map.get(event.key())
            if field is not None:
                self._field_copy_handler(self, field)
                return
        super().keyPressEvent(event)
