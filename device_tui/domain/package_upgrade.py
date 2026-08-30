"""Vendor-neutral package-upgrade domain values and cleanup policy.

The package-upgrade Workflow is an application feature, but the values passed
between its policy and vendor adapters belong to the domain boundary.  This
module intentionally has no dependency on CLI parsers, command builders, or
the workflow runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_MASTER_STORAGE = "flash:/"
DEFAULT_SLAVE_STORAGE = "slave#flash:/"
CC_SUFFIX = ".cc"


@dataclass(slots=True)
class StartupInfo:
    """Observed startup software paths reported by a device."""

    current_system: str = ""
    next_system: str = ""


@dataclass(slots=True)
class PackageFileEntry:
    """A package-like file observed in a device storage listing."""

    path: str
    name: str
    size_bytes: int
    storage: str = DEFAULT_MASTER_STORAGE
    modified_text: str = ""


@dataclass(slots=True)
class CleanupPlan:
    """Business decision for reclaiming enough space for a new package."""

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
    """Inputs for the operator-facing package-upgrade fallback plan."""

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
    """Rendered manual plan metadata exposed by the upgrade application API."""

    commands: list[str]
    cleanup_paths: list[str]
    protected_paths: list[str]
    notes: list[str] = field(default_factory=list)


def normalize_storage(value: str) -> str:
    storage = value.strip() or DEFAULT_MASTER_STORAGE
    return storage if storage.endswith("/") else f"{storage}/"


def join_storage_path(storage: str, filename: str) -> str:
    return f"{normalize_storage(storage)}{Path(filename).name}"


def package_basename(value: str) -> str:
    cleaned = value.strip().replace("\\", "/")
    return cleaned.rsplit("/", 1)[-1].casefold()


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
    """Choose old system packages without touching protected artifacts."""

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
    candidates = [
        entry
        for entry in entries
        if _can_delete_package(entry, protected, target_package_name)
    ]
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


def _can_delete_package(
    entry: PackageFileEntry,
    protected_paths: set[str],
    target_package_name: str,
) -> bool:
    if not entry.name.casefold().endswith(CC_SUFFIX):
        return False
    if package_basename(entry.name) == package_basename(target_package_name):
        return False
    normalized_path = normalize_package_path(entry.path)
    normalized_name = package_basename(entry.name)
    return normalized_path not in protected_paths and normalized_name not in protected_paths


__all__ = [
    "CC_SUFFIX",
    "CleanupPlan",
    "DEFAULT_MASTER_STORAGE",
    "DEFAULT_SLAVE_STORAGE",
    "PackageFileEntry",
    "PackageUpgradeConfig",
    "PackageUpgradePlan",
    "StartupInfo",
    "build_cleanup_plan",
    "join_storage_path",
    "normalize_package_path",
    "normalize_storage",
    "package_basename",
]
