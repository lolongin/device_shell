"""Native Huawei VRP implementation of the device Activity port.

The Framework calls this adapter directly in production.  Vendor command
selection and fact parsing live here; orchestration and recovery remain in the
Framework runtime.  A one-argument legacy constructor is retained for old
ActionHandler callers during the compatibility window.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from device_tui.application.device_control import ControlContext, DeviceTarget
from device_tui.application.device_control.protocol import DeviceWorkflowExecutionError
from device_tui.application.errors import ApplicationError
from device_tui.framework import ActionResult, ActionSpec, ActionStatus, ActivityContext, ActivityInvocation, ActivityResult, ActivityStatus, Event
from device_tui.framework.plugins import AdapterRegistry

from .drivers import UpgradeDriverRegistry, UpgradeTargetFacts
from .parsers import (
    CONTROLLER_TOPOLOGY_DUAL, CONTROLLER_TOPOLOGY_SINGLE,
    DEFAULT_MASTER_STORAGE, DEFAULT_SLAVE_STORAGE, STANDBY_STORAGE_NOT_PROBED,
    classify_controller_topology, classify_standby_storage, dir_contains_package,
    package_basename, parse_display_startup, startup_uses_package,
)


@dataclass(frozen=True, slots=True)
class _ExecutionStep:
    """Structural step accepted by DeviceExecutionTool without importing the task package."""

    id: str
    kind: str
    action: str
    params: dict[str, Any]


class HuaweiVrpDeviceVendorAdapter:
    """Execute Huawei-specific Activities through DeviceExecutionTool."""

    id = "huawei.vrp"
    _ACTIVITIES = {"device.probe", "device.storage.cleanup", "device.storage.sync", "device.verify", "device.verify_artifact", "device.startup.configure", "device.startup.rollback"}
    _OPERATIONS = {
        "device.storage.cleanup": "huawei.storage.cleanup",
        "device.storage.sync": "huawei.storage.sync",
        "device.verify_artifact": "device.verify",
        "device.verify": "device.verify",
        "device.startup.configure": "huawei.startup.configure",
        "device.startup.rollback": "huawei.startup.rollback",
    }

    def __init__(self, execution: Any = None, adapters: AdapterRegistry | None = None, transfers: Any = None, drivers: UpgradeDriverRegistry | None = None, *, legacy_handler: Any | None = None) -> None:
        if legacy_handler is not None:
            execution = legacy_handler
        # Historical callers pass the old ActionHandler as the sole argument.
        self._legacy = execution if not callable(getattr(execution, "execute_operation", None)) else None
        self._execution = None if self._legacy is not None else execution
        self._adapters = adapters
        self._transfers = transfers
        self._drivers = drivers or UpgradeDriverRegistry()

    async def execute_activity(self, activity_id: str, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        if activity_id not in self._ACTIVITIES:
            return ActivityResult(status=ActivityStatus.FAILED, error={"code": "unsupported_vendor_activity", "message": f"Huawei adapter does not support {activity_id}.", "class": "deterministic"})
        if self._legacy is not None:
            return await self._execute_legacy(activity_id, invocation, context, report)
        try:
            data = await self._execute_native(activity_id, invocation, context, report)
            return ActivityResult(status=ActivityStatus.SUCCEEDED, outputs=data, evidence=tuple(x for x in data.get("evidence", ()) if isinstance(x, dict)), operation_id=str(data.get("operation_id") or data.get("execution_id") or ""))
        except asyncio.CancelledError:
            raise
        except DeviceWorkflowExecutionError as exc:
            uncertain = activity_id in {"device.startup.configure", "device.startup.rollback"} and (exc.error_class in {"unknown", "timeout", "transient", "connection"} or any(x in exc.code.casefold() for x in ("timeout", "disconnect", "connection", "interrupted")))
            return ActivityResult(status=ActivityStatus.UNKNOWN if uncertain else ActivityStatus.FAILED, outputs=dict(exc.details), evidence=({"kind": "huawei_activity_error", "activity_id": activity_id, "code": exc.code},), error={"code": exc.code, "message": str(exc), "class": exc.error_class, "retryable": exc.retryable})
        except Exception as exc:
            return ActivityResult(status=ActivityStatus.FAILED, evidence=({"kind": "huawei_activity_error", "activity_id": activity_id},), error={"code": "huawei_activity_failed", "message": str(exc), "class": "unknown"})

    async def cancel_activity(self, activity_id: str, invocation: ActivityInvocation, context: ActivityContext) -> None:
        if self._legacy is not None:
            operation = self._OPERATIONS.get(activity_id)
            if operation:
                await self._legacy.cancel(ActionSpec(id=activity_id, operation=operation, params=dict(invocation.inputs)), context.workflow_run)
        elif self._execution is not None:
            self._execution.cancel_target(self._target(context.workflow_run))

    async def _execute_legacy(self, activity_id: str, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> ActivityResult:
        operation = self._OPERATIONS.get(activity_id)
        if not operation:
            return ActivityResult(status=ActivityStatus.FAILED, error={"code": "unsupported_vendor_activity"})
        action = ActionSpec(id=activity_id, operation=operation, params=dict(invocation.inputs), timeout_seconds=float(invocation.inputs.get("activity_timeout_seconds") or invocation.inputs.get("timeout_seconds") or 30))
        try:
            result: ActionResult = await self._legacy.execute(action, context.workflow_run, report)
        except Exception as exc:
            code = str(getattr(exc, "code", "activity_failed")); error_class = str(getattr(exc, "error_class", "unknown"))
            uncertain = operation in {"huawei.startup.configure", "huawei.startup.rollback"} and (error_class in {"unknown", "timeout", "transient", "connection"} or "timeout" in code.casefold() or "disconnect" in code.casefold())
            return ActivityResult(status=ActivityStatus.UNKNOWN if uncertain else ActivityStatus.FAILED, error={"code": code, "message": str(exc), "class": error_class, "retryable": bool(getattr(exc, "retryable", False))})
        outputs = dict(result.facts)
        return ActivityResult(status={ActionStatus.SUCCEEDED: ActivityStatus.SUCCEEDED, ActionStatus.FAILED: ActivityStatus.FAILED, ActionStatus.UNKNOWN: ActivityStatus.UNKNOWN, ActionStatus.CANCELLED: ActivityStatus.CANCELLED}.get(str(result.status), ActivityStatus.FAILED), outputs=outputs, evidence=tuple(x for x in outputs.get("evidence", ()) if isinstance(x, dict)), operation_id=str(outputs.get("operation_id") or outputs.get("execution_id") or ""), error=result.error)

    @staticmethod
    def _normalize(result: ActionResult) -> ActivityResult:
        """Normalize a legacy ActionResult for historical adapter callers."""
        outputs = dict(result.facts)
        operation_id = str(outputs.get("operation_id") or outputs.get("execution_id") or "")
        evidence = tuple(x for x in (outputs.get("evidence") or ()) if isinstance(x, dict))
        status = {
            ActionStatus.SUCCEEDED: ActivityStatus.SUCCEEDED,
            ActionStatus.FAILED: ActivityStatus.FAILED,
            ActionStatus.UNKNOWN: ActivityStatus.UNKNOWN,
            ActionStatus.CANCELLED: ActivityStatus.CANCELLED,
        }.get(str(result.status), ActivityStatus.FAILED)
        return ActivityResult(status=status, outputs=outputs, evidence=evidence, operation_id=operation_id, error=result.error)

    async def _execute_native(self, activity_id: str, invocation: ActivityInvocation, context: ActivityContext, report: Any) -> dict[str, Any]:
        run = context.workflow_run; params = dict(invocation.inputs); target = self._target(run); driver = self._driver(params, run)
        control_context = ControlContext(source=str(invocation.context.get("source") or "framework"), request_id=str(invocation.context.get("request_id") or invocation.invocation_id), task_id=str(invocation.context.get("task_id") or run.id), step_id=activity_id, lease_token=str(invocation.context.get("lease_token") or ""), actor=str(invocation.context.get("actor") or ""))
        report(self._event("huawei.activity.sent", invocation, {"operation": self._OPERATIONS.get(activity_id, activity_id)}))
        if activity_id == "device.startup.configure":
            # Kept as a durable compatibility fact because the package-upgrade
            # workflow uses it as the command-dispatch boundary.
            report(self._event("framework.action.sent", invocation, {"operation": "huawei.startup.configure"}))
        if activity_id == "device.probe":
            commands = driver.probe_commands(tuple(params.get("probes", ())), master_storage=str(params.get("master_storage") or DEFAULT_MASTER_STORAGE), slave_storage=str(params.get("slave_storage") or DEFAULT_SLAVE_STORAGE))
            data = await self._run_step(target, activity_id, "precheck", {**params, "commands": commands}, control_context)
            data = await self._probe_standby(data, params, driver, target, control_context, invocation, report)
            facts = self._probe_facts(data, params, driver)
            if facts["topology_detection"]["effective_mode"] == "indeterminate":
                raise DeviceWorkflowExecutionError("topology_indeterminate", "无法根据设备角色和备控存储证据确认双主控拓扑。", error_class="ambiguous", details=facts)
            report(self._event("huawei.cli.ready", invocation, {"output_present": bool(data.get("output"))}))
            report(self._event("huawei.device.facts.collected", invocation, {"facts": facts}, progress=True))
            return {**data, **facts}
        if activity_id == "device.storage.cleanup":
            commands = self._cleanup_commands(params, run, driver)
            data = await self._run_step(target, activity_id, "command", {**params, "commands": commands}, control_context) if commands else {"status": "completed", "output": "", "data": {"skipped": True}}
            report(self._event("huawei.storage.cleaned", invocation, {"skipped": not bool(commands)})); return data
        if activity_id == "device.storage.sync":
            commands = self._sync_commands(params, run, driver)
            data = await self._run_step(target, activity_id, "command", {**params, "commands": commands}, control_context) if commands else {"status": "completed", "output": "", "data": {"skipped": True}}
            report(self._event("huawei.storage.synced", invocation, {"skipped": not bool(commands)})); return data
        if activity_id in {"device.verify", "device.verify_artifact"}:
            fact = str(params.get("fact") or "package"); data = await self._run_step(target, activity_id, "verify", {**params, "commands": params.get("commands") or driver.verification_commands(fact)}, control_context); output = str(data.get("output") or ""); expected = str(params.get("expected") or params.get("package") or "")
            if not self._verify_artifact(output, fact, expected, params):
                raise DeviceWorkflowExecutionError("verification_failed", f"Verification did not confirm {expected or fact}.", error_class="deterministic", details={"output": output, "expected": expected, "fact": fact})
            event_type = {
                "package": "huawei.package.verified",
                "running_version": "huawei.version.match",
                "startup_package": "huawei.startup.package.match",
                "validation": "huawei.validation.passed",
            }.get(fact, "huawei.verification.passed")
            report(self._event(event_type, invocation, {"fact": fact}, progress=True)); return data
        if activity_id == "device.startup.configure":
            package = package_basename(str(params.get("package") or ""))
            if not package: raise DeviceWorkflowExecutionError("startup_package_missing", "Startup configuration requires a package name.", error_class="deterministic")
            master = driver.package_path(str(params.get("master_storage") or DEFAULT_MASTER_STORAGE), package); standby = driver.package_path(str(params.get("slave_storage") or DEFAULT_SLAVE_STORAGE), package)
            primary, _fallback = driver.activation_commands(master, standby, self._include_slave(run, params))
            timeout = max(1, int(float(params.get("activity_timeout_seconds") or params.get("timeout_seconds") or 120)))
            command_data = await self._run_step(target, activity_id, "activate", {**params, "mode": "interactive", "steps": self._interactive_steps(primary), "total_timeout_seconds": timeout}, control_context)
            readback = await self._run_step(target, f"{activity_id}.readback", "verify", {"commands": (driver.startup_query_command(),), "timeout_seconds": 30}, control_context); startup_output = str(readback.get("output") or "")
            if not driver.startup_uses_artifact(startup_output, package): raise DeviceWorkflowExecutionError("startup_verification_failed", f"display startup did not confirm {package!r} as the next startup system software.", error_class="deterministic", details={"expected_package": package, "startup_output": startup_output})
            report(self._event("huawei.startup.command.completed", invocation, {"execution_id": command_data.get("execution_id", "")})); report(self._event("huawei.startup.verified", invocation, {"package": package}, progress=True))
            return {**command_data, "output": "\n".join(x for x in (command_data.get("output"), startup_output) if x), "startup_output": startup_output, "startup_verified": True, "evidence": list(command_data.get("evidence") or ()) + list(readback.get("evidence") or ()) + [{"kind": "startup_readback", "expected_package": package, "verified": True}]}
        if activity_id == "device.startup.rollback":
            command = str(params.get("rollback_command") or "").strip()
            if not command:
                precheck = run.context.get("action.precheck.facts", {}); startup = precheck.get("startup", {}) if isinstance(precheck, dict) else {}; previous = str(startup.get("current_system") or "").strip()
                if not previous: raise DeviceWorkflowExecutionError("rollback_state_unknown", "The pre-upgrade startup package could not be confirmed; rollback needs an explicit operator decision.", error_class="ambiguous")
                command = driver.rollback_command(previous)
            data = await self._run_step(target, activity_id, "command", {**params, "commands": (command,)}, control_context); report(self._event("huawei.rollback.verified", invocation, {"command": command}, progress=True)); return data
        raise DeviceWorkflowExecutionError("unsupported_vendor_activity", f"No native Huawei implementation for {activity_id}.")

    async def _run_step(self, target: DeviceTarget, step_id: str, action: str, params: dict[str, Any], control_context: ControlContext) -> dict[str, Any]:
        if self._execution is None: raise DeviceWorkflowExecutionError("execution_unavailable", "Huawei Activity execution is not configured.")
        execute_operation = getattr(self._execution, "execute_operation", None)
        if callable(execute_operation):
            result = dict(await execute_operation(target, action, params, context=control_context))
        else:
            result = dict(await self._execution.execute(target, _ExecutionStep(step_id, kind="device", action=action, params=params), context=control_context))
        if str(result.get("status") or "completed").casefold() not in {"success", "succeeded", "completed", "ok", "ready"}:
            raise DeviceWorkflowExecutionError(str(result.get("error_code") or result.get("status") or "device_operation_failed"), str(result.get("output") or "Device operation failed."))
        return result

    async def _probe_standby(self, data: dict[str, Any], params: dict[str, Any], driver: Any, target: DeviceTarget, control_context: ControlContext, invocation: ActivityInvocation, report: Any) -> dict[str, Any]:
        output = str(data.get("output") or "")
        if str(params.get("topology_policy") or "auto").casefold() == "single" or classify_controller_topology(output) != CONTROLLER_TOPOLOGY_DUAL: return data
        storage = str(params.get("slave_storage") or DEFAULT_SLAVE_STORAGE); standby = await self._run_step(target, f"{invocation.activity_id}.standby_storage", "command", {"commands": (driver.storage_query_command(storage),), "timeout_seconds": 60}, control_context)
        report(self._event("huawei.topology.standby_storage.probed", invocation, {"storage": storage, "output_present": bool(standby.get("output"))}, progress=True))
        return {**data, "output": f"{output}\n{standby.get('output', '')}", "standby_storage_output": standby.get("output", ""), "evidence": list(data.get("evidence") or ()) + list(standby.get("evidence") or ())}

    def _probe_facts(self, data: dict[str, Any], params: dict[str, Any], driver: Any) -> dict[str, Any]:
        output = str(data.get("output") or ""); controller = classify_controller_topology(output); slave_storage = str(params.get("slave_storage") or DEFAULT_SLAVE_STORAGE); standby_output = str(data.get("standby_storage_output") or ""); standby = classify_standby_storage(standby_output, slave_storage) if controller == CONTROLLER_TOPOLOGY_DUAL else STANDBY_STORAGE_NOT_PROBED; policy = str(params.get("topology_policy") or "auto").casefold(); effective = "single_controller" if policy == "single" or controller == CONTROLLER_TOPOLOGY_SINGLE else "dual_controller" if controller == CONTROLLER_TOPOLOGY_DUAL and standby == "available" else "indeterminate"
        facts: dict[str, Any] = {"topology_detection": {"policy": policy, "controller_status": controller, "master_storage": str(params.get("master_storage") or DEFAULT_MASTER_STORAGE), "standby_storage": slave_storage, "standby_status": standby, "effective_mode": effective, "include_slave": effective == "dual_controller", "decision": effective}}
        startup = parse_display_startup(output)
        if startup.current_system or startup.next_system: facts["startup"] = {"current_system": startup.current_system, "next_system": startup.next_system}
        package = str(params.get("package") or "").strip()
        if package and str(params.get("package_source") or "local").casefold() == "local":
            name = PurePosixPath(package.replace("\\", "/")).name; size = 0
            if self._transfers is not None:
                try: size = int(self._transfers.resolve_source(package).size_bytes)
                except (ApplicationError, OSError, ValueError): pass
            storage = str(params.get("master_storage") or DEFAULT_MASTER_STORAGE); facts["package"] = {"name": name, "storage": storage, "size_bytes": size, "present": driver.package_is_present(self._storage_output(output, storage), storage=storage, package_name=name, package_size=size)}
            if effective == "dual_controller": facts["standby_package"] = {"name": name, "storage": slave_storage, "size_bytes": size, "present": dir_contains_package(standby_output, storage=slave_storage, package_name=name)}
        return facts

    def _cleanup_commands(self, params: dict[str, Any], run: Any, driver: Any) -> tuple[str, ...]:
        package = str(params.get("package") or ""); name = PurePosixPath(package.replace("\\", "/")).name; size = 0
        if str(params.get("package_source") or "local").casefold() == "local" and self._transfers is not None: size = int(self._transfers.resolve_source(package).size_bytes)
        facts = run.context.get("action.precheck.facts", {}); output = str(facts.get("output") or "") if isinstance(facts, dict) else ""; startup = str(facts.get("startup_output") or output) if isinstance(facts, dict) else output; topology = facts.get("topology_detection", {}) if isinstance(facts, dict) else {}; include_slave = bool(topology.get("include_slave", params.get("include_slave", True))) if isinstance(topology, dict) else bool(params.get("include_slave", True)); commands: list[str] = []
        for label, storage in (("master", params.get("master_storage") or DEFAULT_MASTER_STORAGE), ("slave", params.get("slave_storage") or DEFAULT_SLAVE_STORAGE)):
            if label == "slave" and not include_slave: continue
            plan = driver.cleanup_plan(storage=str(storage), output=self._storage_output(output, str(storage)), startup_output=startup, package_name=name, package_size=size)
            if not plan.has_enough_space: raise DeviceWorkflowExecutionError("insufficient_space", f"{label} storage is insufficient for the package.", error_class="deterministic")
            if plan.delete_paths and not bool(params.get("auto_delete_old_packages", False)): raise DeviceWorkflowExecutionError("cleanup_required", f"{label} storage requires cleanup before transfer.", error_class="deterministic")
            commands.extend(driver.cleanup_command(path) for path in plan.delete_paths)
        return tuple(commands)

    @staticmethod
    def _sync_commands(params: dict[str, Any], run: Any, driver: Any) -> tuple[str, ...]:
        facts = run.context.get("action.precheck.facts", {}); topology = facts.get("topology_detection", {}) if isinstance(facts, dict) else {}
        if not bool(topology.get("include_slave", False)): return ()
        standby = facts.get("standby_package") if isinstance(facts, dict) else None
        if isinstance(standby, dict) and bool(standby.get("present")): return ()
        name = PurePosixPath(str(params.get("package") or "").replace("\\", "/")).name; primary = driver.package_path(str(params.get("master_storage") or DEFAULT_MASTER_STORAGE), name); secondary = driver.package_path(str(params.get("slave_storage") or DEFAULT_SLAVE_STORAGE), name); return driver.sync_commands(primary, secondary)

    @staticmethod
    def _verify_artifact(output: str, fact: str, expected: str, params: dict[str, Any]) -> bool:
        if fact == "startup_package": return bool(expected and startup_uses_package(output, expected))
        if fact == "package":
            name = PurePosixPath((expected or str(params.get("package") or "")).replace("\\", "/")).name; return bool(name and name.casefold() in output.replace("\\", "/").casefold())
        return bool(expected and expected.casefold() in output.casefold()) if expected else bool(output.strip())

    def _driver(self, params: dict[str, Any], run: Any) -> Any:
        facts = dict(run.context.get("device_facts") or {}); target = self._target(run); return self._drivers.resolve(UpgradeTargetFacts(target.device_id, str(facts.get("vendor") or ""), str(facts.get("model") or ""), str(facts.get("platform") or "")), str(params.get("driver_id") or "auto"))

    @staticmethod
    def _target(run: Any) -> DeviceTarget:
        values = run.context.get("target"); values = values if isinstance(values, dict) else {}; return DeviceTarget(device_id=str(values.get("device_id") or run.device_id), session_id=str(values.get("session_id") or run.context.get("session_id") or ""), protocol=str(values.get("protocol") or run.context.get("protocol") or "auto"))

    @staticmethod
    def _include_slave(run: Any, params: dict[str, Any]) -> bool:
        facts = run.context.get("action.precheck.facts", {}); topology = facts.get("topology_detection", {}) if isinstance(facts, dict) else {}; return bool(topology.get("include_slave", params.get("include_slave", True)))

    @staticmethod
    def _interactive_steps(commands: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
        return tuple({"type": "send", "text": command, "label": command} for command in commands) + ({"type": "expect", "success": ["device_prompt"], "failures": ["Error:", "Failed", "Failure", "not found", "invalid", "denied", "refused"], "responses": [{"match": "confirmation_prompt", "text": "y", "max_matches": 3}], "timeout_seconds": 120, "label": "等待命令完成"},)

    @staticmethod
    def _storage_output(output: str, storage: str) -> str:
        marker = f"directory of {storage.rstrip('/')}".casefold(); lowered = output.casefold(); start = lowered.find(marker)
        if start < 0: return output
        end = lowered.find("directory of ", start + len(marker)); return output[start:end if end >= 0 else len(output)]

    @staticmethod
    def _event(event_type: str, invocation: ActivityInvocation, payload: dict[str, Any], *, progress: bool = False) -> Event:
        return Event(type=event_type, run_id=invocation.workflow_run_id, action_id=invocation.activity_id, source="huawei.vrp.activity", payload=payload, progress=progress)


__all__ = ["HuaweiVrpDeviceVendorAdapter"]
