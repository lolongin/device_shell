"""QWebEngineView backed device navigation panel."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPoint, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget


class _DeviceNavigationBridge(QObject):
    device_selected = Signal(str)
    filters_changed = Signal(str)
    refresh_requested = Signal()
    clear_requested = Signal()
    device_context_requested = Signal(str, int, int)

    @Slot(str)
    def selectDevice(self, device_id: str) -> None:
        self.device_selected.emit(device_id)

    @Slot(str)
    def updateFilters(self, payload: str) -> None:
        self.filters_changed.emit(payload)

    @Slot()
    def requestRefresh(self) -> None:
        self.refresh_requested.emit()

    @Slot()
    def clearFilters(self) -> None:
        self.clear_requested.emit()

    @Slot(str, int, int)
    def requestDeviceContextMenu(self, device_id: str, x: int, y: int) -> None:
        self.device_context_requested.emit(device_id, x, y)


class DeviceNavigationWebWidget(QWidget):
    """Compact Web UI for device filtering and list navigation."""

    device_selected = Signal(str)
    filters_changed = Signal(dict)
    refresh_requested = Signal()
    clear_requested = Signal()
    device_context_requested = Signal(str, int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("deviceNavigationWebWidget")
        self._loaded = False
        self._pending_payload: dict[str, Any] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = QWebEngineView(self)
        self.view.setObjectName("deviceNavigationWebView")
        self.view.setStyleSheet("QWebEngineView#deviceNavigationWebView { background: #020617; border: 0; }")
        layout.addWidget(self.view)

        self.bridge = _DeviceNavigationBridge(self)
        self.bridge.device_selected.connect(self.device_selected)
        self.bridge.filters_changed.connect(self._handle_filters_changed)
        self.bridge.refresh_requested.connect(self.refresh_requested)
        self.bridge.clear_requested.connect(self.clear_requested)
        self.bridge.device_context_requested.connect(self._handle_device_context_requested)

        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("deviceNavigationBridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.loadFinished.connect(self._handle_load_finished)

        html_path = Path(__file__).resolve().parents[1] / "web" / "device_navigation.html"
        self.view.load(QUrl.fromLocalFile(str(html_path)))

    def set_payload(self, payload: dict[str, Any]) -> None:
        self._pending_payload = payload
        if not self._loaded:
            return
        self._apply_payload(payload)

    def _apply_payload(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False)
        self.view.page().runJavaScript(f"window.setDeviceNavigationPayload({encoded});")

    def _handle_load_finished(self, ok: bool) -> None:
        self._loaded = ok
        if ok and self._pending_payload is not None:
            self._apply_payload(self._pending_payload)

    def _handle_filters_changed(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return
        if isinstance(data, dict):
            self.filters_changed.emit(data)

    def _handle_device_context_requested(self, device_id: str, x: int, y: int) -> None:
        global_pos = self.view.mapToGlobal(QPoint(x, y))
        self.device_context_requested.emit(device_id, global_pos.x(), global_pos.y())
