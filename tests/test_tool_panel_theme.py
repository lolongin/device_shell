from __future__ import annotations

from src.styles import APP_STYLE


def test_tool_panel_label_transparency_block_present() -> None:
    assert "/* Tool panel label transparency */" in APP_STYLE
    block = APP_STYLE[APP_STYLE.index("/* Tool panel label transparency */") :]
    assert "QGroupBox#navShell QLabel," in block
    assert "background: transparent;" in block


def test_tool_panel_translucent_surfaces_block_present() -> None:
    assert "/* Tool panel translucent surfaces */" in APP_STYLE
    block = APP_STYLE[APP_STYLE.index("/* Tool panel translucent surfaces */") :]
    assert "QFrame#transferConfigCard," in block
    assert "background: rgba(8, 16, 29, 0.72);" in block
    assert "background: rgba(15, 23, 42, 0.66);" in block


def test_tool_panel_blocks_precede_text_selection() -> None:
    assert APP_STYLE.index("/* Tool panel label transparency */") < APP_STYLE.rindex(
        "/* Global text selection */"
    )
    assert APP_STYLE.index("/* Tool panel translucent surfaces */") < APP_STYLE.rindex(
        "/* Global text selection */"
    )
