"""Password field helpers for PySide6 forms."""

from __future__ import annotations

from typing import Any

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import QLineEdit
except ModuleNotFoundError:  # pragma: no cover - GUI helper is inert without PySide6
    Qt = None
    QColor = None
    QIcon = None
    QPainter = None
    QPen = None
    QPixmap = None
    QLineEdit = None


def password_visibility_icon(visible: bool) -> Any:
    """Build a compact eye icon for password visibility actions."""
    if QIcon is None or QPainter is None or QPen is None or QPixmap is None or QColor is None or Qt is None:
        return QIcon() if QIcon is not None else None

    pixmap = QPixmap(18, 18)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor("#d0d0d0" if visible else "#808080"), 1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(3, 5, 12, 8)
    painter.drawEllipse(7, 7, 4, 4)
    if not visible:
        painter.drawLine(4, 14, 14, 4)
    painter.end()
    return QIcon(pixmap)


def configure_password_visibility(line_edit: Any) -> Any:
    """Mask a password input and add a trailing show/hide action."""
    if QLineEdit is None or line_edit is None:
        return line_edit

    line_edit.setEchoMode(QLineEdit.Password)
    action = line_edit.addAction(password_visibility_icon(False), QLineEdit.TrailingPosition)
    action.setCheckable(True)
    action.setToolTip("显示密码")

    def toggle_password_visible(checked: bool) -> None:
        line_edit.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
        action.setIcon(password_visibility_icon(checked))
        action.setToolTip("隐藏密码" if checked else "显示密码")

    action.toggled.connect(toggle_password_visible)
    line_edit.password_visibility_action = action
    return line_edit
