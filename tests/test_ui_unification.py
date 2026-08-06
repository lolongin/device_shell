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
