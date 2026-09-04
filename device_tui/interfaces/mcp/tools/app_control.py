"""MCP control-plane tools for the Electron application resources."""

from __future__ import annotations

from typing import Any, Literal

from ..gateway import McpGateway


def _call(gateway: McpGateway, tool: str, **params: Any) -> dict[str, Any]:
    return gateway.call("mcp_tool", tool, **params)


def register_app_control_tools(mcp: Any, gateway: McpGateway) -> None:
    @mcp.tool(name="app.capabilities")
    def app_capabilities() -> dict[str, Any]:
        """Discover the application resources and safe MCP control boundaries."""
        return _call(gateway, "app.capabilities")

    @mcp.tool(name="app.status")
    def app_status() -> dict[str, Any]:
        """Read application readiness, sessions, and active operations."""
        return _call(gateway, "system_status")

    @mcp.tool(name="device.list")
    def device_list() -> dict[str, Any]:
        """List devices visible to the active OdyTerm source."""
        return _call(gateway, "device_list")

    @mcp.tool(name="device.get")
    def device_get(device_id: str) -> dict[str, Any]:
        """Read credential-free details for one device."""
        return _call(gateway, "device_get", device_id=device_id)

    @mcp.tool(name="device.select")
    def device_select(device_id: str) -> dict[str, Any]:
        """Set the application-selected device."""
        return _call(gateway, "device_select", device_id=device_id)

    @mcp.tool(name="device.open")
    def device_open(device_id: str, protocol: Literal["auto", "ssh", "telnet", "serial", "simulated"] = "auto") -> dict[str, Any]:
        """Open a device using auto, SSH, Telnet, serial, or simulated transport."""
        return _call(gateway, "device.open", device_id=device_id, protocol=protocol)

    @mcp.tool(name="connection.open")
    def connection_open(profile_id: str, protocol: Literal["ssh", "telnet", "serial"] = "ssh", title: str = "") -> dict[str, Any]:
        """Open SSH, Telnet, or serial using a saved connection profile credential."""
        return _call(gateway, "connection.open", profile_id=profile_id, protocol=protocol, title=title)

    @mcp.tool(name="device.action")
    def device_action(device_id: str, action: str, confirm: bool = False) -> dict[str, Any]:
        """Run an allow-listed device action; writes require confirm=true."""
        return _call(gateway, "device.action", device_id=device_id, action=action, confirm=confirm)

    @mcp.tool(name="session.open")
    def session_open(device_id: str, protocol: Literal["auto", "ssh", "telnet", "serial", "simulated"] = "auto") -> dict[str, Any]:
        """Open or reuse a terminal session."""
        return _call(gateway, "session.manage", action="open", device_id=device_id, protocol=protocol)

    @mcp.tool(name="session.list")
    def session_list(device_id: str = "") -> dict[str, Any]:
        """List terminal sessions."""
        return _call(gateway, "session.list", device_id=device_id)

    @mcp.tool(name="session.manage")
    def session_manage(action: Literal["open", "status", "reconnect", "disconnect", "close"], session_id: str = "", device_id: str = "", protocol: Literal["auto", "ssh", "telnet", "serial", "simulated"] = "auto") -> dict[str, Any]:
        """Reconnect, disconnect, close, or inspect a terminal session."""
        return _call(gateway, "session.manage", action=action, session_id=session_id, device_id=device_id, protocol=protocol)

    @mcp.tool(name="source.status")
    def source_status() -> dict[str, Any]:
        """Read the active data source and import state."""
        return _call(gateway, "source.status")

    @mcp.tool(name="source.plugins")
    def source_plugins() -> dict[str, Any]:
        """List data-source plugins without returning secrets."""
        return _call(gateway, "source.plugins")

    @mcp.tool(name="source.switch")
    def source_switch(source: str, confirm: bool = False) -> dict[str, Any]:
        """Switch the active device data source after explicit confirmation."""
        return _call(gateway, "source.switch", source=source, confirm=confirm)

    @mcp.tool(name="source.plugin.update")
    def source_plugin_update(source_id: str, config: dict[str, Any] | None = None, secrets: dict[str, str | None] | None = None, enabled: bool | None = None, confirm: bool = False) -> dict[str, Any]:
        """Update a data-source plugin; returned configuration is redacted."""
        return _call(gateway, "source.plugin.update", source_id=source_id, config=config or {}, secrets=secrets or {}, enabled=enabled, confirm=confirm)

    @mcp.tool(name="source.plugin.test")
    def source_plugin_test(source_id: str) -> dict[str, Any]:
        """Test a data-source plugin configuration."""
        return _call(gateway, "source.plugin.test", source_id=source_id)

    @mcp.tool(name="profile.list")
    def profile_list() -> dict[str, Any]:
        """List saved connection profiles without credentials."""
        return _call(gateway, "profile.list")

    @mcp.tool(name="profile.save")
    def profile_save(profile: dict[str, Any], allow_duplicate: bool = False) -> dict[str, Any]:
        """Create or update a connection profile; passwords are never returned."""
        return _call(gateway, "profile.save", **profile, allow_duplicate=allow_duplicate)

    @mcp.tool(name="profile.delete")
    def profile_delete(profile_id: str, confirm: bool = False) -> dict[str, Any]:
        """Delete a saved connection profile after explicit confirmation."""
        return _call(gateway, "profile.delete", profile_id=profile_id, confirm=confirm)

    @mcp.tool(name="command.workspace")
    def command_workspace() -> dict[str, Any]:
        """Read command groups, preferences, and redacted history."""
        return _call(gateway, "command.workspace")

    @mcp.tool(name="command.group.save")
    def command_group_save(name: str = "", content: str = "", group_id: str = "") -> dict[str, Any]:
        """Create or update a command group."""
        return _call(gateway, "command.group.save", name=name, content=content, group_id=group_id)

    @mcp.tool(name="command.group.delete")
    def command_group_delete(group_id: str, confirm: bool = False) -> dict[str, Any]:
        """Delete a command group after explicit confirmation."""
        return _call(gateway, "command.group.delete", group_id=group_id, confirm=confirm)

    @mcp.tool(name="command.group.reorder")
    def command_group_reorder(group_ids: list[str]) -> dict[str, Any]:
        """Persist command-group order."""
        return _call(gateway, "command.group.reorder", group_ids=group_ids)

    @mcp.tool(name="command.preferences")
    def command_preferences(current_group_id: str = "", enter_sends: bool | None = None) -> dict[str, Any]:
        """Update command workspace preferences."""
        return _call(gateway, "command.preferences", current_group_id=current_group_id, enter_sends=enter_sends)

    @mcp.tool(name="automation.workspace")
    def automation_workspace() -> dict[str, Any]:
        """Read automation rules, runtime statuses, quick-send buttons, and activity."""
        return _call(gateway, "automation.workspace")

    @mcp.tool(name="automation.preview")
    def automation_preview(rule: dict[str, Any], session_id: str = "", sample_output: str = "", max_steps: int = 200) -> dict[str, Any]:
        """Preview an automation rule without writing to a session."""
        return _call(gateway, "automation.preview", rule=rule, session_id=session_id, sample_output=sample_output, max_steps=max_steps)

    @mcp.tool(name="automation.rule.save")
    def automation_rule_save(rule: dict[str, Any], rule_id: str = "") -> dict[str, Any]:
        """Create or update a validated terminal automation rule."""
        return _call(gateway, "automation.rule.save", rule=rule, rule_id=rule_id)

    @mcp.tool(name="automation.rule.delete")
    def automation_rule_delete(rule_id: str, confirm: bool = False) -> dict[str, Any]:
        """Delete an automation rule after explicit confirmation."""
        return _call(gateway, "automation.rule.delete", rule_id=rule_id, confirm=confirm)

    @mcp.tool(name="automation.rule.clone")
    def automation_rule_clone(rule_id: str) -> dict[str, Any]:
        """Clone an automation rule in disabled state."""
        return _call(gateway, "automation.rule.clone", rule_id=rule_id)

    @mcp.tool(name="automation.rule.enable")
    def automation_rule_enable(rule_id: str, enabled: bool) -> dict[str, Any]:
        """Enable or disable an automation rule."""
        return _call(gateway, "automation.rule.enable", rule_id=rule_id, enabled=enabled)

    @mcp.tool(name="automation.rule.trigger")
    def automation_rule_trigger(rule_id: str, session_id: str) -> dict[str, Any]:
        """Trigger an automation rule for one session."""
        return _call(gateway, "automation.rule.trigger", rule_id=rule_id, session_id=session_id)

    @mcp.tool(name="automation.cancel")
    def automation_cancel(session_id: str) -> dict[str, Any]:
        """Cancel active automation for one session."""
        return _call(gateway, "automation.cancel", session_id=session_id)

    @mcp.tool(name="automation.quick_send.save")
    def automation_quick_send_save(button: dict[str, Any], button_id: str = "") -> dict[str, Any]:
        """Create or update a quick-send button without returning its secret text."""
        return _call(gateway, "automation.quick_send.save", **button, button_id=button_id)

    @mcp.tool(name="automation.quick_send.delete")
    def automation_quick_send_delete(button_id: str, confirm: bool = False) -> dict[str, Any]:
        """Delete a quick-send button after explicit confirmation."""
        return _call(gateway, "automation.quick_send.delete", button_id=button_id, confirm=confirm)

    @mcp.tool(name="automation.quick_send.send")
    def automation_quick_send_send(button_id: str, session_id: str) -> dict[str, Any]:
        """Send a configured quick-send button to a terminal session."""
        return _call(gateway, "automation.quick_send.send", button_id=button_id, session_id=session_id)

    @mcp.tool(name="transfer.settings")
    def transfer_settings() -> dict[str, Any]:
        """Read managed transfer settings without the password."""
        return _call(gateway, "transfer.settings")

    @mcp.tool(name="transfer.service")
    def transfer_service(action: str) -> dict[str, Any]:
        """Start, stop, or clear the managed transfer service log."""
        return _call(gateway, "transfer.service", action=action)

    @mcp.tool(name="transfer.files")
    def transfer_files(path: str = "", recursive: bool = True, limit: int = 200) -> dict[str, Any]:
        """List files in the managed transfer share."""
        return _call(gateway, "transfer.files", path=path, recursive=recursive, limit=limit)

    @mcp.tool(name="transfer.start")
    def transfer_start(device_id: str, source_path: str, destination_path: str, overwrite: bool = False) -> dict[str, Any]:
        """Start a managed upload through the application transfer service."""
        return _call(gateway, "transfer.start", device_id=device_id, source_path=source_path, destination_path=destination_path, overwrite=overwrite)

    @mcp.tool(name="operation.get")
    def operation_get(operation_id: str) -> dict[str, Any]:
        """Read a long-running operation."""
        return _call(gateway, "operation.get", operation_id=operation_id)

    @mcp.tool(name="operation.wait")
    def operation_wait(operation_id: str, timeout_seconds: int = 60, since_revision: int = 0) -> dict[str, Any]:
        """Wait for an operation state change."""
        return _call(gateway, "operation.wait", operation_id=operation_id, timeout_seconds=timeout_seconds, since_revision=since_revision)

    @mcp.tool(name="operation.cancel")
    def operation_cancel(operation_id: str, confirm: bool = False) -> dict[str, Any]:
        """Cancel a long-running operation after explicit confirmation."""
        return _call(gateway, "operation.cancel", operation_id=operation_id, confirm=confirm)

    @mcp.tool(name="terminal.execute")
    def terminal_execute(command: str, session_id: str = "", device_id: str = "", timeout_seconds: int = 30) -> dict[str, Any]:
        """Execute one policy-checked terminal command."""
        return _call(gateway, "terminal.execute", command=command, session_id=session_id, device_id=device_id, timeout_seconds=timeout_seconds)

    @mcp.tool(name="terminal.batch")
    def terminal_batch(commands: list[str], session_id: str = "", device_id: str = "", command_timeout_seconds: int = 30, total_timeout_seconds: int | None = None) -> dict[str, Any]:
        """Execute a policy-checked terminal command batch."""
        return _call(gateway, "terminal.execute_batch", commands=commands, session_id=session_id, device_id=device_id, command_timeout_seconds=command_timeout_seconds, total_timeout_seconds=total_timeout_seconds)

    @mcp.tool(name="terminal.parallel")
    def terminal_parallel(requests: list[dict[str, Any]], max_concurrency: int = 8) -> dict[str, Any]:
        """Execute batches concurrently across independent device sessions."""
        return _call(gateway, "terminal.execute_parallel", requests=requests, max_concurrency=max_concurrency)

    @mcp.tool(name="terminal.interact")
    def terminal_interact(steps: list[dict[str, Any]], session_id: str = "", device_id: str = "", total_timeout_seconds: int = 60) -> dict[str, Any]:
        """Run a policy-checked terminal interaction plan."""
        return _call(gateway, "terminal.interact", steps=steps, session_id=session_id, device_id=device_id, total_timeout_seconds=total_timeout_seconds)

    @mcp.tool(name="terminal.read")
    def terminal_read(device_id: str, max_chars: int = 4096) -> dict[str, Any]:
        """Read recent terminal output."""
        return _call(gateway, "terminal.read", device_id=device_id, max_chars=max_chars)
