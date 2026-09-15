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
from device_tui.infrastructure.transports.session_protocol import SessionCallbacks


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def run(self, *, session_id, device_id, plan, owner_id):
        self.calls.append({
            "session_id": session_id,
            "device_id": device_id,
            "plan": plan,
            "owner_id": owner_id,
        })
        return {
            "execution_id": "exec-1",
            "session_id": session_id,
            "device_id": device_id,
            "status": "completed",
            "steps": [{"output": "ok\n", "status": "completed"}],
            "duration_ms": 1,
        }


class SlowAdapterFactory:
    def __init__(self, connect_delay_seconds: float = 0.05) -> None:
        self.connect_delay_seconds = connect_delay_seconds
        self.adapters: list[SlowAdapter] = []
        self.targets = []

    def create(self, target, callbacks: SessionCallbacks) -> "SlowAdapter":
        self.targets.append(target)
        adapter = SlowAdapter(callbacks, self.connect_delay_seconds)
        self.adapters.append(adapter)
        return adapter


def test_control_uses_workflow_custom_endpoint() -> None:
    async def scenario() -> None:
        factory = SlowAdapterFactory()
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(factory),  # type: ignore[arg-type]
        )

        session = await application.control.open_session(
            DeviceTarget(
                device_id="MOCK-LAB-000",
                protocol="ssh",
                host="10.20.30.40",
                port=2222,
            ),
            reuse=True,
        )

        assert session.protocol == "ssh"
        assert factory.targets[0].host == "10.20.30.40"
        assert factory.targets[0].port == 2222
        await application.sessions.close_all()

    asyncio.run(scenario())


class FailingAdapterFactory:
    def create(self, target, callbacks: SessionCallbacks) -> "FailingAdapter":
        del target
        return FailingAdapter(callbacks)


class FailingAdapter:
    def __init__(self, callbacks: SessionCallbacks) -> None:
        self._callbacks = callbacks

    @property
    def is_connected(self) -> bool:
        return False

    async def connect(self, target, term_size) -> None:
        del target, term_size
        self._callbacks.on_status("Connecting")
        raise OSError("expected connection failure")

    async def disconnect(self, message: str = "Disconnected.") -> None:
        del message

    async def send_text(self, text: str) -> None:
        del text

    async def send_command(self, command: str) -> None:
        del command

    async def resize(self, columns: int, lines: int) -> None:
        del columns, lines


class SlowAdapter:
    def __init__(self, callbacks: SessionCallbacks, connect_delay_seconds: float) -> None:
        self._callbacks = callbacks
        self._connect_delay_seconds = connect_delay_seconds
        self.is_connected = False
        self.sent: list[str] = []

    async def connect(self, target, term_size) -> None:
        del target, term_size
        self._callbacks.on_status("Connecting")
        await asyncio.sleep(self._connect_delay_seconds)
        self.is_connected = True
        self._callbacks.on_status("Connected")

    async def disconnect(self, message: str = "Disconnected.") -> None:
        del message
        self.is_connected = False
        self._callbacks.on_status("Disconnected")

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def send_command(self, command: str) -> None:
        del command

    async def resize(self, columns: int, lines: int) -> None:
        del columns, lines


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


class CustomCommandProfile:
    def version_query(self) -> str:
        return "show version"

    def startup_query(self) -> str:
        return "show startup"

    def storage_query(self, storage: str) -> str:
        return f"list {storage}"

    def activation_command(self, destination_path: str) -> str:
        return f"boot {destination_path}"

    def startup_package_matches(self, output: str, package_name: str) -> bool:
        return package_name in output

    def reboot_steps(self) -> tuple[dict[str, object], ...]:
        return ({"type": "send", "text": "restart"},)


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


def test_device_execution_tool_uses_injected_command_profile() -> None:
    class ProfileControl:
        async def execute(self, target, request, *, context):
            del target, context
            assert request.commands == ("show startup",)
            return CommandResult(
                operation_id="probe-1",
                execution_id="probe-1",
                session_id="session-1",
                device_id="d1",
                status="completed",
                output="target.cc",
            )

    async def scenario() -> None:
        result = await DeviceExecutionTool(
            ProfileControl(), command_profile=CustomCommandProfile()
        ).execute(
            DeviceTarget(device_id="d1"),
            WorkflowStep(
                "verify_version",
                kind="device",
                action="verify_version",
                params={
                    "fact": "startup_package",
                    "expected": "target.cc",
                    "commands": ("show startup",),
                },
            ),
            context=ControlContext(source="test"),
        )
        assert result["status"] == "completed"

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


def test_control_exposes_session_status_for_workflow_preconditions() -> None:
    async def scenario() -> None:
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(),
        )
        session = await application.control.open_session(
            DeviceTarget(device_id=SIMULATED_DEVICE_ID),
        )

        observed = application.control.session_status(
            DeviceTarget(session_id=session.session_id),
        )

        assert observed["session_id"] == session.session_id
        assert observed["device_id"] == SIMULATED_DEVICE_ID
        assert observed["status"] == "connected"
        assert observed["value"] == "connected"
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


def test_control_execute_waits_for_newly_created_session_to_connect() -> None:
    async def scenario() -> None:
        executor = FakeExecutor()
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(adapter_factory=SlowAdapterFactory()),
            terminal_executor=executor,
        )
        result = await application.control.execute(
            DeviceTarget(device_id=SIMULATED_DEVICE_ID),
            CommandRequest(commands=("display version",)),
        )

        assert result.status == "completed"
        assert len(executor.calls) == 1
        assert result.session_id == executor.calls[0]["session_id"]
        await application.sessions.close_all()

    asyncio.run(scenario())


def test_control_send_raw_waits_for_newly_created_session_to_connect() -> None:
    async def scenario() -> None:
        factory = SlowAdapterFactory()
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(adapter_factory=factory),
        )
        result = await application.control.send_raw(
            DeviceTarget(device_id=SIMULATED_DEVICE_ID),
            "display version",
        )

        assert result.sent is True
        assert factory.adapters[0].sent == ["display version\r"]
        await application.sessions.close_all()

    asyncio.run(scenario())


def test_control_execute_reports_connection_failure() -> None:
    async def scenario() -> None:
        application = build_desktop_application(
            SampleDeviceRepository(),
            SessionHub(adapter_factory=FailingAdapterFactory()),
            terminal_executor=FakeExecutor(),
        )
        with pytest.raises(ApplicationError, match="failed to connect"):
            await application.control.execute(
                DeviceTarget(device_id=SIMULATED_DEVICE_ID),
                CommandRequest(commands=("display version",)),
            )
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
