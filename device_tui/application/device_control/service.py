"""Application-level facade shared by all device-control adapters."""

from __future__ import annotations

import inspect
from uuid import uuid4

from device_tui.application.devices import DeviceActionResult, DeviceService
from device_tui.application.commands import CommandService
from device_tui.application.credentials import ConnectionTarget
from device_tui.application.errors import ApplicationConflictError, ResourceNotFoundError, UnsupportedOperationError
from device_tui.application.operations import OperationManager, OperationRecord
from device_tui.application.sessions import SessionRecord, SessionService
from device_tui.application.terminal.orchestration import (
    TerminalPlanError,
    build_batch_plan,
    parse_terminal_plan,
)
from device_tui.application.transfers import ManagedTransferService, TerminalPlanExecutor
from device_tui.application.upgrades import PackageUpgradeService

from .models import (
    CommandRequest,
    CommandResult,
    ControlContext,
    DeviceTarget,
    OperationView,
    PackageUpgradeRequest,
    SendResult,
    BroadcastResult,
    SessionView,
    TransferRequest,
)
from .lease import DeviceLeaseService


class DeviceControlService:
    """Coordinate device operations while delegating transport work to existing services.

    This facade intentionally contains no SSH, serial, Telnet, FTP, or terminal
    protocol implementation. It only resolves targets and selects the existing
    application services used by the desktop today.
    """

    def __init__(
        self,
        devices: DeviceService,
        sessions: SessionService,
        transfers: ManagedTransferService,
        operations: OperationManager,
        terminal_executor: TerminalPlanExecutor,
        upgrades: PackageUpgradeService,
        leases: DeviceLeaseService | None = None,
    ) -> None:
        self._devices = devices
        self._sessions = sessions
        self._transfers = transfers
        self._operations = operations
        self._executor = terminal_executor
        self._upgrades = upgrades
        self._leases = leases

    async def open_session(
        self,
        target: DeviceTarget,
        *,
        reuse: bool = True,
        title: str = "",
        term_size: tuple[int, int] = (160, 40),
        timeout_seconds: int = 15,
        context: ControlContext | None = None,
    ) -> SessionView:
        del timeout_seconds, context
        if target.session_id:
            session = self._session(target.session_id)
            return self._session_view(session, reused=True)
        device_id = self._required_device_id(target)
        requested_protocol = target.protocol.casefold()
        if reuse:
            for session in self._sessions.list_sessions():
                same_protocol = (
                    requested_protocol == "auto"
                    or session.kind.casefold() == requested_protocol
                )
                if session.device_id == device_id and session.status == "connected" and same_protocol:
                    return self._session_view(session, reused=True)
        protocol = requested_protocol
        if protocol == "auto":
            protocol = self._protocol_for(self._devices.require_device(device_id))
        session = await self._sessions.create(device_id, protocol, title, term_size)
        return self._session_view(session)

    async def open_connection(
        self,
        target: ConnectionTarget,
        *,
        reuse: bool = False,
        title: str = "",
        term_size: tuple[int, int] = (160, 40),
        context: ControlContext | None = None,
    ) -> SessionView:
        del context
        if reuse:
            for session in self._sessions.list_sessions():
                if session.device_id == target.device_id and session.status == "connected":
                    return self._session_view(session, reused=True)
        session = await self._sessions.create_target(target, title, term_size)
        return self._session_view(session)

    async def reconnect_session(
        self,
        target: DeviceTarget,
        *,
        timeout_seconds: int = 15,
        context: ControlContext | None = None,
    ) -> SessionView:
        del timeout_seconds, context
        session = self._session_for_target(target)
        return self._session_view(await self._sessions.reconnect(session.id))

    async def disconnect_session(
        self,
        target: DeviceTarget,
        *,
        context: ControlContext | None = None,
    ) -> SessionView:
        del context
        session = self._session_for_target(target)
        return self._session_view(await self._sessions.disconnect(session.id))

    async def close_session(
        self,
        target: DeviceTarget,
        *,
        context: ControlContext | None = None,
    ) -> None:
        del context
        await self._sessions.close(self._session_for_target(target).id)

    async def send_raw(
        self,
        target: DeviceTarget,
        text: str,
        *,
        context: ControlContext | None = None,
    ) -> SendResult:
        self._validate_task_lease(target, context)
        value = str(text)
        if not value.strip():
            raise UnsupportedOperationError("Command text cannot be empty.")
        session = self._connected_session_for_target(target)
        await self._sessions.write(session.id, CommandService.command_payload(value))
        return SendResult(session_id=session.id, device_id=session.device_id, sent=True)

    async def broadcast(
        self,
        text: str,
        *,
        session_ids: list[str] | None = None,
        context: ControlContext | None = None,
    ) -> BroadcastResult:
        del context
        value = str(text)
        if not value.strip():
            raise UnsupportedOperationError("Command text cannot be empty.")
        requested = set(session_ids or [])
        targets = [
            session
            for session in self._sessions.list_sessions()
            if session.status == "connected" and (not requested or session.id in requested)
        ]
        if not targets:
            raise UnsupportedOperationError("No connected terminal session is available.")
        payload = CommandService.command_payload(value)
        for session in targets:
            await self._sessions.write(session.id, payload)
        return BroadcastResult(tuple(session.id for session in targets), value)

    async def execute(
        self,
        target: DeviceTarget,
        request: CommandRequest,
        *,
        context: ControlContext | None = None,
    ) -> CommandResult:
        self._validate_task_lease(target, context)
        session = self._connected_session_for_target(target)
        mode = request.mode.casefold()
        if mode == "interactive":
            if not request.steps:
                raise UnsupportedOperationError("Interactive execution requires steps.")
            try:
                plan = parse_terminal_plan(
                    [dict(step) for step in request.steps],
                    total_timeout_seconds=request.total_timeout_seconds or 60,
                )
            except TerminalPlanError as exc:
                raise UnsupportedOperationError(str(exc), details={"code": exc.code}) from exc
        else:
            if not request.commands:
                raise UnsupportedOperationError("Command execution requires at least one command.")
            try:
                plan = build_batch_plan(
                    list(request.commands),
                    command_timeout_seconds=request.timeout_seconds,
                    total_timeout_seconds=request.total_timeout_seconds,
                    max_output_chars=request.max_output_chars,
                )
            except TerminalPlanError as exc:
                raise UnsupportedOperationError(str(exc), details={"code": exc.code}) from exc
        execution_id = str(uuid4())
        owner_id = f"device-control:{execution_id}"
        if context is not None and context.operation_callback is not None:
            context.operation_callback("execution", execution_id)
        run_args = {
            "session_id": session.id,
            "device_id": session.device_id,
            "plan": plan,
            "owner_id": owner_id,
        }
        # Older injected test/plugin executors predate preallocated execution
        # ids. The bundled executor accepts the id, allowing Task cancellation
        # to address the terminal run before it has completed.
        if "execution_id" in inspect.signature(self._executor.run).parameters:
            run_args["execution_id"] = execution_id
        result = await self._executor.run(**run_args)
        data = dict(result)
        status = str(data.get("status") or "failed")
        output = "".join(
            str(step.get("output") or "")
            for step in data.get("steps", [])
            if isinstance(step, dict)
        )
        actual_execution_id = str(data.get("execution_id") or execution_id)
        return CommandResult(
            operation_id=actual_execution_id,
            execution_id=actual_execution_id,
            session_id=session.id,
            device_id=session.device_id,
            status=status,
            output=output,
            error_code=str(data.get("error_code") or ""),
            steps=tuple(step for step in data.get("steps", []) if isinstance(step, dict)),
            duration_ms=float(data.get("duration_ms") or 0),
            data=data,
        )

    def transfer(
        self,
        target: DeviceTarget,
        request: TransferRequest,
        *,
        context: ControlContext | None = None,
    ) -> OperationView:
        self._validate_task_lease(target, context)
        session = self._connected_session_for_target(target)
        direction = request.direction.casefold()
        if direction == "upload":
            record = self._transfers.start_upload(
                session_id=session.id,
                source_path=request.source_path,
                destination_path=request.destination_path,
                overwrite=request.overwrite,
                terminal_environment=request.terminal_environment,
                command_mode=request.command_mode,
            )
        elif direction == "download":
            record = self._transfers.start_download(
                session_id=session.id,
                source_path=request.source_path,
                destination_path=request.destination_path,
                overwrite=request.overwrite,
                terminal_environment=request.terminal_environment,
                command_mode=request.command_mode,
            )
        else:
            raise UnsupportedOperationError(f"Unsupported transfer direction: {request.direction}")
        return self._operation_view(record)

    async def reboot(
        self,
        target: DeviceTarget,
        *,
        timeout_seconds: int = 190,
        context: ControlContext | None = None,
    ) -> CommandResult:
        self._validate_task_lease(target, context)
        return await self.execute(
            target,
            CommandRequest(
                commands=("reboot",),
                mode="interactive",
                total_timeout_seconds=timeout_seconds,
                steps=(
                    {"type": "send", "text": "reboot", "label": "发送 reboot"},
                    {
                        "type": "expect",
                        "success": ["device_prompt", "login_prompt", "username_prompt"],
                        "failures": [],
                        # Huawei VRP may ask one or more destructive-action
                        # confirmations after ``reboot``. These are device
                        # prompts, not task approvals; answer them inside the
                        # interactive command plan so the workflow can reach
                        # the post-reboot wait/verification steps.
                        "responses": [
                            {"match": "confirmation_prompt", "text": "y", "max_matches": 3},
                        ],
                        "timeout_seconds": timeout_seconds - 10,
                        "label": "等待设备重启完成",
                        "max_output_chars": 32_768,
                    },
                ),
            ),
            context=context,
        )

    def power_off(
        self,
        device_id: str,
        *,
        context: ControlContext | None = None,
    ) -> DeviceActionResult:
        self._validate_task_lease(DeviceTarget(device_id=device_id), context)
        return self._devices.power_off(device_id)

    def start_package_upgrade(
        self,
        target: DeviceTarget,
        request: PackageUpgradeRequest,
        *,
        context: ControlContext | None = None,
    ) -> OperationView:
        self._validate_task_lease(target, context)
        session = self._session_for_target(target)
        record = self._upgrades.start(
            session_id=session.id,
            package_path=request.package_path,
            package_source=request.package_source,
            include_slave=request.include_slave,
            standby_required=request.standby_required,
            auto_delete_old_packages=request.auto_delete_old_packages,
            reboot_after_setting=request.reboot_after_setting,
            master_storage=request.master_storage,
            slave_storage=request.slave_storage,
            driver_id=request.driver_id,
        )
        return self._operation_view(record)

    def approve_package_upgrade_reboot(
        self,
        operation_id: str,
        *,
        context: ControlContext | None = None,
    ) -> OperationView:
        record = self._operations.get(operation_id)
        self._validate_task_lease(DeviceTarget(device_id=record.device_id, session_id=record.session_id), context)
        return self._operation_view(self._upgrades.approve_reboot(operation_id))

    def _validate_task_lease(self, target: DeviceTarget, context: ControlContext | None) -> None:
        if self._leases is None:
            return
        device_id = target.device_id
        if not device_id and target.session_id:
            device_id = self._session(target.session_id).device_id
        if not device_id:
            return
        current = self._leases.get(device_id)
        if current is None:
            if context is not None and context.task_id and context.lease_token:
                self._leases.renew(device_id, context.lease_token)
            return
        if context is None or not context.task_id or not context.lease_token:
            raise ApplicationConflictError(
                "设备正在由任务执行，当前操作已被策略拒绝。",
                details={"device_id": device_id, "owner_id": current.owner_id},
            )
        self._leases.renew(device_id, context.lease_token)

    def get_operation(self, operation_id: str) -> OperationView:
        return self._operation_view(self._operations.get(operation_id))

    def list_operations(self, *, kind: str = "", limit: int = 200) -> list[OperationView]:
        return [self._operation_view(item) for item in self._operations.list(kind=kind, limit=limit)]

    def cancel_operation(self, operation_id: str) -> OperationView:
        return self._operation_view(self._operations.cancel(operation_id))

    def get_execution(self, execution_id: str) -> dict[str, object]:
        return dict(self._executor.get_execution(execution_id))

    def cancel_execution(self, execution_id: str) -> dict[str, object]:
        return dict(self._executor.cancel_execution(execution_id))

    def cancel_active_execution(self, target: DeviceTarget) -> str:
        """Cancel the active terminal plan for a task target."""
        return self._executor.cancel_active(self._session_for_target(target).id)

    def _session_for_target(self, target: DeviceTarget) -> SessionRecord:
        if target.session_id:
            return self._session(target.session_id)
        device_id = self._required_device_id(target)
        for session in self._sessions.list_sessions():
            if session.device_id == device_id:
                return session
        raise ResourceNotFoundError(
            f"No session for device: {device_id}",
            details={"device_id": device_id},
        )

    def _connected_session_for_target(self, target: DeviceTarget) -> SessionRecord:
        session = self._session_for_target(target)
        if session.status != "connected":
            raise UnsupportedOperationError(
                f"Session is not connected: {session.id}",
                details={"session_id": session.id, "status": session.status},
            )
        return session

    def _session(self, session_id: str) -> SessionRecord:
        for session in self._sessions.list_sessions():
            if session.id == session_id:
                return session
        raise ResourceNotFoundError(
            f"Unknown session: {session_id}",
            details={"session_id": session_id},
        )

    @staticmethod
    def _required_device_id(target: DeviceTarget) -> str:
        value = target.device_id.strip()
        if not value:
            raise UnsupportedOperationError("device_id or session_id is required.")
        return value

    @staticmethod
    def _session_view(session: SessionRecord, *, reused: bool = False) -> SessionView:
        return SessionView(
            session_id=session.id,
            device_id=session.device_id,
            protocol=session.kind,
            status=session.status,
            title=session.title,
            sequence=session.sequence,
            generation=session.generation,
            reused=reused,
        )

    @staticmethod
    def _protocol_for(device: object) -> str:
        device_type = str(getattr(device, "device_type", "")).casefold()
        if device_type.startswith("mock"):
            return "simulated"
        if getattr(device, "ssh_endpoint", None):
            return "ssh"
        if getattr(device, "telnet_endpoint", None):
            return "telnet"
        if getattr(device, "serial_endpoint", None):
            return "serial"
        return "simulated"

    @staticmethod
    def _operation_view(record: OperationRecord) -> OperationView:
        return OperationView(
            operation_id=record.id,
            kind=record.kind,
            direction=record.direction,
            device_id=record.device_id,
            session_id=record.session_id,
            status=record.status,
            stage=record.stage,
            message=record.message,
            progress_percent=record.progress_percent,
            bytes_transferred=record.bytes_transferred,
            total_bytes=record.total_bytes,
            bytes_per_second=record.bytes_per_second,
            eta_seconds=record.eta_seconds,
            queue_position=record.queue_position,
            retry_of=record.retry_of,
            cancellable=record.cancellable,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            error_code=record.error_code,
            data=dict(record.data),
        )
