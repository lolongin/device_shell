"""Compatibility entry point for :mod:`src.device_mcp.server`."""

from .device_mcp.server import *  # noqa: F403
from .device_mcp.server import main, mcp

__all__ = ["main", "mcp"]


if __name__ == "__main__":
    main()
