from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_collapse_toggle_updates_state_and_persists(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.session_tab_layout = "side"
    window.session_manager_collapse_button.setChecked(True)
    window.toggle_session_manager_collapsed()

    assert window.session_manager_collapsed is True
    assert not window.session_manager_panel.isVisible()
    window.close()


def test_width_drag_finished_clamps_and_persists(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    # The drag_finished signal reports the LEFT panel width (sizes[0]), so the
    # refined handler ignores the passed width and reads the actual right-panel
    # width from splitter.sizes()[-1]. Exercise that real behavior:
    #   - "side" layout makes the session-manager panel visible (a hidden pane
    #     collapses to 0 in a QSplitter);
    #   - showing the window gives the splitter real geometry so setSizes sticks
    #     (setSizes is a no-op on an un-laid-out splitter).
    window.set_session_tab_layout("side")
    window.show()
    app.processEvents()
    window.main_splitter.setSizes([520, 1080, 500])
    window.handle_session_manager_width_drag_finished(500)
    assert window.session_manager_width == window.SESSION_MANAGER_MAX_WIDTH
    window.main_splitter.setSizes([520, 1080, 10])
    window.handle_session_manager_width_drag_finished(10)
    assert window.session_manager_width == window.SESSION_MANAGER_MIN_WIDTH
    window.close()


def test_set_main_splitter_width_preserves_right_panel(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.session_manager_width = 340
    window.set_session_tab_layout("side")  # makes the right panel visible
    window.show()
    app.processEvents()
    # Give the splitter a real 3-child layout first.
    window.main_splitter.setSizes([420, 800, 340])
    window.set_main_splitter_width(360)
    sizes = window.main_splitter.sizes()
    assert len(sizes) == 3
    # The left sidebar reaches the requested width and the right session-manager
    # panel keeps the user's dragged/persisted width (not snapped to minimum).
    assert sizes[0] == 360
    assert sizes[2] == 340
    window.close()


def test_set_main_splitter_width_top_layout_keeps_panel_hidden(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    # Default "top" layout: the session-manager panel must stay collapsed to 0
    # even while set_main_splitter_width runs (it must not reserve right space).
    window.session_tab_layout = "top"
    window.session_manager_width = 340
    window.show()
    app.processEvents()
    window.main_splitter.setSizes([420, 800, 0])
    window.set_main_splitter_width(360)
    sizes = window.main_splitter.sizes()
    assert len(sizes) == 3
    assert sizes[0] == 360
    assert sizes[2] == 0
    window.close()
