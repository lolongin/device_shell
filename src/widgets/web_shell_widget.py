"""QWebEngineView backed main web shell."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget


class _WebShellBridge(QObject):
    device_selected = Signal(str)
    filters_changed = Signal(str)
    action_requested = Signal(str)
    refresh_requested = Signal()
    clear_requested = Signal()

    @Slot(str)
    def selectDevice(self, device_id: str) -> None:
        self.device_selected.emit(device_id)

    @Slot(str)
    def requestAction(self, action: str) -> None:
        self.action_requested.emit(action)

    @Slot(str)
    def updateFilters(self, payload: str) -> None:
        self.filters_changed.emit(payload)

    @Slot()
    def requestRefresh(self) -> None:
        self.refresh_requested.emit()

    @Slot()
    def clearFilters(self) -> None:
        self.clear_requested.emit()


class WebShellWidget(QWidget):
    """Main web shell for the desktop UI migration."""

    device_selected = Signal(str)
    filters_changed = Signal(dict)
    action_requested = Signal(str)
    refresh_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("webShellWidget")
        self._loaded = False
        self._pending_payload: dict[str, Any] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = QWebEngineView(self)
        self.view.setObjectName("webShellView")
        self.view.setStyleSheet("QWebEngineView#webShellView { background: #07090c; border: 0; }")
        layout.addWidget(self.view)

        self.bridge = _WebShellBridge(self)
        self.bridge.device_selected.connect(self.device_selected)
        self.bridge.filters_changed.connect(self._handle_filters_changed)
        self.bridge.action_requested.connect(self.action_requested)
        self.bridge.refresh_requested.connect(self.refresh_requested)
        self.bridge.clear_requested.connect(self.clear_requested)

        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("webShellBridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.loadFinished.connect(self._handle_load_finished)

        html_path = Path(__file__).resolve().parents[1] / "web" / "web_shell.html"
        self.view.load(QUrl.fromLocalFile(str(html_path)))

    def set_payload(self, payload: dict[str, Any]) -> None:
        self._pending_payload = payload
        if self._loaded:
            self._apply_payload(payload)

    def _apply_payload(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False)
        self.view.page().runJavaScript(f"window.setWebShellPayload({encoded});")

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
