from __future__ import annotations

from device_tui.application.workflows import HuaweiVrpPackageUpgradeProvider


def test_huawei_package_provider_declares_the_single_executable_path() -> None:
    workflow = HuaweiVrpPackageUpgradeProvider().build({
        "package_ref": "images/router-v2.cc",
        "expected_version": "VRP V8",
        "validation_commands": ["display version"],
        "activation_policy": "reboot",
        "auto_reboot": False,
        "topology_policy": "auto",
    })

    assert workflow.id == "network.package_upgrade"
    assert [state.id for state in workflow.states] == [
        "precheck", "cleanup", "transfer", "verify_package",
        "sync_standby", "configure_startup", "reboot_approval", "reboot",
        "wait_online", "verify_version", "validation", "rollback", "complete",
    ]
    reboot_approval = next(state for state in workflow.states if state.id == "reboot_approval")
    assert [option.id for option in reboot_approval.decision_options] == [
        "approve_reboot", "abort_reboot",
    ]
    configure_startup = next(state for state in workflow.states if state.id == "configure_startup")
    assert configure_startup.action is not None
    assert [item.event_type for item in configure_startup.action.expectations] == [
        "framework.action.sent",
        "huawei.startup.command.completed",
        "huawei.startup.verified",
    ]


def test_huawei_package_provider_omits_transfer_for_device_resident_package() -> None:
    workflow = HuaweiVrpPackageUpgradeProvider().build({
        "package_ref": "flash:/router-v2.cc",
        "package_source": "device",
        "activation_policy": "stage_only",
    })

    assert "ftp_login" not in {state.id for state in workflow.states}
    assert "transfer" not in {state.id for state in workflow.states}
    assert workflow.states[-1].id == "complete"


def test_huawei_package_provider_can_auto_reboot_without_approval_state() -> None:
    workflow = HuaweiVrpPackageUpgradeProvider().build({
        "package_ref": "flash:/router-v2.cc",
        "package_source": "device",
        "activation_policy": "reboot",
        "auto_reboot": True,
    })

    configure = next(state for state in workflow.states if state.id == "configure_startup")
    assert configure.next_state == "reboot"


def test_huawei_package_provider_defaults_to_automatic_reboot() -> None:
    workflow = HuaweiVrpPackageUpgradeProvider().build({
        "package_ref": "flash:/router-v2.cc",
        "activation_policy": "reboot",
    })

    configure = next(state for state in workflow.states if state.id == "configure_startup")
    assert configure.next_state == "reboot"
