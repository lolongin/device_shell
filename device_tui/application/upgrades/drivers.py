"""Vendor-specific device upgrade drivers.

The workflow service owns orchestration and policy. Drivers own device CLI
syntax, output parsing, topology detection, and artifact verification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .package import (
    DEFAULT_MASTER_STORAGE,
    DEFAULT_SLAVE_STORAGE,
    PackageUpgradeConfig,
    STANDBY_STORAGE_ABSENT,
    STANDBY_STORAGE_AVAILABLE,
    StartupInfo,
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
from device_tui.infrastructure.transfers.managed_file_transfer import TransferInteractionProfile


@dataclass(frozen=True, slots=True)
class UpgradeTargetFacts:
    device_id: str
    vendor: str = ""
    model: str = ""
    platform: str = ""


@dataclass(frozen=True, slots=True)
class UpgradeCleanupDecision:
    delete_paths: tuple[str, ...]
    has_enough_space: bool
    free_bytes: int
    required_bytes: int
    reclaim_bytes: int


@dataclass(frozen=True, slots=True)
class UpgradeManualPlan:
    commands: tuple[str, ...]
    cleanup_paths: tuple[str, ...]
    notes: tuple[str, ...]


class UpgradeDriver(Protocol):
    id: str
    display_name: str
    artifact_suffixes: tuple[str, ...]
    default_primary_storage: str
    default_standby_storage: str

    def matches(self, target: UpgradeTargetFacts) -> bool: ...
    def validate_artifact(self, path: Path) -> None: ...
    def disable_paging_command(self) -> str: ...
    def version_query_command(self) -> str: ...
    def startup_query_command(self) -> str: ...
    def storage_query_command(self, storage: str) -> str: ...
    def package_path(self, storage: str, package_name: str) -> str: ...
    def classify_standby(self, output: str, storage: str) -> str: ...
    def cleanup_plan(self, *, storage: str, output: str, startup_output: str, package_name: str, package_size: int) -> UpgradeCleanupDecision: ...
    def cleanup_command(self, path: str) -> str: ...
    def package_is_present(self, output: str, *, storage: str, package_name: str, package_size: int) -> bool: ...
    def sync_commands(self, primary_package: str, standby_package: str) -> tuple[str, ...]: ...
    def activation_commands(self, primary_package: str, standby_package: str, include_standby: bool) -> tuple[tuple[str, ...], tuple[str, ...]]: ...
    def startup_uses_artifact(self, output: str, package_name: str) -> bool: ...
    def failure_marker(self, output: str) -> str: ...
    def reboot_plan_steps(self) -> tuple[dict[str, object], ...]: ...
    def manual_plan(self, config: PackageUpgradeConfig) -> UpgradeManualPlan: ...
    def transfer_profile(self, protocol: str, terminal_environment: str = "vrp") -> TransferInteractionProfile: ...


class HuaweiVrpUpgradeDriver:
    id = "huawei-vrp"
    display_name = "Huawei VRP"
    artifact_suffixes = (".cc",)
    default_primary_storage = DEFAULT_MASTER_STORAGE
    default_standby_storage = DEFAULT_SLAVE_STORAGE

    def matches(self, target: UpgradeTargetFacts) -> bool:
        identity = " ".join((target.vendor, target.model, target.platform)).casefold()
        return "huawei" in identity or "vrp" in identity

    def validate_artifact(self, path: Path) -> None:
        if path.suffix.casefold() not in self.artifact_suffixes:
            raise ValueError("Huawei VRP upgrades require a .cc system package.")

    @staticmethod
    def disable_paging_command() -> str:
        return "screen-length 0 temporary"

    @staticmethod
    def version_query_command() -> str:
        return "display version"

    @staticmethod
    def startup_query_command() -> str:
        return "display startup"

    @staticmethod
    def storage_query_command(storage: str) -> str:
        return f"dir {storage}"

    @staticmethod
    def package_path(storage: str, package_name: str) -> str:
        return join_storage_path(storage, package_name)

    @staticmethod
    def classify_standby(output: str, storage: str) -> str:
        return classify_standby_storage(output, storage)

    @staticmethod
    def cleanup_plan(
        *,
        storage: str,
        output: str,
        startup_output: str,
        package_name: str,
        package_size: int,
    ) -> UpgradeCleanupDecision:
        plan = build_cleanup_plan(
            storage=storage,
            free_bytes=parse_free_space_bytes(output),
            target_bytes=package_size,
            entries=parse_dir_entries(output, storage),
            startup=parse_display_startup(startup_output),
            target_package_name=package_name,
        )
        return UpgradeCleanupDecision(
            delete_paths=tuple(item.path for item in plan.delete_entries),
            has_enough_space=plan.has_enough_space,
            free_bytes=plan.free_bytes,
            required_bytes=plan.required_bytes,
            reclaim_bytes=plan.reclaim_bytes,
        )

    @staticmethod
    def cleanup_command(path: str) -> str:
        return f"delete /unreserved /quiet {path}"

    @staticmethod
    def package_is_present(
        output: str,
        *,
        storage: str,
        package_name: str,
        package_size: int,
    ) -> bool:
        return dir_contains_package(
            output,
            storage=storage,
            package_name=package_name,
            expected_size=package_size,
        )

    @staticmethod
    def sync_commands(primary_package: str, standby_package: str) -> tuple[str, ...]:
        return (f"copy {primary_package} {standby_package}",)

    @staticmethod
    def activation_commands(
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
    def startup_uses_artifact(output: str, package_name: str) -> bool:
        return startup_uses_package(output, package_name)

    @staticmethod
    def failure_marker(output: str) -> str:
        return find_upgrade_failure(output)

    @staticmethod
    def reboot_plan_steps() -> tuple[dict[str, object], ...]:
        return (
            {"type": "send", "text": "reboot", "label": "发送 reboot"},
            {
                "type": "expect",
                "success": ["device_prompt", "login_prompt", "username_prompt"],
                "failures": [],
                # VRP can emit more than one confirmation while rebooting;
                # handle those terminal prompts automatically.
                "responses": [
                    {"match": "confirmation_prompt", "text": "y", "max_matches": 3},
                ],
                "disconnect_is_success": True,
                "timeout_seconds": 180,
                "label": "等待设备重启完成",
                "max_output_chars": 32_768,
            },
        )

    @staticmethod
    def manual_plan(config: PackageUpgradeConfig) -> UpgradeManualPlan:
        plan = generate_huawei_upgrade_plan(config)
        return UpgradeManualPlan(tuple(plan.commands), tuple(plan.cleanup_paths), tuple(plan.notes))

    @staticmethod
    def transfer_profile(protocol: str, terminal_environment: str = "vrp") -> TransferInteractionProfile:
        # Keep terminal vocabulary in the selected driver so vendor/client
        # differences do not leak into the generic transfer builder.
        return TransferInteractionProfile(id=f"huawei-vrp-{protocol.casefold()}")


class SimulatedVrpUpgradeDriver(HuaweiVrpUpgradeDriver):
    """VRP-compatible driver for the built-in simulator.

    The simulator intentionally exposes the same command vocabulary as the
    Huawei workflow, but its device identity is ``SIM-TERMINAL``/``SimOS``.
    Keeping that identity match in a separate driver prevents the generic
    Huawei driver from being selected for an unrelated real vendor.
    """

    id = "simulated-vrp"
    display_name = "Simulated VRP"

    def matches(self, target: UpgradeTargetFacts) -> bool:
        identity = " ".join((target.device_id, target.vendor, target.model, target.platform)).casefold()
        return (
            target.device_id.casefold() == "sim-terminal"
            or "simos" in identity
            or "simulated" in identity
        )


class UpgradeDriverRegistry:
    def __init__(self, drivers: tuple[UpgradeDriver, ...] | None = None) -> None:
        self._drivers = tuple(drivers or (SimulatedVrpUpgradeDriver(), HuaweiVrpUpgradeDriver()))

    def get(self, driver_id: str) -> UpgradeDriver:
        for driver in self._drivers:
            if driver.id == driver_id:
                return driver
        raise KeyError(driver_id)

    def resolve(self, target: UpgradeTargetFacts, requested: str = "") -> UpgradeDriver:
        if requested and requested != "auto":
            return self.get(requested)
        for driver in self._drivers:
            if driver.matches(target):
                return driver
        # Only use the legacy default when the source supplied no identity at
        # all. Never run a Huawei CLI plan against a known non-Huawei target.
        if not any((target.vendor, target.model, target.platform)):
            return self._drivers[0]
        raise KeyError(f"No upgrade driver matched target {target.device_id}")


__all__ = [
    "HuaweiVrpUpgradeDriver",
    "SimulatedVrpUpgradeDriver",
    "UpgradeCleanupDecision",
    "UpgradeDriver",
    "UpgradeDriverRegistry",
    "UpgradeManualPlan",
    "UpgradeTargetFacts",
]
