"""Main workspace splitter with explicit drag lifecycle signals."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QSplitterHandle, QWidget


class SidebarSplitterHandle(QSplitterHandle):
    """Splitter handle that reports when a user drag starts and finishes.

    The drag signals carry this handle's index so consumers can tell the left
    sidebar boundary (handle index 1) apart from the right session-manager
    boundary (handle index 2). A left-boundary drag drives the left-sidebar
    sizing lifecycle; a right-boundary drag only updates the right panel width.
    """

    drag_started = Signal(int)  # handle index
    drag_finished = Signal(int, int)  # (left panel width, handle index)

    def handle_index(self) -> int:
        splitter = self.splitter()
        if splitter is None:
            return 0
        # QSplitter has no handleIndex(); indexOf(handle) returns the handle's
        # position, which matches the handle-index contract used elsewhere
        # (handle 1 = left sidebar boundary, handle 2 = session-manager width).
        return splitter.indexOf(self)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.drag_started.emit(self.handle_index())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            sizes = self.splitter().sizes()
            self.drag_finished.emit(sizes[0] if sizes else 0, self.handle_index())


class SidebarSplitter(QSplitter):
    """Horizontal splitter used by the activity rail and left workspace."""

    drag_started = Signal(int)  # handle index
    drag_finished = Signal(int, int)  # (left panel width, handle index)

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self.setObjectName("mainSplitter")

    def createHandle(self) -> QSplitterHandle:  # noqa: N802
        handle = SidebarSplitterHandle(self.orientation(), self)
        handle.setObjectName("mainSplitterHandle")
        handle.drag_started.connect(self.drag_started.emit)
        handle.drag_finished.connect(self.drag_finished.emit)
        return handle

    def set_collapse_hint(self, enabled: bool) -> None:
        handle = self.handle(1) if self.count() > 1 else None
        if handle is None:
            return
        enabled = bool(enabled)
        if bool(handle.property("collapseHint")) == enabled:
            return
        handle.setProperty("collapseHint", enabled)
        handle.setToolTip("释放以收起" if enabled else "拖动调整左侧宽度")
        style = handle.style()
        style.unpolish(handle)
        style.polish(handle)
        handle.update()
