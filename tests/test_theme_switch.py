from __future__ import annotations

import os
from pathlib import Path

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


def test_persisted_light_theme_applied_to_web_widgets_after_build(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persisted light theme must reach the web widgets once they exist."""
    import json
    import tempfile

    from pathlib import Path

    _ = app
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(Path(td) / "state.json"))
        # Seed a persisted light theme.
        (Path(td) / "state.json").write_text(
            json.dumps({"theme_mode": "light"}), encoding="utf-8"
        )
        window = DeviceDesktopApp()
        try:
            # The post-build apply in _build_layout must have delivered the
            # persisted theme into the web widgets' pending-theme slot.
            assert window.theme_mode == "light"
            for attr in ("web_shell", "device_navigation_web"):
                widget = getattr(window, attr, None)
                assert widget is not None
                assert widget._pending_theme == "light"
        finally:
            window.close()


def _web_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "web"


def test_web_pages_expose_set_workspace_theme() -> None:
    for page_name in ("web_shell.html", "device_navigation.html", "xterm_terminal.html", "auto_response_editor.html"):
        page = (_web_root() / page_name).read_text(encoding="utf-8")
        assert "window.setWorkspaceTheme" in page


def test_apply_theme_reaches_session_terminals(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    calls: list[str] = []
    fake = type("F", (), {"set_theme": lambda self, mode: calls.append(mode)})()
    original = window.session_tabs_by_id
    window.session_tabs_by_id = {"t1": type("S", (), {"terminal": fake})()}
    try:
        window.apply_theme("light")
        assert calls == ["light"]
    finally:
        # Restore the real (empty) session registry before closing so the
        # closeEvent log-flush path never touches the minimal fake state.
        window.session_tabs_by_id = original
        window.close()
