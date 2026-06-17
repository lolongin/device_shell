"""Device list table widget with copy support."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QTableView,
    QTableWidget,
    QWidget,
)


class NoFocusItemDelegate(QStyledItemDelegate):
    """Delegate that hides the dotted focus rectangle on table cells."""

    def paint(self, painter: Any, option: Any, index: Any) -> None:
        clean_option = QStyleOptionViewItem(option)
        clean_option.state &= ~QStyle.State_HasFocus
        super().paint(painter, clean_option, index)


class _HeaderItem:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class _VirtualTableItem:
    def __init__(self, table: "VirtualDeviceTable", row: int, column: int) -> None:
        self._table = table
        self._row = row
        self._column = column

    @property
    def row(self) -> int:
        return self._row

    @property
    def column(self) -> int:
        return self._column

    def text(self) -> str:
        return str(self._table.model().index(self._row, self._column).data(Qt.DisplayRole) or "")

    def data(self, role: int) -> object:
        return self._table.model().index(self._row, self._column).data(role)

    def toolTip(self) -> str:  # noqa: N802
        return str(self._table.model().index(self._row, self._column).data(Qt.ToolTipRole) or "")

    def background(self) -> QBrush:
        value = self._table.model().index(self._row, self._column).data(Qt.BackgroundRole)
        return value if isinstance(value, QBrush) else QBrush()

    def foreground(self) -> QBrush:
        value = self._table.model().index(self._row, self._column).data(Qt.ForegroundRole)
        return value if isinstance(value, QBrush) else QBrush()


class VirtualDeviceTableModel(QAbstractTableModel):
    """Lightweight table model for large device lists."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._headers: list[str] = []
        self._rows: list[dict[str, object]] = []

    def set_headers(self, headers: list[str]) -> None:
        self.beginResetModel()
        self._headers = headers
        self.endResetModel()

    def set_rows(self, rows: list[dict[str, object]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def row_payload(self, row: int) -> dict[str, object] | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def cell_payload(self, row: int, column: int) -> dict[str, object] | None:
        row_payload = self.row_payload(row)
        if row_payload is None:
            return None
        cells = row_payload.get("cells")
        if not isinstance(cells, list) or not (0 <= column < len(cells)):
            return None
        cell = cells[column]
        return cell if isinstance(cell, dict) else None

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid():
            return None
        cell = self.cell_payload(index.row(), index.column())
        if cell is None:
            return None
        if role in {Qt.DisplayRole, Qt.EditRole}:
            return str(cell.get("text") or "")
        if role == Qt.UserRole:
            return str(cell.get("device_id") or "")
        if role == Qt.ToolTipRole:
            return str(cell.get("tooltip") or cell.get("text") or "")
        if role == Qt.TextAlignmentRole:
            return Qt.AlignLeft | Qt.AlignVCenter
        if role == Qt.BackgroundRole:
            color = cell.get("background")
            return QBrush(QColor(str(color))) if color else None
        if role == Qt.ForegroundRole:
            color = cell.get("foreground")
            return QBrush(QColor(str(color))) if color else None
        if role == Qt.FontRole and cell.get("bold"):
            font = QFont()
            font.setBold(True)
            return font
        return None

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.DisplayRole,
    ) -> object:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < len(self._headers):
            return self._headers[section]
        return None


class VirtualDeviceTable(QTableView):
    """A virtualized device table that keeps the old QTableWidget-facing API."""

    itemSelectionChanged = Signal()

    def __init__(
        self,
        copy_handler: Callable[["VirtualDeviceTable"], None],
        field_copy_handler: Callable[["VirtualDeviceTable", str], None],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._copy_handler = copy_handler
        self._field_copy_handler = field_copy_handler
        self._stretch_column = 1
        self._stretch_base = 200
        self._stretch_auto_fit = True
        self._stretch_padding = 28
        self._stretch_sample_limit = 300
        self._fill_column: int | None = None
        self._column_base_widths: dict[int, int] = {}
        self._adapting_columns = False
        self._adapt_timer: QTimer | None = None
        self._model = VirtualDeviceTableModel(self)
        self.setModel(self._model)
        self.setItemDelegate(NoFocusItemDelegate(self))
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setMouseTracking(True)
        self.selectionModel().selectionChanged.connect(lambda *_args: self.itemSelectionChanged.emit())

    def setColumnCount(self, count: int) -> None:  # noqa: N802
        headers = self._model._headers
        if count < len(headers):
            self._model.set_headers(headers[:count])
        elif count > len(headers):
            self._model.set_headers([*headers, *([""] * (count - len(headers)))])

    def setHorizontalHeaderLabels(self, headers: list[str]) -> None:  # noqa: N802
        self._model.set_headers(headers)

    def horizontalHeaderItem(self, column: int) -> _HeaderItem | None:  # noqa: N802
        if not (0 <= column < self.columnCount()):
            return None
        return _HeaderItem(str(self._model.headerData(column, Qt.Horizontal, Qt.DisplayRole) or ""))

    def set_device_rows(self, rows: list[dict[str, object]]) -> None:
        self.setUpdatesEnabled(False)
        try:
            self._model.set_rows(rows)
            self.clearSpans()
            for row, row_data in enumerate(rows):
                if row_data.get("kind") == "group":
                    self.setSpan(row, 0, 1, 2)
                self.setRowHeight(row, int(row_data.get("height") or 30))
        finally:
            self.setUpdatesEnabled(True)
        self.schedule_column_adapt()

    def rowCount(self) -> int:  # noqa: N802
        return self._model.rowCount()

    def columnCount(self) -> int:  # noqa: N802
        return self._model.columnCount()

    def item(self, row: int, column: int) -> _VirtualTableItem | None:
        if not (0 <= row < self.rowCount() and 0 <= column < self.columnCount()):
            return None
        return _VirtualTableItem(self, row, column)

    def itemAt(self, pos: Any) -> _VirtualTableItem | None:  # noqa: N802
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        return _VirtualTableItem(self, index.row(), index.column())

    def currentRow(self) -> int:  # noqa: N802
        index = self.currentIndex()
        if index.isValid():
            return index.row()
        selected = self.selectionModel().selectedRows()
        return selected[0].row() if selected else -1

    def scrollToItem(self, item: _VirtualTableItem) -> None:  # noqa: N802
        self.scrollTo(self._model.index(item.row, item.column), QAbstractItemView.PositionAtCenter)

    def device_id_at_row(self, row: int) -> str:
        item = self.item(row, 0)
        return str(item.data(Qt.UserRole) or "") if item is not None else ""

    def setColumnWidth(self, column: int, width: int) -> None:  # noqa: N802
        super().setColumnWidth(column, width)
        if not self._adapting_columns:
            self._column_base_widths[column] = width

    def set_stretch_column(self, column: int) -> None:
        self._stretch_column = column

    def set_stretch_base(self, width: int) -> None:
        self._stretch_base = width

    def set_fill_column(self, column: int) -> None:
        self._fill_column = column
        self._column_base_widths.setdefault(column, self.columnWidth(column))

    def set_stretch_auto_fit(
        self,
        enabled: bool,
        *,
        padding: int = 28,
        sample_limit: int = 300,
    ) -> None:
        self._stretch_auto_fit = enabled
        self._stretch_padding = max(0, padding)
        self._stretch_sample_limit = max(1, sample_limit)

    def schedule_column_adapt(self) -> None:
        if self._adapt_timer is None:
            self._adapt_timer = QTimer(self)
            self._adapt_timer.setSingleShot(True)
            self._adapt_timer.timeout.connect(self._spread)
        if not self._adapt_timer.isActive():
            self._adapt_timer.start(30)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.schedule_column_adapt()

    def _spread(self) -> None:
        vp = self.viewport()
        if vp is None or self.columnCount() == 0:
            return
        available = vp.width()
        fill_column = self._fill_column
        other_total = 0
        for col in range(self.columnCount()):
            if col != self._stretch_column:
                if fill_column is not None and col == fill_column:
                    other_total += self._column_base_widths.get(col, self.columnWidth(col))
                else:
                    other_total += self.columnWidth(col)
        if other_total <= 0:
            return
        desired = max(self._stretch_base, available - other_total)
        if self._stretch_auto_fit:
            desired = min(desired, self._stretch_content_width())
        self._adapting_columns = True
        try:
            if self.columnWidth(self._stretch_column) != desired:
                self.setColumnWidth(self._stretch_column, desired)
            self._spread_fill_column(available)
        finally:
            self._adapting_columns = False

    def _spread_fill_column(self, available: int) -> None:
        fill_column = self._fill_column
        if fill_column is None or fill_column == self._stretch_column:
            return
        if not (0 <= fill_column < self.columnCount()):
            return
        fill_base = self._column_base_widths.get(fill_column, self.columnWidth(fill_column))
        non_fill_total = 0
        for col in range(self.columnCount()):
            if col != fill_column:
                non_fill_total += self.columnWidth(col)
        fill_width = max(fill_base, available - non_fill_total)
        if self.columnWidth(fill_column) != fill_width:
            self.setColumnWidth(fill_column, fill_width)

    def _stretch_content_width(self) -> int:
        column = self._stretch_column
        header = self.horizontalHeaderItem(column)
        values = [header.text() if header is not None else ""]
        sampled = 0
        for row in range(self.rowCount()):
            item = self.item(row, column)
            if item is None:
                continue
            values.append(item.text())
            sampled += 1
            if sampled >= self._stretch_sample_limit:
                break
        metrics = self.fontMetrics()
        content_width = max((metrics.horizontalAdvance(value) for value in values), default=0)
        return max(self._stretch_base, content_width + self._stretch_padding)

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
        self._stretch_auto_fit = True
        self._stretch_padding = 28
        self._stretch_sample_limit = 300
        self._fill_column: int | None = None
        self._column_base_widths: dict[int, int] = {}
        self._adapting_columns = False
        self._adapt_timer: QTimer | None = None
        self.setItemDelegate(NoFocusItemDelegate(self))

    def setColumnWidth(self, column: int, width: int) -> None:  # noqa: N802
        super().setColumnWidth(column, width)
        if not self._adapting_columns:
            self._column_base_widths[column] = width

    def set_stretch_column(self, column: int) -> None:
        self._stretch_column = column

    def set_stretch_base(self, width: int) -> None:
        self._stretch_base = width

    def set_fill_column(self, column: int) -> None:
        self._fill_column = column
        self._column_base_widths.setdefault(column, self.columnWidth(column))

    def set_stretch_auto_fit(
        self,
        enabled: bool,
        *,
        padding: int = 28,
        sample_limit: int = 300,
    ) -> None:
        self._stretch_auto_fit = enabled
        self._stretch_padding = max(0, padding)
        self._stretch_sample_limit = max(1, sample_limit)

    def schedule_column_adapt(self) -> None:
        if self._adapt_timer is None:
            self._adapt_timer = QTimer(self)
            self._adapt_timer.setSingleShot(True)
            self._adapt_timer.timeout.connect(self._spread)
        if not self._adapt_timer.isActive():
            self._adapt_timer.start(30)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.schedule_column_adapt()

    def _spread(self) -> None:
        vp = self.viewport()
        if vp is None:
            return
        available = vp.width()
        fill_column = self._fill_column
        other_total = 0
        for col in range(self.columnCount()):
            if col != self._stretch_column:
                if fill_column is not None and col == fill_column:
                    other_total += self._column_base_widths.get(col, self.columnWidth(col))
                else:
                    other_total += self.columnWidth(col)
        if other_total <= 0:
            return
        desired = max(self._stretch_base, available - other_total)
        if self._stretch_auto_fit:
            desired = min(desired, self._stretch_content_width())
        self._adapting_columns = True
        try:
            if self.columnWidth(self._stretch_column) != desired:
                self.setColumnWidth(self._stretch_column, desired)
            self._spread_fill_column(available)
        finally:
            self._adapting_columns = False

    def _spread_fill_column(self, available: int) -> None:
        fill_column = self._fill_column
        if fill_column is None or fill_column == self._stretch_column:
            return
        if not (0 <= fill_column < self.columnCount()):
            return
        fill_base = self._column_base_widths.get(fill_column, self.columnWidth(fill_column))
        non_fill_total = 0
        for col in range(self.columnCount()):
            if col != fill_column:
                non_fill_total += self.columnWidth(col)
        fill_width = max(fill_base, available - non_fill_total)
        if self.columnWidth(fill_column) != fill_width:
            self.setColumnWidth(fill_column, fill_width)

    def _stretch_content_width(self) -> int:
        column = self._stretch_column
        header = self.horizontalHeaderItem(column)
        values = [header.text() if header is not None else ""]
        sampled = 0
        for row in range(self.rowCount()):
            item = self.item(row, column)
            if item is None:
                continue
            values.append(item.text())
            sampled += 1
            if sampled >= self._stretch_sample_limit:
                break
        metrics = self.fontMetrics()
        content_width = max((metrics.horizontalAdvance(value) for value in values), default=0)
        return max(self._stretch_base, content_width + self._stretch_padding)

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
