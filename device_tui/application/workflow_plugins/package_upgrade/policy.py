"""Package-upgrade application policy and manual-plan projection.

The reusable values and cleanup decision live in ``device_tui.domain`` so
vendor adapters can consume them without importing this Workflow package.
"""

from __future__ import annotations

from device_tui.domain.package_upgrade import (
    CC_SUFFIX,
    CleanupPlan,
    DEFAULT_MASTER_STORAGE,
    DEFAULT_SLAVE_STORAGE,
    PackageFileEntry,
    PackageUpgradeConfig,
    PackageUpgradePlan,
    StartupInfo,
    build_cleanup_plan,
    join_storage_path,
    normalize_package_path,
    normalize_storage,
    package_basename,
)


def generate_huawei_upgrade_plan(config: PackageUpgradeConfig) -> PackageUpgradePlan:
    """Render the vendor command plan for the manual fallback API."""

    from device_tui.infrastructure.vendor_adapters.huawei_vrp.commands import HuaweiVrpCommandSet

    command_plan = HuaweiVrpCommandSet().manual_upgrade_plan(config)
    cleanup_paths = [
        entry.path
        for entry in config.cleanup_entries
        if config.auto_delete_old_packages and entry.name.casefold().endswith(CC_SUFFIX)
    ]
    return PackageUpgradePlan(
        commands=list(command_plan.commands),
        cleanup_paths=cleanup_paths,
        protected_paths=[],
        notes=list(command_plan.notes),
    )


__all__ = [
    "CC_SUFFIX", "CleanupPlan", "DEFAULT_MASTER_STORAGE", "DEFAULT_SLAVE_STORAGE",
    "PackageFileEntry", "PackageUpgradeConfig", "PackageUpgradePlan", "StartupInfo",
    "build_cleanup_plan", "generate_huawei_upgrade_plan", "join_storage_path",
    "normalize_package_path", "normalize_storage", "package_basename",
]
