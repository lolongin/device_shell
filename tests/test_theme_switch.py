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


from src.widgets.terminal_canvas import TerminalCanvasWidget


def test_canvas_terminal_has_theme_switch(app: QApplication) -> None:
    _ = app
    w = TerminalCanvasWidget()
    assert hasattr(w, "apply_canvas_theme")
    w.apply_canvas_theme("light")
    # Canvas bg color changes from dark #020617 to light #f2f4f6.
    assert w.DEFAULT_BG.name().lower() == "#f2f4f6"
    w.apply_canvas_theme("dark")
    assert w.DEFAULT_BG.name().lower() == "#020617"
    w.close()


def test_apply_theme_to_new_terminal(app: QApplication) -> None:
    """A session terminal created in light mode must be themed to light."""
    _ = app
    window = DeviceDesktopApp()
    window.theme_mode = "light"
    calls: list[str] = []
    fake = type("F", (), {"set_theme": lambda self, mode: calls.append(mode)})()
    window._apply_theme_to_terminal(fake)
    assert calls == ["light"]
    window.close()


def test_apply_theme_to_new_canvas_terminal(app: QApplication) -> None:
    """A canvas terminal created in light mode must switch to the light palette."""
    _ = app
    window = DeviceDesktopApp()
    window.theme_mode = "light"
    terminal = TerminalCanvasWidget()
    try:
        window._apply_theme_to_terminal(terminal)
        assert terminal.DEFAULT_BG.name().lower() == "#f2f4f6"
    finally:
        terminal.close()
        window.close()


def test_web_shell_light_map_overrides_surfaces() -> None:
    """web_shell light theme must lighten the surfaces used by headings/cards."""
    page = (_web_root() / "web_shell.html").read_text(encoding="utf-8")
    assert "--surface-top" in page
    assert "--surface-filter" in page
    assert "--surface-card" in page


def test_auto_response_editor_dialog_wires_theme() -> None:
    """The editor dialog must push the active theme into its page on load."""
    session_ops = (Path(__file__).resolve().parents[1] / "src" / "app" / "session_ops.py").read_text(
        encoding="utf-8"
    )
    assert "window.setWorkspaceTheme" in session_ops
    assert "self.web_view.loadFinished.connect" in session_ops
    assert "self._theme_mode" in session_ops


def test_tree_foreground_uses_dark_text_in_light_theme(app: QApplication) -> None:
    """In light theme the session-manager tree must use dark text for its
    setForeground brushes (regression: it hardcoded light #e5edf6/#a7b4c7,
    making tree text invisible on the light background)."""
    from src._sample_data import sample_devices

    _ = app
    window = DeviceDesktopApp()
    window.theme_mode = "light"
    devices = sample_devices()[:1]
    device = devices[0]
    device.id = "theme-tree-device"
    device.name = "主题树设备"
    window.devices = devices
    window.rebuild_device_indexes()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(window, "connect_session_tab", lambda tab_id: None)
    try:
        window.ensure_session_tab(
            kind="simulated", device=device, host="10.0.0.1", port=22,
            username="admin", password="secret", title="浅色会话", suppress_initial_error=True,
        )
        window.refresh_session_manager_tree()
        tree = window.session_manager_tree
        parent = tree.topLevelItem(0)
        assert parent is not None
        fg0 = parent.foreground(0).color().name()
        assert fg0 != "#e5edf6", "tree col0 must not stay light in light theme"
        child = parent.child(0)
        assert child is not None
        fg1 = child.foreground(1).color().name()
        assert fg1 != "#a7b4c7", "tree col1 must not stay light in light theme"
    finally:
        monkeypatch.undo()
        window.close()


def test_xterm_light_map_includes_scrollbar_tokens() -> None:
    """xterm's light theme must override the scrollbar tokens (--input,
    --line-strong, --scroll-hover) in its lightVars map, or the scrollbar
    stays dark on a light terminal."""
    page = (_web_root() / "xterm_terminal.html").read_text(encoding="utf-8")
    light = page[page.index("const lightVars") : page.index("const root")]
    assert "'--input':" in light
    assert "'--line-strong':" in light
    assert "'--scroll-hover':" in light


def test_apply_theme_updates_command_record_line_area(app: QApplication) -> None:
    """Switching theme must update the command-record editor's theme so its
    line-number gutter (QPainter-drawn, bypasses QSS) matches the theme."""
    _ = app
    window = DeviceDesktopApp()
    assert hasattr(window, "command_record_input")
    window.apply_theme("light")
    assert window.command_record_input._theme_mode == "light"
    window.apply_theme("dark")
    assert window.command_record_input._theme_mode == "dark"
    window.close()


def test_light_theme_primary_button_uses_white_text() -> None:
    """In the light theme the primary (green) button must keep white text, not
    the mapped near-black green that reads poorly on the deep-green fill."""
    from src.styles import APP_STYLE_LIGHT

    light = APP_STYLE_LIGHT[APP_STYLE_LIGHT.index("QPushButton#primaryButton,") :]
    # The light override appended after generation forces white text.
    assert "color: #ffffff;" in light


def test_breadcrumb_has_polished_style() -> None:
    """The session breadcrumb must have a styled container and separators, not
    bare labels."""
    from src.styles import APP_STYLE

    assert "QWidget#sessionBreadcrumb {" in APP_STYLE
    assert "QLabel#breadcrumbSeparator {" in APP_STYLE
    assert "QLabel#breadcrumbHome {" in APP_STYLE
    assert "border-radius: 10px;" in APP_STYLE


def test_breadcrumb_hover_blue_mapped_to_light() -> None:
    """The breadcrumb hover blue rgba must be covered by the light mapping so
    it doesn't stay dark in the light theme."""
    from src.theme_tokens import DARK_TO_LIGHT

    assert "rgba(96, 165, 250, 0.14)" in DARK_TO_LIGHT
