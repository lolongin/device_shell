"""Package-upgrade business rules and application services.

Generic Workflow execution lives in :mod:`device_tui.framework`. Huawei
commands and upgrade drivers live in
``device_tui.infrastructure.vendor_adapters.huawei_vrp``.
"""

from typing import Any


def __getattr__(name: str) -> Any:
    # Keep the service lazy because ``transfers`` imports ``upgrades.package``
    # during application module initialization.
    if name == "PackageUpgradeService":
        from .service import PackageUpgradeService

        return PackageUpgradeService
    raise AttributeError(name)

__all__ = ["PackageUpgradeService"]
