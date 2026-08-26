"""Package-upgrade planning and application service."""

from typing import Any

__all__ = [
    "HuaweiVrpUpgradeDriver",
    "HuaweiVrpCommandSet",
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
    if name in {"HuaweiVrpCommandSet", "CommandPlan"}:
        from .commands import CommandPlan, HuaweiVrpCommandSet

        return {"HuaweiVrpCommandSet": HuaweiVrpCommandSet, "CommandPlan": CommandPlan}[name]
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
