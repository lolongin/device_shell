"""Compatibility alias for :mod:`src.device_mcp.service`."""

import sys

from .device_mcp import service as _implementation

sys.modules[__name__] = _implementation
