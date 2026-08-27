"""Bridge framework actions to the existing device-control execution stack.

This module is intentionally an adapter, not a second device executor.  The
legacy ``DeviceExecutionTool`` remains the compatibility-facing translation to
``DeviceControlService`` while the framework owns action identity, events,
watchdogs, reconciliation, and decisions.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Any

from device_tui.application.device_control import ControlContext, DeviceControlService, DeviceTarget
from device_tui.application.errors import ApplicationError
from device_tui.application.tasking.execution import (
    DeviceExecutionTool,
    DeviceWorkflowExecutionError,
)
from device_tui.application.tasking.models import WorkflowStep
from device_tui.application.upgrades.commands import HuaweiVrpCommandSet
from device_tui.application.upgrades.drivers import UpgradeDriverRegistry, UpgradeTargetFacts
from device_tui.application.upgrades.package import (
    DEFAULT_MASTER_STORAGE,
    DEFAULT_SLAVE_STORAGE,
    CONTROLLER_TOPOLOGY_DUAL,
    CONTROLLER_TOPOLOGY_SINGLE,
    STANDBY_STORAGE_NOT_PROBED,
    classify_controller_topology,
    build_cleanup_plan,
    classify_standby_storage,
    find_free_space_bytes,
    parse_dir_entries,
    package_basename,
    parse_display_startup,
    startup_uses_package,
)

from .events import Event
from .models import (
    ActionResult,
    ActionSpec,
    ActionStatus,
    ReconcileClassification,
    ReconcileResult,
    WorkflowRun,
)
from .plugins import ActionRegistry, AdapterRegistry, ReconcileRegistry


class DeviceExecutionActionHandler:
    """Execute one framework operation through the existing device facade."""

    def __init__(
        self,
        execution: DeviceExecutionTool,
        adapters: AdapterRegistry,
        transfers: Any = None,
        drivers: UpgradeDriverRegistry | None = None,
    ) -> None:
        self._execution = execution
        self._adapters = adapters
        self._transfers = transfers
        self._drivers = drivers or UpgradeDriverRegistry()

    async def execute(self, action: ActionSpec, run: WorkflowRun, emit: Any) -> ActionResult:
        step = await self._legacy_step(action, run)
        target = _target_for_run(run)
        context = ControlContext(
            source="framework",
            task_id=run.id,
            step_id=action.id,
            lease_token=str(run.context.get("lease_token") or ""),
        )
        emitted: set[str] = set()

        def publish(event: Event) -> None:
            key = f"{event.type}:{event.payload.get('status', '')}"
            if key in emitted:
                return
            emitted.add(key)
            emit(event)

        publish(Event(
            type="framework.action.sent",
            run_id=run.id,
            action_id=action.id,
            source="device.bridge",
        ))
        if action.operation == "file.transfer" and self._package_already_present(run, action):
            data = {
                "status": "completed",
                "output": "目标系统包已存在，跳过重复传输。",
                "data": {"skipped": True, "reason": "package_already_present"},
            }
        elif action.operation in {"huawei.storage.cleanup", "huawei.storage.sync"} and not step.params.get("commands"):
            data = {"status": "completed", "output": "", "data": {"skipped": True}}
        else:
            data = await self._execution.execute(target, step, context=context)
        if action.operation == "device.probe":
            data = await self._probe_confirmed_standby_storage(action, run, target, context, data, publish)
        if action.operation == "huawei.startup.configure":
            publish(Event(
                type="huawei.startup.command.completed",
                run_id=run.id,
                action_id=action.id,
                source="device.bridge",
                payload={"execution_id": data.get("execution_id", "")},
            ))
            data = await self._verify_startup_configuration(action, run, target, context, data)
        if action.operation == "file.transfer":
            operation_id = str(data.get("operation_id") or "").strip()
            if operation_id:
                publish(Event(
                    type="huawei.transfer.started",
                    run_id=run.id,
                    action_id=action.id,
                    source="device.bridge",
                    progress=True,
                    payload={"operation_id": operation_id},
                ))
                data = {
                    **data,
                    **await self._wait_for_operation(operation_id, action.timeout_seconds, run, action, publish),
                }
        output = str(data.get("output") or "")
        facts = self._facts(action, data, output, run)
        topology = facts.get("topology_detection")
        if (
            action.operation == "device.probe"
            and isinstance(topology, dict)
            and topology.get("effective_mode") == "indeterminate"
        ):
            return ActionResult(
                status=ActionStatus.FAILED,
                events=(),
                facts=facts,
                error={
                    "code": "topology_indeterminate",
                    "message": "无法根据设备角色和备控存储证据确认双主控拓扑。",
                    "class": "ambiguous",
                },
            )
        if action.operation == "device.verify" and not self._verification_confirmed(action, output):
            expected = str(action.params.get("expected") or "").strip()
            return ActionResult(
                status=ActionStatus.FAILED,
                events=(),
                facts=facts,
                error={
                    "code": "verification_failed",
                    "message": f"Verification did not confirm {expected or action.params.get('fact', 'the expected state') }.",
                    "class": "deterministic",
                },
            )
        # Success events are facts consumed by the runtime. Do not publish
        # them for an action whose deterministic verification has failed.
        for event in self._parse_output(output, run, action):
            publish(event)
        for event in self._semantic_events(action, run, data, output):
            publish(event)
        return ActionResult(
            status=ActionStatus.SUCCEEDED,
            events=(),
            facts=facts,
        )

    async def _verify_startup_configuration(
        self,
        action: ActionSpec,
        run: WorkflowRun,
        target: DeviceTarget,
        context: ControlContext,
        command_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Read back ``display startup`` before treating activation as successful."""
        driver = self._driver(action, run)
        package = package_basename(str(action.params.get("package") or ""))
        if not package:
            raise DeviceWorkflowExecutionError(
                "startup_package_missing",
                "Startup configuration requires the target package name.",
                error_class="deterministic",
            )
        readback = await self._execution.execute(
            target,
            WorkflowStep(
                f"{action.id}.readback",
                kind="device",
                action="command",
                params={
                    "commands": (driver.startup_query_command(),),
                    "timeout_seconds": min(30, max(1, int(action.timeout_seconds))),
                },
            ),
            context=context,
        )
        startup_output = str(readback.get("output") or "")
        if not driver.startup_uses_artifact(startup_output, package):
            raise DeviceWorkflowExecutionError(
                "startup_verification_failed",
                f"display startup did not confirm {package!r} as the next startup system software.",
                error_class="deterministic",
                details={"expected_package": package, "startup_output": startup_output},
            )
        command_output = str(command_data.get("output") or "")
        evidence = list(command_data.get("evidence") or ())
        evidence.extend(readback.get("evidence") or ())
        evidence.append({
            "kind": "startup_readback",
            "command": driver.startup_query_command(),
            "expected_package": package,
            "verified": True,
        })
        return {
            **command_data,
            "output": "\n".join(item for item in (command_output, startup_output) if item),
            "startup_output": startup_output,
            "startup_verified": True,
            "evidence": tuple(evidence),
        }

    async def cancel(self, action: ActionSpec, run: WorkflowRun) -> None:
        """Request cancellation through the existing control-plane facade."""
        del action
        self._execution.cancel_target(_target_for_run(run))

    def _facts(
        self,
        action: ActionSpec,
        data: dict[str, Any],
        output: str,
        run: WorkflowRun,
    ) -> dict[str, Any]:
        facts: dict[str, Any] = {
            "status": data.get("status", "completed"),
            "output": output,
            "session_id": data.get("session_id") or "",
            "device_id": data.get("device_id") or "",
            "operation_id": data.get("operation_id") or "",
            "data": dict(data.get("data") or {}),
            "evidence": list(data.get("evidence") or ()),
        }
        if action.operation == "device.probe":
            startup = parse_display_startup(output)
            if startup.current_system or startup.next_system:
                facts["startup"] = {
                    "current_system": startup.current_system,
                    "next_system": startup.next_system,
                }
            slave_storage = str(action.params.get("slave_storage") or DEFAULT_SLAVE_STORAGE)
            controller_status = classify_controller_topology(output)
            slave_output = str(data.get("standby_storage_output") or "")
            standby_status = (
                classify_standby_storage(slave_output, slave_storage)
                if controller_status == CONTROLLER_TOPOLOGY_DUAL
                else STANDBY_STORAGE_NOT_PROBED
            )
            policy = str(action.params.get("topology_policy") or "auto").casefold()
            effective_mode = (
                "single_controller"
                if policy == "single" or controller_status == CONTROLLER_TOPOLOGY_SINGLE
                else "dual_controller"
                if controller_status == CONTROLLER_TOPOLOGY_DUAL and standby_status == "available"
                else "indeterminate"
            )
            facts["topology_detection"] = {
                "policy": policy,
                "controller_status": controller_status,
                "master_storage": str(action.params.get("master_storage") or DEFAULT_MASTER_STORAGE),
                "standby_storage": slave_storage,
                "standby_status": standby_status,
                "effective_mode": effective_mode,
                "include_slave": effective_mode == "dual_controller",
                "decision": effective_mode,
            }
            package = str(action.params.get("package") or "").strip()
            if package and str(action.params.get("package_source") or "local").casefold() == "local":
                package_name = PurePosixPath(package.replace("\\", "/")).name
                package_size = 0
                if self._transfers is not None:
                    try:
                        package_size = int(self._transfers.resolve_source(package).size_bytes)
                    except (ApplicationError, OSError, ValueError):
                        package_size = 0
                driver = self._driver(action, run)
                master_storage = str(action.params.get("master_storage") or DEFAULT_MASTER_STORAGE)
                master_output = _extract_storage_output(output, master_storage)
                facts["package"] = {
                    "name": package_name,
                    "storage": master_storage,
                    "size_bytes": package_size,
                    "present": driver.package_is_present(
                        master_output,
                        storage=master_storage,
                        package_name=package_name,
                        package_size=package_size,
                    ),
                }
                if bool(facts.get("topology_detection", {}).get("include_slave")):
                    standby_storage = str(action.params.get("slave_storage") or DEFAULT_SLAVE_STORAGE)
                    standby_output = str(data.get("standby_storage_output") or "")
                    facts["standby_package"] = {
                        "name": package_name,
                        "storage": standby_storage,
                        "size_bytes": package_size,
                        "present": driver.package_is_present(
                            standby_output,
                            storage=standby_storage,
                            package_name=package_name,
                            package_size=package_size,
                        ),
                    }
        if action.operation == "device.reboot":
            facts["reboot"] = {
                "command_sent": bool(data.get("reboot_command_sent", False)),
                "disconnect_observed": bool(data.get("reboot_disconnect_observed", False)),
            }
        if action.operation == "huawei.startup.configure":
            startup = parse_display_startup(str(data.get("startup_output") or output))
            facts["startup"] = {
                "current_system": startup.current_system,
                "next_system": startup.next_system,
                "verified": bool(data.get("startup_verified", False)),
            }
        if action.operation == "device.wait_online":
            facts["readiness"] = {
                "transport_status": str(data.get("transport_status") or "unknown"),
                "cli_status": str(data.get("cli_status") or "unknown"),
                "probe_command": str(data.get("probe_command") or ""),
                "probe_execution_id": str(data.get("probe_execution_id") or ""),
            }
        return facts

    async def _probe_confirmed_standby_storage(
        self,
        action: ActionSpec,
        run: WorkflowRun,
        target: DeviceTarget,
        context: ControlContext,
        data: dict[str, Any],
        publish: Any,
    ) -> dict[str, Any]:
        """Probe standby storage only after the device table confirms a standby."""
        output = str(data.get("output") or "")
        topology = classify_controller_topology(output)
        policy = str(action.params.get("topology_policy") or "auto").casefold()
        if policy == "single" or topology != CONTROLLER_TOPOLOGY_DUAL:
            return data
        storage = str(action.params.get("slave_storage") or DEFAULT_SLAVE_STORAGE)
        probe = WorkflowStep(
            f"{action.id}.standby_storage",
            kind="device",
            action="command",
            params={
                "commands": (self._driver(action, run).storage_query_command(storage),),
                "timeout_seconds": min(60, int(action.timeout_seconds)),
            },
        )
        standby_data = await self._execution.execute(target, probe, context=context)
        standby_output = str(standby_data.get("output") or "")
        publish(Event(
            type="huawei.topology.standby_storage.probed",
            run_id=run.id,
            action_id=action.id,
            source="device.bridge",
            progress=True,
            payload={"storage": storage, "output_present": bool(standby_output)},
        ))
        return {
            **data,
            "output": f"{output}\n{standby_output}",
            "standby_storage_output": standby_output,
            "evidence": list(data.get("evidence") or ()) + list(standby_data.get("evidence") or ()),
        }

    async def _wait_for_operation(
        self,
        operation_id: str,
        timeout_seconds: float,
        run: WorkflowRun,
        action: ActionSpec,
        publish: Any,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + max(1.0, timeout_seconds)
        last_progress_signature: tuple[object, ...] | None = None
        while True:
            snapshot = self._execution.get_resource("operation", operation_id)
            status = str(snapshot.get("status") or "").casefold()
            progress_signature = (
                snapshot.get("revision"),
                status,
                snapshot.get("stage", ""),
                snapshot.get("bytes_transferred"),
                snapshot.get("progress_percent"),
            )
            if progress_signature != last_progress_signature:
                last_progress_signature = progress_signature
                publish(Event(
                    type="huawei.transfer.progress",
                    run_id=run.id,
                    action_id=action.id,
                    source="device.bridge",
                    progress=True,
                    payload={
                        "operation_id": operation_id,
                        "status": status,
                        "stage": snapshot.get("stage", ""),
                        "revision": snapshot.get("revision", 0),
                        "bytes_transferred": snapshot.get("bytes_transferred", 0),
                        "total_bytes": snapshot.get("total_bytes", 0),
                        "progress_percent": snapshot.get("progress_percent", 0),
                    },
                ))
            if status in {"completed", "success", "succeeded"}:
                publish(Event(
                    type="huawei.transfer.completed",
                    run_id=run.id,
                    action_id=action.id,
                    source="device.bridge",
                    progress=True,
                    payload={"operation_id": operation_id, "status": status},
                ))
                return snapshot
            if status in {"failed", "cancelled", "canceled", "interrupted", "timeout", "timed_out"}:
                raise DeviceWorkflowExecutionError(
                    str(snapshot.get("error_code") or status),
                    str(snapshot.get("message") or "File transfer failed."),
                    error_class="timeout" if "timeout" in status else "unknown",
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise DeviceWorkflowExecutionError(
                    "transfer_timeout",
                    "File transfer did not complete before the action timeout.",
                    error_class="timeout",
                )
            await asyncio.sleep(0.1)

    @staticmethod
    def _verification_confirmed(action: ActionSpec, output: str) -> bool:
        expected = str(action.params.get("expected") or "").strip()
        fact = str(action.params.get("fact") or "").casefold()
        if fact == "package" and expected:
            normalized_expected = expected.replace("\\", "/").rstrip("/").casefold()
            expected_name = PurePosixPath(normalized_expected).name
            haystack = output.replace("\\", "/").casefold()
            return bool(expected_name and expected_name in haystack)
        if expected:
            return expected.casefold() in output.casefold()
        if fact == "package":
            package = str(action.params.get("expected") or action.params.get("package") or "").strip()
            package_name = PurePosixPath(package.replace("\\", "/").rstrip("/")).name
            return bool(package_name and package_name.casefold() in output.replace("\\", "/").casefold())
        return bool(output.strip())

    def _package_already_present(self, run: WorkflowRun, action: ActionSpec) -> bool:
        if str(action.params.get("package_source") or "local").casefold() != "local":
            return False
        precheck = run.context.get("action.precheck.facts")
        if not isinstance(precheck, dict):
            return False
        output = str(precheck.get("output") or "")
        package = PurePosixPath(
            str(action.params.get("source") or action.params.get("package") or "")
            .replace("\\", "/")
        ).name.casefold()
        if not package:
            return False
        package_size = 0
        if self._transfers is not None:
            try:
                package_size = int(self._transfers.resolve_source(str(action.params.get("package") or package)).size_bytes)
            except (ApplicationError, OSError, ValueError):
                package_size = 0
        driver = self._driver(action, run)
        storage = str(action.params.get("master_storage") or DEFAULT_MASTER_STORAGE)
        scoped_output = _extract_storage_output(output, storage)
        return driver.package_is_present(
            scoped_output,
            storage=storage,
            package_name=package,
            package_size=package_size,
        )

    def _parse_output(self, output: str, run: WorkflowRun, action: ActionSpec) -> tuple[Event, ...]:
        if not output:
            return ()
        facts = dict(run.context.get("device_facts") or {})
        try:
            adapter = self._adapters.resolve(facts)
        except LookupError:
            adapters = self._adapters.list()
            adapter = adapters[0] if len(adapters) == 1 else None
        if adapter is None:
            return ()
        return adapter.parse_output(output, run_id=run.id, action_id=action.id)

    @staticmethod
    def _semantic_events(action: ActionSpec, run: WorkflowRun, data: dict[str, Any], output: str) -> tuple[Event, ...]:
        operation = action.operation
        event_types: list[tuple[str, bool]] = []
        if operation == "device.probe":
            event_types.extend((("huawei.cli.ready", False), ("huawei.device.facts.collected", True)))
        elif operation == "file.transfer" and not data.get("operation_id"):
            # Normal transfers publish lifecycle events while their Operation
            # is being observed. A skipped transfer has no Operation, so it
            # completes semantically here instead.
            event_types.extend((("huawei.transfer.started", True), ("huawei.transfer.completed", True)))
        elif operation == "device.verify":
            fact = str(action.params.get("fact") or "")
            event_types.append((
                {
                    "package": "huawei.package.verified",
                    "running_version": "huawei.version.match",
                    "validation": "huawei.validation.passed",
                }.get(fact, "huawei.verification.passed"),
                False,
            ))
        elif operation == "huawei.startup.configure" and data.get("startup_verified"):
            event_types.append(("huawei.startup.verified", False))
        elif operation == "huawei.storage.cleanup":
            event_types.append(("huawei.storage.cleaned", False))
        elif operation == "huawei.storage.sync":
            event_types.append(("huawei.storage.synced", False))
        elif operation == "device.reboot":
            event_types.append(("huawei.reboot.started", False))
        elif operation == "device.wait_online":
            if str(data.get("cli_status") or "").casefold() == "ready":
                event_types.append(("huawei.cli.ready", True))
        elif operation == "huawei.startup.rollback":
            event_types.append(("huawei.rollback.verified", False))
        return tuple(
            Event(
                type=event_type,
                run_id=run.id,
                action_id=action.id,
                source="device.bridge",
                progress=progress,
                payload={"output_present": bool(output), "operation_id": data.get("operation_id", "")},
            )
            for event_type, progress in event_types
        )

    async def _legacy_step(self, action: ActionSpec, run: WorkflowRun) -> WorkflowStep:
        params = dict(action.params)
        for name in ("server_host", "server_port", "ftp_host", "ftp_port", "device_path"):
            if name not in params and name in run.context:
                params[name] = run.context[name]
        params.setdefault("timeout_seconds", max(1, int(action.timeout_seconds)))
        operation = action.operation
        if operation == "device.probe":
            driver = self._driver(action, run)
            params["commands"] = driver.commands.probe_plan(
                tuple(params.get("probes", ())),
                master_storage=str(params.get("master_storage") or DEFAULT_MASTER_STORAGE),
                slave_storage=str(params.get("slave_storage") or DEFAULT_SLAVE_STORAGE),
            ).commands
            return WorkflowStep(action.id, kind="device", action="precheck", params=params)
        if operation == "device.verify":
            fact = str(params.get("fact") or "")
            action_name = "verify_version" if fact == "running_version" else "validation" if fact == "validation" else "verify"
            if "commands" not in params:
                params["commands"] = self._driver(action, run).commands.verification_plan(fact).commands
            return WorkflowStep(action.id, kind="device", action=action_name, params=params)
        if operation == "huawei.startup.configure":
            driver = self._driver(action, run)
            package = str(params.get("package") or "").strip()
            if package:
                # Workflow inputs may be local relative paths. The Huawei
                # startup command needs the device-side artifact path.
                package_name = PurePosixPath(package.replace("\\", "/")).name
                params.setdefault("destination_path", driver.package_path(DEFAULT_MASTER_STORAGE, package_name))
            package_name = PurePosixPath(str(params.get("destination_path") or "").replace("\\", "/")).name
            master_package = driver.package_path(
                str(params.get("master_storage") or DEFAULT_MASTER_STORAGE), package_name,
            )
            slave_package = driver.package_path(
                str(params.get("slave_storage") or DEFAULT_SLAVE_STORAGE), package_name,
            )
            primary_commands, _fallback_commands = driver.activation_commands(
                master_package,
                slave_package,
                bool(self._precheck_topology(run).get("include_slave", False)),
            )
            params["mode"] = "interactive"
            # Interactive terminal execution has its own plan-level deadline.
            # Without an explicit value DeviceControlService defaults it to
            # 60 seconds, which is shorter than the framework action budget
            # and can report a timeout after the device already applied the
            # startup command but before it returned the final prompt.
            params["total_timeout_seconds"] = max(1, int(action.timeout_seconds))
            params["steps"] = _interactive_command_steps(
                primary_commands,
                allow_confirmation=True,
                failures=("Error:", "Failed", "Failure", "not found", "invalid", "denied", "refused"),
            )
            return WorkflowStep(action.id, kind="device", action="activate", params=params)
        if operation == "huawei.storage.cleanup":
            params["commands"] = self._cleanup_commands(action, run)
            return WorkflowStep(action.id, kind="device", action="command", params=params)
        if operation == "huawei.storage.sync":
            params["commands"] = self._sync_commands(action, run)
            return WorkflowStep(action.id, kind="device", action="command", params=params)
        if operation == "huawei.startup.rollback":
            rollback_command = str(params.get("rollback_command") or "").strip()
            if not rollback_command:
                startup = _previous_startup(run)
                current_system = str(startup.get("current_system") or "").strip()
                if not current_system:
                    raise DeviceWorkflowExecutionError(
                        "rollback_state_unknown",
                        "The pre-upgrade startup package could not be confirmed; rollback needs an explicit operator decision.",
                        error_class="ambiguous",
                    )
                rollback_command = self._driver(action, run).rollback_command(current_system)
            params["commands"] = (rollback_command,)
            return WorkflowStep(action.id, kind="device", action="command", params=params)
        if operation == "file.transfer":
            source = str(params.get("source") or params.get("source_path") or "").strip()
            destination = str(params.get("destination") or params.get("device_path") or "").strip()
            if not destination and source:
                destination = self._driver(action, run).package_path(
                    DEFAULT_MASTER_STORAGE,
                    PurePosixPath(source.replace(chr(92), "/")).name,
                )
            protocol = str(params.get("protocol") or "ftp")
            params.update(
                source_path=source,
                destination_path=destination,
                interaction_profile=asdict(self._driver(action, run).transfer_profile(protocol)),
            )
            # ``transfer`` returns the Operation immediately. The framework
            # can then observe progress and enforce milestone deadlines while
            # FTP remains active; ``upload`` waits for completion and hides
            # the started event until it is too late for the watchdog.
            return WorkflowStep(action.id, kind="device", action="transfer", params=params)
        if operation == "device.reboot":
            params.setdefault("steps", list(self._driver(action, run).reboot_plan_steps()))
            return WorkflowStep(action.id, kind="device", action="reboot", params=params)
        if operation == "device.wait_online":
            params.setdefault(
                "readiness_command",
                self._driver(action, run).commands.version_query(),
            )
            reconnect = run.context.get("framework.reconnect")
            if isinstance(reconnect, dict) and reconnect.get("state") == run.current_state:
                params["force_reconnect"] = True
            return WorkflowStep(action.id, kind="device", action="wait_online", params=params)
        raise DeviceWorkflowExecutionError(
            "unsupported_framework_operation",
            f"No device execution bridge is registered for {operation}.",
        )

    def _driver(self, action: ActionSpec, run: WorkflowRun) -> Any:
        facts = dict(run.context.get("device_facts") or {})
        target = _target_for_run(run)
        return self._drivers.resolve(
            UpgradeTargetFacts(
                device_id=target.device_id,
                vendor=str(facts.get("vendor") or ""),
                model=str(facts.get("model") or ""),
                platform=str(facts.get("platform") or ""),
            ),
            str(action.params.get("driver_id") or "auto"),
        )

    @staticmethod
    def _precheck_facts(run: WorkflowRun) -> dict[str, Any]:
        facts = run.context.get("action.precheck.facts")
        return dict(facts) if isinstance(facts, dict) else {}

    def _precheck_topology(self, run: WorkflowRun) -> dict[str, Any]:
        topology = self._precheck_facts(run).get("topology_detection")
        return dict(topology) if isinstance(topology, dict) else {}

    def _cleanup_commands(self, action: ActionSpec, run: WorkflowRun) -> tuple[str, ...]:
        params = action.params
        package = str(params.get("package") or "").strip()
        package_name = PurePosixPath(package.replace("\\", "/")).name
        package_size = 0
        if str(params.get("package_source") or "local") == "local" and self._transfers is not None:
            package_size = int(self._transfers.resolve_source(package).size_bytes)
        output = str(self._precheck_facts(run).get("output") or "")
        startup = str(self._precheck_facts(run).get("startup_output") or output)
        driver = self._driver(action, run)
        topology = self._precheck_topology(run)
        include_slave = bool(topology.get("include_slave", params.get("include_slave", True)))
        commands: list[str] = []
        for label, storage in (
            ("master", params.get("master_storage") or DEFAULT_MASTER_STORAGE),
            ("slave", params.get("slave_storage") or DEFAULT_SLAVE_STORAGE),
        ):
            if label == "slave" and not include_slave:
                continue
            scoped = _extract_storage_output(output, str(storage))
            free_bytes = find_free_space_bytes(scoped)
            if free_bytes is None:
                raise DeviceWorkflowExecutionError(
                    "storage_space_indeterminate",
                    f"Unable to parse {label} storage capacity from its directory response.",
                    error_class="ambiguous",
                )
            plan = build_cleanup_plan(
                storage=str(storage),
                free_bytes=free_bytes,
                target_bytes=package_size,
                entries=parse_dir_entries(scoped, str(storage)),
                startup=parse_display_startup(startup),
                target_package_name=package_name,
            )
            if not plan.has_enough_space:
                raise DeviceWorkflowExecutionError(
                    "insufficient_space",
                    f"{label} storage is insufficient for the package: "
                    f"{plan.free_bytes} bytes free, {plan.required_bytes} bytes required.",
                    error_class="deterministic",
                )
            if plan.delete_entries and not bool(params.get("auto_delete_old_packages", False)):
                raise DeviceWorkflowExecutionError("cleanup_required", f"{label} storage requires cleanup before transfer.")
            commands.extend(driver.cleanup_command(item.path) for item in plan.delete_entries)
        return tuple(commands)

    def _sync_commands(self, action: ActionSpec, run: WorkflowRun) -> tuple[str, ...]:
        if not bool(self._precheck_topology(run).get("include_slave", False)):
            return ()
        standby_package = self._precheck_facts(run).get("standby_package")
        if isinstance(standby_package, dict) and bool(standby_package.get("present")):
            return ()
        params = action.params
        package_name = PurePosixPath(str(params.get("package") or "").replace("\\", "/")).name
        driver = self._driver(action, run)
        primary = driver.package_path(str(params.get("master_storage") or DEFAULT_MASTER_STORAGE), package_name)
        standby = driver.package_path(str(params.get("slave_storage") or DEFAULT_SLAVE_STORAGE), package_name)
        return driver.sync_commands(primary, standby)


class DeviceReconcileProvider:
    """Read-only reconciliation against the same device-control services."""

    def __init__(self, provider_id: str, execution: DeviceExecutionTool, control: DeviceControlService) -> None:
        self.id = provider_id
        self._execution = execution
        self._control = control
        self._commands = HuaweiVrpCommandSet()

    async def reconcile(self, action: ActionSpec, run: WorkflowRun, reason: str, emit: Any) -> ReconcileResult:
        target = _target_for_run(run)
        evidence: list[dict[str, Any]] = [{"reason": reason, "provider": self.id}]
        try:
            if self.id.endswith("online") or action.operation == "device.wait_online":
                view = await self._control.open_session(target, reuse=True, context=_control_context(run, action))
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
                step = WorkflowStep(
                    "reconcile", kind="device", action="verify",
                    params={"commands": (self._commands.startup_query(),)},
                )
                data = await self._execution.execute(target, step, context=_control_context(run, action))
                output = str(data.get("output") or "")
                matched = bool(package and startup_uses_package(output, package))
                evidence.append({"probe": self._commands.startup_query(), "expected_package": package, "matched": matched})
                if matched:
                    return ReconcileResult(ReconcileClassification.SUCCESS, {"output": output}, tuple(evidence))
                return ReconcileResult(ReconcileClassification.INDETERMINATE, {"output": output}, tuple(evidence))
            if self.id.endswith("rollback"):
                expected = package_basename(str(_previous_startup(run).get("current_system") or ""))
                step = WorkflowStep(
                    "reconcile", kind="device", action="verify",
                    params={"commands": (self._commands.startup_query(),)},
                )
                data = await self._execution.execute(target, step, context=_control_context(run, action))
                output = str(data.get("output") or "")
                matched = bool(expected and expected in output.casefold())
                evidence.append({"probe": self._commands.startup_query(), "expected_current_system": expected, "matched": matched})
                if matched:
                    return ReconcileResult(ReconcileClassification.SUCCESS, {"output": output}, tuple(evidence))
                return ReconcileResult(ReconcileClassification.INDETERMINATE, {"output": output}, tuple(evidence))
        except (ApplicationError, OSError, DeviceWorkflowExecutionError, KeyError) as exc:
            evidence.append({"error": str(exc), "error_code": getattr(exc, "code", "reconcile_failed")})
        return ReconcileResult(ReconcileClassification.INDETERMINATE, {}, tuple(evidence))


def build_device_action_registry(execution: DeviceExecutionTool, adapters: AdapterRegistry, transfers: Any = None) -> ActionRegistry:
    registry = ActionRegistry()
    handler = DeviceExecutionActionHandler(execution, adapters, transfers)
    for operation in (
        "device.probe", "file.transfer", "device.verify",
        "huawei.storage.cleanup", "huawei.storage.sync",
        "huawei.startup.configure", "device.reboot", "device.wait_online", "huawei.startup.rollback",
    ):
        registry.register(handler, item_id=operation)
    return registry


def build_device_reconcile_registry(execution: DeviceExecutionTool, control: DeviceControlService) -> ReconcileRegistry:
    registry = ReconcileRegistry()
    for provider_id in (
        "huawei.reconcile.transfer", "huawei.reconcile.startup",
        "huawei.reconcile.reboot", "huawei.reconcile.online", "huawei.reconcile.rollback",
    ):
        registry.register(DeviceReconcileProvider(provider_id, execution, control), item_id=provider_id)
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


def _extract_storage_output(output: str, storage: str) -> str:
    """Keep every storage decision scoped to its own directory response."""
    marker = f"directory of {storage.rstrip('/')}".casefold()
    lowered = output.casefold()
    start = lowered.find(marker)
    if start < 0:
        return ""
    next_directory = lowered.find("directory of ", start + len(marker))
    return output[start:next_directory if next_directory >= 0 else None]


def _interactive_command_steps(
    commands: tuple[str, ...],
    *,
    allow_confirmation: bool = False,
    failures: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for command in commands:
        if not str(command).strip():
            continue
        steps.append({"type": "send", "text": str(command), "label": str(command)})
        steps.append({
            "type": "expect",
            "success": ["device_prompt"],
            "failures": list(failures),
            "responses": (
                [{"match": "confirmation_prompt", "text": "y", "max_matches": 3}]
                if allow_confirmation
                else []
            ),
            "timeout_seconds": 90,
            "label": f"等待 {command}",
        })
    return steps


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
    "DeviceExecutionActionHandler",
    "DeviceReconcileProvider",
    "build_device_action_registry",
    "build_device_reconcile_registry",
]
