"""Cutover contract tests for the Electron + Python backend architecture."""

from __future__ import annotations

from pathlib import Path


GUI_TOKENS = (
    "PySide6",
    "PyQt",
    "QtWidgets",
    "QtCore",
    "QtGui",
    "QtWeb",
)

BACKEND_CORE_PATHS = (
    Path("src/desktop_backend"),
    Path("src/application"),
    Path("src/infrastructure"),
    Path("src/device_mcp"),
    Path("src/terminal_execution.py"),
    Path("src/session_protocol.py"),
)


def test_backend_and_core_modules_do_not_import_qt() -> None:
    """The final Electron path must not pull PySide/PyQt into backend/core code."""

    scanned: list[Path] = []
    offenders: list[str] = []
    for path in BACKEND_CORE_PATHS:
        files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for file_path in files:
            if not file_path.exists():
                continue
            scanned.append(file_path)
            source = file_path.read_text(encoding="utf-8")
            for token in GUI_TOKENS:
                if token in source:
                    offenders.append(f"{file_path}: {token}")

    assert scanned
    assert offenders == []
