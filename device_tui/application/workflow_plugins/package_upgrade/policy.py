"""Package-upgrade domain policy and cleanup planning.

Vendor output parsing lives in
``infrastructure.vendor_adapters.huawei_vrp.parsers``. This module only owns
upgrade inputs, business cleanup decisions, and the manual-plan projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from device_tui.infrastructure.vendor_adapters.huawei_vrp.parsers import (
    DEFAULT_MASTER_STORAGE,
    DEFAULT_SLAVE_STORAGE,
    PackageFileEntry,
    StartupInfo,
    join_storage_path,
    normalize_storage,
    package_basename,
)

CC_SUFFIX = ".cc"


@dataclass(slots=True)
class CleanupPlan:
    """Automatic cleanup decision for old system packages."""

    storage: str
    required_bytes: int
    free_bytes: int
    target_bytes: int
    delete_entries: list[PackageFileEntry] = field(default_factory=list)
    protected_paths: set[str] = field(default_factory=set)

    @property
    def reclaim_bytes(self) -> int:
        return sum(entry.size_bytes for entry in self.delete_entries)

    @property
    def has_enough_space(self) -> bool:
        return self.free_bytes + self.reclaim_bytes >= self.required_bytes


@dataclass(slots=True)
class PackageUpgradeConfig:
    """Inputs needed to generate a package upgrade command script."""

    package_path: Path
    server_host: str
    protocol: str = "ftp"
    port: int = 2121
    username: str = "device"
    password: str = "device"
    master_storage: str = DEFAULT_MASTER_STORAGE
    slave_storage: str = DEFAULT_SLAVE_STORAGE
    include_slave: bool = True
    auto_delete_old_packages: bool = True
    reboot_after_setting: bool = False
    verify_md5: str = ""
    cleanup_entries: list[PackageFileEntry] = field(default_factory=list)


@dataclass(slots=True)
class PackageUpgradePlan:
    """Generated commands and metadata for the UI to run or inspect."""

    commands: list[str]
    cleanup_paths: list[str]
    protected_paths: list[str]
    notes: list[str] = field(default_factory=list)


def normalize_package_path(value: str) -> str:
    return value.strip().replace("\\", "/").casefold()


def build_cleanup_plan(
    *,
    storage: str,
    free_bytes: int,
    target_bytes: int,
    entries: list[PackageFileEntry],
    startup: StartupInfo,
    target_package_name: str,
    reserve_bytes: int = 64 * 1024 * 1024,
    protected_names: set[str] | None = None,
) -> CleanupPlan:
    """Choose old system packages to delete without touching protected files."""

    required_bytes = max(0, target_bytes + reserve_bytes)
    protected = _protected_package_paths(
        startup=startup,
        target_package_name=target_package_name,
        storage=storage,
        protected_names=protected_names or set(),
    )
    plan = CleanupPlan(
        storage=normalize_storage(storage),
        required_bytes=required_bytes,
        free_bytes=max(0, free_bytes),
        target_bytes=max(0, target_bytes),
        protected_paths=protected,
    )
    if plan.free_bytes >= required_bytes:
        return plan
    candidates = [entry for entry in entries if _can_delete_package(entry, protected, target_package_name)]
    candidates.sort(key=lambda entry: (-entry.size_bytes, entry.name.casefold()))
    available = plan.free_bytes
    for entry in candidates:
        if available >= required_bytes:
            break
        plan.delete_entries.append(entry)
        available += entry.size_bytes
    return plan


def _protected_package_paths(
    *,
    startup: StartupInfo,
    target_package_name: str,
    storage: str,
    protected_names: set[str],
) -> set[str]:
    protected = {
        normalize_package_path(startup.current_system),
        normalize_package_path(startup.next_system),
        normalize_package_path(join_storage_path(storage, target_package_name)),
        package_basename(startup.current_system),
        package_basename(startup.next_system),
        package_basename(target_package_name),
    }
    protected.update(package_basename(name) for name in protected_names if name.strip())
    protected.discard("")
    return protected


def _can_delete_package(entry: PackageFileEntry, protected_paths: set[str], target_package_name: str) -> bool:
    if not entry.name.casefold().endswith(CC_SUFFIX):
        return False
    if package_basename(entry.name) == package_basename(target_package_name):
        return False
    normalized_path = normalize_package_path(entry.path)
    normalized_name = package_basename(entry.name)
    return normalized_path not in protected_paths and normalized_name not in protected_paths


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
