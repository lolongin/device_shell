"""QWebEngineView backed device navigation panel."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPoint, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

try:
    from ..theme_tokens import qwebengine_background_stylesheet
except ImportError:  # pragma: no cover - direct script execution fallback
    from theme_tokens import qwebengine_background_stylesheet


class _DeviceNavigationBridge(QObject):
    device_selected = Signal(str)
    device_connect_requested = Signal(str, str)
    session_selected = Signal(str)
    session_close_requested = Signal(str)
    session_close_others_requested = Signal(str)
    session_close_all_requested = Signal()
    session_context_requested = Signal(str, int, int)
    home_requested = Signal()
    filters_changed = Signal(str)
    refresh_requested = Signal()
    clear_requested = Signal()
    device_context_requested = Signal(str, int, int)
    navigation_state_changed = Signal(str)

    @Slot(str)
    def selectDevice(self, device_id: str) -> None:
        self.device_selected.emit(device_id)

    @Slot(str, str)
    def requestDeviceConnect(self, device_id: str, kind: str) -> None:
        self.device_connect_requested.emit(device_id, kind)

    @Slot(str)
    def selectSession(self, tab_id: str) -> None:
        self.session_selected.emit(tab_id)

    @Slot(str)
    def closeSession(self, tab_id: str) -> None:
        self.session_close_requested.emit(tab_id)

    @Slot(str)
    def closeOtherSessions(self, tab_id: str) -> None:
        self.session_close_others_requested.emit(tab_id)

    @Slot()
    def closeAllSessions(self) -> None:
        self.session_close_all_requested.emit()

    @Slot(str, int, int)
    def requestSessionContextMenu(self, tab_id: str, x: int, y: int) -> None:
        self.session_context_requested.emit(tab_id, x, y)

    @Slot()
    def requestHome(self) -> None:
        self.home_requested.emit()

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

    @Slot(str)
    def updateNavigationState(self, payload: str) -> None:
        self.navigation_state_changed.emit(payload)


class DeviceNavigationWebWidget(QWidget):
    """Compact Web UI for terminal session navigation."""

    device_selected = Signal(str)
    device_connect_requested = Signal(str, str)
    session_selected = Signal(str)
    session_close_requested = Signal(str)
    session_close_others_requested = Signal(str)
    session_close_all_requested = Signal()
    session_context_requested = Signal(str, int, int)
    home_requested = Signal()
    filters_changed = Signal(dict)
    refresh_requested = Signal()
    clear_requested = Signal()
    device_context_requested = Signal(str, int, int)
    navigation_state_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("deviceNavigationWebWidget")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self._loaded = False
        self._pending_payload: dict[str, Any] | None = None
        self._pending_payload_json = ""
        self._last_applied_payload_json = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = QWebEngineView(self)
        self.view.setObjectName("deviceNavigationWebView")
        self.view.setMinimumWidth(0)
        self.view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.view.setStyleSheet(qwebengine_background_stylesheet("deviceNavigationWebView"))
        layout.addWidget(self.view)

        self.bridge = _DeviceNavigationBridge(self)
        self.bridge.device_selected.connect(self.device_selected)
        self.bridge.device_connect_requested.connect(self.device_connect_requested)
        self.bridge.session_selected.connect(self.session_selected)
        self.bridge.session_close_requested.connect(self.session_close_requested)
        self.bridge.session_close_others_requested.connect(self.session_close_others_requested)
        self.bridge.session_close_all_requested.connect(self.session_close_all_requested)
        self.bridge.session_context_requested.connect(self._handle_session_context_requested)
        self.bridge.home_requested.connect(self.home_requested)
        self.bridge.filters_changed.connect(self._handle_filters_changed)
        self.bridge.refresh_requested.connect(self.refresh_requested)
        self.bridge.clear_requested.connect(self.clear_requested)
        self.bridge.device_context_requested.connect(self._handle_device_context_requested)
        self.bridge.navigation_state_changed.connect(self._handle_navigation_state_changed)

        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("deviceNavigationBridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.loadFinished.connect(self._handle_load_finished)

        html_path = Path(__file__).resolve().parents[1] / "web" / "device_navigation.html"
        self.view.load(QUrl.fromLocalFile(str(html_path)))

    def set_payload(self, payload: dict[str, Any]) -> None:
        self._pending_payload = payload
        self._pending_payload_json = json.dumps(payload, ensure_ascii=False)
        if not self._loaded:
            return
        self._apply_payload_json(self._pending_payload_json)

    def _apply_payload(self, payload: dict[str, Any]) -> None:
        self._apply_payload_json(json.dumps(payload, ensure_ascii=False))

    def _apply_payload_json(self, encoded: str) -> None:
        if encoded == self._last_applied_payload_json:
            return
        self._last_applied_payload_json = encoded
        self.view.page().runJavaScript(f"window.setDeviceNavigationPayload({encoded});")

    def _handle_load_finished(self, ok: bool) -> None:
        self._loaded = ok
        if ok and self._pending_payload is not None:
            self._apply_payload_json(self._pending_payload_json)

    def set_theme(self, mode: str) -> None:
        """Push the active theme to the loaded page via window.setWorkspaceTheme."""
        view = self.view if hasattr(self, "view") else getattr(self, "_view", None)
        if view is None:
            return
        mode = "light" if mode == "light" else "dark"
        view.page().runJavaScript(f"window.setWorkspaceTheme('{mode}')")

    def _handle_filters_changed(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return
        if isinstance(data, dict):
            self.filters_changed.emit(data)

    def _handle_navigation_state_changed(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return
        if isinstance(data, dict):
            self.navigation_state_changed.emit(data)

    def _handle_device_context_requested(self, device_id: str, x: int, y: int) -> None:
        global_pos = self.view.mapToGlobal(QPoint(x, y))
        self.device_context_requested.emit(device_id, global_pos.x(), global_pos.y())

    def _handle_session_context_requested(self, tab_id: str, x: int, y: int) -> None:
        global_pos = self.view.mapToGlobal(QPoint(x, y))
        self.session_context_requested.emit(tab_id, global_pos.x(), global_pos.y())
