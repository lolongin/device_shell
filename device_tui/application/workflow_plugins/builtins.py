"""Default domain plugins shipped with the desktop product."""

from device_tui.application.device_control import DeviceControlService
from device_tui.application.tasking.execution import DeviceExecutionTool
from device_tui.framework import (
    ActivityDefinition,
    ActivityExecutor,
    ExchangeSpec,
    GuardSpec,
    IdempotencyPolicy,
    MonitorSpec,
)
from device_tui.framework.plugins import AdapterRegistry, WorkflowRegistry

from .huawei_package import HuaweiVrpPackageUpgradeProvider, HuaweiVrpWorkflowAdapter
from .process import ProcessActivityHandler
from .terminal_transfer import TerminalTransferAdapter
from .device_activity import DeviceActivityHandler
from .device_bridge import DeviceExecutionActionHandler
from .transfer import TransferActivityHandler
from .generic import build_default_activity_workflow_providers
from .vendor_adapter import DeviceVendorActivityHandler, HuaweiVrpDeviceVendorAdapter


def build_default_workflow_registry() -> WorkflowRegistry:
    registry = WorkflowRegistry()
    # Keep the established vendor workflow first in catalog projections; the
    # generic providers follow as reusable building blocks.
    registry.register(HuaweiVrpPackageUpgradeProvider())
    for provider in build_default_activity_workflow_providers():
        registry.register(provider)
    return registry


def build_default_adapter_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(HuaweiVrpWorkflowAdapter())
    return registry


def build_default_activity_executor(
    control: DeviceControlService | None = None,
    execution: DeviceExecutionTool | None = None,
    *,
    adapters: AdapterRegistry | None = None,
    transfers: object | None = None,
) -> ActivityExecutor:
    """Build built-in Activities, optionally including device transfers.

    ``control`` is optional to keep the registry usable in headless tests and
    plugin discovery.  Desktop composition supplies it once the application
    services have been constructed.
    """
    executor = ActivityExecutor()
    for activity_id in ("script.run", "artifact.build"):
        executor.register_definition(ActivityDefinition(
            id=activity_id,
            output_schema={
                "type": "object",
                "properties": {
                    "output": {"type": "string"},
                    "returncode": {"type": ["integer", "null"]},
                },
            },
        ))
        executor.register_handler(ProcessActivityHandler(activity_id))
    if control is not None:
        executor.register_definition(ActivityDefinition(
            id="file.transfer",
            preparation=("managed_transfer.dispatch",),
            preconditions=(
                GuardSpec(
                    id="session.connected",
                    probe="session.status",
                    predicate={"equals": "connected"},
                ),
            ),
            exchanges=(
                ExchangeSpec(
                    id="transfer.started",
                    send="managed_transfer.dispatch",
                    accepted_signals=("operation.queued", "operation.started"),
                    failure_signals=("operation.rejected",),
                ),
            ),
            monitor=MonitorSpec(id="managed-transfer", poller="operation.poll"),
        ))
        # ``TerminalTransferAdapter`` implements the transport-facing staged
        # contract; the Activity handler owns lifecycle/status mapping.
        executor.register_handler(TransferActivityHandler(TerminalTransferAdapter(control)))
    if execution is not None:
        for activity_id in ("device.reboot", "device.wait_online", "device.verify_version"):
            if activity_id == "device.reboot":
                definition = ActivityDefinition(
                    id=activity_id,
                    preconditions=(GuardSpec(id="session.connected", probe="session.status", predicate={"equals": "connected"}),),
                    exchanges=(ExchangeSpec(id="reboot.dispatched", send="reboot", accepted_signals=("disconnect_observed",), failure_signals=("command_failed",)),),
                    idempotency=IdempotencyPolicy.UNSAFE,
                )
            elif activity_id == "device.wait_online":
                definition = ActivityDefinition(
                    id=activity_id,
                    preparation=("session.reconnect",),
                    monitor=MonitorSpec(id="device-readiness", poller="cli.readiness", timeout_seconds=300),
                )
            else:
                definition = ActivityDefinition(
                    id=activity_id,
                    preconditions=(GuardSpec(id="session.connected", probe="session.status", predicate={"equals": "connected"}),),
                    exchanges=(ExchangeSpec(id="version.probe", send="version_query", accepted_signals=("probe.completed",), failure_signals=("probe.failed",)),),
                )
            executor.register_definition(definition)
            executor.register_handler(DeviceActivityHandler(execution, activity_id))
        # Storage and startup operations are exposed under stable, vendor-
        # neutral Activity ids.  The temporary compatibility handler delegates
        # command generation and read-back verification to the registered
        # vendor bridge; the executor still owns Activity lifecycle/status.
        legacy = DeviceExecutionActionHandler(
            execution,
            adapters or build_default_adapter_registry(),
            transfers,
        )
        vendor = HuaweiVrpDeviceVendorAdapter(legacy)
        migrated_operations = {
            "device.storage.cleanup": "huawei.storage.cleanup",
            "device.storage.sync": "huawei.storage.sync",
            "device.verify_artifact": "device.verify",
            "device.startup.configure": "huawei.startup.configure",
            "device.startup.rollback": "huawei.startup.rollback",
        }
        for activity_id, legacy_operation in migrated_operations.items():
            executor.register_definition(ActivityDefinition(
                id=activity_id,
                idempotency=(
                    IdempotencyPolicy.UNSAFE
                    if activity_id in {"device.startup.configure", "device.startup.rollback"}
                    else IdempotencyPolicy.SAFE
                    if activity_id == "device.verify_artifact"
                    else IdempotencyPolicy.CONDITIONAL
                ),
                preconditions=(GuardSpec(
                    id="session.connected",
                    probe="session.status",
                    predicate={"equals": "connected"},
                ),),
            ))
            executor.register_handler(
                DeviceVendorActivityHandler(vendor, activity_id),
            )
    return executor


__all__ = [
    "HuaweiVrpPackageUpgradeProvider",
    "HuaweiVrpWorkflowAdapter",
    "build_default_adapter_registry",
    "build_default_activity_executor",
    "build_default_workflow_registry",
]
