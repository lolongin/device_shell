"""Line edit that selects all text on double-click."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLineEdit


class SelectAllLineEdit(QLineEdit):
    """A QLineEdit that selects all text on double-click."""

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setObjectName("detailValueInput")

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802
        super().mouseDoubleClickEvent(event)
        self.selectAll()
