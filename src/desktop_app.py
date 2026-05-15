"""Device TUI desktop application entry point."""
from __future__ import annotations

import sys

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:
    QApplication = None
    PYSIDE6_IMPORT_ERROR = __import__("sys").exc_info()[1]
else:
    PYSIDE6_IMPORT_ERROR = None

try:
    from src.app.main_window import DeviceDesktopApp
except ImportError:
    from app.main_window import DeviceDesktopApp


def main() -> None:
    if PYSIDE6_IMPORT_ERROR is not None:
        raise SystemExit(
            "PySide6 is not installed. Run `pip install -e .` or `pip install PySide6` and try again."
        )
    app = QApplication.instance() or QApplication([])
    window = DeviceDesktopApp()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
