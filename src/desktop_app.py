"""Device TUI desktop application entry point."""
from __future__ import annotations

import os
import sys

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:
    Qt = None
    QApplication = None
    PYSIDE6_IMPORT_ERROR = __import__("sys").exc_info()[1]
else:
    PYSIDE6_IMPORT_ERROR = None


def configure_qt_webengine_startup() -> None:
    """Apply WebEngine settings before importing widgets which touch it."""
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    defaults = [
        "--disable-gpu",
        "--disable-gpu-compositing",
        "--disable-accelerated-2d-canvas",
        "--disable-accelerated-video-decode",
        "--disable-accelerated-compositing",
        "--disable-features=CalculateNativeWinOcclusion",
        "--log-level=3",
    ]
    merged = flags.split() if flags else []
    for flag in defaults:
        if flag not in merged:
            merged.append(flag)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(merged)
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("QT_LOGGING_RULES", "qt.webenginecontext.debug=false;qt.webengine.*=false")

    if QApplication is None or Qt is None:
        return
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)


def import_main_window() -> type:
    try:
        from src.app.main_window import DeviceDesktopApp
    except ImportError:
        from app.main_window import DeviceDesktopApp
    return DeviceDesktopApp


def main() -> None:
    if PYSIDE6_IMPORT_ERROR is not None:
        raise SystemExit(
            "PySide6 is not installed. Run `pip install -e .` or `pip install PySide6` and try again."
        )
    configure_qt_webengine_startup()
    DeviceDesktopApp = import_main_window()
    app = QApplication.instance() or QApplication([])
    window = DeviceDesktopApp()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
