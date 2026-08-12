"""Capture the legacy PySide desktop against isolated sample state."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-ms", type=int, default=3_500)
    parser.add_argument("--width", type=int, default=1_560)
    parser.add_argument("--height", type=int, default=960)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))

    with tempfile.TemporaryDirectory(prefix="device-tui-legacy-capture-") as state_root:
        os.environ["APPDATA"] = state_root
        os.environ["DEVICE_TUI_DATA_SOURCE"] = "sample"
        os.environ["DEVICE_TUI_SAMPLE_COUNT"] = "20"
        os.environ["DEVICE_TUI_APP_CONTROL"] = "0"
        os.environ.setdefault("QT_OPENGL", "software")
        os.environ.setdefault("QT_QUICK_BACKEND", "software")

        from src.desktop_app import configure_qt_webengine_startup, import_main_window

        configure_qt_webengine_startup()
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        window = import_main_window()()
        window.resize(max(1_180, args.width), max(720, args.height))
        window.show()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result = {"ok": False}

        def capture() -> None:
            pixmap = window.grab()
            result["ok"] = not pixmap.isNull() and pixmap.save(str(args.output), "PNG")
            window.close()
            QTimer.singleShot(100, app.quit)

        QTimer.singleShot(max(500, args.wait_ms), capture)
        app.exec()
        if not result["ok"]:
            raise RuntimeError(f"Legacy UI capture failed: {args.output}")
    print(f"LegacyCapture={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
