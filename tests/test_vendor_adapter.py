from __future__ import annotations

import asyncio

from device_tui.application.workflows import (
    ActionResult,
    ActionStatus,
    ActivityContext,
    ActivityInvocation,
    ActivityStatus,
    WorkflowRun,
)
from device_tui.application.workflow_plugins import (
    DeviceVendorActivityHandler,
    HuaweiVrpDeviceVendorAdapter,
)


class _Legacy:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.actions = []

    async def execute(self, action, run, emit):
        self.actions.append(action)
        if self.error is not None:
            raise self.error
        return self.result or ActionResult(ActionStatus.SUCCEEDED, facts={"verified": True})

    async def cancel(self, action, run):
        self.actions.append(action)


def _context(activity_id: str = "device.verify_artifact"):
    invocation = ActivityInvocation(activity_id, "inv-1", "run-1", inputs={"package": "vrp.cc"})
    return invocation, ActivityContext(WorkflowRun("run-1", "wf", "1", "d1"), invocation)


def test_huawei_vendor_adapter_maps_generic_activity_to_legacy_operation() -> None:
    legacy = _Legacy(ActionResult(ActionStatus.SUCCEEDED, facts={"value": 1}))
    handler = DeviceVendorActivityHandler(HuaweiVrpDeviceVendorAdapter(legacy), "device.verify_artifact")
    invocation, context = _context()

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert legacy.actions[0].operation == "device.verify"


def test_huawei_vendor_adapter_preserves_unknown_for_uncertain_startup() -> None:
    error = RuntimeError("connection timeout")
    error.code = "connection_timeout"
    error.error_class = "connection"
    legacy = _Legacy(error=error)
    handler = DeviceVendorActivityHandler(
        HuaweiVrpDeviceVendorAdapter(legacy),
        "device.startup.configure",
    )
    invocation, context = _context("device.startup.configure")

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.UNKNOWN
