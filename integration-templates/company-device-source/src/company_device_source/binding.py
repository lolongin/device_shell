"""The one-file binding that is replaced when the real internal API is ready."""

from __future__ import annotations

from device_tui.plugin_api import DeviceSourceContext, PluginConfigField

from .demo_api import DemoCompanyWebApi
from .web_api import CompanyWebApi


SOURCE_ID = "internal-site"
PLUGIN_LABEL = "公司设备平台"
PLUGIN_DESCRIPTION = "从公司内部设备网站加载设备。"
PLUGIN_VERSION = "0.1.0"
PLUGIN_PUBLISHER = "Your Company"

CONFIG_FIELDS: tuple[PluginConfigField, ...] = (
    PluginConfigField(
        key="base_url",
        label="平台地址",
        kind="url",
        description="演示接口可以留空；替换真实接口后填写内部网站地址。",
        placeholder="https://devices.example.internal",
    ),
    PluginConfigField(
        key="timeout_seconds",
        label="请求超时（秒）",
        kind="number",
        default=5,
        minimum=0.5,
        maximum=120,
    ),
    PluginConfigField(
        key="refresh_seconds",
        label="设备刷新周期（秒）",
        kind="number",
        default=30,
        minimum=1,
        maximum=3600,
    ),
)


def create_company_web_api(context: DeviceSourceContext) -> CompanyWebApi:
    """Return a working demo now; replace only this body with the real adapter.

    Example replacement::

        from internal_device.web_api import InternalCompanyWebApi
        return InternalCompanyWebApi(
            base_url=str(context.config.get("base_url") or ""),
            timeout_seconds=float(context.config.get("timeout_seconds") or 5),
        )
    """

    del context
    return DemoCompanyWebApi()
