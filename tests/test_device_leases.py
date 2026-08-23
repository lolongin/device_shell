from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from device_tui.application import SIMULATED_DEVICE_ID, DeviceTarget, build_desktop_application
from device_tui.application.device_control import ControlContext, DeviceLeaseService
from device_tui.application.errors import ApplicationConflictError, ResourceNotFoundError
from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.session_hub import SessionHub


def test_device_lease_fences_other_owners_and_expires() -> None:
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    clock = lambda: now
    leases = DeviceLeaseService(ttl_seconds=30, clock=clock)
    first = leases.acquire("device-1", "task-1")

    with pytest.raises(ApplicationConflictError):
        leases.acquire("device-1", "task-2")
    assert leases.validate("device-1", first.token).owner_id == "task-1"

    now += timedelta(seconds=31)
    with pytest.raises(ResourceNotFoundError):
        leases.validate("device-1", first.token)
    assert leases.acquire("device-1", "task-2").owner_id == "task-2"


def test_device_control_policy_rejects_manual_write_while_task_owns_device() -> None:
    async def scenario() -> None:
        application = build_desktop_application(SampleDeviceRepository(), SessionHub())
        session = await application.sessions.create(SIMULATED_DEVICE_ID, "simulated")
        lease = application.leases.acquire(SIMULATED_DEVICE_ID, "task-1")

        with pytest.raises(ApplicationConflictError):
            await application.control.send_raw(DeviceTarget(session_id=session.id), "display version")

        sent = await application.control.send_raw(
            DeviceTarget(session_id=session.id),
            "display version",
            context=ControlContext(task_id="task-1", lease_token=lease.token),
        )
        assert sent.sent is True
        await application.sessions.close_all()

    asyncio.run(scenario())
