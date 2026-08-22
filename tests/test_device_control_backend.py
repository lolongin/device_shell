from __future__ import annotations

import asyncio

from device_tui.application import SIMULATED_DEVICE_ID, build_desktop_application
from device_tui.application.ai.operations import AiDeviceAction, RiskLevel
from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.mcp.device_control_backend import DeviceControlAppBackend
from device_tui.interfaces.desktop_api.session_hub import SessionHub


class FakeExecutor:
    async def run(self, *, session_id, device_id, plan, owner_id):
        del plan, owner_id
        return {
            "execution_id": "adapter-exec",
            "session_id": session_id,
            "device_id": device_id,
            "status": "completed",
            "steps": [{"status": "completed", "output": "ok\n"}],
        }


def test_legacy_mcp_backend_routes_to_device_control_facade() -> None:
    async def scenario() -> None:
        desktop = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(),
            terminal_executor=FakeExecutor(),
        )
        backend = DeviceControlAppBackend(desktop)
        opened = backend.execute_ai_device_action(
            AiDeviceAction("open_session", "open", RiskLevel.LOW, device_id=SIMULATED_DEVICE_ID)
        )
        assert opened.ok is True
        session_id = str(opened.data["session"]["session_id"])
        sent = backend.execute_ai_device_action(
            AiDeviceAction(
                "send_command", "send", 1, device_id=SIMULATED_DEVICE_ID,
                command="display version", params={"session_id": session_id},
            )
        )
        assert sent.ok is True
        await desktop.sessions.close_all()

    asyncio.run(scenario())
