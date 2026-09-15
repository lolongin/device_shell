"""Generic staged file-transfer Activity."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol

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
        invocation = self._with_workflow_target(invocation, context)
        try:
            preconditions_ok = await self._adapter.check_preconditions(invocation)
        except Exception as exc:
            return self._failure_result("transfer_precondition_failed", exc)
        if not preconditions_ok:
            return ActivityResult(
                ActivityStatus.FAILED,
                outputs=self._normalize_outputs({}, status="failed"),
                error={"code": "transfer_precondition_failed", "message": "transfer preconditions were not satisfied", "class": "deterministic"},
            )
        report(self._event("transfer.precondition.checked", invocation, {"satisfied": True}))
        # A prior read-only probe may prove that the destination already has
        # the requested artifact.  Adapters can opt into this idempotent path
        # without manufacturing a transfer operation or re-sending bytes.
        should_skip = getattr(self._adapter, "should_skip", None)
        try:
            skip_transfer = callable(should_skip) and await should_skip(invocation)
        except Exception as exc:
            return self._failure_result("transfer_skip_failed", exc)
        if skip_transfer:
            outputs = {
                "status": "completed",
                "operation_id": "",
                "skipped": True,
                "skip_reason": "destination_already_present",
                "verified": True,
                "output": "",
                "evidence": [],
            }
            report(self._event("transfer.started", invocation, {"skipped": True}))
            report(self._event("transfer.completed", invocation, {"skipped": True}))
            report(self._event("transfer.verification.passed", invocation, {"skipped": True}))
            return ActivityResult(ActivityStatus.SUCCEEDED, outputs=outputs, evidence=({
                "kind": "transfer_skip",
                "reason": "destination_already_present",
            },))
        try:
            await self._adapter.prepare(invocation, report)
        except Exception as exc:
            return self._failure_result("transfer_prepare_failed", exc)
        report(self._event("transfer.prepared", invocation, {}))
        try:
            handle = await self._adapter.start(invocation, report)
        except Exception as exc:
            return self._failure_result("transfer_start_failed", exc)
        if not handle.operation_id.strip():
            return self._failure_result(
                "transfer_start_failed",
                ValueError("transfer adapter returned an empty operation id"),
            )
        self._handles[invocation.invocation_id] = (handle, invocation)
        report(self._event("transfer.started", invocation, {"operation_id": handle.operation_id}))
        try:
            try:
                observation = await self._adapter.monitor(handle, invocation, report)
            except asyncio.TimeoutError:
                return ActivityResult(ActivityStatus.UNKNOWN, operation_id=handle.operation_id, outputs=self._normalize_outputs({}, status="unknown", operation_id=handle.operation_id), error={"code": "transfer_timeout", "message": "transfer monitor timed out", "class": "timeout"})
            except Exception as exc:
                return self._failure_result("transfer_monitor_failed", exc, operation_id=handle.operation_id)
            if observation.status == "unknown":
                outputs = self._normalize_outputs(observation.outputs, status="unknown", operation_id=handle.operation_id)
                return ActivityResult(ActivityStatus.UNKNOWN, operation_id=handle.operation_id, outputs=outputs, evidence=observation.evidence, error={"code": "transfer_observation_unknown", "message": "transfer completion could not be confirmed", "class": "timeout"})
            if observation.status != "completed":
                outputs = self._normalize_outputs(observation.outputs, status=observation.status, operation_id=handle.operation_id)
                return ActivityResult(ActivityStatus.FAILED, operation_id=handle.operation_id, outputs=outputs, evidence=observation.evidence, error={"code": "transfer_failed", "message": "transfer did not complete", "class": "deterministic"})
            report(self._event("transfer.completed", invocation, {"operation_id": handle.operation_id}))
            try:
                verified, outputs, evidence = await self._adapter.verify(handle, observation, invocation)
            except Exception as exc:
                return self._failure_result("transfer_verify_failed", exc, operation_id=handle.operation_id)
            if not verified:
                report(self._event("transfer.verification.failed", invocation, {"operation_id": handle.operation_id}))
                return ActivityResult(ActivityStatus.FAILED, operation_id=handle.operation_id, outputs=self._normalize_outputs({**observation.outputs, **outputs}, status="failed", operation_id=handle.operation_id), evidence=observation.evidence + evidence, error={"code": "transfer_verification_failed", "message": "target file verification failed", "class": "deterministic"})
            report(self._event("transfer.verification.passed", invocation, {"operation_id": handle.operation_id}))
            return ActivityResult(
                ActivityStatus.SUCCEEDED,
                operation_id=handle.operation_id,
                outputs=self._normalize_outputs(
                    {
                        **observation.outputs,
                        **outputs,
                        "evidence": list(observation.evidence + evidence),
                    },
                    status="completed",
                    operation_id=handle.operation_id,
                    verified=True,
                ),
                evidence=observation.evidence + evidence,
            )
        finally:
            self._handles.pop(invocation.invocation_id, None)

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None:
        del context
        active = self._handles.get(invocation.invocation_id)
        if active is not None:
            await self._adapter.cancel(active[0], active[1])

    @staticmethod
    def _with_workflow_target(invocation: ActivityInvocation, context: ActivityContext) -> ActivityInvocation:
        """Keep the workflow's device target available to every transfer stage."""
        target = invocation.context.get("target")
        target_values = dict(target) if isinstance(target, Mapping) else {}
        if not str(target_values.get("device_id") or "").strip():
            device_id = str(context.workflow_run.device_id or "").strip()
            if device_id:
                target_values["device_id"] = device_id
        if not target_values:
            return invocation
        return replace(
            invocation,
            context={**invocation.context, "target": target_values},
        )

    @staticmethod
    def _normalize_outputs(
        outputs: Mapping[str, Any],
        *,
        status: str,
        operation_id: str = "",
        verified: bool = False,
    ) -> dict[str, Any]:
        normalized = dict(outputs)
        normalized.setdefault("status", status)
        normalized.setdefault("operation_id", operation_id)
        normalized.setdefault("verified", verified)
        normalized.setdefault("skipped", False)
        normalized.setdefault("skip_reason", "")
        normalized.setdefault("output", "")
        normalized.setdefault("evidence", [])
        return normalized

    @classmethod
    def _failure_result(cls, code: str, exc: Exception, *, operation_id: str = "") -> ActivityResult:
        return ActivityResult(
            ActivityStatus.FAILED,
            operation_id=operation_id,
            outputs=cls._normalize_outputs({}, status="failed", operation_id=operation_id),
            error={"code": code, "message": str(exc), "class": "transient"},
        )

    @staticmethod
    def _event(event_type: str, invocation: ActivityInvocation, payload: dict[str, Any]) -> Event:
        return Event(type=event_type, run_id=invocation.workflow_run_id, action_id=invocation.activity_id, source="transfer.activity", payload=payload)


__all__ = ["TransferActivityHandler", "TransferAdapter", "TransferHandle", "TransferObservation"]
