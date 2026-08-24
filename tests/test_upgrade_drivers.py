from pathlib import Path

import pytest

from device_tui.application.upgrades.drivers import (
    HuaweiVrpUpgradeDriver,
    SimulatedVrpUpgradeDriver,
    UpgradeDriverRegistry,
    UpgradeTargetFacts,
)


def test_registry_matches_huawei_and_rejects_known_unknown_vendor() -> None:
    registry = UpgradeDriverRegistry()
    assert registry.resolve(UpgradeTargetFacts("d", vendor="Huawei"), "auto").id == "huawei-vrp"
    assert registry.resolve(UpgradeTargetFacts("SIM-TERMINAL", vendor="本地", model="终端"), "auto").id == "simulated-vrp"
    with pytest.raises(KeyError):
        registry.resolve(UpgradeTargetFacts("d", vendor="Cisco"), "auto")


def test_huawei_driver_owns_commands_and_artifact_policy() -> None:
    driver = HuaweiVrpUpgradeDriver()
    assert driver.storage_query_command("flash:/") == "dir flash:/"
    assert driver.activation_commands("flash:/a.cc", "slave#flash:/a.cc", False)[0] == (
        "startup system-software flash:/a.cc",
    )
    with pytest.raises(ValueError):
        driver.validate_artifact(Path("target.bin"))


def test_simulated_driver_reuses_vrp_command_contract() -> None:
    driver = SimulatedVrpUpgradeDriver()
    assert driver.matches(UpgradeTargetFacts("SIM-TERMINAL", vendor="本地"))
    assert driver.storage_query_command("flash:/") == "dir flash:/"
