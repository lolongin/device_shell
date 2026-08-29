"""Application service for package-upgrade workflow support."""

from __future__ import annotations

from dataclasses import dataclass
import re

from device_tui.application.errors import (
    ApplicationConflictError,
    ResourceNotFoundError,
    UnsupportedOperationError,
)
from device_tui.application.devices import DeviceService
from device_tui.application.sessions import SessionRecord, SessionService
from device_tui.application.transfers import (
    ManagedTransferService,
    PreparedTransferSource,
)
from .policy import (
    PackageFileEntry,
    PackageUpgradeConfig,
    build_cleanup_plan,
    package_basename,
)
from device_tui.infrastructure.vendor_adapters.huawei_vrp.parsers import (
    DEFAULT_MASTER_STORAGE,
    DEFAULT_SLAVE_STORAGE,
    parse_dir_entries,
    parse_display_startup,
    parse_free_space_bytes,
)
from device_tui.infrastructure.vendor_adapters.huawei_vrp.drivers import (
    UpgradeDriver,
    UpgradeDriverRegistry,
    UpgradeTargetFacts,
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
    """Manual package-upgrade fallback support.

    Automatic package upgrades are executed exclusively by ``WorkflowRuntime``
    through ``TaskManager``. This service intentionally has no scheduler,
    workflow runner, or operation projection.
    """

    def __init__(
        self,
        sessions: SessionService,
        transfers: ManagedTransferService,
        devices: DeviceService | None = None,
        drivers: UpgradeDriverRegistry | None = None,
    ) -> None:
        self._sessions = sessions
        self._transfers = transfers
        self._devices = devices
        self._drivers = drivers or UpgradeDriverRegistry()
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
        """Keep a uniform application lifecycle hook for manual support."""
        return None

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
