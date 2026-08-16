from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.device_source_plugins as plugin_module
from src.desktop_backend.app import create_app
from src.desktop_backend.session_hub import SessionHub
from src.device_source_plugins import (
    DEVICE_SOURCE_ENTRY_POINT_GROUP,
    DeviceSourceContext,
    DeviceSourceDescriptor,
    DeviceSourcePluginError,
    PluginCheckResult,
    PluginConfigField,
    build_device_source_registry,
    discover_device_source_plugins,
    validate_device_repository,
)
from src.imported_devices import MemoryImportedDeviceStore
from src.application.secrets import MemorySecretStore
from src.application.settings import MemorySettingsStore
from src.infrastructure.sqlite_desktop import SQLiteDesktopStore
from src.infrastructure.sqlite_settings import SQLiteSettingsStore
from src.repository import InternalAuthStatus, SampleDeviceRepository


class _InternalRepository(SampleDeviceRepository):
    def __init__(self) -> None:
        super().__init__(current_user="internal-user")
        self._authenticated = False
        self.login_received_password = False

    def internal_auth_status(self) -> InternalAuthStatus:
        return InternalAuthStatus(
            available=True,
            configured=True,
            authenticated=self._authenticated,
            username=self.current_user(),
        )

    def login_internal(self, username: str, password: str, cid: str) -> InternalAuthStatus:
        assert password
        self.login_received_password = True
        self._current_user = username
        self._authenticated = True
        return InternalAuthStatus(True, True, True, username=username, cid=cid)

    def logout_internal(self) -> InternalAuthStatus:
        self._authenticated = False
        return self.internal_auth_status()


@dataclass
class _InternalPlugin:
    repository: _InternalRepository

    @property
    def descriptor(self) -> DeviceSourceDescriptor:
        return DeviceSourceDescriptor(
            id="internal-site",
            label="公司设备平台",
            description="通过独立插件访问公司设备网站。",
            icon="globe",
            requires_login=True,
            default_priority=100,
        )

    def create_repository(self, context: DeviceSourceContext) -> _InternalRepository:
        assert context.imported_store is not None
        return self.repository


class _BrokenPlugin:
    descriptor = DeviceSourceDescriptor(
        id="broken-source",
        label="损坏插件",
        description="用于验证加载失败隔离。",
    )

    def create_repository(self, context: DeviceSourceContext):
        del context
        raise RuntimeError("provider initialization failed")


class _ConfigurablePlugin:
    descriptor = DeviceSourceDescriptor(
        id="configured-source",
        label="可配置来源",
        description="验证插件配置和密钥隔离。",
        version="2.3.4",
        publisher="Test Publisher",
        default_priority=60,
    )
    config_fields = (
        PluginConfigField(
            key="base_url",
            label="平台地址",
            kind="url",
            required=True,
        ),
        PluginConfigField(
            key="api_token",
            label="API Token",
            kind="secret",
            required=True,
        ),
    )

    def __init__(self) -> None:
        self.received_config: dict[str, object] = {}
        self.received_token = ""

    def create_repository(self, context: DeviceSourceContext) -> _InternalRepository:
        self.received_config = dict(context.config)
        self.received_token = context.secrets.get("api_token") or ""
        if not self.received_token:
            raise RuntimeError("missing API token")
        return _InternalRepository()

    def test_connection(self, context: DeviceSourceContext) -> PluginCheckResult:
        return PluginCheckResult(
            bool(context.config.get("base_url") and context.secrets.get("api_token")),
            "连接配置有效",
        )


def test_registry_accepts_independent_source_and_uses_its_default_priority() -> None:
    repository = _InternalRepository()
    registry = build_device_source_registry(
        imported_store=MemoryImportedDeviceStore(),
        plugins=[_InternalPlugin(repository)],
        discover=False,
    )

    assert registry.preferred_default_source() == "internal-site"
    assert registry.repositories()["internal-site"] is repository
    assert registry.descriptor("internal-site").requires_login is True


def test_plugin_initialization_failure_is_isolated() -> None:
    registry = build_device_source_registry(
        imported_store=MemoryImportedDeviceStore(),
        plugins=[_BrokenPlugin()],
        discover=False,
    )

    assert "broken-source" not in registry.repositories()
    assert "initialization failed" in registry.unavailable_reason("broken-source")
    assert registry.preferred_default_source() == "sample"


def test_duplicate_source_ids_are_rejected() -> None:
    registry = build_device_source_registry(
        imported_store=MemoryImportedDeviceStore(),
        discover=False,
    )

    with pytest.raises(DeviceSourcePluginError, match="Duplicate device source id"):
        registry.register(plugin_module.SampleDeviceSourcePlugin())


def test_repository_contract_rejects_incomplete_provider() -> None:
    with pytest.raises(DeviceSourcePluginError, match="missing required members"):
        validate_device_repository(object())


def test_plugin_api_version_mismatch_is_rejected() -> None:
    with pytest.raises(DeviceSourcePluginError, match="Unsupported device source plugin API"):
        DeviceSourceDescriptor(
            id="future-source",
            label="未来插件",
            description="使用尚未支持的插件协议。",
            plugin_api_version=2,
        )


def test_entry_point_discovery_loads_plugin_factory(monkeypatch) -> None:
    plugin = _InternalPlugin(_InternalRepository())

    class _EntryPoint:
        name = "internal"

        @staticmethod
        def load():
            return lambda: plugin

    class _EntryPoints(list):
        def select(self, *, group: str):
            return self if group == DEVICE_SOURCE_ENTRY_POINT_GROUP else []

    monkeypatch.setattr(plugin_module.metadata, "entry_points", lambda: _EntryPoints([_EntryPoint()]))

    discovered, warnings = discover_device_source_plugins()

    assert discovered == [plugin]
    assert warnings == []


def test_real_distribution_metadata_entry_point_is_discovered(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / "external_device_source.py").write_text(
        """
from src.device_source_plugins import DeviceSourceDescriptor
from src.repository import SampleDeviceRepository

class Plugin:
    descriptor = DeviceSourceDescriptor(
        id="external-metadata",
        label="外部元数据插件",
        description="通过真实 Entry Point 元数据发现。",
        default_priority=50,
    )

    def create_repository(self, context):
        return SampleDeviceRepository()

def create_plugin():
    return Plugin()
""".strip(),
        encoding="utf-8",
    )
    metadata_root = tmp_path / "external_device_source-1.0.dist-info"
    metadata_root.mkdir()
    (metadata_root / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: external-device-source\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata_root / "entry_points.txt").write_text(
        "[device_tui.device_sources]\n"
        "external-metadata = external_device_source:create_plugin\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    discovered, warnings = discover_device_source_plugins()

    assert any(plugin.descriptor.id == "external-metadata" for plugin in discovered)
    assert not any("external-metadata" in warning for warning in warnings)


def test_backend_exposes_dynamic_plugin_metadata_without_source_id_hardcoding(
    monkeypatch,
) -> None:
    monkeypatch.delenv("DEVICE_TUI_DATA_SOURCE", raising=False)
    monkeypatch.delenv("DEVICE_TUI_DEFAULT_DATA_SOURCE", raising=False)
    repository = _InternalRepository()
    secrets = MemorySecretStore()
    app = create_app(
        token="plugin-test",
        session_hub=SessionHub(),
        imported_device_store=MemoryImportedDeviceStore(),
        secret_store=secrets,
        device_source_plugins=[_InternalPlugin(repository)],
        discover_source_plugins=False,
    )

    with TestClient(app) as client:
        status = client.get(
            "/api/v1/device-source",
            headers={"Authorization": "Bearer plugin-test"},
        )
        login = client.post(
            "/api/v1/internal-auth/login",
            headers={"Authorization": "Bearer plugin-test"},
            json={
                "username": "plugin-user",
                "password": "one-time-secret",
                "cid": "CID-PLUGIN",
                "remember": True,
            },
        )

    assert status.status_code == 200
    payload = status.json()
    assert payload["active_source"] == "internal-site"
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    assert repository.login_received_password is True
    assert secrets.get("internal-auth/internal-site/password") == "one-time-secret"
    assert secrets.get("internal-auth/password") is None
    source = next(item for item in payload["sources"] if item["id"] == "internal-site")
    assert source == {
        "id": "internal-site",
        "label": "公司设备平台",
        "description": "通过独立插件访问公司设备网站。",
        "icon": "globe",
        "available": True,
        "unavailable_reason": "",
        "requires_login": True,
        "supports_import": False,
    }


def test_unavailable_plugin_is_reported_without_breaking_builtin_sources() -> None:
    app = create_app(
        token="plugin-test",
        repository=SampleDeviceRepository(),
        session_hub=SessionHub(),
        imported_device_store=MemoryImportedDeviceStore(),
        device_source_plugins=[_BrokenPlugin()],
        discover_source_plugins=False,
    )

    with TestClient(app) as client:
        status = client.get(
            "/api/v1/device-source",
            headers={"Authorization": "Bearer plugin-test"},
        )
        switch = client.put(
            "/api/v1/device-source",
            headers={"Authorization": "Bearer plugin-test"},
            json={"source": "broken-source"},
        )

    assert status.status_code == 200
    broken = next(
        source for source in status.json()["sources"] if source["id"] == "broken-source"
    )
    assert broken["available"] is False
    assert "initialization failed" in broken["unavailable_reason"]
    assert switch.status_code == 409


def test_internal_release_build_collects_plugin_modules_and_metadata() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "desktop"
        / "scripts"
        / "build-python-backend.ps1"
    ).read_text(encoding="utf-8")

    assert "DEVICE_TUI_SOURCE_PLUGIN_DISTRIBUTIONS" in script
    assert "DEVICE_TUI_SOURCE_PLUGIN_MODULES" in script
    assert '"--collect-all", $module' in script
    assert '"--copy-metadata", $distribution' in script


def test_plugin_configuration_uses_settings_and_scoped_secret_store() -> None:
    plugin = _ConfigurablePlugin()
    settings = MemorySettingsStore()
    secrets = MemorySecretStore()
    registry = build_device_source_registry(
        imported_store=MemoryImportedDeviceStore(),
        plugins=[plugin],
        discover=False,
        settings_store=settings,
        secret_store=secrets,
    )

    assert "configured-source" not in registry.repositories()
    repository = registry.apply_configuration(
        "configured-source",
        config_updates={"base_url": "https://devices.example.test"},
        secret_updates={"api_token": "vault-only-token"},
    )

    assert repository is not None
    assert plugin.received_config == {"base_url": "https://devices.example.test"}
    assert plugin.received_token == "vault-only-token"
    assert settings.get("device_source_plugins.config.configured-source") == {
        "base_url": "https://devices.example.test"
    }
    assert secrets.get("device-source-plugin/configured-source/api_token") == "vault-only-token"
    assert registry.configuration("configured-source") == {
        "base_url": "https://devices.example.test"
    }
    assert registry.secret_configured("configured-source", "api_token") is True
    assert registry.test_configuration("configured-source").success is True


def test_external_plugin_can_be_disabled_without_affecting_builtins() -> None:
    plugin = _ConfigurablePlugin()
    registry = build_device_source_registry(
        imported_store=MemoryImportedDeviceStore(),
        plugins=[plugin],
        discover=False,
    )
    registry.apply_configuration(
        "configured-source",
        config_updates={"base_url": "https://devices.example.test"},
        secret_updates={"api_token": "token"},
    )

    assert "configured-source" in registry.repositories()
    registry.apply_configuration("configured-source", enabled=False)

    assert registry.enabled("configured-source") is False
    assert "configured-source" not in registry.repositories()
    assert registry.unavailable_reason("configured-source") == "插件已禁用。"
    assert "sample" in registry.repositories()


def test_builtin_plugin_cannot_be_disabled() -> None:
    registry = build_device_source_registry(
        imported_store=MemoryImportedDeviceStore(),
        discover=False,
    )

    with pytest.raises(DeviceSourcePluginError, match="内置插件不能禁用"):
        registry.apply_configuration("sample", enabled=False)


def test_plugin_configuration_survives_sqlite_registry_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "desktop.sqlite3"
    secrets = MemorySecretStore()
    settings = SQLiteSettingsStore(SQLiteDesktopStore(database_path))
    first = build_device_source_registry(
        imported_store=MemoryImportedDeviceStore(),
        plugins=[_ConfigurablePlugin()],
        discover=False,
        settings_store=settings,
        secret_store=secrets,
    )
    first.apply_configuration(
        "configured-source",
        config_updates={"base_url": "https://persistent.example.test"},
        secret_updates={"api_token": "persistent-vault-token"},
    )

    reopened = build_device_source_registry(
        imported_store=MemoryImportedDeviceStore(),
        plugins=[_ConfigurablePlugin()],
        discover=False,
        settings_store=SQLiteSettingsStore(SQLiteDesktopStore(database_path)),
        secret_store=secrets,
    )

    assert reopened.configuration("configured-source") == {
        "base_url": "https://persistent.example.test"
    }
    assert reopened.secret_configured("configured-source", "api_token") is True
    assert "configured-source" in reopened.repositories()
