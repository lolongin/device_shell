from __future__ import annotations

from pathlib import Path

from src.styles import APP_STYLE


def _web_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "web"


def test_xterm_scrollbar_matches_workspace_capsule() -> None:
    page = (_web_root() / "xterm_terminal.html").read_text(encoding="utf-8")
    viewport = page[page.index(".xterm .xterm-viewport") :]
    assert "scrollbar-width: thin;" in viewport
    scrollbar_block = viewport[viewport.index("::-webkit-scrollbar") :]
    assert "width: 10px;" in scrollbar_block
    assert "border: 2px solid var(--input);" in scrollbar_block
    assert "border-radius: 999px;" in scrollbar_block


def test_unified_component_block_lands_before_global_text_selection() -> None:
    assert "/* Unified component system */" in APP_STYLE
    assert APP_STYLE.index("/* Unified component system */") < APP_STYLE.rindex(
        "/* Global text selection */"
    )


def test_spinbox_uses_workspace_input_surface() -> None:
    block = APP_STYLE[APP_STYLE.index("/* Unified component system */") :]
    assert "QSpinBox,\nQAbstractSpinBox {" in block
    assert "background: #08101d;" in block
    assert "border: 1px solid #243244;" in block
    assert "border-radius: 8px;" in block


def test_server_cards_radius_unified_to_12() -> None:
    block = APP_STYLE[APP_STYLE.index("/* Unified component system */") :]
    assert "QFrame#serverCard,\nQFrame#serverGroupHeader {" in block
    assert "border-radius: 12px;" in block


def test_settings_hint_label_styled() -> None:
    block = APP_STYLE[APP_STYLE.index("/* Unified component system */") :]
    assert "QLabel#settingsHint {" in block
