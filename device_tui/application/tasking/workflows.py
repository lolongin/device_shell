"""Reusable workflow definitions for common device operations."""

from __future__ import annotations

from typing import Any

from .models import Action, WorkflowDefinition, WorkflowStep


def device_upgrade_workflow(
    *,
    device_id: str,
    package: str,
    options: dict[str, Any] | None = None,
) -> WorkflowDefinition:
    """Build the canonical resumable device upgrade workflow.

    This function only produces protocol data.  All device-side work is
    performed by ``DeviceExecutionTool`` through ``DeviceControlService``.
    """
    if not str(device_id).strip():
        raise ValueError("device_id is required")
    if not str(package).strip():
        raise ValueError("package is required")
    opts = dict(options or {})
    package_name = str(package).replace("\\", "/").rsplit("/", 1)[-1]
    destination = str(opts.get("destination_path") or f"flash:/{package_name}")
    retry = lambda attempts: {"max_attempts": max(1, int(attempts)), "deterministic": True, "retryable": True}
    steps = (
        WorkflowStep("precheck", kind="device", action="precheck", params={"device_id": device_id, "commands": opts.get("precheck_commands", ("display version",)), "timeout_seconds": opts.get("timeout_seconds", 30)}, retry_policy={"terminal": True}),
        WorkflowStep("backup", kind="device", action="backup", depends_on=("precheck",), params={"device_id": device_id, "commands": opts.get("backup_commands", ("display startup",))}),
        WorkflowStep("upload", kind="device", action="upload", depends_on=("backup",), params={"device_id": device_id, "package": package, "source_path": package, "destination_path": destination, "overwrite": bool(opts.get("overwrite", True)), "timeout_seconds": opts.get("upload_timeout_seconds", 300)}, retry_policy=retry(3)),
        WorkflowStep("verify", kind="device", action="verify", depends_on=("upload",), params={"device_id": device_id, "commands": opts.get("verify_commands", (f"dir {destination}",))}, retry_policy=retry(2)),
        WorkflowStep("activate", kind="device", action="activate", depends_on=("verify",), params={"device_id": device_id, "commands": opts.get("activate_commands", (str(opts.get("activate_command") or f"startup system-software {destination}"),))}, retry_policy=retry(2)),
        WorkflowStep("reboot", kind="device", action=Action("reboot", risk="high", confirmation_required=True), depends_on=("activate",), params={"device_id": device_id, "timeout_seconds": opts.get("reboot_timeout_seconds", 190)}, retry_policy=retry(2)),
        WorkflowStep("wait_online", kind="device", action="wait_online", depends_on=("reboot",), params={"device_id": device_id, "timeout_seconds": opts.get("online_timeout_seconds", 180)}, retry_policy=retry(3)),
        WorkflowStep("verify_version", kind="device", action="verify_version", depends_on=("wait_online",), params={"device_id": device_id, "commands": opts.get("version_commands", ("display version",)), "expected_version": opts.get("expected_version", "")}, retry_policy=retry(2)),
        # The simulator supports ``display version`` as a healthy validation
        # probe.  Callers can override this with an unsupported command to
        # exercise terminal workflow failure handling.
        WorkflowStep("validation", kind="device", action="validation", depends_on=("verify_version",), params={"device_id": device_id, "commands": opts.get("validation_commands", ("display version",))}, retry_policy={"terminal": True}),
    )
    return WorkflowDefinition(
        id="device_upgrade", name="Device upgrade", description="Checkpointed device package upgrade",
        steps=steps, metadata={"device_id": device_id, "package": package, "options": opts},
    )


def package_upgrade_workflow(
    *,
    package_path: str,
    include_slave: bool = True,
    auto_delete_old_packages: bool = True,
    reboot_after_setting: bool = False,
    approve_reboot: bool = False,
    timeout_seconds: int = 900,
    master_storage: str = "flash:",
    slave_storage: str = "slave#flash:",
) -> WorkflowDefinition:
    """Build the standard verified package replacement workflow.

    The detailed precheck, cleanup, transfer, verification, startup-setting,
    reboot approval and reconnect logic remains owned by PackageUpgradeService.
    """

    params: dict[str, Any] = {
        "package_path": package_path,
        "include_slave": include_slave,
        "auto_delete_old_packages": auto_delete_old_packages,
        "reboot_after_setting": reboot_after_setting,
        "approve_reboot": approve_reboot,
        "timeout_seconds": timeout_seconds,
        "wait": True,
        "master_storage": master_storage,
        "slave_storage": slave_storage,
    }
    return WorkflowDefinition(
        id="package-upgrade",
        steps=(WorkflowStep(id="upgrade", kind="execution", action="package_upgrade", params=params),),
    )
