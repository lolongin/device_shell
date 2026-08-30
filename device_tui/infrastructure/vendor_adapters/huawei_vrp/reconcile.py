"""Huawei VRP reconciliation adapters for the generic workflow runtime.

Reconciliation is a vendor/transport integration concern.  The framework
only consumes the ``ReconcileProvider`` protocol; this module owns the VRP
commands and evidence needed to classify an uncertain operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Protocol

from device_tui.application.device_control import ControlContext, DeviceTarget
from device_tui.application.errors import ApplicationError
from device_tui.framework.models import (
    ActionSpec,
    ReconcileClassification,
    ReconcileResult,
    WorkflowRun,
)
from device_tui.framework.plugins import ReconcileRegistry

from .commands import HuaweiVrpCommandSet
from .parsers import package_basename, startup_uses_package


class DeviceExecutionPort(Protocol):
    async def probe_cli(
        self,
        target: DeviceTarget,
        *,
        command: str,
        timeout_seconds: int,
        context: ControlContext,
    ) -> dict[str, Any]: ...

    async def execute(self, target: DeviceTarget, step: Any, *, context: ControlContext) -> dict[str, Any]: ...

    def get_resource(self, kind: str, resource_id: str) -> dict[str, Any]: ...


class DeviceControlPort(Protocol):
    async def open_session(
        self,
        target: DeviceTarget,
        *,
        reuse: bool,
        context: ControlContext,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class _CommandStep:
    """Structural command value accepted by the legacy execution port."""

    id: str
    kind: str
    action: str
    params: dict[str, Any]


class HuaweiVrpReconcileProvider:
    """Confirm outcomes using VRP read-only probes and operation state."""

    def __init__(
        self,
        provider_id: str,
        execution: DeviceExecutionPort,
        control: DeviceControlPort,
    ) -> None:
        self.id = provider_id
        self._execution = execution
        self._control = control
        self._commands = HuaweiVrpCommandSet()

    async def reconcile(
        self,
        action: ActionSpec,
        run: WorkflowRun,
        reason: str,
        emit: Any,
    ) -> ReconcileResult:
        del emit
        target = _target_for_run(run)
        evidence: list[dict[str, Any]] = [{"reason": reason, "provider": self.id}]
        try:
            if self.id.endswith("online") or action.operation == "device.wait_online":
                view = await self._control.open_session(
                    target,
                    reuse=True,
                    context=_control_context(run, action),
                )
                evidence.append({"probe": "session", "status": view.status, "session_id": view.session_id})
                transport_status = str(view.status).casefold()
                if transport_status not in {"connected", "ready", "open"}:
                    classification = (
                        ReconcileClassification.IN_PROGRESS
                        if transport_status in {"creating", "connecting", "authenticating"}
                        else ReconcileClassification.INDETERMINATE
                    )
                    return ReconcileResult(
                        classification,
                        {
                            "session_id": view.session_id,
                            "transport_status": transport_status,
                            "cli_status": "unknown",
                        },
                        tuple(evidence),
                    )
                probe = await self._execution.probe_cli(
                    DeviceTarget(session_id=view.session_id),
                    command=str(
                        action.params.get("readiness_command")
                        or self._commands.version_query()
                    ),
                    timeout_seconds=min(30, max(1, int(action.reconcile.budget_seconds))),
                    context=_control_context(run, action),
                )
                evidence.append({
                    "probe": "cli",
                    "transport_status": transport_status,
                    "cli_status": probe.get("cli_status", "unknown"),
                    "probe_command": probe.get("probe_command", ""),
                    "execution_id": probe.get("execution_id", ""),
                    "error_code": probe.get("error_code", ""),
                })
                facts = {
                    "session_id": view.session_id,
                    "transport_status": transport_status,
                    **probe,
                }
                if probe.get("cli_status") == "ready":
                    return ReconcileResult(ReconcileClassification.SUCCESS, facts, tuple(evidence))
                return ReconcileResult(ReconcileClassification.INDETERMINATE, facts, tuple(evidence))

            if self.id.endswith("reboot"):
                reboot = _action_facts(run, action.id).get("reboot")
                signals = dict(reboot) if isinstance(reboot, dict) else {}
                command_sent = bool(signals.get("command_sent", False))
                disconnect_observed = bool(signals.get("disconnect_observed", False))
                evidence.append({
                    "probe": "reboot_execution",
                    "command_sent": command_sent,
                    "disconnect_observed": disconnect_observed,
                })
                if command_sent and disconnect_observed:
                    return ReconcileResult(ReconcileClassification.SUCCESS, signals, tuple(evidence))
                if not command_sent:
                    return ReconcileResult(ReconcileClassification.NOT_STARTED, signals, tuple(evidence))
                return ReconcileResult(ReconcileClassification.INDETERMINATE, signals, tuple(evidence))

            if self.id.endswith("transfer"):
                operation_id = _last_operation_id(run, action.id)
                if operation_id:
                    snapshot = self._execution.get_resource("operation", operation_id)
                    status = str(snapshot.get("status") or "").casefold()
                    evidence.append({"probe": "operation", "operation_id": operation_id, "status": status})
                    if status in {"completed", "success", "succeeded"}:
                        return ReconcileResult(ReconcileClassification.SUCCESS, snapshot, tuple(evidence))
                    if status in {"running", "pending", "queued", "downloading", "verifying"}:
                        return ReconcileResult(ReconcileClassification.IN_PROGRESS, snapshot, tuple(evidence))
                    if status in {"failed", "cancelled", "canceled", "interrupted"}:
                        return ReconcileResult(ReconcileClassification.FAILED, snapshot, tuple(evidence))

            if self.id.endswith("startup"):
                package = package_basename(str(action.params.get("package") or ""))
                data = await self._execution.execute(
                    target,
                    _CommandStep(
                        "reconcile",
                        "device",
                        "verify",
                        {"commands": (self._commands.startup_query(),)},
                    ),
                    context=_control_context(run, action),
                )
                output = str(data.get("output") or "")
                matched = bool(package and startup_uses_package(output, package))
                evidence.append({
                    "probe": self._commands.startup_query(),
                    "expected_package": package,
                    "matched": matched,
                })
                if matched:
                    return ReconcileResult(ReconcileClassification.SUCCESS, {"output": output}, tuple(evidence))
                return ReconcileResult(ReconcileClassification.INDETERMINATE, {"output": output}, tuple(evidence))

            if self.id.endswith("rollback"):
                expected = package_basename(str(_previous_startup(run).get("current_system") or ""))
                data = await self._execution.execute(
                    target,
                    _CommandStep(
                        "reconcile",
                        "device",
                        "verify",
                        {"commands": (self._commands.startup_query(),)},
                    ),
                    context=_control_context(run, action),
                )
                output = str(data.get("output") or "")
                matched = bool(expected and expected in output.casefold())
                evidence.append({
                    "probe": self._commands.startup_query(),
                    "expected_current_system": expected,
                    "matched": matched,
                })
                if matched:
                    return ReconcileResult(ReconcileClassification.SUCCESS, {"output": output}, tuple(evidence))
                return ReconcileResult(ReconcileClassification.INDETERMINATE, {"output": output}, tuple(evidence))
        except (ApplicationError, OSError, KeyError) as exc:
            evidence.append({"error": str(exc), "error_code": getattr(exc, "code", "reconcile_failed")})
        return ReconcileResult(ReconcileClassification.INDETERMINATE, {}, tuple(evidence))


def build_huawei_reconcile_registry(
    execution: DeviceExecutionPort,
    control: DeviceControlPort,
) -> ReconcileRegistry:
    """Register the reconciliation providers implemented by this adapter."""

    registry = ReconcileRegistry()
    for provider_id in (
        "huawei.reconcile.transfer",
        "huawei.reconcile.startup",
        "huawei.reconcile.reboot",
        "huawei.reconcile.online",
        "huawei.reconcile.rollback",
    ):
        registry.register(
            HuaweiVrpReconcileProvider(provider_id, execution, control),
            item_id=provider_id,
        )
    return registry


def _target_for_run(run: WorkflowRun) -> DeviceTarget:
    target = run.context.get("target")
    target_dict = target if isinstance(target, dict) else {}
    return DeviceTarget(
        device_id=str(target_dict.get("device_id") or run.device_id),
        session_id=str(target_dict.get("session_id") or run.context.get("session_id") or ""),
        protocol=str(target_dict.get("protocol") or run.context.get("protocol") or "auto"),
    )


def _control_context(run: WorkflowRun, action: ActionSpec) -> ControlContext:
    return ControlContext(
        source="framework.reconcile",
        task_id=run.id,
        step_id=action.id,
        lease_token=str(run.context.get("lease_token") or ""),
    )


def _last_operation_id(run: WorkflowRun, action_id: str) -> str:
    for attempt in reversed(run.attempts):
        if attempt.action_id != action_id:
            continue
        result = attempt.result
        direct = str(result.get("operation_id") or "").strip()
        if direct:
            return direct
        nested = result.get("data")
        if isinstance(nested, dict):
            return str(nested.get("operation_id") or "").strip()
    return ""


def _action_facts(run: WorkflowRun, action_id: str) -> dict[str, Any]:
    facts = run.context.get(f"action.{action_id}.facts")
    return dict(facts) if isinstance(facts, dict) else {}


def _previous_startup(run: WorkflowRun) -> dict[str, Any]:
    facts = run.context.get("action.precheck.facts")
    if not isinstance(facts, dict):
        return {}
    startup = facts.get("startup")
    return dict(startup) if isinstance(startup, dict) else {}


__all__ = [
    "DeviceExecutionPort",
    "DeviceControlPort",
    "HuaweiVrpReconcileProvider",
    "build_huawei_reconcile_registry",
]
