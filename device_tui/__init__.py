"""Stable public extension surface for Device TUI integrations."""

from .plugin_api import (
    DEVICE_SOURCE_ENTRY_POINT_GROUP,
    DEVICE_SOURCE_PLUGIN_API_VERSION,
    DeviceSourceContext,
    DeviceSourceDescriptor,
    DeviceSourcePlugin,
    DeviceSourcePluginError,
    PluginCheckResult,
    PluginConfigField,
    PluginConfigOption,
    PluginSecretReader,
)
from .plugin_api.repository import (
    Device,
    DeviceRepository,
    InternalAuthStatus,
    RepositoryConflictError,
    RepositoryError,
)

__all__ = [
    "DEVICE_SOURCE_ENTRY_POINT_GROUP",
    "DEVICE_SOURCE_PLUGIN_API_VERSION",
    "DeviceSourceContext",
    "DeviceSourceDescriptor",
    "DeviceSourcePlugin",
    "DeviceSourcePluginError",
    "PluginCheckResult",
    "PluginConfigField",
    "PluginConfigOption",
    "PluginSecretReader",
    "Device",
    "DeviceRepository",
    "InternalAuthStatus",
    "RepositoryConflictError",
    "RepositoryError",
]
