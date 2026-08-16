from __future__ import annotations

from dataclasses import dataclass

import pytest

from device_tui.plugin_api import DeviceSourceContext, DeviceSourceDescriptor
from device_tui.application.secrets import MemorySecretStore
from device_tui.application.settings import MemorySettingsStore
from device_tui.device_sources.service import DeviceSourceService, DeviceSourceServiceError
from device_tui.device_sources.imported import MemoryImportedDeviceStore
from device_tui.device_sources.profile import ProductProfile
from device_tui.device_sources.sample import SampleDeviceRepository


@dataclass
class _WebsitePlugin:
    repository: SampleDeviceRepository

    descriptor = DeviceSourceDescriptor(
        id="internal-site",
        label="公司设备平台",
        description="固定网站产品测试来源。",
        requires_login=True,
        default_priority=100,
    )

    def create_repository(self, context: DeviceSourceContext) -> SampleDeviceRepository:
        assert context.imported_store is not None
        return self.repository


def _service(
    *,
    profile: ProductProfile = ProductProfile(),
    store: MemoryImportedDeviceStore | None = None,
    settings: MemorySettingsStore | None = None,
    plugins=(),
) -> DeviceSourceService:
    return DeviceSourceService.create(
        imported_store=store or MemoryImportedDeviceStore(),
        settings=settings or MemorySettingsStore(),
        secrets=MemorySecretStore(),
        product_profile=profile,
        plugins=plugins,
        discover_plugins=False,
        injected_repository=SampleDeviceRepository(),
    )


def test_service_owns_only_current_electron_sources() -> None:
    service = _service()

    assert service.active_source == "sample"
    assert set(service.source_ids()) == {"sample", "imported"}
    assert "api" not in {item.id for item in service.registry.descriptors()}


def test_spreadsheet_product_starts_on_empty_import_repository() -> None:
    service = _service(profile=ProductProfile(mode="spreadsheet"))

    assert service.active_source == "imported"
    assert service.default_source == "imported"


def test_web_product_fixes_external_source_and_rejects_switch() -> None:
    service = _service(
        profile=ProductProfile(mode="web", source_id="internal-site"),
        plugins=[_WebsitePlugin(SampleDeviceRepository())],
    )

    assert service.active_source == "internal-site"
    with pytest.raises(DeviceSourceServiceError, match="开发配置固定"):
        service.activate("sample")


def test_universal_activation_is_persisted() -> None:
    store = MemoryImportedDeviceStore()
    store.replace_imported_devices(
        SampleDeviceRepository(device_count=1).fetch_devices(),
        source_name="devices.csv",
        sheet_name="devices",
        imported_at="2026-08-16T00:00:00+00:00",
    )
    settings = MemorySettingsStore()
    service = _service(store=store, settings=settings)

    service.activate("imported")

    assert service.active_source == "imported"
    assert settings.get("devices.active_source") == "imported"
