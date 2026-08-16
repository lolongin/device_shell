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
    "src/desktop_app.py",
    "src/app",
    "src/widgets",
    "src/web",
    "src/app_state.py",
    "src/async_utils.py",
    "src/styles.py",
    "src/theme_tokens.py",
)


def test_python_source_has_no_qt_dependency() -> None:
    offenders: list[str] = []
    scanned = sorted((ROOT / "src").rglob("*.py"))

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
        "device-tui-backend": "src.desktop_backend.main:main",
        "device-tui-mcp": "src.device_mcp.server:main",
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


def test_electron_and_backend_entry_points_exist() -> None:
    assert (ROOT / "desktop/package.json").is_file()
    assert (ROOT / "desktop/src/main").is_dir()
    assert (ROOT / "desktop/src/renderer/src/App.vue").is_file()
    assert (ROOT / "src/desktop_backend/main.py").is_file()
