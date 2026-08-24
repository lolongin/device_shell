"""Backend-owned package-upgrade workflow built on terminal plans."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
import posixpath
import re

from device_tui.application.errors import (
    ApplicationError,
    ApplicationConflictError,
    PackageUpgradeError,
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
from device_tui.application.terminal.orchestration import TerminalPlanError, parse_terminal_plan
from device_tui.application.transfers import (
    ManagedTransferService,
    PreparedTransferSource,
    TerminalPlanExecutor,
)
from device_tui.application.upgrades.package import (
    DEFAULT_MASTER_STORAGE,
    DEFAULT_SLAVE_STORAGE,
    PackageFileEntry,
    PackageUpgradeConfig,
    STANDBY_STORAGE_ABSENT,
    STANDBY_STORAGE_AVAILABLE,
    build_cleanup_plan,
    classify_standby_storage,
    dir_contains_package,
    find_upgrade_failure,
    generate_huawei_upgrade_plan,
    join_storage_path,
    parse_dir_entries,
    parse_display_startup,
    parse_free_space_bytes,
    startup_uses_package,
)
from device_tui.application.upgrades.drivers import (
    UpgradeDriver,
    UpgradeDriverRegistry,
    UpgradeTargetFacts,
)
from device_tui.infrastructure.transfers.managed_file_transfer import (
    build_managed_transfer_steps,
    source_fingerprint,
)


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
        terminal_executor: TerminalPlanExecutor,
        devices: DeviceService | None = None,
        drivers: UpgradeDriverRegistry | None = None,
    ) -> None:
        self._sessions = sessions
        self._operations = operations
        self._transfers = transfers
        self._executor = terminal_executor
        self._devices = devices
        self._drivers = drivers or UpgradeDriverRegistry()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._reboot_approvals: dict[str, asyncio.Event] = {}

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
                "auto_delete_old_packages": bool(auto_delete_old_packages),
                "reboot_after_setting": bool(reboot_after_setting),
                "master_storage": primary_storage,
                "slave_storage": standby_storage,
                "driver_id": driver.id,
                "driver_name": driver.display_name,
            },
        )
        task = asyncio.create_task(
            self._run(record.id, session, source),
            name=f"package-upgrade-{record.id}",
        )
        self._tasks[record.id] = task
        self._operations.register_canceller(
            record.id,
            lambda: self._cancel_task(record.id, session.id),
        )
        return self._operations.get(record.id)

    def approve_reboot(self, operation_id: str) -> OperationRecord:
        record = self._operations.get(operation_id)
        if record.kind != "package_upgrade":
            raise UnsupportedOperationError("The operation is not a package upgrade.")
        approval = self._reboot_approvals.get(operation_id)
        if record.status != "waiting_approval" or approval is None:
            raise ApplicationConflictError("The package upgrade is not waiting for reboot approval.")
        updated = self._operations.update(
            operation_id,
            status="running",
            stage="rebooting",
            message="重启已批准，正在等待设备重新进入可交互状态。",
            progress_percent=96,
            stage_actions=["发送 reboot", "等待设备重新进入可交互状态"],
        )
        approval.set()
        return updated

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

    async def _run(
        self,
        operation_id: str,
        session: SessionRecord,
        initial_source: PreparedTransferSource | None,
    ) -> None:
        owner_id = f"package-upgrade:{operation_id}"
        acquired = False
        try:
            driver = self._drivers.get(str(self._operations.get(operation_id).data["driver_id"]))
            self._executor.acquire(
                session.id,
                owner_id,
                on_cancel=lambda: self._cancel_task(operation_id, session.id),
            )
            acquired = True
            record = self._operations.update(
                operation_id,
                stage="prechecking",
                message="正在读取启动项、主控和备控存储。",
                progress_percent=5,
                stage_actions=[
                    driver.disable_paging_command(),
                    driver.startup_query_command(),
                    driver.storage_query_command(str(self._operations.get(operation_id).data["master_storage"])),
                    f'{driver.storage_query_command(str(self._operations.get(operation_id).data["slave_storage"]))}（检查备控存储）',
                ],
            )
            await self._command(session, owner_id, driver.disable_paging_command(), driver=driver)
            startup_output = await self._command(session, owner_id, driver.startup_query_command(), driver=driver)
            master_storage = str(record.data["master_storage"])
            slave_storage = str(record.data["slave_storage"])
            master_output = await self._command(
                session,
                owner_id,
                driver.storage_query_command(master_storage),
                driver=driver,
            )
            include_slave = bool(record.data["include_slave"])
            slave_output = ""
            if include_slave:
                slave_output = await self._command(
                    session,
                    owner_id,
                    driver.storage_query_command(slave_storage),
                    allow_failure_output=True,
                    driver=driver,
                )
                standby = driver.classify_standby(slave_output, slave_storage)
                if standby == STANDBY_STORAGE_ABSENT:
                    if bool(record.data.get("standby_required", False)):
                        raise _UpgradeRunError(
                            "standby_storage_required",
                            "升级策略要求备控，但设备未检测到备控存储。",
                        )
                    include_slave = False
                elif standby != STANDBY_STORAGE_AVAILABLE:
                    raise _UpgradeRunError(
                        "standby_storage_indeterminate",
                        "无法确认备控存储是否存在，升级已停止。",
                    )
            cleanup_paths = self._cleanup_paths(
                package_name=str(record.data["package_name"]),
                package_size=int(record.data.get("package_size") or 0),
                startup_output=startup_output,
                master_storage=master_storage,
                master_output=master_output,
                include_slave=include_slave,
                slave_storage=slave_storage,
                slave_output=slave_output,
                auto_delete=bool(record.data["auto_delete_old_packages"]),
                driver=driver,
            )
            if initial_source is not None and source_fingerprint(initial_source.path) != initial_source.fingerprint:
                raise _UpgradeRunError("upgrade_source_changed", "预检期间本地系统包发生变化。")
            self._operations.update(
                operation_id,
                stage="cleanup",
                message=(
                    f"正在安全删除 {len(cleanup_paths)} 个未使用旧包。"
                    if cleanup_paths
                    else "存储空间满足要求，无需删除旧包。"
                ),
                progress_percent=20,
                stage_actions=(
                    [driver.cleanup_command(path) for path in cleanup_paths]
                    if cleanup_paths
                    else ["无需删除旧包：可用空间满足要求"]
                ),
                data={
                    "include_slave": include_slave,
                    "cleanup_paths": cleanup_paths,
                },
            )
            for cleanup_path in cleanup_paths:
                await self._command(
                    session,
                    owner_id,
                    driver.cleanup_command(cleanup_path),
                    driver=driver,
                )
            package_name = str(record.data["package_name"])
            package_size = int(record.data.get("package_size") or 0)
            master_package = (
                str(record.data["package_path"])
                if str(record.data.get("package_source")) == "device"
                else driver.package_path(master_storage, package_name)
            )
            if not driver.package_is_present(
                master_output,
                storage=master_storage,
                package_name=package_name,
                package_size=package_size,
            ):
                if initial_source is None:
                    raise _UpgradeRunError("device_package_missing", f"设备主控未找到系统包 {master_package}，已跳过传包。")
                await self._download(operation_id, session, owner_id, initial_source, master_package, driver)
            else:
                self._operations.update(
                    operation_id,
                    stage="verifying",
                    message="主控已存在大小匹配的目标包，跳过下载。",
                    progress_percent=62,
                    stage_actions=[f"跳过下载：{driver.storage_query_command(master_package)} 已确认文件大小匹配"],
                )
            if initial_source is not None and source_fingerprint(initial_source.path) != initial_source.fingerprint:
                raise _UpgradeRunError("upgrade_source_changed", "升级期间本地系统包发生变化。")
            verified_master = await self._command(
                session,
                owner_id,
                driver.storage_query_command(master_package),
                driver=driver,
            )
            self._require_package(
                verified_master,
                master_storage,
                package_name,
                package_size,
                "主控",
                driver,
            )
            slave_package = driver.package_path(slave_storage, package_name)
            if include_slave:
                self._operations.update(
                    operation_id,
                    stage="synchronizing",
                    message="正在同步并核对备控系统包。",
                    progress_percent=72,
                    stage_actions=[
                        *driver.sync_commands(master_package, slave_package),
                        f"{driver.storage_query_command(slave_package)}（核对备控文件大小）",
                    ],
                )
                for command in driver.sync_commands(master_package, slave_package):
                    await self._command(session, owner_id, command, timeout_seconds=90, driver=driver)
                verified_slave = await self._command(
                    session,
                    owner_id,
                    driver.storage_query_command(slave_package),
                    driver=driver,
                )
                self._require_package(
                    verified_slave,
                    slave_storage,
                    package_name,
                    package_size,
                    "备控",
                    driver,
                )
            await self._set_startup(
                operation_id,
                session,
                owner_id,
                package_name,
                master_package,
                slave_package,
                include_slave,
                driver,
            )
            confirmed = await self._command(session, owner_id, driver.startup_query_command(), driver=driver)
            if not driver.startup_uses_artifact(confirmed, package_name):
                raise _UpgradeRunError(
                    "startup_verification_failed",
                    "最终 display startup 未确认目标包为下次启动系统包。",
                )
            record = self._operations.get(operation_id)
            if not bool(record.data["reboot_after_setting"]):
                self._operations.update(
                    operation_id,
                    status="staged",
                    stage="staged",
                    message="系统包已核对并设为下次启动项，尚未重启激活。",
                    progress_percent=90,
                    stage_actions=[
                        "确认 display startup 已指向目标系统包",
                        "不自动重启：等待业务窗口人工重启",
                    ],
                    data={"reboot_required": True},
                )
                return
            approval = asyncio.Event()
            self._reboot_approvals[operation_id] = approval
            self._operations.update(
                operation_id,
                status="waiting_approval",
                stage="reboot_approval",
                message="系统包和启动项已确认，等待人工批准重启。",
                progress_percent=95,
                stage_actions=["等待人工批准 reboot"],
                data={"reboot_required": True},
            )
            await approval.wait()
            await self._reboot(session, owner_id, driver)
            self._operations.update(
                operation_id,
                status="completed",
                stage="completed",
                message="系统包升级完成，设备已重新进入可交互状态。",
                progress_percent=100,
                stage_actions=["reboot", "确认设备重新进入可交互状态"],
                data={"reboot_required": False},
            )
        except asyncio.CancelledError:
            self._mark_cancelled(operation_id)
        except (ApplicationError, TerminalPlanError, OSError, _UpgradeRunError) as exc:
            self._mark_failed(
                operation_id,
                getattr(exc, "code", "package_upgrade_failed"),
                str(exc),
            )
        finally:
            self._reboot_approvals.pop(operation_id, None)
            if acquired:
                self._executor.release(session.id, owner_id)
            self._tasks.pop(operation_id, None)

    async def _download(
        self,
        operation_id: str,
        session: SessionRecord,
        owner_id: str,
        source: PreparedTransferSource,
        master_package: str,
        driver: UpgradeDriver,
    ) -> None:
        prepared = await self._transfers.prepare_upload_source(
            session,
            source_path=source.relative_path,
            destination_path=master_package,
        )
        steps, timeout = build_managed_transfer_steps(
            protocol=prepared.protocol,
            host=prepared.host,
            port=prepared.port,
            source_path=prepared.relative_path,
            destination_path=master_package,
            source_size=prepared.size_bytes,
        )
        self._operations.update(
            operation_id,
            stage="downloading",
            message=f"正在通过 {prepared.protocol.upper()} 下载系统包到主控。",
            progress_percent=38,
            stage_actions=self._transfer_actions(steps),
        )
        result = await self._executor.run(
            session_id=session.id,
            device_id=session.device_id,
            plan=parse_terminal_plan(steps, total_timeout_seconds=timeout),
            owner_id=owner_id,
        )
        self._require_completed(result, "系统包下载")
        self._operations.update(
            operation_id,
            stage="verifying",
            message="系统包下载完成，正在核对主控文件大小。",
            progress_percent=62,
            stage_actions=[f"{driver.storage_query_command(master_package)}（核对主控文件大小）"],
        )

    @staticmethod
    def _transfer_actions(steps: list[dict[str, object]]) -> list[str]:
        """Expose safe transfer-plan labels without leaking credentials."""

        actions: list[str] = []
        for item in steps:
            label = str(item.get("label") or "").strip()
            if label and label not in actions:
                actions.append(label)
        return actions or ["执行文件传输计划"]

    async def _set_startup(
        self,
        operation_id: str,
        session: SessionRecord,
        owner_id: str,
        package_name: str,
        master_package: str,
        slave_package: str,
        include_slave: bool,
        driver: UpgradeDriver,
    ) -> None:
        primary_commands, fallback_commands = driver.activation_commands(
            master_package,
            slave_package,
            include_slave,
        )
        self._operations.update(
            operation_id,
            stage="setting_startup",
            message="正在设置并最终确认下次启动系统包。",
            progress_percent=86,
            stage_actions=[
                *primary_commands,
                f"{driver.startup_query_command()}（最终确认下次启动项）",
            ],
        )
        output = ""
        for command in primary_commands:
            output = await self._command(
                session,
                owner_id,
                command,
                allow_failure_output=bool(fallback_commands),
                driver=driver,
            )
        failure = driver.failure_marker(output)
        if not failure:
            return
        if not include_slave:
            raise _UpgradeRunError(
                "startup_command_failed",
                f"设置启动项失败，设备输出包含: {failure}",
            )
        for command in fallback_commands:
            await self._command(session, owner_id, command, driver=driver)

    async def _reboot(
        self,
        session: SessionRecord,
        owner_id: str,
        driver: UpgradeDriver,
    ) -> None:
        plan = parse_terminal_plan(
            list(driver.reboot_plan_steps()),
            total_timeout_seconds=190,
        )
        result = await self._executor.run(
            session_id=session.id,
            device_id=session.device_id,
            plan=plan,
            owner_id=owner_id,
        )
        self._require_completed(result, "设备重启")

    async def _command(
        self,
        session: SessionRecord,
        owner_id: str,
        command: str,
        *,
        timeout_seconds: int = 30,
        allow_failure_output: bool = False,
        driver: UpgradeDriver | None = None,
    ) -> str:
        last_result: dict[str, object] = {}
        for attempt in range(2):
            plan = parse_terminal_plan(
                [
                    {"type": "send", "text": command, "label": command},
                    {
                        "type": "expect",
                        "success": ["device_prompt"],
                        "failures": [] if allow_failure_output else [
                            "Error:",
                            "failed",
                            "Unrecognized command",
                            "Unknown command",
                        ],
                        "timeout_seconds": timeout_seconds,
                        "label": f"等待 {command}",
                        "max_output_chars": 32_768,
                    },
                ],
                total_timeout_seconds=timeout_seconds + 5,
            )
            last_result = await self._executor.run(
                session_id=session.id,
                device_id=session.device_id,
                plan=plan,
                owner_id=owner_id,
            )
            if str(last_result.get("status") or "") == "completed":
                output = self._result_output(last_result)
                if not allow_failure_output:
                    failure = driver.failure_marker(output) if driver is not None else find_upgrade_failure(output)
                    if failure:
                        raise _UpgradeRunError(
                            "upgrade_command_failed",
                            f"{command} 失败，设备输出包含: {failure}",
                        )
                return output
            if attempt == 0 and str(last_result.get("status") or "") == "timed_out":
                continue
            break
        self._require_completed(last_result, command)
        return ""

    def _cleanup_paths(
        self,
        *,
        package_name: str,
        package_size: int,
        startup_output: str,
        master_storage: str,
        master_output: str,
        include_slave: bool,
        slave_storage: str,
        slave_output: str,
        auto_delete: bool,
        driver: UpgradeDriver,
    ) -> list[str]:
        paths: list[str] = []
        for label, storage, output in (
            ("主控", master_storage, master_output),
            ("备控", slave_storage, slave_output),
        ):
            if label == "备控" and not include_slave:
                continue
            plan = driver.cleanup_plan(
                storage=storage,
                output=output,
                startup_output=startup_output,
                package_name=package_name,
                package_size=package_size,
            )
            if plan.free_bytes <= 0:
                raise _UpgradeRunError(
                    "storage_space_indeterminate",
                    f"无法确认{label}剩余空间。",
                )
            if not plan.has_enough_space:
                raise _UpgradeRunError(
                    "insufficient_space",
                    f"{label}清理后空间仍不足。",
                )
            if auto_delete:
                paths.extend(plan.delete_paths)
            elif plan.delete_paths:
                raise _UpgradeRunError(
                    "cleanup_required",
                    f"{label}需要清理旧包，但自动删除已关闭。",
                )
        return paths

    @staticmethod
    def _require_package(
        output: str,
        storage: str,
        package_name: str,
        package_size: int,
        label: str,
        driver: UpgradeDriver,
    ) -> None:
        if not driver.package_is_present(
            output,
            storage=storage,
            package_name=package_name,
            package_size=package_size,
        ):
            raise _UpgradeRunError(
                "package_verification_failed",
                f"{label}未确认到目标系统包，或文件大小校验失败。",
            )

    @classmethod
    def _require_completed(cls, result: dict[str, object], label: str) -> None:
        status = str(result.get("status") or "")
        if status == "completed":
            return
        if status in {"cancelled", "cancelled_by_user"}:
            raise _UpgradeRunError("package_upgrade_cancelled", "系统包升级已取消。")
        if status == "timed_out":
            raise _UpgradeRunError("package_upgrade_timeout", f"{label}超时。")
        raise _UpgradeRunError(
            "package_upgrade_command_failed",
            str(result.get("message") or f"{label}失败。"),
        )

    @staticmethod
    def _result_output(result: dict[str, object]) -> str:
        return "".join(
            str(step.get("output") or "")
            for step in result.get("steps", [])
            if isinstance(step, dict)
        )

    def _cancel_task(self, operation_id: str, session_id: str) -> None:
        self._executor.cancel_active(session_id)
        self._executor.release(session_id, f"package-upgrade:{operation_id}")
        approval = self._reboot_approvals.get(operation_id)
        if approval is not None:
            approval.set()
        task = self._tasks.get(operation_id)
        if task is not None and not task.done():
            task.cancel()
        self._mark_cancelled(operation_id)

    def _mark_cancelled(self, operation_id: str) -> None:
        record = self._operations.get(operation_id)
        if record.status in TERMINAL_OPERATION_STATUSES:
            return
        self._operations.update(
            operation_id,
            status="cancelled",
            stage="cancelled",
            message="系统包升级已取消。",
            error_code="package_upgrade_cancelled",
        )

    def _mark_failed(self, operation_id: str, code: str, message: str) -> None:
        record = self._operations.get(operation_id)
        if record.status in TERMINAL_OPERATION_STATUSES:
            return
        if code == "package_upgrade_cancelled":
            self._mark_cancelled(operation_id)
            return
        self._operations.update(
            operation_id,
            status="failed",
            stage=record.stage,
            message=message,
            error_code=code,
        )

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


class _UpgradeRunError(PackageUpgradeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message, details={"upgrade_code": code})
        self.code = code
