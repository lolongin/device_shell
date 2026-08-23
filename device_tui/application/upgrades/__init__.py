"""Package-upgrade planning and application service."""

from typing import Any

__all__ = [
    "HuaweiVrpUpgradeDriver",
    "PackageUpgradeService",
    "UpgradeDriver",
    "UpgradeDriverRegistry",
    "UpgradeTargetFacts",
]


def __getattr__(name: str) -> Any:
    if name == "PackageUpgradeService":
        from .service import PackageUpgradeService

        return PackageUpgradeService
    if name in {"HuaweiVrpUpgradeDriver", "UpgradeDriver", "UpgradeDriverRegistry", "UpgradeTargetFacts"}:
        from .drivers import HuaweiVrpUpgradeDriver, UpgradeDriver, UpgradeDriverRegistry, UpgradeTargetFacts

        return {
            "HuaweiVrpUpgradeDriver": HuaweiVrpUpgradeDriver,
            "UpgradeDriver": UpgradeDriver,
            "UpgradeDriverRegistry": UpgradeDriverRegistry,
            "UpgradeTargetFacts": UpgradeTargetFacts,
        }[name]
    raise AttributeError(name)
