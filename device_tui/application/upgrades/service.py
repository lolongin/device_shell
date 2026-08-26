"""Compatibility facade for the framework-backed package-upgrade workflow."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import posixpath
import re

from device_tui.application.errors import (
    ApplicationConflictError,
    ResourceNotFoundError,
    UnsupportedOperationError,
)
from device_tui.application.devices import DeviceService
from device_tui.application.operations import (
    OperationManager,
    OperationRecord,
    TERMINAL_OPERATION_STATUSES,
)
from device_tui.application.sessions import SessionRecord, SessionService
from device_tui.application.transfers import (
    ManagedTransferService,
    PreparedTransferSource,
)
from device_tui.application.upgrades.package import (
    DEFAULT_MASTER_STORAGE,
    DEFAULT_SLAVE_STORAGE,
    PackageFileEntry,
    PackageUpgradeConfig,
    build_cleanup_plan,
    package_basename,
    parse_dir_entries,
    parse_display_startup,
    parse_free_space_bytes,
)
from device_tui.application.upgrades.drivers import (
    UpgradeDriver,
    UpgradeDriverRegistry,
    UpgradeTargetFacts,
)
from device_tui.application.workflows.decisions import DecisionSubmission
from device_tui.application.workflows.models import RunStatus
from device_tui.application.workflows.runtime import WorkflowRuntime
from device_tui.application.workflows.plugins import WorkflowRegistry
from device_tui.application.workflows.models import WorkflowRun as FrameworkWorkflowRun


MANUAL_PASSWORD_PLACEHOLDER = "{{file_transfer.password}}"
MAX_MANUAL_SCRIPT_CHARS = 100_000
_MANUAL_PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}")


@dataclass(frozen=True, slots=True)
class ManualUpgradePlan:
    """Secret-free, operator-editable package-upgrade fallback plan."""

    script: str
    package_name: str
    cleanup_paths: list[str]
    notes: list[str]
    password_placeholder: str = MANUAL_PASSWORD_PLACEHOLDER


class PackageUpgradeService:
    """Run one verified package replacement at a time on a terminal session."""

    def __init__(
        self,
        sessions: SessionService,
        operations: OperationManager,
        transfers: ManagedTransferService,
        devices: DeviceService | None = None,
        drivers: UpgradeDriverRegistry | None = None,
    ) -> None:
        self._sessions = sessions
        self._operations = operations
        self._transfers = transfers
        self._devices = devices
        self._drivers = drivers or UpgradeDriverRegistry()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._framework_runtime: WorkflowRuntime | None = None
        self._framework_workflows: WorkflowRegistry | None = None

    def bind_framework(
        self,
        runtime: WorkflowRuntime,
        workflows: WorkflowRegistry,
    ) -> None:
        """Attach the canonical workflow engine used by compatibility APIs."""

        self._framework_runtime = runtime
        self._framework_workflows = workflows

    def start(
        self,
        *,
        session_id: str,
        package_path: str,
        package_source: str = "local",
        include_slave: bool = True,
        standby_required: bool = False,
        auto_delete_old_packages: bool = True,
        reboot_after_setting: bool = False,
        master_storage: str = DEFAULT_MASTER_STORAGE,
        slave_storage: str = DEFAULT_SLAVE_STORAGE,
        driver_id: str = "auto",
    ) -> OperationRecord:
        session = self._connected_session(session_id)
        package_source = str(package_source or "local").casefold()
        if package_source not in {"local", "device"}:
            raise UnsupportedOperationError("package_source must be local or device.")
        source = self._transfers.resolve_source(package_path) if package_source == "local" else None
        package_name = source.name if source is not None else posixpath.basename(package_path.replace("\\", "/").rstrip("/"))
        if not package_name or package_name in {".", ".."}:
            raise UnsupportedOperationError("设备上的系统包路径无效。")
        driver = self._resolve_driver(session, driver_id)
        try:
            if source is not None:
                driver.validate_artifact(source.path)
        except ValueError as exc:
            raise UnsupportedOperationError(str(exc)) from exc
        primary_storage = master_storage or driver.default_primary_storage
        standby_storage = slave_storage or driver.default_standby_storage
        record = self._operations.create(
            kind="package_upgrade",
            direction="upgrade",
            device_id=session.device_id,
            session_id=session.id,
            stage="queued",
            message="系统包升级已排队。",
            data={
                "package_path": source.relative_path if source is not None else package_path,
                "package_source": package_source,
                "package_name": package_name,
                "package_size": source.size_bytes if source is not None else 0,
                "include_slave": bool(include_slave),
                "standby_required": bool(standby_required),
                "topology_policy": (
                    "required" if standby_required else "single" if not include_slave else "auto"
                ),
                "auto_delete_old_packages": bool(auto_delete_old_packages),
                "reboot_after_setting": bool(reboot_after_setting),
                "master_storage": primary_storage,
                "slave_storage": standby_storage,
                "driver_id": driver.id,
                "driver_name": driver.display_name,
            },
        )
        if self._framework_runtime is None or self._framework_workflows is None:
            raise UnsupportedOperationError("The workflow framework is not configured.")
        workflow_inputs = {
                "package_ref": source.relative_path if source is not None else package_path,
                "package_source": package_source,
                "activation_policy": "reboot" if reboot_after_setting else "stage_only",
                "topology_policy": (
                    "required" if standby_required else "single" if not include_slave else "auto"
                ),
                "cleanup_policy": "auto" if auto_delete_old_packages else "never",
                "recovery_protocol": "same",
                "master_storage": primary_storage,
                "slave_storage": standby_storage,
                "driver_id": driver.id,
            }
        definition = self._framework_workflows.build("network.package_upgrade", workflow_inputs)
        run = self._framework_runtime.start(
            definition,
            device_id=session.device_id,
            run_id=record.id,
            context={
                "target": {
                    "device_id": session.device_id,
                    "session_id": session.id,
                    "protocol": "auto",
                },
                "session_id": session.id,
                "package_source": package_source,
                "workflow_inputs": workflow_inputs,
            },
        )
        self._project_framework_run(record.id, run)
        task = asyncio.create_task(
            self._run_framework(record.id),
            name=f"package-upgrade-framework-{record.id}",
        )
        self._tasks[record.id] = task
        self._operations.register_canceller(
            record.id,
            lambda: self._cancel_framework_task(record.id, session.id),
        )
        return self._operations.get(record.id)

    def approve_reboot(self, operation_id: str) -> OperationRecord:
        record = self._operations.get(operation_id)
        if record.kind != "package_upgrade":
            raise UnsupportedOperationError("The operation is not a package upgrade.")
        if self._framework_runtime is None:
            raise UnsupportedOperationError("The workflow framework is not configured.")
        run = self._framework_runtime.runs.get(operation_id)
        point = run.decision_point
        option = next((item for item in point.options if item.id == "approve_reboot"), None) if point else None
        if record.status != "waiting_approval" or point is None or option is None:
            raise ApplicationConflictError("The package upgrade is not waiting for reboot approval.")
        updated_run = self._framework_runtime.apply_decision(
            operation_id,
            DecisionSubmission(
                decision_point_id=point.id,
                expected_revision=run.revision,
                option_id=option.id,
                actor_type="human",
                actor_id="compatibility-api",
            ),
        )
        self._project_framework_run(operation_id, updated_run)
        if str(updated_run.status) in {RunStatus.RUNNING.value, RunStatus.RECOVERING.value} and operation_id not in self._tasks:
            self._tasks[operation_id] = asyncio.create_task(
                self._run_framework(operation_id),
                name=f"package-upgrade-framework-{operation_id}-approval",
            )
        return self._operations.get(operation_id)

    async def _run_framework(self, operation_id: str) -> None:
        """Drive the canonical runtime and keep the legacy operation view current."""

        if self._framework_runtime is None:
            return
        try:
            await self._framework_runtime.run_until_blocked(
                operation_id,
                on_update=lambda run: self._project_framework_run(operation_id, run),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record = self._operations.get(operation_id)
            if record.status not in TERMINAL_OPERATION_STATUSES:
                self._operations.update(
                    operation_id,
                    status="failed",
                    message=str(exc),
                    error_code=getattr(exc, "code", "package_upgrade_framework_failed"),
                )
        finally:
            self._tasks.pop(operation_id, None)

    def _cancel_framework_task(self, operation_id: str, session_id: str) -> None:
        del session_id
        if self._framework_runtime is not None:
            self._framework_runtime.cancel(operation_id)
            self._project_framework_run(operation_id, self._framework_runtime.runs.get(operation_id))
        task = self._tasks.get(operation_id)
        if task is not None and not task.done():
            task.cancel()

    def _project_framework_run(self, operation_id: str, run: FrameworkWorkflowRun) -> None:
        record = self._operations.get(operation_id)
        if record.status in TERMINAL_OPERATION_STATUSES and str(run.status) not in {RunStatus.SUCCEEDED.value}:
            return
        state = str(run.current_state or "")
        activation = str(run.context.get("workflow_inputs", {}).get("activation_policy") or "stage_only")
        stage = {
            "precheck": "prechecking",
            "ftp_login": "prechecking",
            "cleanup": "cleanup",
            "transfer": "downloading",
            "verify_package": "verifying",
            "sync_standby": "synchronizing",
            "configure_startup": "setting_startup",
            "reboot_approval": "reboot_approval",
            "reboot": "rebooting",
            "wait_online": "waiting_online",
            "verify_version": "verifying_version",
            "validation": "validating",
            "rollback": "rollback",
            "complete": "completed" if activation == "reboot" else "staged",
        }.get(state, state or record.stage)
        status = {
            RunStatus.RUNNING.value: "running",
            RunStatus.RECOVERING.value: "running",
            RunStatus.WAITING_RECONCILE.value: "running",
            RunStatus.WAITING_DECISION.value: "waiting_approval" if state == "reboot_approval" else "waiting_decision",
            RunStatus.SUCCEEDED.value: "completed" if activation == "reboot" else "staged",
            RunStatus.FAILED.value: "failed",
            RunStatus.CANCELLED.value: "cancelled",
        }.get(str(run.status), "running")
        facts = self._framework_facts(run)
        data = {
            "workflow_id": run.workflow_id,
            "workflow_version": run.workflow_version,
            "framework_run_id": run.id,
            "package_source": run.context.get("workflow_inputs", {}).get("package_source", "local"),
            "include_slave": facts.get("include_slave", run.context.get("workflow_inputs", {}).get("topology_policy") != "single"),
            "topology_detection": facts.get("topology_detection", {}),
            "reboot_required": activation == "stage_only" or state in {"reboot_approval", "reboot", "wait_online", "verify_version", "validation"},
            "framework_state": state,
            "framework_revision": run.revision,
        }
        if str(run.status) == RunStatus.SUCCEEDED.value:
            data["reboot_required"] = False if activation == "reboot" else True
        error = run.error or {}
        message = (
            "系统包已核对并设为下次启动项，尚未重启激活。" if status == "staged" else
            "系统包升级完成，设备已重新进入可交互状态。" if status == "completed" else
            "系统包和启动项已确认，等待人工批准重启。" if status == "waiting_approval" else
            str(error.get("message") or "系统包升级正在执行。")
        )
        actions = self._framework_stage_actions(stage, run)
        self._operations.update(
            operation_id,
            status=status,
            stage=stage,
            message=message,
            progress_percent=self._framework_progress(state, status),
            error_code=str(error.get("code") or "") if status == "failed" else "",
            stage_actions=actions,
            data=data,
        )

    @staticmethod
    def _framework_stage_actions(stage: str, run: FrameworkWorkflowRun) -> list[str]:
        inputs = run.context.get("workflow_inputs")
        values = inputs if isinstance(inputs, dict) else {}
        package = str(values.get("package_ref") or "<package>")
        master = str(values.get("master_storage") or "flash:/")
        slave = str(values.get("slave_storage") or "slave#flash:/")
        return {
            "prechecking": [
                "screen-length 0 temporary",
                "display startup",
                f"dir {master}",
                f"dir {slave}（检查备控存储）",
            ],
            "cleanup": ["根据预检结果清理未使用旧系统包"],
            "downloading": [f"下载 {package}"],
            "verifying": [f"dir {master}{package_basename(package)}（核对系统包）"],
            "synchronizing": [f"copy {master}{package_basename(package)} {slave}{package_basename(package)}"],
            "setting_startup": [f"startup system-software {master}{package_basename(package)}"],
            "rebooting": ["发送 reboot", "等待设备重新进入可交互状态"],
            "waiting_online": ["确认设备重新上线"],
            "verifying_version": ["display version"],
            "validating": ["执行升级后校验"],
            "rollback": ["恢复升级前启动项"],
        }.get(stage, [])

    @staticmethod
    def _framework_facts(run: FrameworkWorkflowRun) -> dict[str, object]:
        result: dict[str, object] = {}
        for attempt in run.attempts:
            if str(attempt.status) != "succeeded":
                continue
            facts = dict(attempt.result or {})
            nested = facts.get("data")
            if isinstance(nested, dict):
                result.update(nested)
            result.update({key: value for key, value in facts.items() if key in {"include_slave", "topology_detection"}})
        precheck = run.context.get("action.precheck.facts")
        if isinstance(precheck, dict):
            result.update({key: value for key, value in precheck.items() if key in {"include_slave", "topology_detection"}})
        return result

    @staticmethod
    def _framework_progress(state: str, status: str) -> int:
        if status in {"completed", "staged"}:
            return 100 if status == "completed" else 90
        return {
            "precheck": 5, "ftp_login": 8, "cleanup": 20, "transfer": 55,
            "verify_package": 65, "sync_standby": 75, "configure_startup": 90,
            "reboot_approval": 95, "reboot": 96, "wait_online": 98,
            "verify_version": 99, "validation": 99, "rollback": 95,
        }.get(state, 0)

    def cancel(self, operation_id: str) -> OperationRecord:
        return self._operations.cancel(operation_id)

    def cancel_session(self, session_id: str) -> int:
        cancelled = 0
        for operation_id in tuple(self._tasks):
            record = self._operations.get(operation_id)
            if record.session_id != session_id or record.status in TERMINAL_OPERATION_STATUSES:
                continue
            self.cancel(operation_id)
            cancelled += 1
        return cancelled

    def manual_terminal_snapshot(
        self,
        session_id: str,
        *,
        max_chars: int = 200_000,
    ) -> tuple[str, bool]:
        """Return the already-redacted terminal tail used by the manual fallback."""

        self._session(session_id)
        record = self._sessions.read_log(session_id, max_chars=max_chars)
        return record.content, record.truncated

    async def generate_manual_plan(
        self,
        *,
        session_id: str,
        package_path: str,
        startup_output: str = "",
        master_dir_output: str = "",
        slave_dir_output: str = "",
        include_slave: bool = True,
        auto_delete_old_packages: bool = True,
        reboot_after_setting: bool = False,
        master_storage: str = DEFAULT_MASTER_STORAGE,
        slave_storage: str = DEFAULT_SLAVE_STORAGE,
    ) -> ManualUpgradePlan:
        """Generate a safe editable script while keeping transfer credentials in Python."""

        session = self._connected_session(session_id)
        source = self._transfers.resolve_source(package_path)
        driver = self._resolve_driver(session, "auto")
        try:
            driver.validate_artifact(source.path)
        except ValueError as exc:
            raise UnsupportedOperationError(str(exc)) from exc
        if driver.id != "huawei-vrp":
            raise UnsupportedOperationError(
                f"{driver.display_name} 暂不支持手工脚本回退，请使用标准 Task 流程。"
            )
        master_storage = master_storage or driver.default_primary_storage
        slave_storage = slave_storage or driver.default_standby_storage
        prepared = await self._transfers.prepare_upload_source(
            session,
            source_path=source.relative_path,
            destination_path=driver.package_path(master_storage, source.name),
        )
        settings = self._transfers.settings()
        cleanup_entries, cleanup_notes = self._manual_cleanup_entries(
            source=source,
            startup_output=startup_output,
            master_storage=master_storage,
            master_output=master_dir_output,
            include_slave=include_slave,
            slave_storage=slave_storage,
            slave_output=slave_dir_output,
            auto_delete=auto_delete_old_packages,
        )
        plan = driver.manual_plan(PackageUpgradeConfig(
            package_path=source.path,
            server_host=prepared.host,
            protocol=prepared.protocol or settings.protocol,
            port=prepared.port or settings.bound_port or settings.port,
            username=settings.username,
            password=MANUAL_PASSWORD_PLACEHOLDER,
            master_storage=master_storage,
            slave_storage=slave_storage,
            include_slave=include_slave,
            auto_delete_old_packages=auto_delete_old_packages,
            reboot_after_setting=reboot_after_setting,
            cleanup_entries=cleanup_entries,
        ))
        notes = [
            "脚本中的文件服务密码为安全占位符；只能通过“发送脚本”由 Python 解析。",
            *cleanup_notes,
            *plan.notes,
        ]
        return ManualUpgradePlan(
            script="\n".join(plan.commands),
            package_name=source.name,
            cleanup_paths=list(plan.cleanup_paths),
            notes=notes,
        )

    async def send_manual_script(
        self,
        *,
        session_id: str,
        script: str,
        interval_ms: int = 900,
    ) -> int:
        """Resolve the one supported secret placeholder and send commands in order."""

        self._connected_session(session_id)
        if not script.strip():
            raise UnsupportedOperationError("The manual package-upgrade script is empty.")
        if len(script) > MAX_MANUAL_SCRIPT_CHARS:
            raise UnsupportedOperationError("The manual package-upgrade script is too large.")
        commands = [
            line.strip()
            for line in script.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not commands:
            raise UnsupportedOperationError("The manual package-upgrade script has no commands.")
        for command in commands:
            placeholders = _MANUAL_PLACEHOLDER.findall(command)
            if placeholders and command != MANUAL_PASSWORD_PLACEHOLDER:
                raise UnsupportedOperationError(
                    "Secret placeholders are only allowed as the complete password command."
                )
            if any(item != MANUAL_PASSWORD_PLACEHOLDER for item in placeholders):
                raise UnsupportedOperationError("The manual script contains an unsupported placeholder.")

        password = ""
        if MANUAL_PASSWORD_PLACEHOLDER in commands:
            password = self._transfers.resolve_secret("file_transfer.password")
            if not password:
                raise UnsupportedOperationError("The file-transfer password is unavailable.")
        safe_interval = max(0, min(5_000, int(interval_ms)))
        for index, command in enumerate(commands):
            payload = command
            if command == MANUAL_PASSWORD_PLACEHOLDER:
                payload = password
                self._sessions.protect_sensitive_output(session_id, password, ttl_seconds=30.0)
            await self._sessions.write(session_id, f"{payload}\r", origin="automation")
            if safe_interval and index < len(commands) - 1:
                await asyncio.sleep(safe_interval / 1000)
        return len(commands)

    async def close(self) -> None:
        for operation_id in tuple(self._tasks):
            with suppress(ResourceNotFoundError, UnsupportedOperationError):
                self.cancel(operation_id)
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks.values()), return_exceptions=True)

    def _manual_cleanup_entries(
        self,
        *,
        source: PreparedTransferSource,
        startup_output: str,
        master_storage: str,
        master_output: str,
        include_slave: bool,
        slave_storage: str,
        slave_output: str,
        auto_delete: bool,
    ) -> tuple[list[PackageFileEntry], list[str]]:
        if not auto_delete:
            return [], ["自动清理已关闭，脚本不会删除旧系统包。"]
        startup = parse_display_startup(startup_output)
        entries: list[PackageFileEntry] = []
        notes: list[str] = []
        candidates = [("主控", master_storage, master_output)]
        if include_slave:
            candidates.append(("备控", slave_storage, slave_output))
        for label, storage, output in candidates:
            if not output.strip():
                notes.append(f"未提供{label}目录输出，已跳过{label}旧包自动清理。")
                continue
            cleanup = build_cleanup_plan(
                storage=storage,
                free_bytes=parse_free_space_bytes(output),
                target_bytes=source.size_bytes,
                entries=parse_dir_entries(output, storage),
                startup=startup,
                target_package_name=source.name,
            )
            entries.extend(cleanup.delete_entries)
            notes.append(
                f"{label}计划清理 {len(cleanup.delete_entries)} 个未使用旧包，"
                f"预计释放 {cleanup.reclaim_bytes // (1024 * 1024)} MB。"
            )
            if not cleanup.has_enough_space:
                notes.append(f"{label}清理后空间仍可能不足，请在发送前复核目录输出。")
        return entries, notes

    def _session(self, session_id: str) -> SessionRecord:
        session = next(
            (item for item in self._sessions.list_sessions() if item.id == session_id),
            None,
        )
        if session is None:
            raise ResourceNotFoundError(
                f"Unknown session: {session_id}",
                details={"resource": "session", "session_id": session_id},
            )
        return session

    def _connected_session(self, session_id: str) -> SessionRecord:
        session = next(
            (item for item in self._sessions.list_sessions() if item.id == session_id),
            None,
        )
        if session is None:
            raise ResourceNotFoundError(
                f"Unknown session: {session_id}",
                details={"resource": "session", "session_id": session_id},
            )
        if session.status != "connected":
            raise ApplicationConflictError("The terminal session is not connected.")
        return session

    def _resolve_driver(self, session: SessionRecord, requested: str) -> UpgradeDriver:
        if self._devices is None:
            facts = UpgradeTargetFacts(session.device_id)
        else:
            device = self._devices.require_device(session.device_id)
            facts = UpgradeTargetFacts(
                device_id=device.id,
                vendor=device.vendor,
                model=device.model,
                platform=str(getattr(device, "hardware_platform", "") or getattr(device, "cpu", "")),
            )
        try:
            return self._drivers.resolve(facts, requested)
        except KeyError as exc:
            raise UnsupportedOperationError(
                f"设备 {facts.device_id} 没有可用的系统包升级驱动，请先配置对应厂商驱动。"
            ) from exc
