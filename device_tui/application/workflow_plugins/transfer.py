"""Generic staged file-transfer Activity."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from device_tui.framework.activity import ActivityContext, ActivityInvocation, ActivityResult, ActivityStatus
from device_tui.framework.events import Event


@dataclass(frozen=True, slots=True)
class TransferHandle:
    operation_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransferObservation:
    status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[dict[str, Any], ...] = ()


class TransferAdapter(Protocol):
    async def check_preconditions(self, invocation: ActivityInvocation) -> bool: ...
    async def should_skip(self, invocation: ActivityInvocation) -> bool: ...
    async def prepare(self, invocation: ActivityInvocation, report: Any) -> None: ...
    async def start(self, invocation: ActivityInvocation, report: Any) -> TransferHandle: ...
    async def monitor(self, handle: TransferHandle, invocation: ActivityInvocation, report: Any) -> TransferObservation: ...
    async def verify(self, handle: TransferHandle, observation: TransferObservation, invocation: ActivityInvocation) -> tuple[bool, dict[str, Any], tuple[dict[str, Any], ...]]: ...
    async def cancel(self, handle: TransferHandle, invocation: ActivityInvocation) -> None: ...


class TransferActivityHandler:
    """Run precondition, dispatch, monitor, and verification as one Activity."""

    def __init__(self, adapter: TransferAdapter, activity_id: str = "file.transfer") -> None:
        self.activity_id = activity_id
        self._adapter = adapter
        self._handles: dict[str, tuple[TransferHandle, ActivityInvocation]] = {}

    async def execute(self, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        del context
        if not await self._adapter.check_preconditions(invocation):
            return ActivityResult(ActivityStatus.FAILED, error={"code": "transfer_precondition_failed", "message": "transfer preconditions were not satisfied", "class": "deterministic"})
        report(self._event("transfer.precondition.checked", invocation, {"satisfied": True}))
        # A prior read-only probe may prove that the destination already has
        # the requested artifact.  Adapters can opt into this idempotent path
        # without manufacturing a transfer operation or re-sending bytes.
        should_skip = getattr(self._adapter, "should_skip", None)
        if callable(should_skip) and await should_skip(invocation):
            outputs = {
                "status": "completed",
                "skipped": True,
                "skip_reason": "destination_already_present",
                "verified": True,
            }
            report(self._event("transfer.started", invocation, {"skipped": True}))
            report(self._event("transfer.completed", invocation, {"skipped": True}))
            report(self._event("transfer.verification.passed", invocation, {"skipped": True}))
            return ActivityResult(ActivityStatus.SUCCEEDED, outputs=outputs, evidence=({
                "kind": "transfer_skip",
                "reason": "destination_already_present",
            },))
        await self._adapter.prepare(invocation, report)
        report(self._event("transfer.prepared", invocation, {}))
        handle = await self._adapter.start(invocation, report)
        if not handle.operation_id.strip():
            raise ValueError("transfer adapter returned an empty operation id")
        self._handles[invocation.invocation_id] = (handle, invocation)
        report(self._event("transfer.started", invocation, {"operation_id": handle.operation_id}))
        try:
            observation = await self._adapter.monitor(handle, invocation, report)
            if observation.status == "unknown":
                return ActivityResult(ActivityStatus.UNKNOWN, operation_id=handle.operation_id, outputs=dict(observation.outputs), evidence=observation.evidence, error={"code": "transfer_observation_unknown", "message": "transfer completion could not be confirmed", "class": "timeout"})
            if observation.status != "completed":
                return ActivityResult(ActivityStatus.FAILED, operation_id=handle.operation_id, outputs=dict(observation.outputs), evidence=observation.evidence, error={"code": "transfer_failed", "message": "transfer did not complete", "class": "deterministic"})
            report(self._event("transfer.completed", invocation, {"operation_id": handle.operation_id}))
            verified, outputs, evidence = await self._adapter.verify(handle, observation, invocation)
            if not verified:
                report(self._event("transfer.verification.failed", invocation, {"operation_id": handle.operation_id}))
                return ActivityResult(ActivityStatus.FAILED, operation_id=handle.operation_id, outputs={**observation.outputs, **outputs}, evidence=observation.evidence + evidence, error={"code": "transfer_verification_failed", "message": "target file verification failed", "class": "deterministic"})
            report(self._event("transfer.verification.passed", invocation, {"operation_id": handle.operation_id}))
            return ActivityResult(ActivityStatus.SUCCEEDED, operation_id=handle.operation_id, outputs={**observation.outputs, **outputs}, evidence=observation.evidence + evidence)
        except asyncio.TimeoutError:
            return ActivityResult(ActivityStatus.UNKNOWN, operation_id=handle.operation_id, error={"code": "transfer_timeout", "message": "transfer monitor timed out", "class": "timeout"})
        finally:
            self._handles.pop(invocation.invocation_id, None)

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del context
        active = self._handles.get(invocation.invocation_id)
        if active is not None:
            await self._adapter.cancel(active[0], active[1])

    @staticmethod
    def _event(event_type: str, invocation: ActivityInvocation, payload: dict[str, Any]) -> Event:
        return Event(type=event_type, run_id=invocation.workflow_run_id, action_id=invocation.activity_id, source="transfer.activity", payload=payload)


__all__ = ["TransferActivityHandler", "TransferAdapter", "TransferHandle", "TransferObservation"]
