"""Huawei VRP CLI output parsers.

This module contains terminal-format knowledge only. Upgrade policy consumes
the structured values returned here and does not parse vendor output itself.
"""

from __future__ import annotations

import re
from device_tui.domain.package_upgrade import (
    PackageFileEntry,
    StartupInfo,
    join_storage_path,
    normalize_storage,
    package_basename,
)


DEFAULT_MASTER_STORAGE = "flash:/"
DEFAULT_SLAVE_STORAGE = "slave#flash:/"
STANDBY_STORAGE_AVAILABLE = "available"
STANDBY_STORAGE_ABSENT = "absent"
STANDBY_STORAGE_INDETERMINATE = "indeterminate"
STANDBY_STORAGE_NOT_PROBED = "not_probed"
CONTROLLER_TOPOLOGY_DUAL = "dual_controller"
CONTROLLER_TOPOLOGY_SINGLE = "single_controller"
CONTROLLER_TOPOLOGY_INDETERMINATE = "indeterminate"
UPGRADE_FAILURE_PATTERNS = (
    "error", "failed", "failure", "fail", "not found", "no such file",
    "insufficient", "not enough", "invalid", "denied", "refused", "timeout",
    "timed out", "unrecognized command", "unknown command", "too large",
    "md5 check failed", "wrong", "abort", "错误", "失败", "不存在", "没有",
    "空间不足", "无效", "拒绝", "超时", "中止",
)
STANDBY_STORAGE_ABSENT_PATTERNS = (
    "device is not present", "device not present", "device does not exist",
    "no such device", "no device available", "storage device does not exist",
    "path does not exist", "directory does not exist", "filesystem does not exist",
    "file system does not exist", "wrong device", "设备不存在", "存储设备不存在",
    "文件系统不存在", "无此设备",
)


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


def find_free_space_bytes(output: str) -> int | None:
    value = r"(?P<value>[\d,]+(?:\.\d+)?)"
    unit = r"(?P<unit>字节|bytes?|[kmgt]i?b)"
    patterns = (
        rf"\({value}\s*{unit}\s+(?:free|available)\b",
        rf"{value}\s*{unit}\s+(?:free|available)\b",
        rf"(?:free|available)(?:\s+space)?\s*[:=]\s*{value}\s*{unit}",
        rf"(?:free|available)(?:\s+space)?\s*[:=]?\s*\(?\s*{value}\s*{unit}\b",
        rf"{value}\s*{unit}\s*(?:free|available)(?:\s+space)?\b",
        rf"(?:剩余|可用)\s*(?:空间)?\s*[:：=]?\s*{value}\s*{unit}",
    )
    for pattern in patterns:
        matches = list(re.finditer(pattern, output, flags=re.IGNORECASE))
        if matches:
            match = matches[-1]
            return _to_bytes(match.group("value"), match.group("unit"))
    return None


def parse_free_space_bytes(output: str) -> int:
    return find_free_space_bytes(output) or 0


def classify_standby_storage(output: str, storage: str = DEFAULT_SLAVE_STORAGE) -> str:
    normalized_storage = normalize_storage(storage).casefold()
    section = _storage_section(output, normalized_storage)
    if section is not None and f"directory of {normalized_storage.rstrip('/')}" in section.casefold():
        return STANDBY_STORAGE_AVAILABLE
    scoped_output = section if section is not None else output
    if any(pattern.casefold() in scoped_output.casefold() for pattern in STANDBY_STORAGE_ABSENT_PATTERNS):
        return STANDBY_STORAGE_ABSENT
    return STANDBY_STORAGE_INDETERMINATE


def classify_controller_topology(output: str) -> str:
    lowered = output.casefold()
    has_standby = bool(re.search(r"\b(?:standby|slave)\b", lowered))
    has_master = bool(re.search(r"\b(?:master|active)\b", lowered))
    has_device_table = any(marker in lowered for marker in ("slot", "role", "board", "device state"))
    if has_standby and has_master:
        return CONTROLLER_TOPOLOGY_DUAL
    if has_master and has_device_table:
        return CONTROLLER_TOPOLOGY_SINGLE
    return CONTROLLER_TOPOLOGY_INDETERMINATE


def _storage_section(output: str, normalized_storage: str) -> str | None:
    marker = f"directory of {normalized_storage.rstrip('/')}"
    lowered = output.casefold()
    start = lowered.find(marker)
    if start < 0:
        return None
    next_directory = lowered.find("directory of ", start + len(marker))
    return output[start:next_directory if next_directory >= 0 else None]


def parse_dir_entries(output: str, storage: str = DEFAULT_MASTER_STORAGE) -> list[PackageFileEntry]:
    normalized_storage = normalize_storage(storage)
    entries: list[PackageFileEntry] = []
    for line in output.splitlines():
        entry = _parse_numbered_dir_line(line, normalized_storage)
        if entry is None:
            entry = _parse_simple_size_line(line, normalized_storage)
        if entry is not None:
            entries.append(entry)
    return entries


def find_upgrade_failure(output: str) -> str:
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
    target = package_basename(package_name)
    for entry in parse_dir_entries(output, storage):
        if package_basename(entry.name) != target:
            continue
        if expected_size <= 0:
            return True
        allowed_delta = max(4096, int(expected_size * tolerance_ratio))
        return abs(entry.size_bytes - expected_size) <= allowed_delta
    return False


def startup_uses_package(output: str, package_name: str) -> bool:
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
    return PackageFileEntry(
        path=join_storage_path(storage, name),
        name=name,
        size_bytes=int(match.group("size").replace(",", "")),
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
    multipliers = {
        "b": 1, "byte": 1, "bytes": 1, "字节": 1,
        "kb": 1024, "kib": 1024,
        "mb": 1024 * 1024, "mib": 1024 * 1024,
        "gb": 1024 * 1024 * 1024, "gib": 1024 * 1024 * 1024,
        "tb": 1024 * 1024 * 1024 * 1024, "tib": 1024 * 1024 * 1024 * 1024,
    }
    return int(float(value.replace(",", "")) * multipliers.get(unit.lower(), 1))


__all__ = [
    "CONTROLLER_TOPOLOGY_DUAL", "CONTROLLER_TOPOLOGY_INDETERMINATE",
    "CONTROLLER_TOPOLOGY_SINGLE", "DEFAULT_MASTER_STORAGE", "DEFAULT_SLAVE_STORAGE",
    "PackageFileEntry", "STANDBY_STORAGE_ABSENT", "STANDBY_STORAGE_AVAILABLE",
    "STANDBY_STORAGE_INDETERMINATE", "STANDBY_STORAGE_NOT_PROBED", "StartupInfo", "classify_controller_topology",
    "classify_standby_storage", "dir_contains_package", "find_free_space_bytes",
    "find_upgrade_failure", "join_storage_path", "normalize_storage", "package_basename",
    "parse_dir_entries", "parse_display_startup", "parse_free_space_bytes",
    "startup_uses_package",
]
