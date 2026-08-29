"""Unified Agent/Workflow MCP capabilities.

These functions are a thin transport layer. They do not import or expose a
WorkflowEngine; all state changes go through the Backend MCP facade.
"""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_workflow_task_tools(mcp: Any, gateway: McpGateway) -> None:
    @mcp.tool(name="task.create")
    def task_create(
        workflow_id: str,
        device_id: str,
        package: str = "",
        options: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        protocol: str = "auto",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a backend Task; the caller acts as an Agent operator."""
        return gateway.call(
            "mcp_tool",
            "task.create",
            workflow_id=workflow_id,
            device_id=device_id,
            package=package,
            options=options or {},
            parameters=parameters or {},
            protocol=protocol,
            context=context or {},
            source="agent",
        )

    @mcp.tool(name="task.get")
    def task_get(task_id: str) -> dict[str, Any]:
        """Read a Task, checkpoint, step results, and current status."""
        return gateway.call("mcp_tool", "task.get", task_id=task_id)

    @mcp.tool(name="task.list")
    def task_list(limit: int = 200) -> dict[str, Any]:
        """List backend Tasks."""
        return gateway.call("mcp_tool", "task.list", limit=limit)

    @mcp.tool(name="task.framework.start")
    def task_framework_start(
        plan: dict[str, Any],
        device_id: str,
        inputs: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        task_run_id: str = "",
    ) -> dict[str, Any]:
        """Create a generic Task that composes reusable Workflow providers."""
        return gateway.call(
            "mcp_tool",
            "task.framework.start",
            plan=plan,
            device_id=device_id,
            inputs=inputs or {},
            context=context or {},
            task_run_id=task_run_id,
        )

    @mcp.tool(name="task.framework.execute")
    def task_framework_execute(task_run_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        """Execute a generic Task until terminal or recovery/decision state."""
        return gateway.call(
            "mcp_tool",
            "task.framework.execute",
            task_run_id=task_run_id,
            plan=plan,
        )

    @mcp.tool(name="task.framework.get")
    def task_framework_get(task_run_id: str) -> dict[str, Any]:
        """Read generic TaskRun composition state and child Workflow outputs."""
        return gateway.call("mcp_tool", "task.framework.get", task_run_id=task_run_id)

    @mcp.tool(name="task.resume")
    def task_resume(task_id: str, step_id: str = "", context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resume a paused or failed Task from its checkpoint."""
        return gateway.call("mcp_tool", "task.resume", task_id=task_id, step_id=step_id, context=context or {})

    @mcp.tool(name="task.cancel")
    def task_cancel(task_id: str) -> dict[str, Any]:
        """Cancel a backend Task."""
        return gateway.call("mcp_tool", "task.cancel", task_id=task_id)

    @mcp.tool(name="task.pause")
    def task_pause(task_id: str) -> dict[str, Any]:
        """Pause a backend Task at its checkpoint."""
        return gateway.call("mcp_tool", "task.pause", task_id=task_id)

    @mcp.tool(name="workflow.list")
    def workflow_list() -> dict[str, Any]:
        """List workflow definitions without returning runtime Engine objects."""
        return gateway.call("mcp_tool", "workflow.list")

    @mcp.tool(name="workflow.plan.validate")
    def workflow_plan_validate(plan: dict[str, Any]) -> dict[str, Any]:
        """Validate and compile an Agent-authored declarative workflow plan."""
        return gateway.call("mcp_tool", "workflow.plan.validate", plan=plan, source="agent")

    @mcp.tool(name="workflow.plan.get")
    def workflow_plan_get(plan_id: str) -> dict[str, Any]:
        """Read a previously validated workflow plan and its policy result."""
        return gateway.call("mcp_tool", "workflow.plan.get", plan_id=plan_id)

    @mcp.tool(name="workflow.plan.approve")
    def workflow_plan_approve(plan_id: str, reason: str = "", plan_hash: str = "") -> dict[str, Any]:
        """Approve a validated high-risk plan before it is run."""
        return gateway.call("mcp_tool", "workflow.plan.approve", plan_id=plan_id, plan_hash=plan_hash, reason=reason, actor_type="user")

    @mcp.tool(name="workflow.run")
    def workflow_run(
        workflow_id: str = "",
        device_id: str = "",
        package: str = "",
        options: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        protocol: str = "auto",
        context: dict[str, Any] | None = None,
        plan_id: str = "",
        plan_hash: str = "",
    ) -> dict[str, Any]:
        """Start a validated plan or named workflow as a Task through Backend."""
        return gateway.call(
            "mcp_tool",
            "workflow.run",
            workflow_id=workflow_id,
            device_id=device_id,
            package=package,
            options=options or {},
            parameters=parameters or {},
            protocol=protocol,
            context=context or {},
            plan_id=plan_id,
            plan_hash=plan_hash,
            source="agent",
        )

    @mcp.tool(name="task.replan")
    def task_replan(
        parent_task_id: str,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate and run a new plan linked to a failed or completed task."""
        return gateway.call("mcp_tool", "task.replan", parent_task_id=parent_task_id, plan=plan, source="agent")

    @mcp.tool(name="decision.get")
    def decision_get(task_id: str) -> dict[str, Any]:
        """Get the structured DecisionContext for a waiting Task."""
        return gateway.call("mcp_tool", "decision.get", task_id=task_id)

    @mcp.tool(name="decision.apply")
    def decision_apply(
        task_id: str,
        action: dict[str, Any],
        reason: str = "",
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Apply a structured Agent Decision through the Backend API."""
        return gateway.call(
            "mcp_tool",
            "decision.apply",
            task_id=task_id,
            action=action,
            reason=reason,
            expected_revision=expected_revision,
            actor_type="agent",
            actor_id="agent",
        )

    @mcp.tool(name="tool.execute")
    def tool_execute(name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute an allowed diagnostic Backend Tool, never a Workflow Engine method."""
        return gateway.call("mcp_tool", "tool.execute", name=name, params=params or {})
