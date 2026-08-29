"""Adapter from the generic transfer Activity to the device-control service.

The managed transfer service remains the owner of FTP/SFTP and terminal-plan
details.  This module only translates the application-level operation record
into the transport-neutral :class:`TransferAdapter` contract.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from device_tui.application.device_control import (
    ControlContext,
    DeviceControlService,
    DeviceTarget,
    TransferRequest,
)
from device_tui.application.device_control.models import OperationView
from device_tui.framework import ActivityInvocation, Event

from .transfer import TransferAdapter, TransferHandle, TransferObservation


class TerminalTransferAdapter(TransferAdapter):
    """Use the existing managed transfer operation as a generic Activity."""

    def __init__(
        self,
        control: DeviceControlService,
        *,
        poll_interval_seconds: float = 0.25,
        default_timeout_seconds: float = 900.0,
    ) -> None:
        self.activity_id = "file.transfer"
        self._control = control
        self._poll_interval = max(0.05, float(poll_interval_seconds))
        self._default_timeout = max(1.0, float(default_timeout_seconds))

    async def check_preconditions(self, invocation: ActivityInvocation) -> bool:
        """Validate the target and required transfer fields before dispatch."""
        inputs = invocation.inputs
        target = self._target_values(invocation)
        session_id = str(target.get("session_id") or "").strip()
        direction = str(inputs.get("direction") or "upload").strip().casefold()
        source = str(inputs.get("source_path") or "").strip()
        destination = str(inputs.get("destination_path") or "").strip()
        if not session_id or direction not in {"upload", "download"}:
            return False
        if not source or not destination:
            return False
        # transfer() performs the authoritative connected-session and device
        # lease checks.  Keeping this probe side-effect free avoids opening a
        # second session merely to check a precondition.
        return True

    async def should_skip(self, invocation: ActivityInvocation) -> bool:
        """Honor an explicit probe-backed idempotency decision.

        The adapter does not parse vendor output.  It only consumes the
        structured ``package.present`` fact produced by an earlier read-only
        probe and requires the caller to opt in with ``skip_if_present``.
        """
        if not bool(invocation.inputs.get("skip_if_present", False)):
            return False
        facts = invocation.context.get("action.precheck.facts")
        if not isinstance(facts, dict):
            return False
        package = facts.get("package")
        return isinstance(package, dict) and bool(package.get("present"))

    async def prepare(self, invocation: ActivityInvocation, report: Any) -> None:
        del invocation, report

    async def start(self, invocation: ActivityInvocation, report: Any) -> TransferHandle:
        inputs = invocation.inputs
        target = self._target_values(invocation)
        session_id = str(target.get("session_id") or "").strip()
        device_id = str(target.get("device_id") or "").strip()
        protocol = str(target.get("protocol") or "auto").strip() or "auto"
        direction = str(inputs.get("direction") or "upload").strip().casefold()
        context = self._context(invocation)
        operation = self._control.transfer(
            DeviceTarget(device_id=device_id, session_id=session_id, protocol=protocol),
            TransferRequest(
                direction=direction,
                source_path=str(inputs.get("source_path") or ""),
                destination_path=str(inputs.get("destination_path") or ""),
                overwrite=bool(inputs.get("overwrite", False)),
                terminal_environment=str(inputs.get("terminal_environment") or "auto"),
                command_mode=str(inputs.get("command_mode") or "vrp"),
                interaction_profile={
                    str(key): str(value)
                    for key, value in dict(inputs.get("interaction_profile") or {}).items()
                },
            ),
            context=context,
        )
        report(self._event("transfer.operation.queued", invocation, self._operation_payload(operation)))
        return TransferHandle(operation.operation_id, metadata={"direction": direction})

    async def monitor(
        self,
        handle: TransferHandle,
        invocation: ActivityInvocation,
        report: Any,
    ) -> TransferObservation:
        timeout = float(
            invocation.inputs.get("monitor_timeout_seconds")
            or invocation.inputs.get("activity_timeout_seconds")
            or self._default_timeout
        )
        deadline = time.monotonic() + max(1.0, timeout)
        last_revision = -1
        while True:
            operation = self._control.get_operation(handle.operation_id)
            if operation.revision != last_revision:
                last_revision = operation.revision
                report(self._event("transfer.operation.observed", invocation, self._operation_payload(operation)))
            if operation.status == "completed":
                return TransferObservation(
                    "completed",
                    outputs=self._operation_outputs(operation),
                    evidence=(self._operation_evidence(operation),),
                )
            if operation.status in {"failed", "cancelled"}:
                return TransferObservation(
                    operation.status,
                    outputs=self._operation_outputs(operation),
                    evidence=(self._operation_evidence(operation),),
                )
            # A process restart turns in-flight operations into interrupted;
            # completion can no longer be proven and must be reconciled.
            if operation.status == "interrupted":
                return TransferObservation(
                    "unknown",
                    outputs=self._operation_outputs(operation),
                    evidence=(self._operation_evidence(operation),),
                )
            if time.monotonic() >= deadline:
                return TransferObservation(
                    "unknown",
                    outputs=self._operation_outputs(operation),
                    evidence=(self._operation_evidence(operation),),
                )
            await asyncio.sleep(self._poll_interval)

    async def verify(
        self,
        handle: TransferHandle,
        observation: TransferObservation,
        invocation: ActivityInvocation,
    ) -> tuple[bool, dict[str, Any], tuple[dict[str, Any], ...]]:
        del invocation
        if observation.status != "completed":
            return False, {}, ()
        operation = self._control.get_operation(handle.operation_id)
        if operation.status != "completed":
            return False, {}, (self._operation_evidence(operation),)
        # ManagedTransferService only marks an operation completed after its
        # target-file verification.  Re-check the durable counters here so the
        # generic Activity contract does not trust a transient progress event.
        total = int(operation.total_bytes or 0)
        transferred = int(operation.bytes_transferred or 0)
        if total > 0 and transferred != total:
            return False, {"bytes_transferred": transferred, "total_bytes": total}, (
                self._operation_evidence(operation),
            )
        return True, self._operation_outputs(operation) | {"verified": True}, (
            self._operation_evidence(operation),
        )

    async def cancel(self, handle: TransferHandle, invocation: ActivityInvocation) -> None:
        del invocation
        self._control.cancel_operation(handle.operation_id)

    @staticmethod
    def _context(invocation: ActivityInvocation) -> ControlContext:
        values = invocation.context
        return ControlContext(
            source=str(values.get("source") or "workflow"),
            request_id=str(values.get("request_id") or invocation.invocation_id),
            task_id=str(values.get("task_id") or ""),
            step_id=str(values.get("step_id") or invocation.activity_id),
            lease_token=str(values.get("lease_token") or ""),
            actor=str(values.get("actor") or ""),
        )

    @staticmethod
    def _target_values(invocation: ActivityInvocation) -> dict[str, Any]:
        values = invocation.context.get("target")
        target = dict(values) if isinstance(values, dict) else {}
        for key in ("device_id", "session_id", "protocol"):
            if key in invocation.inputs:
                target[key] = invocation.inputs[key]
        return target

    @staticmethod
    def _operation_outputs(operation: OperationView) -> dict[str, Any]:
        return {
            "operation_id": operation.operation_id,
            "status": operation.status,
            "stage": operation.stage,
            "progress_percent": operation.progress_percent,
            "bytes_transferred": operation.bytes_transferred,
            "total_bytes": operation.total_bytes,
            "data": dict(operation.data),
        }

    @staticmethod
    def _operation_payload(operation: OperationView) -> dict[str, Any]:
        return {
            "operation_id": operation.operation_id,
            "status": operation.status,
            "stage": operation.stage,
            "progress_percent": operation.progress_percent,
            "bytes_transferred": operation.bytes_transferred,
            "total_bytes": operation.total_bytes,
        }

    @staticmethod
    def _operation_evidence(operation: OperationView) -> dict[str, Any]:
        return {
            "kind": "managed_transfer_operation",
            "operation_id": operation.operation_id,
            "revision": operation.revision,
            "status": operation.status,
            "stage": operation.stage,
            "error_code": operation.error_code,
            "data": dict(operation.data),
        }

    @staticmethod
    def _event(event_type: str, invocation: ActivityInvocation, payload: dict[str, Any]) -> Event:
        return Event(
            type=event_type,
            run_id=invocation.workflow_run_id,
            action_id=invocation.activity_id,
            source="terminal.transfer.adapter",
            payload=payload,
        )


__all__ = ["TerminalTransferAdapter"]
