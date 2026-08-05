from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _state_path(window: DeviceDesktopApp) -> Path:
    return Path(window.state_path)


def test_session_layout_defaults(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.session_tab_layout == "top"
    assert window.terminal_font_size == 14
    assert window.session_manager_default_collapsed is False
    assert window.session_manager_width == 260
    assert window.session_manager_collapsed is False
    assert window.collapsed_device_groups == []
    window.close()


def test_session_layout_round_trip(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ = app
    state_file = tmp_path / "desktop_state.json"
    monkeypatch.setattr(
        DeviceDesktopApp,
        "desktop_state_path",
        staticmethod(lambda: state_file),
    )

    window = DeviceDesktopApp()
    window.session_tab_layout = "side"
    window.terminal_font_size = 18
    window.session_manager_width = 340
    window.session_manager_collapsed = True
    window.collapsed_device_groups = ["R1-核心"]
    window.save_desktop_state()

    saved = json.loads(_state_path(window).read_text(encoding="utf-8"))
    assert saved["version"] == 15
    assert saved["session_layout"]["session_tab_layout"] == "side"
    assert saved["session_layout"]["terminal_font_size"] == 18
    assert saved["session_layout"]["session_manager_width"] == 340
    assert saved["session_layout"]["session_manager_collapsed"] is True
    assert saved["session_layout"]["collapsed_device_groups"] == ["R1-核心"]
    assert saved["session_layout"]["session_manager_default_collapsed"] is False

    window.close()

    reloaded = DeviceDesktopApp()
    try:
        assert reloaded.session_tab_layout == "side"
        assert reloaded.terminal_font_size == 18
        assert reloaded.session_manager_width == 340
        assert reloaded.session_manager_collapsed is True
        assert reloaded.collapsed_device_groups == ["R1-核心"]
        assert reloaded.session_manager_default_collapsed is False
    finally:
        reloaded.close()


def test_session_manager_default_collapsed_seeds_first_load(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ = app
    # A payload with NO `session_manager_collapsed` key (no memorized history):
    # the default-collapse setting governs the first entry into `side`.
    state_file = tmp_path / "desktop_state.json"
    monkeypatch.setattr(
        DeviceDesktopApp,
        "desktop_state_path",
        staticmethod(lambda: state_file),
    )
    state_file.write_text(
        json.dumps(
            {
                "version": 14,
                "session_layout": {
                    "session_tab_layout": "side",
                    "session_manager_default_collapsed": True,
                },
            }
        ),
        encoding="utf-8",
    )
    window = DeviceDesktopApp()
    try:
        assert window.session_manager_collapsed is True
        # The collapse button is synced from the loaded value, not left unchecked.
        assert window.session_manager_collapse_button.isChecked() is True
    finally:
        window.close()


def test_session_manager_memorized_collapse_wins_over_default(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ = app
    # A payload WITH a memorized `session_manager_collapsed` key overrides the
    # default-collapse setting.
    state_file = tmp_path / "desktop_state.json"
    monkeypatch.setattr(
        DeviceDesktopApp,
        "desktop_state_path",
        staticmethod(lambda: state_file),
    )
    state_file.write_text(
        json.dumps(
            {
                "version": 14,
                "session_layout": {
                    "session_tab_layout": "side",
                    "session_manager_default_collapsed": True,
                    "session_manager_collapsed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    window = DeviceDesktopApp()
    try:
        assert window.session_manager_collapsed is False
        assert window.session_manager_collapse_button.isChecked() is False
    finally:
        window.close()
