"""FastMCP entry point for the OdyTerm desktop application."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .gateway import McpGateway
from .tools import register_all_tools


INSTRUCTIONS = (
    "Operate OdyTerm through backend policy. Start with app.capabilities, then "
    "device.list filters/pagination to resolve explicit targets and workflow.list "
    "to discover supported capabilities. For one-off commands use terminal.execute; "
    "for bounded concurrent device commands use terminal.parallel; for prompts use "
    "terminal.interact.* and inspect the current prompt before responding. "
    "For composed tasks submit workflow.plan.validate, inspect errors and required "
    "actions, then workflow.run with the returned plan_id and plan_hash. Named "
    "workflows can run directly via workflow.run/task.create. For reusable fleet "
    "workflows read workflow.authoring.describe and validate/publish definitions "
    "before workflow.definition.run with device_ids. Script tests execute real commands. "
    "Observe TaskRecord IDs using task.get/task.wait. Carry returned cursors into "
    "subsequent waits, removing finished or attention tasks from the wait set. "
    "Follow next_action, inspect result evidence, and report per-device failures. "
    "Decision actions must come from available_actions and permit agent mode; "
    "send a reason and expected_revision to decision.apply. On conflict refresh "
    "task.get before deciding again. User-only decisions require user input. "
    "Failed tasks require diagnosis before resume or task.replan; do not blindly "
    "repeat commands with side effects. Framework TaskRun IDs use task.framework.get, "
    "not task.wait. Confirmation flags acknowledge risk within the user's authority; "
    "they do not grant additional authority. Never invent engine methods or expose "
    "credentials. For package replacement use named device_upgrade, not an embedded "
    "plan capability."
)


gateway = McpGateway()
mcp = FastMCP("OdyTerm", instructions=INSTRUCTIONS)
register_all_tools(mcp, gateway)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
