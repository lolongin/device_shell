"""Package-upgrade domain rules and the manual compatibility service.

Generic Workflow execution lives in :mod:`device_tui.application.workflows`.
Huawei command and driver implementations live in
``device_tui.infrastructure.vendor_adapters.huawei_vrp``; the re-exports below
are retained only for callers using the historical import paths.
"""

from typing import Any

__all__ = [
    "HuaweiVrpUpgradeDriver",
    "HuaweiVrpCommandSet",
    "HuaweiVrpDeviceCommandProfile",
    "CommandPlan",
    "SimulatedVrpUpgradeDriver",
    "PackageUpgradeService",
    "UpgradeDriver",
    "UpgradeDriverRegistry",
    "UpgradeTargetFacts",
]


def __getattr__(name: str) -> Any:
    if name == "PackageUpgradeService":
        from .service import PackageUpgradeService

        return PackageUpgradeService
    if name in {"HuaweiVrpCommandSet", "HuaweiVrpDeviceCommandProfile", "CommandPlan"}:
        from .commands import CommandPlan, HuaweiVrpCommandSet, HuaweiVrpDeviceCommandProfile

        return {
            "HuaweiVrpCommandSet": HuaweiVrpCommandSet,
            "HuaweiVrpDeviceCommandProfile": HuaweiVrpDeviceCommandProfile,
            "CommandPlan": CommandPlan,
        }[name]
    if name in {"HuaweiVrpUpgradeDriver", "SimulatedVrpUpgradeDriver", "UpgradeDriver", "UpgradeDriverRegistry", "UpgradeTargetFacts"}:
        from .drivers import HuaweiVrpUpgradeDriver, SimulatedVrpUpgradeDriver, UpgradeDriver, UpgradeDriverRegistry, UpgradeTargetFacts

        return {
            "HuaweiVrpUpgradeDriver": HuaweiVrpUpgradeDriver,
            "SimulatedVrpUpgradeDriver": SimulatedVrpUpgradeDriver,
            "UpgradeDriver": UpgradeDriver,
            "UpgradeDriverRegistry": UpgradeDriverRegistry,
            "UpgradeTargetFacts": UpgradeTargetFacts,
        }[name]
    raise AttributeError(name)
