from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_theme_mode_defaults_to_dark(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.theme_mode == "dark"
    window.close()


def test_apply_theme_light_sets_stylesheet(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.apply_theme("light")
    assert window.theme_mode == "light"
    ss = window.styleSheet()
    assert "background: #020617" not in ss  # dark bg gone from native style
    window.apply_theme("dark")
    assert window.theme_mode == "dark"
    window.close()


def test_settings_theme_combo_exists(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert hasattr(window, "settings_theme_combo")
    assert window.settings_theme_combo.count() >= 2
    window.close()


def test_settings_theme_combo_switches_theme(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.settings_theme_combo.setCurrentText("浅色")
    assert window.theme_mode == "light"
    assert "background: #020617" not in window.styleSheet()
    window.settings_theme_combo.setCurrentText("深色")
    assert window.theme_mode == "dark"
    window.close()


def test_persisted_light_theme_applied_after_build(
    app: QApplication, tmp_path: object, monkeypatch: object
) -> None:
    _ = app
    from pathlib import Path

    state_file = Path(tmp_path) / "desktop_state.json"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_file))
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text('{"version": 15, "theme_mode": "light"}', encoding="utf-8")
    window = DeviceDesktopApp()
    try:
        assert window.theme_mode == "light"
        # The persisted light theme must survive _build_window, not be
        # clobbered back to the dark stylesheet.
        assert "background: #020617" not in window.styleSheet()
    finally:
        window.close()
