"""Compatibility projection for the legacy tasking API.

The executable workflow definition lives in ``application.workflows``. This
module only preserves the old tasking step contract for existing clients.
"""

from __future__ import annotations

from typing import Any

from device_tui.application.workflows import HuaweiVrpPackageUpgradeProvider

from .models import Action, WorkflowDefinition, WorkflowStep


def device_upgrade_workflow(
    *,
    device_id: str,
    package: str,
    options: dict[str, Any] | None = None,
) -> WorkflowDefinition:
    """Return the legacy-shaped projection of the canonical package workflow."""
    if not str(device_id).strip():
        raise ValueError("device_id is required")
    if not str(package).strip():
        raise ValueError("package is required")

    values = dict(options or {})
    activation_policy = str(values.get("activation_policy") or "stage_only").casefold()
    canonical = HuaweiVrpPackageUpgradeProvider().build({
        **values,
        "package_ref": package,
        "expected_version": str(values.get("expected_version") or ""),
        "activation_policy": activation_policy,
    })
    by_id = {state.id: state for state in canonical.states}
    prepare = WorkflowStep(
        "prepare_upgrade",
        kind="device",
        action=Action("prepare_upgrade", risk="high", confirmation_required=True),
        params={
            "device_id": device_id,
            "package_path": package,
            "package_source": values.get("package_source", "local"),
            "include_slave": values.get("topology_policy", "auto") != "single",
            "standby_required": values.get("topology_policy", "auto") == "required",
            "auto_delete_old_packages": values.get("cleanup_policy", "never") == "auto",
            "reboot_after_setting": False,
            "wait": True,
            "driver_id": str(values.get("driver_id") or "auto"),
            "master_storage": str(values.get("master_storage") or ""),
            "slave_storage": str(values.get("slave_storage") or ""),
            "timeout_seconds": int(values.get("prepare_timeout_seconds") or 900),
        },
        retry_policy={"max_attempts": 2, "deterministic": True, "retryable": True},
        metadata={"phase": "prepare", "result_state": "staged", "canonical_state": by_id["configure_startup"].id},
    )
    steps = [prepare]
    if activation_policy == "reboot":
        steps.extend((
            WorkflowStep(
                "reboot", kind="device",
                action=Action("reboot", risk="high", confirmation_required=False),
                depends_on=("prepare_upgrade",),
                params={"device_id": device_id, "timeout_seconds": values.get("reboot_timeout_seconds", 190)},
                retry_policy={"max_attempts": 2, "deterministic": True, "retryable": True},
                metadata={"phase": "activate", "canonical_state": by_id["reboot"].id},
            ),
            WorkflowStep(
                "wait_online", kind="device", action="wait_online", depends_on=("reboot",),
                params={"device_id": device_id, "recovery_protocol": str(values.get("recovery_protocol") or "").casefold(), "timeout_seconds": values.get("online_timeout_seconds", 180)},
                retry_policy={"max_attempts": 3, "deterministic": True, "retryable": True},
                metadata={"phase": "recover", "canonical_state": by_id["wait_online"].id},
            ),
            WorkflowStep(
                "verify_version", kind="device", action="verify_version", depends_on=("wait_online",),
                params={"device_id": device_id, "commands": values.get("version_commands", ("display version",)), "expected_version": values.get("expected_version", "")},
                retry_policy={"max_attempts": 2, "deterministic": True, "retryable": True},
                metadata={"phase": "verify", "canonical_state": by_id["verify_version"].id},
            ),
            WorkflowStep(
                "validation", kind="device", action="validation", depends_on=("verify_version",),
                params={"device_id": device_id, "commands": values.get("validation_commands", ("display version",))},
                retry_policy={"terminal": True},
                metadata={"phase": "postcheck", "canonical_state": by_id["validation"].id},
            ),
        ))
    return WorkflowDefinition(
        id="device_upgrade",
        name="Device upgrade",
        description="Driver-backed checkpointed device upgrade",
        steps=tuple(steps),
        metadata={
            "device_id": device_id,
            "package": package,
            "options": values,
            "activation_policy": activation_policy,
            "canonical_workflow_id": canonical.id,
            "canonical_workflow_version": canonical.version,
        },
    )
