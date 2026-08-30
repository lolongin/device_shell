"""Package-upgrade business Workflow and application policy."""

from importlib import import_module
from typing import Any

__all__ = [
    "HuaweiVrpPackageUpgradeProvider",
    "PackageUpgradeService",
]

_EXPORT_MODULES = {
    "HuaweiVrpPackageUpgradeProvider": (".workflow", "HuaweiVrpPackageUpgradeProvider"),
    "PackageUpgradeService": (".service", "PackageUpgradeService"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
