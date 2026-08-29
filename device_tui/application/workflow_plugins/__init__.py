"""Optional domain workflow plugins.

The framework in :mod:`device_tui.framework` is vendor-neutral.
This package contains the Huawei VRP package-replacement implementation and
the bridge to the device-control application services.
"""

from .device_bridge import (
    DeviceExecutionActionHandler,
    DeviceReconcileProvider,
    build_device_action_registry,
    build_device_reconcile_registry,
)
from .huawei_package import HuaweiVrpPackageUpgradeProvider, HuaweiVrpWorkflowAdapter
from .builtins import build_default_activity_executor
from .transfer import TransferActivityHandler, TransferAdapter, TransferHandle, TransferObservation
from .terminal_transfer import TerminalTransferAdapter
from .device_activity import CompatibilityDeviceActivityHandler, DeviceActivityHandler
from .vendor_adapter import DeviceVendorActivityHandler, HuaweiVrpDeviceVendorAdapter
from .generic import ActivityWorkflowProvider, build_default_activity_workflow_providers

__all__ = [
    "DeviceExecutionActionHandler",
    "DeviceReconcileProvider",
    "HuaweiVrpPackageUpgradeProvider",
    "HuaweiVrpWorkflowAdapter",
    "build_device_action_registry",
    "build_device_reconcile_registry",
    "build_default_activity_executor",
    "TransferActivityHandler",
    "TransferAdapter",
    "TransferHandle",
    "TransferObservation",
    "TerminalTransferAdapter",
    "DeviceActivityHandler",
    "DeviceVendorActivityHandler",
    "HuaweiVrpDeviceVendorAdapter",
    "CompatibilityDeviceActivityHandler",
    "ActivityWorkflowProvider",
    "build_default_activity_workflow_providers",
]
