from __future__ import annotations

from pathlib import Path


API_ROOT = Path("device_tui/interfaces/desktop_api")


def test_app_is_a_composition_root_without_inline_routes() -> None:
    source = (API_ROOT / "app.py").read_text(encoding="utf-8")

    assert "@app." not in source
    assert "app.include_router(" in source


def test_routers_do_not_import_the_composition_root() -> None:
    for path in (API_ROOT / "routers").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from ..app import" not in source, path
        assert "from device_tui.interfaces.desktop_api.app import" not in source, path
