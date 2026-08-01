from __future__ import annotations

from pathlib import Path

from src.styles import APP_STYLE
from src.theme_tokens import (
    WORKSPACE_SELECTED,
    WORKSPACE_TEXT_SELECTION_BG,
    WORKSPACE_TEXT_SELECTION_FG,
)
from src.widgets.terminal_canvas import TerminalCanvasWidget


def test_text_selection_uses_dedicated_muted_cobalt_tokens() -> None:
    assert WORKSPACE_SELECTED == "#24324a"
    assert WORKSPACE_TEXT_SELECTION_BG == "#315f9f"
    assert WORKSPACE_TEXT_SELECTION_FG == "#f8fafc"
    assert TerminalCanvasWidget.SELECTION_BG.name() == WORKSPACE_TEXT_SELECTION_BG
    assert TerminalCanvasWidget.SELECTION_FG.name() == WORKSPACE_TEXT_SELECTION_FG


def test_qt_text_controls_end_with_global_selection_cascade() -> None:
    marker = "/* Global text selection */"

    assert marker in APP_STYLE
    assert APP_STYLE.rfind(marker) > APP_STYLE.rfind("/* Global button system */")
    final_cascade = APP_STYLE[APP_STYLE.rfind(marker) :]
    for selector in (
        "QLineEdit",
        "QTextEdit",
        "QPlainTextEdit",
        "QTextBrowser",
        "QAbstractSpinBox",
        "QComboBox",
    ):
        assert selector in final_cascade
    assert "selection-background-color: #315f9f;" in final_cascade
    assert "selection-color: #f8fafc;" in final_cascade


def test_web_and_xterm_selection_share_workspace_tokens() -> None:
    root = Path(__file__).resolve().parents[1]
    theme = (root / "src" / "web" / "assets" / "workspace-theme.css").read_text(
        encoding="utf-8"
    )
    xterm = (root / "src" / "web" / "xterm_terminal.html").read_text(
        encoding="utf-8"
    )

    assert "--text-selection-bg: #315f9f;" in theme
    assert "--text-selection-fg: #f8fafc;" in theme
    assert "::selection" in theme
    assert "background: var(--text-selection-bg);" in theme
    assert "color: var(--text-selection-fg);" in theme
    assert "selectionBackground: cssVar('--text-selection-bg')" in xterm
    assert "selectionForeground: cssVar('--text-selection-fg')" in xterm
