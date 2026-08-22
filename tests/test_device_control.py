from __future__ import annotations

import asyncio

from device_tui.application import (
    CommandRequest,
    DeviceTarget,
    SIMULATED_DEVICE_ID,
    build_desktop_application,
)
from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.session_hub import SessionHub


class FakeExecutor:
    async def run(self, *, session_id, device_id, plan, owner_id):
        del plan, owner_id
        return {
            "execution_id": "exec-1",
            "session_id": session_id,
            "device_id": device_id,
            "status": "completed",
            "steps": [{"output": "ok\n", "status": "completed"}],
            "duration_ms": 1,
        }


def test_control_opens_and_sends_through_existing_session_service() -> None:
    async def scenario() -> None:
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(),
        )
        session = await application.control.open_session(
            DeviceTarget(device_id=SIMULATED_DEVICE_ID),
        )
        sent = await application.control.send_raw(
            DeviceTarget(session_id=session.session_id),
            "display version",
        )
        assert sent.sent is True
        assert sent.session_id == session.session_id
        await application.sessions.close_all()

    asyncio.run(scenario())


def test_control_execute_uses_terminal_plan_executor_contract() -> None:
    async def scenario() -> None:
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(),
            terminal_executor=FakeExecutor(),
        )
        session = await application.sessions.create(SIMULATED_DEVICE_ID, "simulated")
        result = await application.control.execute(
            DeviceTarget(session_id=session.id),
            CommandRequest(commands=("display version",)),
        )
        assert result.execution_id == "exec-1"
        assert result.status == "completed"
        assert result.output == "ok\n"
        await application.sessions.close_all()

    asyncio.run(scenario())
