"""Huawei VRP command vocabulary shared by automatic and manual upgrades.

Workflows describe business states.  This module is the single source for
Huawei CLI syntax and terminal interaction required by those states.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from device_tui.infrastructure.transfers.managed_file_transfer import TransferInteractionProfile

from .package import DEFAULT_MASTER_STORAGE, DEFAULT_SLAVE_STORAGE, join_storage_path

if TYPE_CHECKING:
    from .package import PackageUpgradeConfig


@dataclass(frozen=True, slots=True)
class CommandPlan:
    """A vendor command plan consumable by an executor or script renderer."""

    commands: tuple[str, ...] = ()
    steps: tuple[dict[str, Any], ...] = ()
    notes: tuple[str, ...] = ()


class HuaweiVrpCommandSet:
    """The one authoritative Huawei VRP command and interaction vocabulary."""

    id = "huawei-vrp"

    @staticmethod
    def disable_paging() -> str:
        return "screen-length 0 temporary"

    @staticmethod
    def version_query() -> str:
        return "display version"

    @staticmethod
    def startup_query() -> str:
        return "display startup"

    @staticmethod
    def device_query() -> str:
        return "display device"

    @staticmethod
    def storage_query(storage: str) -> str:
        return f"dir {storage}"

    @staticmethod
    def package_path(storage: str, package_name: str) -> str:
        return join_storage_path(storage, package_name)

    @staticmethod
    def cleanup(path: str) -> str:
        return f"delete /unreserved /quiet {path}"

    @staticmethod
    def sync(primary_package: str, standby_package: str) -> tuple[str, ...]:
        return (f"copy {primary_package} {standby_package}",)

    @staticmethod
    def activation(
        primary_package: str,
        standby_package: str,
        include_standby: bool,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        if not include_standby:
            return ((f"startup system-software {primary_package}",), ())
        return (
            (f"startup system-software {primary_package} all",),
            (
                f"startup system-software {primary_package}",
                f"startup system-software {standby_package} slave-board",
            ),
        )

    @staticmethod
    def rollback(previous_package: str) -> str:
        return f"startup system-software {previous_package}"

    def probe_plan(
        self,
        probes: tuple[str, ...] | list[str],
        *,
        master_storage: str = DEFAULT_MASTER_STORAGE,
        slave_storage: str = DEFAULT_SLAVE_STORAGE,
    ) -> CommandPlan:
        commands: list[str] = []
        for probe in probes:
            normalized = str(probe).casefold()
            probe_commands = {
                "version": (self.version_query(),),
                "startup": (self.startup_query(),),
                "storage": (self.storage_query(master_storage),),
                "topology": (self.device_query(),),
            }.get(normalized, ())
            for command in probe_commands:
                if command not in commands:
                    commands.append(command)
        return CommandPlan(commands=tuple(commands or (self.version_query(),)))

    def verification_plan(self, fact: str) -> CommandPlan:
        if fact == "startup_package":
            return CommandPlan(commands=(self.startup_query(),))
        if fact == "running_version":
            return CommandPlan(commands=(self.version_query(),))
        return CommandPlan(commands=(self.storage_query(DEFAULT_MASTER_STORAGE),))

    @staticmethod
    def ftp_connect(host: str, port: int) -> str:
        return f"ftp {host} {int(port)}"

    @staticmethod
    def sftp_connect(host: str, port: int) -> str:
        return f"sftp {host} {int(port)}"

    @staticmethod
    def binary_mode() -> str:
        return "binary"

    @staticmethod
    def download(source: str, destination: str) -> str:
        return f"get {source} {destination}"

    @staticmethod
    def quit_command() -> str:
        return "quit"

    def transfer_profile(self, protocol: str) -> TransferInteractionProfile:
        """Provide VRP interaction tokens to the generic transfer executor."""
        return TransferInteractionProfile(
            id=f"{self.id}-{protocol.casefold()}",
            connect_template="{protocol} {host} {port}",
            binary_command=self.binary_mode(),
            download_template="get {source} {destination}",
            quit_command=self.quit_command(),
        )

    def reboot_plan(self) -> CommandPlan:
        return CommandPlan(steps=(
            {"type": "send", "text": "reboot", "label": "发送 reboot"},
            {
                "type": "expect",
                "success": ["device_prompt", "login_prompt", "username_prompt"],
                "failures": [],
                "responses": [{"match": "confirmation_prompt", "text": "y", "max_matches": 3}],
                "disconnect_is_success": True,
                "timeout_seconds": 180,
                "label": "等待设备重启完成",
                "max_output_chars": 32_768,
            },
        ))

    def manual_upgrade_plan(self, config: PackageUpgradeConfig) -> CommandPlan:
        """Render the same command vocabulary for the controlled manual fallback."""
        package_name = Path(config.package_path).name
        master_package = self.package_path(config.master_storage, package_name)
        slave_package = self.package_path(config.slave_storage, package_name)
        commands: list[str] = [self.disable_paging(), self.version_query(), self.startup_query()]
        cleanup_entries = [
            entry for entry in config.cleanup_entries
            if config.auto_delete_old_packages and entry.name.casefold().endswith(".cc")
        ]
        commands.extend(self.cleanup(entry.path) for entry in cleanup_entries)
        commands.extend(self._manual_transfer_commands(config, package_name, master_package))
        if config.include_slave:
            commands.extend(self.sync(master_package, slave_package))
        commands.extend(self._verification_commands(config, master_package, slave_package))
        primary, _fallback = self.activation(master_package, slave_package, config.include_slave)
        commands.extend(primary)
        if config.include_slave:
            commands.append(
                f"# If this device does not support 'all', run: {self.activation(master_package, slave_package, True)[1][1]}"
            )
        commands.extend((self.startup_query(), "save"))
        commands.append("reboot" if config.reboot_after_setting else "# Reboot manually after confirming display startup.")
        return CommandPlan(
            commands=tuple(commands),
            notes=(
                "旧 .cc 包会在进入下载前删除，保护当前启动包、下次启动包和目标包。",
                "双主控默认使用 startup system-software <package> all；不支持时改用注释里的 slave-board 命令。",
            ),
        )

    def _manual_transfer_commands(
        self,
        config: PackageUpgradeConfig,
        package_name: str,
        master_package: str,
    ) -> tuple[str, ...]:
        if config.protocol.casefold() == "sftp":
            return (
                self.sftp_connect(config.server_host, config.port),
                config.username,
                config.password,
                self.download(package_name, master_package),
                self.quit_command(),
            )
        return (
            self.ftp_connect(config.server_host, config.port),
            config.username,
            config.password,
            self.binary_mode(),
            self.download(package_name, master_package),
            self.quit_command(),
        )

    def _verification_commands(
        self,
        config: PackageUpgradeConfig,
        master_package: str,
        slave_package: str,
    ) -> tuple[str, ...]:
        commands = [self.storage_query(master_package)]
        if config.include_slave:
            commands.append(self.storage_query(slave_package))
        if config.verify_md5:
            commands.append(f"verify /md5 {master_package}")
            if config.include_slave:
                commands.append(f"verify /md5 {slave_package}")
        return tuple(commands)


__all__ = ["CommandPlan", "HuaweiVrpCommandSet"]
