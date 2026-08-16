"""Device TUI Entry Point adapter for the existing internal repository factory."""

from __future__ import annotations

from device_tui.plugin_api import (
    DeviceSourceContext,
    DeviceSourceDescriptor,
    PluginCheckResult,
    PluginConfigField,
)

from . import binding
from .repository import CompanyDeviceRepository


class CompanyDeviceSourcePlugin:
    """Register company-specific repository code without changing Device TUI."""

    @property
    def descriptor(self) -> DeviceSourceDescriptor:
        return DeviceSourceDescriptor(
            id=binding.SOURCE_ID,
            label=binding.PLUGIN_LABEL,
            description=binding.PLUGIN_DESCRIPTION,
            icon="globe",
            version=binding.PLUGIN_VERSION,
            publisher=binding.PLUGIN_PUBLISHER,
            requires_login=True,
            default_priority=100,
        )

    @property
    def config_fields(self) -> tuple[PluginConfigField, ...]:
        return tuple(binding.CONFIG_FIELDS)

    def create_repository(self, context: DeviceSourceContext) -> CompanyDeviceRepository:
        refresh_seconds = float(context.config.get("refresh_seconds") or 30)
        return CompanyDeviceRepository(
            binding.create_company_web_api(context),
            refresh_interval_seconds=refresh_seconds,
        )

    def test_connection(self, context: DeviceSourceContext) -> PluginCheckResult:
        repository = self.create_repository(context)
        status = repository.internal_auth_status()
        if not bool(getattr(status, "available", True)):
            return PluginCheckResult(False, "内部仓库未提供网站登录能力。")
        if not bool(getattr(status, "configured", True)):
            return PluginCheckResult(False, "内部仓库已加载，但网站接口尚未配置。")
        return PluginCheckResult(True, "内部仓库加载成功，可以继续登录验证网站会话。")


def create_plugin() -> CompanyDeviceSourcePlugin:
    return CompanyDeviceSourcePlugin()
