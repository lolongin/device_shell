"""Pluggable device-source discovery and built-in source providers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import metadata
from typing import Iterable, Mapping, Protocol
from urllib.parse import urlparse

from device_tui.plugin_api import (
    DEVICE_SOURCE_ENTRY_POINT_GROUP,
    DEVICE_SOURCE_ID_PATTERN,
    DEVICE_SOURCE_PLUGIN_API_VERSION,
    DeviceSourceContext,
    DeviceSourceDescriptor,
    DeviceSourcePlugin,
    DeviceSourcePluginError,
    PluginCheckResult,
    PluginConfigField,
    PluginConfigValue,
)
from device_tui.repository_api import DEVICE_REPOSITORY_MEMBERS

from ._sample_data import CURRENT_USER
from .imported_devices import ImportedDeviceRepository, ImportedDeviceStore
from .repository import DeviceRepository, SampleDeviceRepository


PLUGIN_ENABLED_SETTING_PREFIX = "device_source_plugins.enabled."
PLUGIN_CONFIG_SETTING_PREFIX = "device_source_plugins.config."
PLUGIN_SECRET_PREFIX = "device-source-plugin"


class _SettingsStore(Protocol):
    def get(self, key: str, default: object = None) -> object: ...
    def set(self, key: str, value: object) -> None: ...


class _SecretStore(Protocol):
    def get(self, secret_id: str) -> str | None: ...
    def set(self, secret_id: str, value: str) -> None: ...
    def delete(self, secret_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class DeviceSourcePluginRegistration:
    plugin: DeviceSourcePlugin
    descriptor: DeviceSourceDescriptor
    config_fields: tuple[PluginConfigField, ...]
    built_in: bool


class _ScopedSecretReader:
    def __init__(
        self,
        registry: "DeviceSourceRegistry",
        source_id: str,
        overrides: Mapping[str, str | None] | None = None,
    ) -> None:
        self._registry = registry
        self._source_id = source_id
        self._overrides = dict(overrides or {})

    def get(self, key: str) -> str | None:
        if key in self._overrides:
            return self._overrides[key]
        return self._registry.secret_value(self._source_id, key)


def validate_device_repository(repository: object) -> DeviceRepository:
    missing = [name for name in DEVICE_REPOSITORY_MEMBERS if not hasattr(repository, name)]
    if missing:
        raise DeviceSourcePluginError(
            "Device source repository is missing required members: " + ", ".join(missing)
        )
    non_callable = [
        name
        for name in DEVICE_REPOSITORY_MEMBERS[2:]
        if not callable(getattr(repository, name, None))
    ]
    if non_callable:
        raise DeviceSourcePluginError(
            "Device source repository members must be callable: "
            + ", ".join(non_callable)
        )
    return repository  # type: ignore[return-value]


class SampleDeviceSourcePlugin:
    @property
    def config_fields(self) -> tuple[PluginConfigField, ...]:
        return ()

    @property
    def descriptor(self) -> DeviceSourceDescriptor:
        return DeviceSourceDescriptor(
            id="sample",
            label="示例数据",
            description="本地演示设备，不依赖网站登录。",
            icon="database",
            version="0.1.0",
            publisher="Device TUI",
            default_priority=0,
        )

    def create_repository(self, context: DeviceSourceContext) -> DeviceRepository:
        del context
        current_user = os.getenv("DEVICE_TUI_CURRENT_USER", CURRENT_USER)
        try:
            sample_count = int(os.getenv("DEVICE_TUI_SAMPLE_DEVICE_COUNT", "0") or "0")
        except ValueError:
            sample_count = 0
        return SampleDeviceRepository(current_user=current_user, device_count=sample_count)


class ImportedDeviceSourcePlugin:
    @property
    def config_fields(self) -> tuple[PluginConfigField, ...]:
        return ()

    @property
    def descriptor(self) -> DeviceSourceDescriptor:
        return DeviceSourceDescriptor(
            id="imported",
            label="Excel / 批量导入",
            description="使用最近一次 Excel、CSV 或 TSV 导入快照。",
            icon="spreadsheet",
            version="0.1.0",
            publisher="Device TUI",
            supports_import=True,
            default_priority=-20,
        )

    def create_repository(self, context: DeviceSourceContext) -> DeviceRepository:
        if context.imported_store is None:
            raise DeviceSourcePluginError("Imported device storage is unavailable.")
        return ImportedDeviceRepository(context.imported_store)  # type: ignore[arg-type]


class DeviceSourceRegistry:
    """Validated descriptors and repositories from built-in and external plugins."""

    def __init__(
        self,
        context: DeviceSourceContext,
        *,
        settings_store: _SettingsStore | None = None,
        secret_store: _SecretStore | None = None,
    ) -> None:
        self._imported_store = context.imported_store
        self._settings_store = settings_store
        self._secret_store = secret_store
        self._runtime_settings: dict[str, object] = {}
        self._runtime_secrets: dict[str, str] = {}
        self._descriptors: dict[str, DeviceSourceDescriptor] = {}
        self._registrations: dict[str, DeviceSourcePluginRegistration] = {}
        self._repositories: dict[str, DeviceRepository] = {}
        self._errors: dict[str, str] = {}
        self._warnings: list[str] = []

    def register(
        self,
        plugin: DeviceSourcePlugin,
        *,
        strict: bool = True,
        built_in: bool = False,
    ) -> None:
        try:
            descriptor = plugin.descriptor
            if not isinstance(descriptor, DeviceSourceDescriptor):
                raise DeviceSourcePluginError(
                    "Device source plugins must expose a DeviceSourceDescriptor."
                )
            fields = tuple(getattr(plugin, "config_fields", ()) or ())
            if any(not isinstance(item, PluginConfigField) for item in fields):
                raise DeviceSourcePluginError(
                    "Device source plugin configuration must use PluginConfigField entries."
                )
            keys = [item.key for item in fields]
            if len(keys) != len(set(keys)):
                raise DeviceSourcePluginError(
                    f"Duplicate configuration field in plugin {descriptor.id}."
                )
        except Exception as exc:
            if strict:
                raise DeviceSourcePluginError(str(exc)) from exc
            self._warnings.append(f"无法读取设备源插件：{_safe_plugin_error(exc)}")
            return
        if descriptor.id in self._descriptors:
            message = f"Duplicate device source id: {descriptor.id}"
            if strict:
                raise DeviceSourcePluginError(message)
            self._warnings.append(message)
            return
        self._descriptors[descriptor.id] = descriptor
        self._registrations[descriptor.id] = DeviceSourcePluginRegistration(
            plugin=plugin,
            descriptor=descriptor,
            config_fields=fields,
            built_in=built_in,
        )
        self.reload(descriptor.id)

    def reload(self, source_id: str) -> DeviceRepository | None:
        registration = self.registration(source_id)
        self._repositories.pop(source_id, None)
        self._errors.pop(source_id, None)
        if not self.enabled(source_id):
            self._errors[source_id] = "插件已禁用。"
            return None
        try:
            repository = self._create_repository(registration)
        except Exception as exc:
            self._errors[source_id] = _safe_plugin_error(exc)
            return None
        self._repositories[source_id] = repository
        return repository

    def apply_configuration(
        self,
        source_id: str,
        *,
        config_updates: Mapping[str, PluginConfigValue] | None = None,
        secret_updates: Mapping[str, str | None] | None = None,
        enabled: bool | None = None,
    ) -> DeviceRepository | None:
        registration = self.registration(source_id)
        if registration.built_in and enabled is False:
            raise DeviceSourcePluginError("内置插件不能禁用。")
        target_enabled = self.enabled(source_id) if enabled is None else bool(enabled)
        config = self._normalized_configuration(
            registration,
            config_updates or {},
            validate_required=target_enabled,
        )
        secrets = self._normalized_secret_updates(
            registration,
            secret_updates or {},
            validate_required=target_enabled,
        )
        candidate: DeviceRepository | None = None
        if target_enabled:
            candidate = self._create_repository(
                registration,
                config_override=config,
                secret_overrides=secrets,
            )
        self._setting_set(self._config_setting_key(source_id), dict(config))
        self._setting_set(self._enabled_setting_key(source_id), target_enabled)
        for key, value in secrets.items():
            self._secret_set(source_id, key, value)
        self._repositories.pop(source_id, None)
        self._errors.pop(source_id, None)
        if candidate is not None:
            self._repositories[source_id] = candidate
        else:
            self._errors[source_id] = "插件已禁用。"
        return candidate

    def test_configuration(self, source_id: str) -> PluginCheckResult:
        registration = self.registration(source_id)
        if not self.enabled(source_id):
            return PluginCheckResult(False, "请先启用插件。")
        try:
            context = self._context_for(registration)
            checker = getattr(registration.plugin, "test_connection", None)
            if callable(checker):
                result = checker(context)
                if not isinstance(result, PluginCheckResult):
                    raise DeviceSourcePluginError(
                        "Plugin test_connection must return PluginCheckResult."
                    )
                return result
            self._create_repository(registration)
        except Exception as exc:
            return PluginCheckResult(False, _safe_plugin_error(exc))
        return PluginCheckResult(True, "插件配置有效，数据源可以初始化。")

    def registration(self, source_id: str) -> DeviceSourcePluginRegistration:
        try:
            return self._registrations[source_id]
        except KeyError as exc:
            raise DeviceSourcePluginError(f"Unknown device source id: {source_id}") from exc

    def registrations(self) -> tuple[DeviceSourcePluginRegistration, ...]:
        return tuple(self._registrations.values())

    def enabled(self, source_id: str) -> bool:
        registration = self.registration(source_id)
        if registration.built_in:
            return True
        return bool(self._setting_get(self._enabled_setting_key(source_id), True))

    def configuration(self, source_id: str) -> dict[str, PluginConfigValue]:
        registration = self.registration(source_id)
        return self._normalized_configuration(
            registration,
            {},
            validate_required=False,
        )

    def secret_configured(self, source_id: str, key: str) -> bool:
        try:
            return bool(self.secret_value(source_id, key))
        except Exception:
            return False

    def secret_value(self, source_id: str, key: str) -> str | None:
        secret_id = self._secret_id(source_id, key)
        if self._secret_store is not None:
            return self._secret_store.get(secret_id)
        return self._runtime_secrets.get(secret_id)

    def _create_repository(
        self,
        registration: DeviceSourcePluginRegistration,
        *,
        config_override: Mapping[str, PluginConfigValue] | None = None,
        secret_overrides: Mapping[str, str | None] | None = None,
    ) -> DeviceRepository:
        context = self._context_for(
            registration,
            config_override=config_override,
            secret_overrides=secret_overrides,
        )
        return validate_device_repository(registration.plugin.create_repository(context))

    def _context_for(
        self,
        registration: DeviceSourcePluginRegistration,
        *,
        config_override: Mapping[str, PluginConfigValue] | None = None,
        secret_overrides: Mapping[str, str | None] | None = None,
    ) -> DeviceSourceContext:
        config = (
            dict(config_override)
            if config_override is not None
            else self._normalized_configuration(registration, {})
        )
        configured_keys = (
            frozenset(config)
            if config_override is not None
            else self._stored_configuration_keys(registration.descriptor.id)
        )
        return DeviceSourceContext(
            imported_store=self._imported_store,
            config=config,
            secrets=_ScopedSecretReader(
                self,
                registration.descriptor.id,
                secret_overrides,
            ),
            configured_keys=configured_keys,
        )

    def _stored_configuration_keys(self, source_id: str) -> frozenset[str]:
        stored = self._setting_get(self._config_setting_key(source_id), {})
        return frozenset(stored) if isinstance(stored, dict) else frozenset()

    def _normalized_configuration(
        self,
        registration: DeviceSourcePluginRegistration,
        updates: Mapping[str, PluginConfigValue],
        *,
        validate_required: bool = True,
    ) -> dict[str, PluginConfigValue]:
        fields = {item.key: item for item in registration.config_fields}
        unknown = sorted(set(updates) - set(fields))
        if unknown:
            raise DeviceSourcePluginError(
                "未知插件配置项：" + "、".join(unknown)
            )
        raw_stored = self._setting_get(
            self._config_setting_key(registration.descriptor.id),
            {},
        )
        stored = raw_stored if isinstance(raw_stored, dict) else {}
        values: dict[str, PluginConfigValue] = {}
        for key, item in fields.items():
            if item.kind == "secret":
                continue
            value = updates.get(key, stored.get(key, item.default))
            values[key] = self._normalize_field_value(
                item,
                value,
                validate_required=validate_required,
            )
        return values

    def _normalized_secret_updates(
        self,
        registration: DeviceSourcePluginRegistration,
        updates: Mapping[str, str | None],
        *,
        validate_required: bool = True,
    ) -> dict[str, str | None]:
        secret_fields = {
            item.key: item for item in registration.config_fields if item.kind == "secret"
        }
        unknown = sorted(set(updates) - set(secret_fields))
        if unknown:
            raise DeviceSourcePluginError(
                "未知插件密钥项：" + "、".join(unknown)
            )
        normalized: dict[str, str | None] = {}
        for key, value in updates.items():
            if value is None:
                normalized[key] = None
                continue
            text = str(value)
            if len(text) > 4096:
                raise DeviceSourcePluginError(f"插件密钥 {key} 不能超过 4096 个字符。")
            normalized[key] = text
        for key, item in secret_fields.items():
            effective = normalized.get(key, self.secret_value(registration.descriptor.id, key))
            if validate_required and item.required and not effective:
                raise DeviceSourcePluginError(f"请填写“{item.label}”。")
        return normalized

    @staticmethod
    def _normalize_field_value(
        field: PluginConfigField,
        value: PluginConfigValue,
        *,
        validate_required: bool = True,
    ) -> PluginConfigValue:
        if value is None and not validate_required:
            return None
        if field.kind == "boolean":
            if not isinstance(value, bool):
                raise DeviceSourcePluginError(f"“{field.label}”必须是开关值。")
            return value
        if field.kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                try:
                    value = float(str(value))
                except (TypeError, ValueError) as exc:
                    raise DeviceSourcePluginError(f"“{field.label}”必须是数字。") from exc
            number = float(value)
            if field.minimum is not None and number < field.minimum:
                raise DeviceSourcePluginError(f"“{field.label}”不能小于 {field.minimum:g}。")
            if field.maximum is not None and number > field.maximum:
                raise DeviceSourcePluginError(f"“{field.label}”不能大于 {field.maximum:g}。")
            return int(number) if number.is_integer() else number
        text = "" if value is None else str(value).strip()
        if validate_required and field.required and not text:
            raise DeviceSourcePluginError(f"请填写“{field.label}”。")
        if len(text) > 4096:
            raise DeviceSourcePluginError(f"“{field.label}”不能超过 4096 个字符。")
        if field.kind == "url" and text:
            parsed = urlparse(text)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise DeviceSourcePluginError(f"“{field.label}”必须是有效的 HTTP(S) 地址。")
        if field.kind == "select" and text not in {item.value for item in field.options}:
            raise DeviceSourcePluginError(f"“{field.label}”包含不支持的选项。")
        return text

    def _setting_get(self, key: str, default: object) -> object:
        if self._settings_store is not None:
            return self._settings_store.get(key, default)
        return self._runtime_settings.get(key, default)

    def _setting_set(self, key: str, value: object) -> None:
        if self._settings_store is not None:
            self._settings_store.set(key, value)
        else:
            self._runtime_settings[key] = value

    def _secret_set(self, source_id: str, key: str, value: str | None) -> None:
        secret_id = self._secret_id(source_id, key)
        if self._secret_store is not None:
            if value is None:
                self._secret_store.delete(secret_id)
            else:
                self._secret_store.set(secret_id, value)
            return
        if value is None:
            self._runtime_secrets.pop(secret_id, None)
        else:
            self._runtime_secrets[secret_id] = value

    @staticmethod
    def _enabled_setting_key(source_id: str) -> str:
        return f"{PLUGIN_ENABLED_SETTING_PREFIX}{source_id}"

    @staticmethod
    def _config_setting_key(source_id: str) -> str:
        return f"{PLUGIN_CONFIG_SETTING_PREFIX}{source_id}"

    @staticmethod
    def _secret_id(source_id: str, key: str) -> str:
        return f"{PLUGIN_SECRET_PREFIX}/{source_id}/{key}"

    def replace_repository(self, source_id: str, repository: DeviceRepository) -> None:
        if source_id not in self._descriptors:
            raise DeviceSourcePluginError(f"Unknown device source id: {source_id}")
        self._repositories[source_id] = validate_device_repository(repository)
        self._errors.pop(source_id, None)

    def descriptor(self, source_id: str) -> DeviceSourceDescriptor:
        try:
            return self._descriptors[source_id]
        except KeyError as exc:
            raise DeviceSourcePluginError(f"Unknown device source id: {source_id}") from exc

    def descriptors(self) -> tuple[DeviceSourceDescriptor, ...]:
        return tuple(self._descriptors.values())

    def repositories(self) -> dict[str, DeviceRepository]:
        return dict(self._repositories)

    def unavailable_reason(self, source_id: str) -> str:
        return self._errors.get(source_id, "")

    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    def record_warning(self, message: str) -> None:
        normalized = message.strip()
        if normalized:
            self._warnings.append(normalized[:500])

    def preferred_default_source(
        self,
        preferred: str = "",
        *,
        allow_import: bool = True,
    ) -> str:
        normalized = preferred.strip().lower()
        if (
            normalized in self._repositories
            and (allow_import or not self._descriptors[normalized].supports_import)
        ):
            return normalized
        candidates = [
            descriptor
            for descriptor in self._descriptors.values()
            if descriptor.id in self._repositories
            and (allow_import or not descriptor.supports_import)
        ]
        if not candidates:
            raise DeviceSourcePluginError("No usable device source plugins are installed.")
        return max(candidates, key=lambda item: (item.default_priority, item.id)).id

    def import_source_id(self) -> str:
        candidates = [
            item.id
            for item in self._descriptors.values()
            if item.supports_import and item.id in self._repositories
        ]
        if len(candidates) != 1:
            raise DeviceSourcePluginError(
                "Exactly one installed device source must support the built-in import workflow."
            )
        return candidates[0]


def builtin_device_source_plugins() -> tuple[DeviceSourcePlugin, ...]:
    return (
        SampleDeviceSourcePlugin(),
        ImportedDeviceSourcePlugin(),
    )


def discover_device_source_plugins() -> tuple[list[DeviceSourcePlugin], list[str]]:
    plugins: list[DeviceSourcePlugin] = []
    warnings: list[str] = []
    try:
        discovered = metadata.entry_points()
        entries = (
            discovered.select(group=DEVICE_SOURCE_ENTRY_POINT_GROUP)
            if hasattr(discovered, "select")
            else discovered.get(DEVICE_SOURCE_ENTRY_POINT_GROUP, [])
        )
    except Exception as exc:
        return [], [f"无法发现设备源插件：{_safe_plugin_error(exc)}"]
    for entry in sorted(entries, key=lambda item: item.name):
        try:
            loaded = entry.load()
            candidate = (
                loaded()
                if isinstance(loaded, type) or not hasattr(loaded, "descriptor")
                else loaded
            )
            plugins.append(candidate)
        except Exception as exc:
            warnings.append(
                f"设备源插件 {entry.name} 加载失败：{_safe_plugin_error(exc)}"
            )
    return plugins, warnings


def build_device_source_registry(
    *,
    imported_store: ImportedDeviceStore | None = None,
    plugins: Iterable[DeviceSourcePlugin] = (),
    discover: bool = True,
    settings_store: _SettingsStore | None = None,
    secret_store: _SecretStore | None = None,
) -> DeviceSourceRegistry:
    registry = DeviceSourceRegistry(
        DeviceSourceContext(imported_store=imported_store),
        settings_store=settings_store,
        secret_store=secret_store,
    )
    for plugin in builtin_device_source_plugins():
        registry.register(plugin, built_in=True)
    if discover:
        discovered, warnings = discover_device_source_plugins()
        for warning in warnings:
            registry.record_warning(warning)
        for plugin in discovered:
            registry.register(plugin, strict=False, built_in=False)
    for plugin in plugins:
        registry.register(plugin, built_in=False)
    return registry


def _safe_plugin_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:300]
