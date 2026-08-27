from __future__ import annotations

import asyncio

import pytest

from device_tui.application import (
    CommandResult,
    ControlContext,
    CommandRequest,
    DeviceTarget,
    SIMULATED_DEVICE_ID,
    SessionView,
    build_desktop_application,
)
from device_tui.application.errors import ApplicationError, UnsupportedOperationError
from device_tui.application.tasking import DeviceExecutionTool, DeviceWorkflowExecutionError
from device_tui.application.tasking.models import WorkflowStep
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


class RebootExecutor:
    def __init__(self) -> None:
        self.plan = None

    async def run(self, *, session_id, device_id, plan, owner_id):
        del owner_id
        self.plan = plan
        return {
            "execution_id": "reboot-exec",
            "session_id": session_id,
            "device_id": device_id,
            "status": "completed",
            "steps": [
                {"type": "send", "status": "completed"},
                {"type": "expect", "status": "completed", "matched": "disconnected"},
            ],
            "duration_ms": 1,
        }


class ReadinessControl:
    def __init__(self, *, cli_ready: bool, reused: bool = False) -> None:
        self.cli_ready = cli_ready
        self.reused = reused
        self.probes = 0
        self.reconnects = 0

    async def open_session(self, target, **kwargs):
        del target, kwargs
        return SessionView("recovery-1", "d1", "ssh", "connected", reused=self.reused)

    async def reconnect_session(self, target, **kwargs):
        del target, kwargs
        self.reconnects += 1
        return SessionView("recovery-1", "d1", "ssh", "connected", reused=True)

    async def execute(self, target, request, *, context):
        del target, request, context
        self.probes += 1
        if not self.cli_ready:
            raise ApplicationError("CLI is still presenting a login prompt.")
        return CommandResult(
            operation_id="probe-1",
            execution_id="probe-1",
            session_id="recovery-1",
            device_id="d1",
            status="completed",
            output="VRP V8\n<Huawei> ",
        )


class StartupVerificationControl:
    def __init__(self, output: str) -> None:
        self.output = output

    async def execute(self, target, request, *, context):
        del target, request, context
        return CommandResult(
            operation_id="startup-1",
            execution_id="startup-1",
            session_id="session-1",
            device_id="d1",
            status="completed",
            output=self.output,
        )


def test_wait_online_requires_a_successful_cli_probe_after_transport_connects() -> None:
    async def scenario() -> None:
        control = ReadinessControl(cli_ready=True)
        result = await DeviceExecutionTool(control).execute(
            DeviceTarget(device_id="d1"),
            WorkflowStep(
                "wait_online",
                kind="device",
                action="wait_online",
                params={"timeout_seconds": 2, "readiness_command": "display version"},
            ),
            context=ControlContext(source="test"),
        )

        assert control.probes == 1
        assert result["transport_status"] == "connected"
        assert result["cli_status"] == "ready"
        assert result["probe_execution_id"] == "probe-1"

    asyncio.run(scenario())


def test_wait_online_does_not_treat_connected_transport_as_cli_ready() -> None:
    async def scenario() -> None:
        control = ReadinessControl(cli_ready=False)
        with pytest.raises(DeviceWorkflowExecutionError) as error:
            await DeviceExecutionTool(control).execute(
                DeviceTarget(device_id="d1"),
                WorkflowStep(
                    "wait_online",
                    kind="device",
                    action="wait_online",
                    params={"timeout_seconds": 1, "readiness_command": "display version"},
                ),
                context=ControlContext(source="test"),
            )

        assert control.probes > 0
        assert error.value.code == "cli_not_ready"
        assert error.value.details["transport_status"] == "connected"
        assert error.value.details["last_probe"]["cli_status"] == "not_ready"

    asyncio.run(scenario())


def test_wait_online_honors_a_framework_requested_reconnect() -> None:
    async def scenario() -> None:
        control = ReadinessControl(cli_ready=True, reused=True)
        result = await DeviceExecutionTool(control).execute(
            DeviceTarget(device_id="d1"),
            WorkflowStep(
                "wait_online",
                kind="device",
                action="wait_online",
                params={"timeout_seconds": 2, "force_reconnect": True},
            ),
            context=ControlContext(source="test"),
        )

        assert control.reconnects == 1
        assert result["cli_status"] == "ready"

    asyncio.run(scenario())


def test_verify_version_matches_rebooted_package_from_display_startup() -> None:
    async def scenario() -> None:
        control = StartupVerificationControl(
            "Current startup system software: flash:/target.cc\n"
            "Next startup system software: flash:/target.cc\n<Huawei> "
        )
        result = await DeviceExecutionTool(control).execute(
            DeviceTarget(device_id="d1"),
            WorkflowStep(
                "verify_version",
                kind="device",
                action="verify_version",
                params={
                    "fact": "startup_package",
                    "expected": "images/target.cc",
                    "commands": ("display startup",),
                },
            ),
            context=ControlContext(source="test"),
        )

        assert result["status"] == "completed"
        assert result["output"].startswith("Current startup system software")

    asyncio.run(scenario())


def test_verify_version_rejects_wrong_rebooted_startup_package() -> None:
    async def scenario() -> None:
        control = StartupVerificationControl(
            "Current startup system software: flash:/other.cc\n"
            "Next startup system software: flash:/other.cc\n<Huawei> "
        )
        with pytest.raises(DeviceWorkflowExecutionError) as error:
            await DeviceExecutionTool(control).execute(
                DeviceTarget(device_id="d1"),
                WorkflowStep(
                    "verify_version",
                    kind="device",
                    action="verify_version",
                    params={
                        "fact": "startup_package",
                        "expected": "images/target.cc",
                        "commands": ("display startup",),
                    },
                ),
                context=ControlContext(source="test"),
            )

        assert error.value.code == "version_mismatch"

    asyncio.run(scenario())


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


def test_control_executes_for_a_device_without_a_preopened_terminal() -> None:
    async def scenario() -> None:
        executor = FakeExecutor()
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(),
            terminal_executor=executor,
        )
        result = await application.control.execute(
            DeviceTarget(device_id=SIMULATED_DEVICE_ID),
            CommandRequest(commands=("display version",)),
        )

        assert result.device_id == SIMULATED_DEVICE_ID
        assert result.session_id
        assert len(application.sessions.list_sessions()) == 1
        await application.sessions.close_all()

    asyncio.run(scenario())


def test_control_rejects_a_session_bound_to_another_device() -> None:
    async def scenario() -> None:
        application = build_desktop_application(SampleDeviceRepository(), SessionHub())
        session = await application.control.open_session(DeviceTarget(device_id=SIMULATED_DEVICE_ID))

        with pytest.raises(UnsupportedOperationError, match="does not belong"):
            await application.control.open_session(
                DeviceTarget(device_id="another-device", session_id=session.session_id),
            )
        await application.sessions.close_all()

    asyncio.run(scenario())


def test_open_session_reconnects_a_management_session_after_reboot() -> None:
    async def scenario() -> None:
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(),
        )
        session = await application.control.open_session(
            DeviceTarget(device_id=SIMULATED_DEVICE_ID),
        )
        await application.sessions.disconnect(session.session_id)

        reconnecting = await application.control.open_session(
            DeviceTarget(session_id=session.session_id),
        )
        assert reconnecting.session_id == session.session_id
        await asyncio.sleep(0.05)
        restored = await application.control.open_session(
            DeviceTarget(session_id=session.session_id),
        )
        assert restored.status == "connected"
        await application.sessions.close_all()

    asyncio.run(scenario())


def test_reboot_reports_command_and_disconnect_evidence() -> None:
    async def scenario() -> None:
        executor = RebootExecutor()
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(),
            terminal_executor=executor,
        )
        session = await application.control.open_session(
            DeviceTarget(device_id=SIMULATED_DEVICE_ID),
        )
        result = await application.control.reboot(
            DeviceTarget(session_id=session.session_id),
        )
        assert result.data["reboot_command_sent"] is True
        assert result.data["reboot_disconnect_observed"] is True
        expect = executor.plan.steps[1]
        assert getattr(expect, "disconnect_is_success", False) is True
        await application.sessions.close_all()

    asyncio.run(scenario())
