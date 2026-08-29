"""Workflow providers backed directly by vendor-neutral Activities."""

from __future__ import annotations

from typing import Any

from device_tui.framework import ActionSpec, StateNode, WorkflowDefinition


class ActivityWorkflowProvider:
    """Expose one reusable Activity as a one-step Workflow.

    The marker in ``ActionSpec.params`` lets the compatibility ActionRegistry
    route this invocation to the ActivityExecutor even when a legacy operation
    with the same public id is still registered.
    """

    def __init__(self, activity_id: str, *, required_capabilities: tuple[str, ...] = ()) -> None:
        self.id = activity_id
        self.version = "1"
        self._required_capabilities = required_capabilities

    def build(self, inputs: dict[str, Any]) -> WorkflowDefinition:
        params = dict(inputs)
        params["_framework_activity"] = True
        action = ActionSpec(
            id="run",
            operation=self.id,
            params=params,
            timeout_seconds=float(params.get("timeout_seconds") or 3_600),
            # ActivityDefinition owns the idempotency classification (including
            # unsafe reboot); this compatibility Action must remain valid
            # without a vendor-specific reconcile provider.
            risk="normal",
        )
        return WorkflowDefinition(
            id=self.id,
            version=self.version,
            start_state="run",
            required_capabilities=self._required_capabilities,
            states=(
                StateNode("run", action, next_state="complete"),
                StateNode("complete", terminal=True),
            ),
        )


def build_default_activity_workflow_providers() -> tuple[ActivityWorkflowProvider, ...]:
    return (
        ActivityWorkflowProvider("script.run"),
        ActivityWorkflowProvider("artifact.build"),
        ActivityWorkflowProvider("file.transfer", required_capabilities=("file.transfer",)),
        ActivityWorkflowProvider("device.reboot", required_capabilities=("device.reboot",)),
        ActivityWorkflowProvider("device.wait_online"),
        ActivityWorkflowProvider("device.verify_version"),
        ActivityWorkflowProvider("device.verify_artifact"),
        ActivityWorkflowProvider("device.storage.cleanup"),
        ActivityWorkflowProvider("device.storage.sync"),
        ActivityWorkflowProvider("device.startup.configure"),
        ActivityWorkflowProvider("device.startup.rollback"),
    )


__all__ = ["ActivityWorkflowProvider", "build_default_activity_workflow_providers"]
