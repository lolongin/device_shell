"""Application service owning device-source policy, plugins, and active repository."""

from __future__ import annotations

import os
from threading import RLock
from typing import Iterable, Mapping

from device_tui.plugin_api import (
    DEVICE_SOURCE_ID_PATTERN,
    DeviceSourceDescriptor,
    DeviceSourcePlugin,
    DeviceSourcePluginError,
    PluginCheckResult,
    PluginConfigValue,
)

from device_tui.application.secrets import SecretStore
from device_tui.application.settings import SettingsStore
from device_tui.device_sources.imported import ImportedDeviceMetadata, ImportedDeviceStore
from device_tui.device_sources.plugins import DeviceSourceRegistry, build_device_source_registry
from device_tui.device_sources.profile import ProductProfile
from device_tui.domain.devices.models import Device
from device_tui.domain.devices.repository import (
    DeviceRepository,
    InternalAuthStatus,
    RepositoryError,
)


ACTIVE_DEVICE_SOURCE_SETTING = "devices.active_source"


class DeviceSourceServiceError(RuntimeError):
    """A user-safe device-source policy or availability failure."""


class DeviceSourceService:
    """Expose one stable repository while owning all source-selection state."""

    def __init__(
        self,
        *,
        registry: DeviceSourceRegistry,
        imported_store: ImportedDeviceStore,
        settings: SettingsStore,
        product_profile: ProductProfile,
        configured_default: str,
        default_source: str,
        active_source: str,
    ) -> None:
        self.registry = registry
        self.imported_store = imported_store
        self.settings = settings
        self.product_profile = product_profile
        self.configured_default = configured_default
        self.default_source = default_source
        self.import_source_id = registry.import_source_id()
        self._repositories = registry.repositories()
        if active_source not in self._repositories:
            raise ValueError(f"Unknown device source: {active_source}")
        self._active_source = active_source
        self._lock = RLock()
        self.settings.set(ACTIVE_DEVICE_SOURCE_SETTING, active_source)

    @classmethod
    def create(
        cls,
        *,
        imported_store: ImportedDeviceStore,
        settings: SettingsStore,
        secrets: SecretStore,
        product_profile: ProductProfile,
        plugins: Iterable[DeviceSourcePlugin] = (),
        discover_plugins: bool = True,
        injected_repository: DeviceRepository | None = None,
    ) -> "DeviceSourceService":
        registry = build_device_source_registry(
            imported_store=imported_store,
            plugins=plugins,
            discover=discover_plugins,
            settings_store=settings,
            secret_store=secrets,
        )
        if injected_repository is not None:
            registry.replace_repository("sample", injected_repository)
        repositories = registry.repositories()
        configured_default = os.getenv(
            "DEVICE_TUI_DEFAULT_DATA_SOURCE", ""
        ).strip().lower()
        import_source_id = registry.import_source_id()
        if product_profile.source_locked:
            default_source = cls._fixed_product_source(
                registry,
                repositories,
                product_profile,
                import_source_id,
            )
        else:
            default_source = (
                "sample"
                if injected_repository is not None
                else registry.preferred_default_source(
                    configured_default,
                    allow_import=False,
                )
            )
        configured_source = os.getenv("DEVICE_TUI_DATA_SOURCE", "").strip().lower()
        if configured_source and not DEVICE_SOURCE_ID_PATTERN.fullmatch(configured_source):
            registry.record_warning(
                f"忽略无效的 DEVICE_TUI_DATA_SOURCE：{configured_source[:80]}"
            )
            configured_source = ""
        persisted_source = str(
            settings.get(ACTIVE_DEVICE_SOURCE_SETTING, "") or ""
        ).strip().lower()
        active_source = default_source if product_profile.source_locked else (
            configured_source
            if configured_source in repositories
            else persisted_source if persisted_source in repositories else default_source
        )
        if (
            registry.descriptor(active_source).supports_import
            and imported_store.imported_device_metadata().row_count <= 0
            and product_profile.mode != "spreadsheet"
        ):
            active_source = registry.preferred_default_source(
                default_source,
                allow_import=False,
            )
        return cls(
            registry=registry,
            imported_store=imported_store,
            settings=settings,
            product_profile=product_profile,
            configured_default=configured_default,
            default_source=default_source,
            active_source=active_source,
        )

    @staticmethod
    def _fixed_product_source(
        registry: DeviceSourceRegistry,
        repositories: Mapping[str, DeviceRepository],
        profile: ProductProfile,
        import_source_id: str,
    ) -> str:
        source_id = profile.source_id or import_source_id
        try:
            descriptor = registry.descriptor(source_id)
        except DeviceSourcePluginError as exc:
            raise RuntimeError(
                f"Configured product source {source_id!r} is not installed."
            ) from exc
        if profile.mode == "web" and not descriptor.requires_login:
            raise RuntimeError(
                f"Product source {source_id!r} does not provide the website login workflow."
            )
        if profile.mode == "spreadsheet" and not descriptor.supports_import:
            raise RuntimeError(
                f"Product source {source_id!r} does not provide the spreadsheet import workflow."
            )
        if source_id not in repositories:
            reason = registry.unavailable_reason(source_id)
            detail = f": {reason}" if reason else ""
            raise RuntimeError(
                f"Configured product source {source_id!r} is unavailable{detail}"
            )
        return source_id

    @property
    def active_source(self) -> str:
        with self._lock:
            return self._active_source

    def source_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._repositories)

    def repository(self, source_id: str | None = None) -> DeviceRepository:
        with self._lock:
            return self._repositories[source_id or self._active_source]

    def activate(self, source_id: str) -> DeviceSourceDescriptor:
        if self.product_profile.source_locked and source_id != self.active_source:
            raise DeviceSourceServiceError(
                "当前产品的数据来源由开发配置固定，用户不能切换。"
            )
        try:
            descriptor = self.registry.descriptor(source_id)
        except DeviceSourcePluginError as exc:
            raise DeviceSourceServiceError(str(exc)) from exc
        if source_id not in self.source_ids():
            reason = self.registry.unavailable_reason(source_id)
            raise DeviceSourceServiceError(
                reason or f"设备数据源“{descriptor.label}”当前不可用。"
            )
        if (
            descriptor.supports_import
            and self.imported_store.imported_device_metadata().row_count <= 0
        ):
            raise DeviceSourceServiceError(
                "尚未导入设备，请先选择 Excel、CSV 或 TSV 文件。"
            )
        with self._lock:
            self._active_source = source_id
        self.settings.set(ACTIVE_DEVICE_SOURCE_SETTING, source_id)
        return descriptor

    def apply_plugin_configuration(
        self,
        source_id: str,
        *,
        config_updates: Mapping[str, PluginConfigValue],
        secret_updates: Mapping[str, str | None],
        enabled: bool | None,
    ) -> DeviceRepository | None:
        repository = self.registry.apply_configuration(
            source_id,
            config_updates=config_updates,
            secret_updates=secret_updates,
            enabled=enabled,
        )
        with self._lock:
            if repository is None:
                self._repositories.pop(source_id, None)
            else:
                self._repositories[source_id] = repository
        self.default_source = self.registry.preferred_default_source(
            self.configured_default,
            allow_import=False,
        )
        return repository

    def test_plugin_configuration(self, source_id: str) -> PluginCheckResult:
        return self.registry.test_configuration(source_id)

    def replace_imported_devices(
        self,
        devices: list[Device],
        *,
        source_name: str,
        sheet_name: str,
        imported_at: str,
    ) -> ImportedDeviceMetadata:
        metadata = self.imported_store.replace_imported_devices(
            devices,
            source_name=source_name,
            sheet_name=sheet_name,
            imported_at=imported_at,
        )
        self.activate(self.import_source_id)
        return metadata

    @property
    def refresh_interval_seconds(self) -> float:
        return self.repository().refresh_interval_seconds

    @property
    def live_update_timeout_seconds(self) -> float:
        return self.repository().live_update_timeout_seconds

    def internal_auth_status(self) -> InternalAuthStatus:
        return self.repository().internal_auth_status()

    def login_internal(self, username: str, password: str, cid: str) -> InternalAuthStatus:
        return self.repository().login_internal(username, password, cid)

    def logout_internal(self) -> InternalAuthStatus:
        return self.repository().logout_internal()

    def current_user(self) -> str:
        return self.repository().current_user()

    def fetch_devices(self):
        return self.repository().fetch_devices()

    def fetch_owned_device_ids(self):
        return self.repository().fetch_owned_device_ids()

    def toggle_device(self, device_id: str, user: str) -> str:
        return self.repository().toggle_device(device_id, user)

    def claim_device(self, device_id: str, user: str) -> str:
        return self.repository().claim_device(device_id, user)

    def release_device(self, device_id: str, user: str) -> str:
        return self.repository().release_device(device_id, user)

    def power_off_device(self, device_id: str, user: str) -> str:
        return self.repository().power_off_device(device_id, user)

    def current_revision(self) -> int:
        return self.repository().current_revision()

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None:
        return self.repository().wait_for_update(since_revision, timeout_seconds)
