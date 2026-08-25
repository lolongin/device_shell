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
    retry = lambda attempts: {"max_attempts": max(1, int(attempts)), "deterministic": True, "retryable": True}
    topology_policy = str(opts.get("topology_policy") or "auto")
    cleanup_policy = str(opts.get("cleanup_policy") or "never")
    activation_policy = str(opts.get("activation_policy") or "stage_only")
    if topology_policy not in {"auto", "single", "required"}:
        raise ValueError("topology_policy must be auto, single, or required")
    if cleanup_policy not in {"never", "auto"}:
        raise ValueError("cleanup_policy must be never or auto")
    if activation_policy not in {"stage_only", "reboot"}:
        raise ValueError("activation_policy must be stage_only or reboot")
    package_source = str(opts.get("package_source") or "local")
    recovery_protocol = str(opts.get("recovery_protocol") or "").casefold()
    if package_source not in {"local", "device"}:
        raise ValueError("package_source must be local or device")
    if recovery_protocol not in {"", "same", "auto", "ssh", "telnet", "serial"}:
        raise ValueError("recovery_protocol must be same, auto, ssh, telnet, or serial")
    prepare = WorkflowStep(
        "prepare_upgrade",
        kind="device",
        action=Action("prepare_upgrade", risk="high", confirmation_required=True),
        params={
            "device_id": device_id,
            "package_path": package,
            "package_source": package_source,
            "include_slave": topology_policy != "single",
            "standby_required": topology_policy == "required",
            "auto_delete_old_packages": cleanup_policy == "auto",
            "reboot_after_setting": False,
            "wait": True,
            "driver_id": str(opts.get("driver_id") or "auto"),
            "master_storage": str(opts.get("master_storage") or ""),
            "slave_storage": str(opts.get("slave_storage") or ""),
            "timeout_seconds": int(opts.get("prepare_timeout_seconds") or 900),
        },
        retry_policy=retry(2),
        metadata={"phase": "prepare", "result_state": "staged"},
    )
    steps: list[WorkflowStep] = [prepare]
    if activation_policy == "reboot":
        steps.extend((
            # ``prepare_upgrade`` is the workflow approval boundary. Once the
            # operator selected ``reboot`` and approved preparation, keeping a
            # second confirmation here leaves the task permanently waiting
            # after the startup item is set instead of running activation.
            WorkflowStep("reboot", kind="device", action=Action("reboot", risk="high", confirmation_required=False), depends_on=("prepare_upgrade",), params={"device_id": device_id, "timeout_seconds": opts.get("reboot_timeout_seconds", 190)}, retry_policy=retry(2), metadata={"phase": "activate"}),
            WorkflowStep("wait_online", kind="device", action="wait_online", depends_on=("reboot",), params={"device_id": device_id, "recovery_protocol": recovery_protocol, "timeout_seconds": opts.get("online_timeout_seconds", 180)}, retry_policy=retry(3), metadata={"phase": "recover"}),
            WorkflowStep("verify_version", kind="device", action="verify_version", depends_on=("wait_online",), params={"device_id": device_id, "commands": opts.get("version_commands", ("display version",)), "expected_version": opts.get("expected_version", "")}, retry_policy=retry(2), metadata={"phase": "verify"}),
            WorkflowStep("validation", kind="device", action="validation", depends_on=("verify_version",), params={"device_id": device_id, "commands": opts.get("validation_commands", ("display version",))}, retry_policy={"terminal": True}, metadata={"phase": "postcheck"}),
        ))
    return WorkflowDefinition(
        id="device_upgrade", name="Device upgrade", description="Driver-backed checkpointed device upgrade",
        steps=tuple(steps), metadata={"device_id": device_id, "package": package, "options": opts, "activation_policy": activation_policy},
    )
