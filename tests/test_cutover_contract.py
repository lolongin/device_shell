"""Final cutover contract for the Electron + Python architecture."""

from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
QT_TOKENS = (
    "PySide",
    "PySide6",
    "PyQt",
    "QtWidgets",
    "QtCore",
    "QtGui",
    "QtWebEngine",
    "QtWebChannel",
)
REMOVED_PATHS = (
    "src",
)


def test_python_source_has_no_qt_dependency() -> None:
    offenders: list[str] = []
    scanned = sorted((ROOT / "device_tui").rglob("*.py"))

    for path in scanned:
        source = path.read_text(encoding="utf-8")
        for token in QT_TOKENS:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)}: {token}")

    assert scanned
    assert offenders == []


def test_python_package_has_no_qt_runtime_dependency_or_gui_script() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    dependencies = "\n".join(project["dependencies"]).casefold()
    scripts = project["scripts"]

    assert "pyside" not in dependencies
    assert "pyqt" not in dependencies
    assert "pyte" not in dependencies
    assert scripts == {
        "device-tui-backend": "device_tui.interfaces.desktop_api.main:main",
        "device-tui-mcp": "device_tui.interfaces.mcp.server:main",
    }


def test_legacy_desktop_paths_are_removed() -> None:
    leftovers: list[str] = []
    for relative in REMOVED_PATHS:
        path = ROOT / relative
        if path.is_file():
            leftovers.append(relative)
        elif path.is_dir():
            files = [
                child
                for child in path.rglob("*")
                if child.is_file() and "__pycache__" not in child.parts
            ]
            leftovers.extend(str(child.relative_to(ROOT)) for child in files)

    assert leftovers == []


def test_device_tui_is_the_only_python_package_root() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "device_tui*"
    ]

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "device_tui").rglob("*.py"))
    )
    assert "from src." not in source
    assert "import src." not in source

    for relative in (
        "device_tui/domain",
        "device_tui/application",
        "device_tui/device_sources",
        "device_tui/infrastructure",
        "device_tui/interfaces/desktop_api",
        "device_tui/interfaces/mcp",
        "device_tui/plugin_api",
    ):
        assert (ROOT / relative).is_dir()


def test_electron_and_backend_entry_points_exist() -> None:
    assert (ROOT / "desktop/package.json").is_file()
    assert (ROOT / "desktop/src/main").is_dir()
    assert (ROOT / "desktop/src/renderer/src/App.vue").is_file()
    assert (ROOT / "device_tui/interfaces/desktop_api/main.py").is_file()
