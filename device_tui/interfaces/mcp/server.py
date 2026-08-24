"""FastMCP entry point for the Device TUI desktop application."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .gateway import McpGateway
from .tools import register_all_tools


INSTRUCTIONS = (
    "Operate the running Device TUI application through its policy-controlled "
    "application control plane. Discover the available resources with "
    "app.capabilities. The public MCP surface includes app, device, session, "
    "source, profile, command, automation, transfer, and namespaced "
    "Task/Workflow/Decision "
    "capabilities: task.create, task.get, task.list, task.resume, task.cancel, "
    "workflow.list, workflow.plan.validate, workflow.plan.get, "
    "workflow.plan.approve, workflow.run, "
    "task.replan, decision.get, decision.apply, and "
    "tool.execute. Use workflow.run for a named workflow and task.create for a "
    "generic Task. Use tool.execute only for an allow-listed diagnostic backend "
    "tool; it is not a way to call Workflow Engine methods. An Agent is an "
    "operator: first submit a declarative WorkflowPlan for backend validation, "
    "then run only the returned validated plan. Inspect Task and "
    "DecisionContext, return a structured action and reason, then apply it "
    "through decision.apply. Use task.replan for a new revision; never mutate "
    "WorkflowEngine state or invent device business logic in MCP. For package "
    "replacement, use the named device_upgrade workflow through workflow.run "
    "or task.create; package.upgrade is not a declarative plan capability."
)


gateway = McpGateway()
mcp = FastMCP("Device TUI", instructions=INSTRUCTIONS)
register_all_tools(mcp, gateway)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
