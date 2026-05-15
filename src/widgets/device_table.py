"""Device list table widget with copy support."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
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
        self.setItemDelegate(NoFocusItemDelegate(self))

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
