"""Private Device TUI source plugin owned by the internal repository."""

from .provider import CompanyDeviceSourcePlugin, create_plugin

__all__ = ["CompanyDeviceSourcePlugin", "create_plugin"]
