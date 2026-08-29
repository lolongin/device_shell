"""Huawei VRP command and protocol adapters."""

from .commands import CommandPlan, HuaweiVrpCommandSet, HuaweiVrpDeviceCommandProfile
from .activity_adapter import HuaweiVrpDeviceVendorAdapter
from .workflow_adapter import HuaweiVrpWorkflowAdapter
from .parsers import (
    PackageFileEntry,
    StartupInfo,
    classify_controller_topology,
    classify_standby_storage,
    dir_contains_package,
    find_free_space_bytes,
    find_upgrade_failure,
    parse_dir_entries,
    parse_display_startup,
    parse_free_space_bytes,
    startup_uses_package,
)
from .drivers import (
    HuaweiVrpUpgradeDriver,
    SimulatedVrpUpgradeDriver,
    UpgradeCleanupDecision,
    UpgradeDriver,
    UpgradeDriverRegistry,
    UpgradeManualPlan,
    UpgradeTargetFacts,
)

__all__ = [
    "CommandPlan",
    "HuaweiVrpCommandSet",
    "HuaweiVrpDeviceCommandProfile",
    "HuaweiVrpDeviceVendorAdapter",
    "HuaweiVrpWorkflowAdapter",
    "PackageFileEntry",
    "StartupInfo",
    "classify_controller_topology",
    "classify_standby_storage",
    "dir_contains_package",
    "find_free_space_bytes",
    "find_upgrade_failure",
    "parse_dir_entries",
    "parse_display_startup",
    "parse_free_space_bytes",
    "startup_uses_package",
    "HuaweiVrpUpgradeDriver",
    "SimulatedVrpUpgradeDriver",
    "UpgradeCleanupDecision",
    "UpgradeDriver",
    "UpgradeDriverRegistry",
    "UpgradeManualPlan",
    "UpgradeTargetFacts",
]
