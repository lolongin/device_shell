from __future__ import annotations

from src.styles import APP_STYLE


def test_session_manager_theme_block_present_before_text_selection() -> None:
    assert "/* Session manager panel */" in APP_STYLE
    assert APP_STYLE.index("/* Session manager panel */") < APP_STYLE.rindex(
        "/* Global text selection */"
    )


def test_session_manager_tree_is_dark_and_has_selected_state() -> None:
    block = APP_STYLE[APP_STYLE.index("/* Session manager panel */") :]
    assert "QTreeWidget#sessionManagerTree {" in block
    assert "background: #020617;" in block
    assert "border: none;" in block
    assert "QTreeWidget#sessionManagerTree::item:selected {" in block
    assert "background: #24324a;" in block


def test_session_manager_panel_and_strip_surfaces() -> None:
    block = APP_STYLE[APP_STYLE.index("/* Session manager panel */") :]
    assert "QWidget#sessionManagerPanel {" in block
    assert "background: transparent;" in block
    assert "QWidget#sessionManagerStrip {" in block
    assert "background: #0f172a;" in block
