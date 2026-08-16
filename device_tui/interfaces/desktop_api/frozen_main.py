"""PyInstaller entry point for the backend executable."""

from __future__ import annotations

from device_tui.interfaces.desktop_api.main import main


if __name__ == "__main__":
    main()
