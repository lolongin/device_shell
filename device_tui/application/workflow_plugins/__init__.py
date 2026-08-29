"""Optional domain Workflow plugins.

The framework in :mod:`device_tui.framework` is vendor-neutral. Plugin
implementations are loaded lazily so importing a single policy or workflow
module does not initialize every device-control and transport adapter.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "DeviceExecutionActionHandler",
    "DeviceReconcileProvider",
    "HuaweiVrpPackageUpgradeProvider",
    "HuaweiVrpWorkflowAdapter",
    "PackageUpgradeService",
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

_EXPORT_MODULES = {
    "DeviceExecutionActionHandler": (".device_bridge", "DeviceExecutionActionHandler"),
    "DeviceReconcileProvider": (".device_bridge", "DeviceReconcileProvider"),
    "build_device_action_registry": (".device_bridge", "build_device_action_registry"),
    "build_device_reconcile_registry": (".device_bridge", "build_device_reconcile_registry"),
    "HuaweiVrpPackageUpgradeProvider": (".package_upgrade.workflow", "HuaweiVrpPackageUpgradeProvider"),
    "HuaweiVrpWorkflowAdapter": (".package_upgrade.workflow", "HuaweiVrpWorkflowAdapter"),
    "PackageUpgradeService": (".package_upgrade.service", "PackageUpgradeService"),
    "build_default_activity_executor": (".builtins", "build_default_activity_executor"),
    "TransferActivityHandler": (".transfer", "TransferActivityHandler"),
    "TransferAdapter": (".transfer", "TransferAdapter"),
    "TransferHandle": (".transfer", "TransferHandle"),
    "TransferObservation": (".transfer", "TransferObservation"),
    "TerminalTransferAdapter": (".terminal_transfer", "TerminalTransferAdapter"),
    "DeviceActivityHandler": (".device_activity", "DeviceActivityHandler"),
    "DeviceVendorActivityHandler": (".vendor_adapter", "DeviceVendorActivityHandler"),
    "HuaweiVrpDeviceVendorAdapter": ("device_tui.infrastructure.vendor_adapters.huawei_vrp.activity_adapter", "HuaweiVrpDeviceVendorAdapter"),
    "CompatibilityDeviceActivityHandler": (".device_activity", "CompatibilityDeviceActivityHandler"),
    "ActivityWorkflowProvider": (".generic", "ActivityWorkflowProvider"),
    "build_default_activity_workflow_providers": (".generic", "build_default_activity_workflow_providers"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORT_MODULES[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
