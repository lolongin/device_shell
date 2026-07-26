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
        self._group_title_column = 0
        self._group_count_column = 5
        self._group_show_count = True

    def set_headers(self, headers: list[str]) -> None:
        self.beginResetModel()
        self._headers = headers
        self.endResetModel()

    def set_rows(self, rows: list[dict[str, object]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def set_group_layout(
        self,
        *,
        title_column: int,
        count_column: int,
        show_count: bool,
    ) -> None:
        changed = (
            self._group_title_column != title_column
            or self._group_count_column != count_column
            or self._group_show_count != show_count
        )
        self._group_title_column = title_column
        self._group_count_column = count_column
        self._group_show_count = show_count
        if changed and self._rows and self._headers:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, len(self._headers) - 1),
            )

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
        row_payload = self.row_payload(index.row())
        if row_payload is not None and row_payload.get("kind") == "group":
            return self._group_data(row_payload, index.column(), role)
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

    def _group_data(self, row_payload: dict[str, object], column: int, role: int) -> object:
        if role in {Qt.DisplayRole, Qt.EditRole}:
            if column == self._group_title_column:
                return str(row_payload.get("group_title") or "")
            if self._group_show_count and column == self._group_count_column:
                return str(row_payload.get("group_count") or "")
            return ""
        if role == Qt.ToolTipRole:
            return str(row_payload.get("group_tooltip") or row_payload.get("group_title") or "")
        if role == Qt.TextAlignmentRole:
            return Qt.AlignLeft | Qt.AlignVCenter
        if role == Qt.BackgroundRole:
            return QBrush(QColor(str(row_payload.get("group_background") or "#08101d")))
        if role == Qt.ForegroundRole:
            color = (
                row_payload.get("group_count_foreground")
                if column == self._group_count_column
                else row_payload.get("group_foreground")
            )
            return QBrush(QColor(str(color or "#f8fafc")))
        if role == Qt.FontRole and column in {
            self._group_title_column,
            self._group_count_column,
        }:
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
    DENSITY_FULL = "full"
    DENSITY_MEDIUM = "medium"
    DENSITY_COMPACT = "compact"
    DENSITY_COLUMNS = {
        DENSITY_FULL: (0, 1, 2, 3, 4, 5),
        DENSITY_MEDIUM: (0, 1, 2, 3, 5),
        DENSITY_COMPACT: (0, 1, 5),
    }
    FULL_BREAKPOINT = 520
    COMPACT_BREAKPOINT = 340
    BREAKPOINT_HYSTERESIS = 16
    ADAPT_DEBOUNCE_MS = 40
    _DENSITY_MIN_WIDTHS = {
        DENSITY_FULL: {0: 58, 1: 120, 2: 86, 3: 60, 4: 50, 5: 88},
        DENSITY_MEDIUM: {0: 52, 1: 92, 2: 68, 3: 52, 5: 76},
        DENSITY_COMPACT: {0: 52, 1: 80, 5: 78},
    }

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
        self._responsive_density_enabled = False
        self._density_adaptation_paused = False
        self._responsive_density: str | None = None
        self._full_density_widths: dict[int, int] = {}
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
        self.horizontalHeader().sectionResized.connect(self._remember_user_column_width)

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
        for row_data in rows:
            if row_data.get("kind") != "group":
                continue
            cells = row_data.get("cells")
            if not isinstance(cells, list):
                continue
            title_cell = cells[0] if cells and isinstance(cells[0], dict) else {}
            count_cell = cells[2] if len(cells) > 2 and isinstance(cells[2], dict) else {}
            row_data.setdefault("group_title", title_cell.get("text") or "")
            row_data.setdefault("group_count", count_cell.get("text") or "")
            row_data.setdefault("group_tooltip", title_cell.get("tooltip") or title_cell.get("text") or "")
            row_data.setdefault("group_background", title_cell.get("background") or "#08101d")
            row_data.setdefault("group_foreground", title_cell.get("foreground") or "#f8fafc")
            row_data.setdefault("group_count_foreground", count_cell.get("foreground") or "#718096")
        self.setUpdatesEnabled(False)
        try:
            self._model.set_rows(rows)
            for row, row_data in enumerate(rows):
                self.setRowHeight(row, int(row_data.get("height") or 30))
            self._apply_group_spans()
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
            if self._responsive_density in {None, self.DENSITY_FULL}:
                self._full_density_widths[column] = width

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

    @property
    def responsive_density(self) -> str:
        return self._responsive_density or self.DENSITY_FULL

    def visible_columns(self) -> tuple[int, ...]:
        return tuple(
            column
            for column in range(self.columnCount())
            if not self.isColumnHidden(column)
        )

    def set_responsive_density_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._responsive_density_enabled == enabled:
            if enabled:
                self.schedule_column_adapt()
            return
        self._responsive_density_enabled = enabled
        if not enabled:
            self._apply_density(self.DENSITY_FULL)
            return
        self._responsive_density = None
        self.schedule_column_adapt()

    def set_density_adaptation_paused(self, paused: bool) -> None:
        paused = bool(paused)
        if self._density_adaptation_paused == paused:
            return
        self._density_adaptation_paused = paused
        if paused:
            if self._adapt_timer is not None:
                self._adapt_timer.stop()
            return
        self.schedule_column_adapt()

    def schedule_column_adapt(self) -> None:
        if self._density_adaptation_paused:
            return
        if self._adapt_timer is None:
            self._adapt_timer = QTimer(self)
            self._adapt_timer.setSingleShot(True)
            self._adapt_timer.timeout.connect(self._spread)
        self._adapt_timer.start(self.ADAPT_DEBOUNCE_MS)

    def resizeEvent(self, event: Any) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.schedule_column_adapt()

    def _spread(self) -> None:
        vp = self.viewport()
        if vp is None or self.columnCount() == 0:
            return
        available = vp.width()
        if self._responsive_density_enabled:
            density = self._density_for_width(available)
            if density != self._responsive_density:
                self._apply_density(density)
            self._spread_responsive_columns(available)
            return
        fill_column = self._fill_column
        other_total = 0
        for col in range(self.columnCount()):
            if self.isColumnHidden(col):
                continue
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
            if col != fill_column and not self.isColumnHidden(col):
                non_fill_total += self.columnWidth(col)
        fill_width = max(fill_base, available - non_fill_total)
        if self.columnWidth(fill_column) != fill_width:
            self.setColumnWidth(fill_column, fill_width)

    def _density_for_width(self, width: int) -> str:
        current = self._responsive_density
        if current is None:
            if width >= self.FULL_BREAKPOINT:
                return self.DENSITY_FULL
            if width >= self.COMPACT_BREAKPOINT:
                return self.DENSITY_MEDIUM
            return self.DENSITY_COMPACT
        if current == self.DENSITY_FULL:
            if width < self.COMPACT_BREAKPOINT:
                return self.DENSITY_COMPACT
            if width < self.FULL_BREAKPOINT:
                return self.DENSITY_MEDIUM
            return current
        if current == self.DENSITY_MEDIUM:
            if width >= self.FULL_BREAKPOINT + self.BREAKPOINT_HYSTERESIS:
                return self.DENSITY_FULL
            if width < self.COMPACT_BREAKPOINT:
                return self.DENSITY_COMPACT
            return current
        if width >= self.FULL_BREAKPOINT + self.BREAKPOINT_HYSTERESIS:
            return self.DENSITY_FULL
        if width >= self.COMPACT_BREAKPOINT + self.BREAKPOINT_HYSTERESIS:
            return self.DENSITY_MEDIUM
        return current

    def _apply_density(self, density: str) -> None:
        if density not in self.DENSITY_COLUMNS:
            density = self.DENSITY_FULL
        previous = self._responsive_density
        if previous == self.DENSITY_FULL and density != self.DENSITY_FULL:
            self._capture_full_density_widths()
        self._responsive_density = density
        visible = set(self.DENSITY_COLUMNS[density])
        self.setUpdatesEnabled(False)
        self._adapting_columns = True
        try:
            for column in range(self.columnCount()):
                self.setColumnHidden(column, column not in visible)
            self._apply_group_spans()
        finally:
            self._adapting_columns = False
            self.setUpdatesEnabled(True)

    def _apply_group_spans(self) -> None:
        self.clearSpans()
        visible = list(self.DENSITY_COLUMNS.get(self.responsive_density, ()))
        if not visible:
            return
        title_column = visible[0]
        non_status_columns = [column for column in visible if column != 5]
        last_title_column = non_status_columns[-1] if non_status_columns else title_column
        show_count = self.responsive_density != self.DENSITY_COMPACT and 5 in visible
        self._model.set_group_layout(
            title_column=title_column,
            count_column=5,
            show_count=show_count,
        )
        span = max(1, last_title_column - title_column + 1)
        for row in range(self.rowCount()):
            row_payload = self._model.row_payload(row)
            if row_payload is not None and row_payload.get("kind") == "group":
                self.setSpan(row, title_column, 1, span)

    def _capture_full_density_widths(self) -> None:
        for column in self.DENSITY_COLUMNS[self.DENSITY_FULL]:
            if not self.isColumnHidden(column):
                self._full_density_widths[column] = self.columnWidth(column)

    def _remember_user_column_width(
        self,
        column: int,
        _old_width: int,
        new_width: int,
    ) -> None:
        if self._adapting_columns or self.responsive_density != self.DENSITY_FULL:
            return
        self._column_base_widths[column] = new_width
        self._full_density_widths[column] = new_width

    def _spread_responsive_columns(self, available: int) -> None:
        density = self.responsive_density
        visible = self.DENSITY_COLUMNS[density]
        if self._stretch_column not in visible:
            return
        minimums = self._DENSITY_MIN_WIDTHS[density]
        fixed_columns = [column for column in visible if column != self._stretch_column]
        fixed_widths = {column: minimums[column] for column in fixed_columns}
        stretch_minimum = minimums[self._stretch_column]
        remaining = max(0, available - stretch_minimum - sum(fixed_widths.values()))
        priority = [5, 2, 0, 3, 4]
        for column in priority:
            if column not in fixed_widths or remaining <= 0:
                continue
            preferred = self._full_density_widths.get(
                column,
                self._column_base_widths.get(column, fixed_widths[column]),
            )
            growth = min(remaining, max(0, preferred - fixed_widths[column]))
            fixed_widths[column] += growth
            remaining -= growth
        stretch_width = max(
            stretch_minimum,
            available - sum(fixed_widths.values()),
        )
        self._adapting_columns = True
        try:
            for column, width in fixed_widths.items():
                if self.columnWidth(column) != width:
                    super().setColumnWidth(column, width)
            if self.columnWidth(self._stretch_column) != stretch_width:
                super().setColumnWidth(self._stretch_column, stretch_width)
        finally:
            self._adapting_columns = False

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
