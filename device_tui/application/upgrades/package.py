"""Huawei VRP system package upgrade planning helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


CC_SUFFIX = ".cc"
DEFAULT_MASTER_STORAGE = "flash:/"
DEFAULT_SLAVE_STORAGE = "slave#flash:/"
STANDBY_STORAGE_AVAILABLE = "available"
STANDBY_STORAGE_ABSENT = "absent"
STANDBY_STORAGE_INDETERMINATE = "indeterminate"
UPGRADE_FAILURE_PATTERNS = (
    "error",
    "failed",
    "failure",
    "fail",
    "not found",
    "no such file",
    "insufficient",
    "not enough",
    "invalid",
    "denied",
    "refused",
    "timeout",
    "timed out",
    "unrecognized command",
    "unknown command",
    "too large",
    "md5 check failed",
    "wrong",
    "abort",
    "错误",
    "失败",
    "不存在",
    "没有",
    "空间不足",
    "无效",
    "拒绝",
    "超时",
    "中止",
)
STANDBY_STORAGE_ABSENT_PATTERNS = (
    "device is not present",
    "device not present",
    "device does not exist",
    "no such device",
    "no device available",
    "storage device does not exist",
    "path does not exist",
    "directory does not exist",
    "filesystem does not exist",
    "file system does not exist",
    "wrong device",
    "设备不存在",
    "存储设备不存在",
    "文件系统不存在",
    "无此设备",
)


@dataclass(slots=True)
class StartupInfo:
    """Current and next startup files parsed from ``display startup``."""

    current_system: str = ""
    next_system: str = ""


@dataclass(slots=True)
class PackageFileEntry:
    """One file entry parsed from a Huawei file-system listing."""

    path: str
    name: str
    size_bytes: int
    storage: str = DEFAULT_MASTER_STORAGE
    modified_text: str = ""


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
    """Inputs needed to generate a Huawei package upgrade command script."""

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


def normalize_storage(value: str) -> str:
    storage = value.strip() or DEFAULT_MASTER_STORAGE
    if storage.endswith("/"):
        return storage
    return f"{storage}/"


def join_storage_path(storage: str, filename: str) -> str:
    return f"{normalize_storage(storage)}{Path(filename).name}"


def normalize_package_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    return normalized.casefold()


def package_basename(value: str) -> str:
    cleaned = value.strip().replace("\\", "/")
    return cleaned.rsplit("/", 1)[-1].casefold()


def parse_display_startup(output: str) -> StartupInfo:
    current = ""
    next_system = ""
    for line in output.splitlines():
        stripped = line.strip()
        lowered = stripped.casefold()
        if "current startup system software" in lowered:
            current = _value_after_colon(stripped)
        elif "next startup system software" in lowered:
            next_system = _value_after_colon(stripped)
    return StartupInfo(current_system=current, next_system=next_system)


def _value_after_colon(line: str) -> str:
    if ":" in line:
        return line.split(":", 1)[1].strip()
    parts = line.split()
    return parts[-1] if parts else ""


def parse_free_space_bytes(output: str) -> int:
    """Parse free flash bytes from common Huawei ``dir`` output variants."""

    patterns = (
        r"\((?P<value>[\d,]+)\s*(?P<unit>[kmgt]?b)\s+free\)",
        r"(?P<value>[\d,]+)\s*(?P<unit>[kmgt]?b)\s+free",
        r"free\s*[:=]\s*(?P<value>[\d,]+)\s*(?P<unit>[kmgt]?b)",
    )
    for pattern in patterns:
        matches = list(re.finditer(pattern, output, flags=re.IGNORECASE))
        if matches:
            match = matches[-1]
            return _to_bytes(match.group("value"), match.group("unit"))
    return 0


def classify_standby_storage(output: str, storage: str = DEFAULT_SLAVE_STORAGE) -> str:
    """Classify whether a standby-controller storage directory is available."""

    lowered = output.casefold()
    normalized_storage = normalize_storage(storage).casefold()
    directory_markers = (
        f"directory of {normalized_storage}",
        f"directory of {normalized_storage.rstrip('/')}",
    )
    if any(marker in lowered for marker in directory_markers) or parse_free_space_bytes(output) > 0:
        return STANDBY_STORAGE_AVAILABLE
    if any(pattern.casefold() in lowered for pattern in STANDBY_STORAGE_ABSENT_PATTERNS):
        return STANDBY_STORAGE_ABSENT
    return STANDBY_STORAGE_INDETERMINATE


def parse_dir_entries(output: str, storage: str = DEFAULT_MASTER_STORAGE) -> list[PackageFileEntry]:
    """Parse file entries from Huawei ``dir`` output.

    The parser intentionally accepts multiple loose formats because VRP output
    varies across product lines and languages.
    """

    normalized_storage = normalize_storage(storage)
    entries: list[PackageFileEntry] = []
    for line in output.splitlines():
        entry = _parse_numbered_dir_line(line, normalized_storage)
        if entry is not None:
            entries.append(entry)
            continue
        entry = _parse_simple_size_line(line, normalized_storage)
        if entry is not None:
            entries.append(entry)
    return entries


def find_upgrade_failure(output: str) -> str:
    """Return a human-readable failure marker found in command output."""

    lowered = output.casefold()
    for pattern in UPGRADE_FAILURE_PATTERNS:
        if pattern.casefold() in lowered:
            return pattern
    return ""


def dir_contains_package(
    output: str,
    *,
    storage: str,
    package_name: str,
    expected_size: int = 0,
    tolerance_ratio: float = 0.02,
) -> bool:
    """Check whether ``dir`` output contains the target package with plausible size."""

    target = package_basename(package_name)
    entries = parse_dir_entries(output, storage)
    for entry in entries:
        if package_basename(entry.name) != target:
            continue
        if expected_size <= 0:
            return True
        allowed_delta = max(4096, int(expected_size * tolerance_ratio))
        return abs(entry.size_bytes - expected_size) <= allowed_delta
    return False


def startup_uses_package(output: str, package_name: str) -> bool:
    """Return True when display startup shows the package as next startup software."""

    target = package_basename(package_name)
    startup = parse_display_startup(output)
    return bool(target and package_basename(startup.next_system) == target)


def _parse_numbered_dir_line(line: str, storage: str) -> PackageFileEntry | None:
    match = re.match(
        r"^\s*\d+\s+[-d][rwx-]+\s+(?P<size>[\d,]+)\s+"
        r"(?P<date>.+?)\s+(?P<name>[^\s]+)\s*$",
        line,
    )
    if match is None:
        return None
    name = match.group("name").strip()
    if not name or name in {".", ".."}:
        return None
    size = int(match.group("size").replace(",", ""))
    return PackageFileEntry(
        path=join_storage_path(storage, name),
        name=name,
        size_bytes=size,
        storage=storage,
        modified_text=match.group("date").strip(),
    )


def _parse_simple_size_line(line: str, storage: str) -> PackageFileEntry | None:
    match = re.search(
        r"(?P<name>[^\s]+\.cc)\s+(?P<size>[\d,]+)\s*(?P<unit>[kmgt]?b)\b",
        line,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    name = match.group("name").strip()
    return PackageFileEntry(
        path=join_storage_path(storage, name),
        name=name,
        size_bytes=_to_bytes(match.group("size"), match.group("unit")),
        storage=storage,
    )


def _to_bytes(value: str, unit: str) -> int:
    number = int(value.replace(",", ""))
    normalized_unit = unit.lower()
    multipliers = {
        "b": 1,
        "kb": 1024,
        "mb": 1024 * 1024,
        "gb": 1024 * 1024 * 1024,
        "tb": 1024 * 1024 * 1024 * 1024,
    }
    return number * multipliers.get(normalized_unit, 1)


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

    candidates = [
        entry for entry in entries
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


def generate_huawei_upgrade_plan(config: PackageUpgradeConfig) -> PackageUpgradePlan:
    # Kept as the legacy public renderer. CLI syntax belongs to CommandSet,
    # so manual scripts cannot drift from the automatic workflow.
    from .commands import HuaweiVrpCommandSet

    command_plan = HuaweiVrpCommandSet().manual_upgrade_plan(config)
    cleanup_paths = [
        entry.path for entry in config.cleanup_entries
        if config.auto_delete_old_packages and entry.name.casefold().endswith(CC_SUFFIX)
    ]
    return PackageUpgradePlan(
        commands=list(command_plan.commands),
        cleanup_paths=cleanup_paths,
        protected_paths=[],
        notes=list(command_plan.notes),
    )
