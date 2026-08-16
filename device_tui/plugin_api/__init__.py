"""Versioned public API implemented by Device TUI device-source plugins.

External plugins import this module instead of depending on internal module paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol, TypeAlias

from .repository import DeviceRepository


DEVICE_SOURCE_PLUGIN_API_VERSION = 1
DEVICE_SOURCE_ENTRY_POINT_GROUP = "device_tui.device_sources"
DEVICE_SOURCE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
DEVICE_SOURCE_ICONS = frozenset({"database", "globe", "spreadsheet", "plug"})
PLUGIN_CONFIG_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")

PluginConfigValue: TypeAlias = str | int | float | bool | None
PluginConfigKind: TypeAlias = Literal["text", "url", "number", "boolean", "select", "secret"]


class DeviceSourcePluginError(RuntimeError):
    """Raised when a source plugin violates the public plugin contract."""


@dataclass(frozen=True, slots=True)
class PluginConfigOption:
    value: str
    label: str

    def __post_init__(self) -> None:
        value = self.value.strip()
        label = self.label.strip()
        if not value or len(value) > 120:
            raise DeviceSourcePluginError("Plugin option values must contain 1-120 characters.")
        if not label or len(label) > 120:
            raise DeviceSourcePluginError("Plugin option labels must contain 1-120 characters.")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "label", label)


@dataclass(frozen=True, slots=True)
class PluginConfigField:
    key: str
    label: str
    kind: PluginConfigKind = "text"
    default: PluginConfigValue = None
    description: str = ""
    placeholder: str = ""
    required: bool = False
    advanced: bool = False
    minimum: float | None = None
    maximum: float | None = None
    options: tuple[PluginConfigOption, ...] = ()

    def __post_init__(self) -> None:
        key = self.key.strip().lower()
        label = self.label.strip()
        if not PLUGIN_CONFIG_KEY_PATTERN.fullmatch(key):
            raise DeviceSourcePluginError(f"Invalid plugin configuration key: {key}")
        if not label or len(label) > 100:
            raise DeviceSourcePluginError("Plugin configuration labels must contain 1-100 characters.")
        if self.kind not in {"text", "url", "number", "boolean", "select", "secret"}:
            raise DeviceSourcePluginError(f"Unsupported plugin configuration kind: {self.kind}")
        if self.kind == "select" and not self.options:
            raise DeviceSourcePluginError(f"Select field {key} must define at least one option.")
        if self.kind != "select" and self.options:
            raise DeviceSourcePluginError(f"Only select fields may define options: {key}")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise DeviceSourcePluginError(f"Invalid numeric bounds for plugin field: {key}")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "description", self.description.strip()[:300])
        object.__setattr__(self, "placeholder", self.placeholder.strip()[:200])


@dataclass(frozen=True, slots=True)
class DeviceSourceDescriptor:
    id: str
    label: str
    description: str
    icon: str = "plug"
    version: str = "1.0.0"
    publisher: str = ""
    requires_login: bool = False
    supports_import: bool = False
    default_priority: int = 0
    plugin_api_version: int = DEVICE_SOURCE_PLUGIN_API_VERSION

    def __post_init__(self) -> None:
        source_id = self.id.strip().lower()
        label = self.label.strip()
        description = self.description.strip()
        icon = self.icon.strip().lower()
        version = self.version.strip()
        publisher = self.publisher.strip()
        if not DEVICE_SOURCE_ID_PATTERN.fullmatch(source_id):
            raise DeviceSourcePluginError(
                "Device source ids must start with a lowercase letter and contain only "
                "lowercase letters, numbers, dots, underscores, or hyphens."
            )
        if not label or len(label) > 80:
            raise DeviceSourcePluginError("Device source labels must contain 1-80 characters.")
        if not description or len(description) > 240:
            raise DeviceSourcePluginError(
                "Device source descriptions must contain 1-240 characters."
            )
        if icon not in DEVICE_SOURCE_ICONS:
            raise DeviceSourcePluginError(f"Unsupported device source icon: {icon}")
        if not version or len(version) > 40:
            raise DeviceSourcePluginError("Plugin versions must contain 1-40 characters.")
        if len(publisher) > 100:
            raise DeviceSourcePluginError("Plugin publishers cannot exceed 100 characters.")
        if self.plugin_api_version != DEVICE_SOURCE_PLUGIN_API_VERSION:
            raise DeviceSourcePluginError(
                f"Unsupported device source plugin API {self.plugin_api_version}; "
                f"expected {DEVICE_SOURCE_PLUGIN_API_VERSION}."
            )
        object.__setattr__(self, "id", source_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "icon", icon)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "publisher", publisher)


class PluginSecretReader(Protocol):
    """Read-only view of secrets scoped to one plugin id."""

    def get(self, key: str) -> str | None: ...


class EmptyPluginSecretReader:
    def get(self, key: str) -> str | None:
        del key
        return None


@dataclass(frozen=True, slots=True)
class DeviceSourceContext:
    imported_store: object | None = None
    config: Mapping[str, PluginConfigValue] = field(default_factory=dict)
    secrets: PluginSecretReader = field(default_factory=EmptyPluginSecretReader)
    configured_keys: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.configured_keys is None:
            object.__setattr__(self, "configured_keys", frozenset(self.config))


@dataclass(frozen=True, slots=True)
class PluginCheckResult:
    success: bool
    message: str


class DeviceSourcePlugin(Protocol):
    @property
    def descriptor(self) -> DeviceSourceDescriptor: ...

    @property
    def config_fields(self) -> tuple[PluginConfigField, ...]: ...

    def create_repository(self, context: DeviceSourceContext) -> DeviceRepository: ...
