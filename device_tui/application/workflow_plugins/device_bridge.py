"""Compatibility registration for device Workflow actions.

Vendor command execution is implemented by the infrastructure adapters.  This
module only keeps the historical registration surface and dispatches marked
Activities during the migration to the generic framework.
"""

from __future__ import annotations

from typing import Any

from device_tui.application.device_control import DeviceControlService
from device_tui.application.tasking.execution import DeviceExecutionTool
from device_tui.infrastructure.vendor_adapters.huawei_vrp.reconcile import (
    HuaweiVrpReconcileProvider,
    build_huawei_reconcile_registry,
)
from device_tui.framework.activity_executor import ActivityActionHandler, ActivityExecutor
from device_tui.framework.plugins import ActionRegistry, AdapterRegistry, ReconcileRegistry


DeviceReconcileProvider = HuaweiVrpReconcileProvider

def __getattr__(name: str) -> Any:
    """Load the historical ActionHandler only for explicit legacy imports."""
    if name == "DeviceExecutionActionHandler":
        from device_tui.infrastructure.vendor_adapters.huawei_vrp.action_handler import DeviceExecutionActionHandler
        globals()[name] = DeviceExecutionActionHandler
        return DeviceExecutionActionHandler
    raise AttributeError(name)


def build_device_action_registry(
    execution: DeviceExecutionTool,
    adapters: AdapterRegistry,
    transfers: Any = None,
    *,
    activity_executor: ActivityExecutor | None = None,
) -> ActionRegistry:
    registry = ActionRegistry()
    # The legacy ActionHandler is instantiated only by callers that do not
    # provide an ActivityExecutor. Desktop composition always supplies one.
    handler: Any | None = None
    if activity_executor is None:
        from device_tui.infrastructure.vendor_adapters.huawei_vrp.action_handler import DeviceExecutionActionHandler
        handler = DeviceExecutionActionHandler(execution, adapters, transfers)
    legacy_operations = (
        "device.probe", "file.transfer", "device.verify",
        "huawei.storage.cleanup", "huawei.storage.sync",
        "huawei.startup.configure", "device.reboot", "device.wait_online", "huawei.startup.rollback",
        "device.storage.cleanup", "device.storage.sync",
        "device.verify_artifact",
        "device.startup.configure", "device.startup.rollback",
        "terminal.command", "terminal.batch", "device.power_off", "operation.wait",
    )
    for operation in legacy_operations:
        selected: Any = handler
        if activity_executor is not None and operation in {
            "device.probe",
            "device.verify",
            "file.transfer",
            "device.reboot",
            "device.wait_online",
            "device.storage.cleanup",
                "device.storage.sync",
                "device.verify_artifact",
                "device.verify",
            "device.startup.configure",
            "device.startup.rollback",
            "terminal.command",
            "terminal.batch",
            "device.power_off",
            "operation.wait",
        }:
            # Framework runs use the Activity lifecycle directly. The legacy
            # Action handler remains available only when no Activity executor
            # was supplied by a compatibility composition root.
            selected = ActivityActionHandler(activity_executor, operation)
            if selected is None:
                # Vendor-neutral Activity ids are the production contract;
                # Huawei-prefixed aliases remain available only to legacy
                # compositions and need not be registered in the new graph.
                if activity_executor is not None:
                    continue
                raise RuntimeError(f"No ActivityExecutor or legacy handler for {operation}")
        registry.register(selected, item_id=operation)
    # Process Activities are fully transport-independent and can be adopted
    # immediately. Generic device Activities remain registered alongside the
    # compatibility actions until all legacy callers use the framework path.
    if activity_executor is not None:
        registry.register(
            ActivityActionHandler(activity_executor, "device.verify_version"),
            item_id="device.verify_version",
        )
        for operation in ("script.run", "artifact.build"):
            registry.register(
                ActivityActionHandler(activity_executor, operation),
                item_id=operation,
            )
    return registry


def build_device_reconcile_registry(execution: DeviceExecutionTool, control: DeviceControlService) -> ReconcileRegistry:
    """Compatibility forwarding for callers using the old application path."""

    return build_huawei_reconcile_registry(execution, control)


__all__ = [
    "DeviceExecutionActionHandler",
    "DeviceReconcileProvider",
    "build_device_action_registry",
    "build_device_reconcile_registry",
]
