"""Explicit semantic adapters for desktop features without an MCP wrapper.

This registry never accepts a route, HTTP method, Python function, or arbitrary
dispatcher name from the model. Each entry binds one reviewed business action.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import inspect
from typing import Any, Callable, Literal, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, create_model


UNAVAILABLE_CAPABILITIES = (
    {"capability": "credential.entry_or_reveal", "status": "unavailable", "reason": "New passwords, API secrets and cookie values must be entered through the application's secure credential dialog; no model-facing tool returns or accepts them.", "alternative": "Use saved connection profiles, auth_login_saved, or ask the user to complete credential entry."},
    {"capability": "ui.appearance_and_window", "status": "unavailable", "reason": "Theme, always-on-top, terminal fonts, window placement and keyboard shortcuts are owned by Electron/renderer state and have no backend command contract.", "alternative": "Open application settings and make the requested display change."},
    {"capability": "ui.terminal_layout_and_clipboard", "status": "unavailable", "reason": "Terminal tabs, split panes, focus, clipboard and local terminal selection require renderer/native-window APIs; backend session tools manage connections only.", "alternative": "Use the terminal workspace UI for layout and clipboard actions."},
    {"capability": "os.dialogs_and_file_export", "status": "unavailable", "reason": "Native file/folder dialogs and Save As are Electron-only. Workflow export and task report tools return content, not an arbitrary filesystem writer.", "alternative": "Use the application's export/save action for the returned content."},
)


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProfileEndpointInput(StrictInput):
    host: str = Field(default="", max_length=255)
    port: int = Field(default=0, ge=0, le=65535)
    username: str = Field(default="", max_length=255)


class ProfileInput(StrictInput):
    profile_type: Literal["temporary", "server"]
    name: str = Field(min_length=1, max_length=160)
    group: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=4000)
    preferred_protocol: Literal["ssh", "telnet", "serial"] = "ssh"
    telnet: ProfileEndpointInput = Field(default_factory=lambda: ProfileEndpointInput(port=23))
    ssh: ProfileEndpointInput = Field(default_factory=lambda: ProfileEndpointInput(port=22))
    serial: ProfileEndpointInput = Field(default_factory=lambda: ProfileEndpointInput(port=23))
    allow_duplicate: bool = False


class TransferSettingsInput(StrictInput):
    protocol: Literal["ftp"] = "ftp"
    host: str = Field(default="0.0.0.0", max_length=255)
    advertised_host: str = Field(default="", max_length=255)
    port: int = Field(default=0, ge=0, le=65535)
    root: str = Field(min_length=1, max_length=4096)
    username: str = Field(min_length=1, max_length=255)
    writable: bool = True


class PluginConfigurationInput(StrictInput):
    config: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    enabled: bool | None = None


class WorkflowImportInput(StrictInput):
    filename: str = Field(default="workflow.workflow.yaml", max_length=255)
    content: str = Field(min_length=1, max_length=500_000)
    conflict_strategy: Literal["create_copy", "error"] = "create_copy"


class WorkflowTemplateInput(StrictInput):
    name: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=4000)
    workflow_id: str = ""
    version: str | int = "draft"
    workflow: dict[str, Any] | None = None


class WorkflowTemplateInstantiationInput(StrictInput):
    id: str = ""
    name: str = ""
    description: str = ""


class WorkflowCustomActionInput(StrictInput):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    workflow_id: str = ""
    version: int | None = None
    action_id: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class DesktopTool:
    name: str
    function: Callable[..., Any]
    model: type[BaseModel]
    description: str
    read_only: bool
    original_types: dict[str, Any]


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


class DesktopAgentTools:
    def __init__(self, context: Callable[[], Any]) -> None:
        from .routers import auth, commands, device_sources, health, operations, package_builds, profiles, session_logs, tasks, transfers, workflow_definitions as workflows

        self._context = context
        self.entries: dict[str, DesktopTool] = {}
        # These explicit bindings are the complete desktop-only allow-list.
        entries = [
            ("app.diagnostics", health.diagnostics, True, "Read persistence and log-policy diagnostics."),
            ("auth.status", auth.internal_auth_status, True, "Read inventory login status without credentials."),
            ("auth.logout", auth.internal_auth_logout, False, "Sign out of the active inventory source."),
            ("profile.create", profiles.create_connection_profile, False, "Create a connection profile without changing vault credentials."),
            ("profile.update", profiles.update_connection_profile, False, "Update connection endpoints and metadata; saved credentials are preserved."),
            ("profile.group.create", profiles.create_connection_profile_group, False, "Create a saved connection group."),
            ("profile.credential.delete", profiles.delete_connection_profile_credential, False, "Delete a saved protocol credential; no credential is returned."),
            ("command.suggestions", commands.command_suggestions, True, "Find command suggestions or command history for a session."),
            ("command.send", commands.send_command, False, "Send raw input through the command workspace and record history. Observe terminal output afterwards."),
            ("command.broadcast", commands.broadcast_command, False, "Broadcast a command to selected sessions; empty session_ids means all sessions."),
            ("command.history.record", commands.record_command, False, "Record a command in session history without executing it."),
            ("transfer.settings.update", transfers.update_file_transfer_settings, False, "Configure FTP sharing while preserving the existing password."),
            ("transfer.service.log", transfers.file_transfer_service_log, True, "Read redacted transfer-service logs and client hints."),
            ("transfer.network.addresses", transfers.file_transfer_network_addresses, True, "Discover local transfer addresses for a session."),
            ("transfer.managed.start", transfers.start_managed_file_transfer, False, "Start a managed upload or download with explicit paths, target, protocol and overwrite policy."),
            ("transfer.retry", transfers.retry_managed_file_transfer, False, "Retry a failed transfer operation."),
            ("transfer.queue.resume", transfers.resume_managed_file_transfer_queue, False, "Resume the paused transfer queue of a session."),
            ("transfer.history.clear", transfers.clear_managed_file_transfer_history, False, "Delete completed transfer history."),
            ("transfer.files.search", transfers.shared_transfer_files, True, "Search, sort and paginate the managed file share."),
            ("package.builders", package_builds.package_builders, True, "List installed package builders and supported package types."),
            ("package.build.start", package_builds.package_build, False, "Start a package build with an installed builder; observe/cancel via operation tools."),
            ("package.upgrade.plan", operations.package_upgrade_manual_plan, False, "Generate a package-upgrade script using the selected session and package."),
            ("package.upgrade.send", operations.package_upgrade_manual_send, False, "Send an approved package-upgrade script through the existing upgrade service."),
            ("package.upgrade.terminal", operations.package_upgrade_manual_terminal, True, "Read terminal output for a manual package upgrade."),
            ("settings.session_logs.get", session_logs.get_session_log_settings, True, "Read session log directory, rotation and retention settings."),
            ("settings.session_logs.update", session_logs.update_session_log_settings, False, "Change session-log directory and rotation size through the existing migration service."),
            ("session.log.read", session_logs.session_log, True, "Read redacted session log content."),
            ("session.log.path", session_logs.session_log_path, True, "Get the backend-managed path of a session log."),
            ("session.log.new", session_logs.create_session_log, False, "Archive the current session log and begin a new log."),
            ("operation.list", operations.list_operations, True, "List transfer, upgrade and package-build operations."),
            ("task.report", tasks.task_report, True, "Get structured task report data suitable for CSV export."),
            ("task.delete", tasks.task_delete, False, "Delete a finished task and its persisted record."),
            ("task.delete_many", tasks.task_delete_many, False, "Delete selected finished task records."),
            ("workflow.framework.list", tasks.framework_workflow_catalog, True, "List reusable Workflow providers for generic Task composition."),
            ("workflow.framework.preview", tasks.framework_workflow_preview, True, "Build a reusable Workflow provider preview without running it."),
            ("workflow.actions.list", workflows.list_workflow_actions, True, "Read all Studio actions and their configuration/output contracts."),
            ("workflow.custom.list", workflows.list_custom_workflow_actions, True, "List reusable custom workflow actions."),
            ("workflow.custom.create", workflows.create_custom_workflow_action, False, "Save a validated reusable action from configuration or a published workflow."),
            ("workflow.custom.delete", workflows.delete_custom_workflow_action, False, "Delete a reusable custom action."),
            ("workflow.template.list", workflows.list_workflow_templates, True, "List built-in and personal workflow templates."),
            ("workflow.template.create", workflows.create_workflow_template, False, "Save a validated workflow snapshot as a reusable template."),
            ("workflow.template.delete", workflows.delete_workflow_template, False, "Delete a personal workflow template."),
            ("workflow.template.instantiate", workflows.instantiate_workflow_template, False, "Create a workflow draft from a selected template."),
            ("workflow.published.list", workflows.list_published_workflow_definitions, True, "List published workflow versions and interfaces."),
            ("workflow.version.list", workflows.list_workflow_versions, True, "Read published version history and reference status."),
            ("workflow.export", workflows.export_workflow_definition, True, "Export a workflow as YAML or JSON content; does not write a local file."),
            ("workflow.import.preview", workflows.preview_workflow_import, True, "Validate portable YAML/JSON workflow content before importing."),
            ("workflow.import", workflows.import_workflow_definition, False, "Import validated portable YAML/JSON as a new workflow draft."),
            ("workflow.definition.delete", workflows.delete_workflow_definition, False, "Delete a workflow draft with optional published-history preservation."),
            ("workflow.version.delete", workflows.delete_workflow_version, False, "Delete one unreferenced published workflow version."),
            ("workflow.version.restore", workflows.restore_workflow_version, False, "Restore a published workflow version into the editable draft."),
        ]
        overrides = {
            "profile.create": {"request": ProfileInput}, "profile.update": {"request": ProfileInput},
            "transfer.settings.update": {"request": TransferSettingsInput},
            "workflow.custom.create": {"payload": WorkflowCustomActionInput},
            "workflow.template.create": {"payload": WorkflowTemplateInput},
            "workflow.template.instantiate": {"payload": WorkflowTemplateInstantiationInput},
            "workflow.import.preview": {"payload": WorkflowImportInput},
            "workflow.import": {"payload": WorkflowImportInput},
        }
        for name, function, read_only, description in entries:
            self.register(name, function, read_only=read_only, description=description, overrides=overrides.get(name))

        self.register("source.plugin.configure", self.configure_plugin, description="Update non-secret plugin settings or enable/disable a plugin; credentials stay in the vault.")
        self.register("source.import.preview", self.import_preview, description="Read a local device spreadsheet and create a preview; password columns are ignored. Returns preview_id for commit.")
        self.register("source.import.commit", self.import_commit, description="Replace imported inventory using a previously reviewed preview_id.")
        self.register("auth.login_saved", self.login_saved, description="Sign in using a password already saved in the OS vault; credential entry stays in the secure application dialog.")
        self.register("ai.result", self.ai_result, read_only=True, description="Read a redacted AI execution result by id.")
        self.register("ai.audit", self.ai_audit, read_only=True, description="Read recent redacted tool audit records.")
        self.register("app.capabilities", self.capabilities, read_only=True, description="Read Agent coverage and explicit unavailable UI/credential capabilities before claiming an action is possible.")

    def register(self, name: str, function: Callable[..., Any], *, description: str,
                 read_only: bool = False, overrides: dict[str, Any] | None = None) -> None:
        hints = get_type_hints(function)
        fields = {}
        for key, parameter in inspect.signature(function).parameters.items():
            if key == "ctx":
                continue
            default = ... if parameter.default is inspect.Parameter.empty else deepcopy(parameter.default)
            annotation = (overrides or {}).get(key, hints[key])
            fields[key] = (annotation, default)
        model = create_model(name.replace(".", "_") + "Input", __config__=ConfigDict(extra="forbid", strict=True), **fields)
        key = name.replace(".", "_")
        self.entries[key] = DesktopTool(name, function, model, description, read_only, hints)

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": key, "description": entry.description + (" Read only." if entry.read_only else " Requires user approval before execution."), "parameters": entry.model.model_json_schema()}} for key, entry in self.entries.items()]

    @property
    def read_only_tools(self) -> frozenset[str]:
        return frozenset(key for key, entry in self.entries.items() if entry.read_only)

    def validate(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        validated = self.entries[name].model.model_validate(params, strict=True).model_dump()
        if name == "source_plugin_configure" and self._context() is not None:
            registration = self._context().repository.registry.registration(validated["source_id"])
            secret_fields = {item.key for item in registration.config_fields if item.kind == "secret"}
            if secret_fields & validated["request"]["config"].keys():
                raise ValueError("Secret plugin fields must be entered in the application's secure settings dialog")
        return validated

    async def invoke(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        entry = self.entries[name]
        parsed = entry.model.model_validate(params, strict=True)
        arguments = {key: getattr(parsed, key) for key in entry.model.model_fields}
        for key, value in list(arguments.items()):
            original = entry.original_types.get(key)
            if isinstance(value, BaseModel):
                if inspect.isclass(original) and issubclass(original, BaseModel):
                    arguments[key] = original.model_validate(value.model_dump())
                else:
                    arguments[key] = value.model_dump(exclude_unset=True)
        if "ctx" in inspect.signature(entry.function).parameters:
            arguments["ctx"] = self._context()
        result = await entry.function(**arguments)
        return {"ok": True, "data": _plain(result) if result is not None else {"completed": True}}

    async def configure_plugin(self, source_id: str, request: PluginConfigurationInput) -> Any:
        from .models import DeviceSourcePluginUpdateRequest
        from .routers.device_sources import update_device_source_plugin
        return await update_device_source_plugin(source_id, DeviceSourcePluginUpdateRequest(**request.model_dump()), self._context())

    async def import_preview(self, path: str) -> dict[str, Any]:
        from .models import DeviceImportPreviewRequest
        from .routers.device_sources import preview_device_import
        preview = await preview_device_import(DeviceImportPreviewRequest(path=path), self._context())
        data = preview.model_dump()
        data["preview_id"] = data.pop("token")
        return data

    async def import_commit(self, preview_id: str) -> Any:
        from .models import DeviceImportCommitRequest
        from .routers.device_sources import commit_device_import
        return await commit_device_import(DeviceImportCommitRequest(token=preview_id), self._context())

    async def login_saved(self, username: str, cid: str, auto_login: bool = False) -> Any:
        from .models import InternalAuthLoginRequest
        from .routers.auth import internal_auth_login
        return await internal_auth_login(InternalAuthLoginRequest(username=username, cid=cid, use_saved_password=True, remember=True, auto_login=auto_login), self._context())

    async def ai_result(self, result_id: str) -> dict[str, Any]:
        return self._context().ai_service.get_result(result_id, include_raw=False)

    async def ai_audit(self, limit: int = 100) -> dict[str, Any]:
        return {"entries": self._context().ai_service.audit_entries(max(1, min(limit, 500)))}

    async def capabilities(self) -> dict[str, Any]:
        ctx = self._context()
        return {
            "tools": [item["function"]["name"] for item in ctx.ai_runtime.definitions],
            "unavailable": list(UNAVAILABLE_CAPABILITIES),
            "approval_mode": "user_required_for_management_writes_and_device_mutations",
            "credentials": "backend_vault_only",
        }

    async def snapshot(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Bind approved edits to the resource state the user reviewed."""
        ctx = self._context()
        if ctx is None:
            raise ValueError("Desktop Agent context is not initialized")
        from .routers import commands, device_sources, profiles, session_logs, transfers, workflow_definitions as workflows
        result: dict[str, Any] = {}
        if name.startswith("profile_"):
            result["profiles"] = _plain(await profiles.connection_profiles(profile_type="", ctx=ctx))
        if name.startswith("source_") or name.startswith("auth_"):
            result["source"] = _plain(await device_sources.device_source_status(ctx))
            result["plugins"] = _plain(await device_sources.device_source_plugins(ctx))
        if name == "source_import_commit":
            cached = ctx.import_previews.get(params["preview_id"])
            if cached is None:
                raise ValueError("Import preview is missing or expired")
            result["import"] = {"expires_at": cached[0], "file": str(cached[1].source_path), "rows": cached[1].total_rows, "preview_rows": list(cached[1].preview_rows)}
        if name.startswith("command_"):
            result["workspace"] = _plain(await commands.get_command_workspace(ctx))
        if name.startswith("transfer_"):
            result["settings"] = _plain(await transfers.file_transfer_settings(ctx))
        if name.startswith(("settings_session_logs_", "session_log_")):
            result["settings"] = _plain(await session_logs.get_session_log_settings(ctx))
        if name.startswith("workflow_"):
            result["drafts"] = [item.to_dict() for item in ctx.desktop.workflow_definitions.list()]
            result["versions"] = [item.to_dict() for item in ctx.desktop.workflow_definitions.list_published(latest_only=False)]
            result["templates"] = await workflows.list_workflow_templates(ctx)
            result["custom_actions"] = await workflows.list_custom_workflow_actions(ctx)
        return result
