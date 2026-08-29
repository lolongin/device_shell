"""Generic Activity handler for a vendor adapter port."""

from __future__ import annotations

from typing import Any

from device_tui.framework import (
    ActivityContext,
    ActivityInvocation,
    ActivityResult,
    DeviceVendorAdapter,
)


class DeviceVendorActivityHandler:
    """Adapt one vendor port operation to the Activity handler contract."""

    def __init__(self, adapter: DeviceVendorAdapter, activity_id: str) -> None:
        self.activity_id = activity_id
        self._adapter = adapter

    async def execute(
        self,
        invocation: ActivityInvocation,
        context: ActivityContext,
        report: Any,
    ) -> ActivityResult:
        return await self._adapter.execute_activity(
            self.activity_id,
            invocation,
            context,
            report,
        )

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        await self._adapter.cancel_activity(self.activity_id, invocation, context)


__all__ = ["DeviceVendorActivityHandler"]
