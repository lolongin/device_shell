from pathlib import Path

import pytest

from device_tui.application.upgrades.drivers import (
    HuaweiVrpUpgradeDriver,
    SimulatedVrpUpgradeDriver,
    UpgradeDriverRegistry,
    UpgradeTargetFacts,
)
from device_tui.application.upgrades.commands import HuaweiVrpCommandSet
from device_tui.application.upgrades.package import PackageUpgradeConfig
from device_tui.infrastructure.vendor_adapters.huawei_vrp import (
    HuaweiVrpCommandSet as VendorHuaweiVrpCommandSet,
    HuaweiVrpUpgradeDriver as VendorHuaweiVrpUpgradeDriver,
)


def test_registry_matches_huawei_and_rejects_known_unknown_vendor() -> None:
    registry = UpgradeDriverRegistry()
    assert registry.resolve(UpgradeTargetFacts("d", vendor="Huawei"), "auto").id == "huawei-vrp"
    assert registry.resolve(UpgradeTargetFacts("SIM-TERMINAL", vendor="本地", model="终端"), "auto").id == "simulated-vrp"
    with pytest.raises(KeyError):
        registry.resolve(UpgradeTargetFacts("d", vendor="Cisco"), "auto")


def test_vendor_adapter_is_the_canonical_home_for_huawei_implementations() -> None:
    assert HuaweiVrpCommandSet is VendorHuaweiVrpCommandSet
    assert HuaweiVrpUpgradeDriver is VendorHuaweiVrpUpgradeDriver
    assert HuaweiVrpCommandSet.__module__.startswith("device_tui.infrastructure.vendor_adapters.")
    assert HuaweiVrpUpgradeDriver.__module__.startswith("device_tui.infrastructure.vendor_adapters.")


def test_huawei_driver_owns_commands_and_artifact_policy() -> None:
    driver = HuaweiVrpUpgradeDriver()
    assert driver.storage_query_command("flash:/") == "dir flash:/"
    assert driver.activation_commands("flash:/a.cc", "slave#flash:/a.cc", False)[0] == (
        "startup system-software flash:/a.cc",
    )
    with pytest.raises(ValueError):
        driver.validate_artifact(Path("target.bin"))
    reboot_expect = driver.reboot_plan_steps()[1]
    assert reboot_expect["responses"] == [
        {"match": "confirmation_prompt", "text": "y", "max_matches": 3},
    ]
    assert driver.commands.verification_plan("startup_package").commands == ("display startup",)


def test_driver_and_manual_renderer_share_the_huawei_command_set() -> None:
    config = PackageUpgradeConfig(
        package_path=Path("target.cc"),
        server_host="192.0.2.10",
        include_slave=True,
    )
    command_set = HuaweiVrpCommandSet()
    driver = HuaweiVrpUpgradeDriver()

    assert driver.manual_plan(config).commands == command_set.manual_upgrade_plan(config).commands
    assert driver.activation_commands("flash:/target.cc", "slave#flash:/target.cc", True) == command_set.activation(
        "flash:/target.cc", "slave#flash:/target.cc", True,
    )


def test_simulated_driver_reuses_vrp_command_contract() -> None:
    driver = SimulatedVrpUpgradeDriver()
    assert driver.matches(UpgradeTargetFacts("SIM-TERMINAL", vendor="本地"))
    assert driver.storage_query_command("flash:/") == "dir flash:/"
