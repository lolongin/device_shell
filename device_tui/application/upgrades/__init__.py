"""Package-upgrade planning and application service."""

from typing import Any

__all__ = ["PackageUpgradeService"]


def __getattr__(name: str) -> Any:
    if name == "PackageUpgradeService":
        from .service import PackageUpgradeService

        return PackageUpgradeService
    raise AttributeError(name)
