"""Presentation mappers shared by desktop API routers."""

from __future__ import annotations

from dataclasses import asdict

from device_tui.application import (
    ApplicationError,
    CommandGroup,
    ConnectionProfile,
    ConnectionProfileDraft,
    DesktopApplication,
    DeviceActionResult,
    DeviceSnapshot,
    ProfileEndpoint,
    SecretStore,
    SessionRecord,
)
from device_tui.application.settings import SettingsStore
from device_tui.device_sources.service import DeviceSourceService
from device_tui.domain.devices.repository import (
    DeviceRepository,
    InternalAuthStatus,
    RepositoryError,
)

from .data_migration import PersistenceMigrationStatus
from .models import (
    AutomationActivityModel,
    AutomationRuleModel,
    AutomationSessionStatusModel,
    AutomationWorkspaceResponse,
    CommandGroupModel,
    CommandHistoryModel,
    CommandWorkspaceResponse,
    ConnectionProfileSummary,
    ConnectionProfileUpsertRequest,
    DeviceActionResponse,
    DeviceFieldDescriptorModel,
    DeviceSourceOptionModel,
    DeviceSourcePluginModel,
    DeviceSourceStatusModel,
    DeviceSummary,
    InternalAuthStatusModel,
    PersistenceDiagnostics,
    PluginConfigFieldModel,
    PluginConfigOptionModel,
    ProfileEndpointModel,
    QuickSendButtonModel,
    SessionLogSettingsModel,
    SessionSummary,
    TaskModel,
    TransferSettingsModel,
)
from .session_hub import SessionHub


def persistence_diagnostics(
    status: PersistenceMigrationStatus | None,
) -> PersistenceDiagnostics:
    if status is None:
        return PersistenceDiagnostics(
            data_root="",
            database_path="",
            schema_version_before=0,
            schema_version_after=0,
            target_schema_version=0,
            migrated=False,
            backup_created=False,
        )
    return PersistenceDiagnostics(
        data_root=str(status.data_root),
        database_path=str(status.database_path),
        schema_version_before=status.schema_version_before,
        schema_version_after=status.schema_version_after,
        target_schema_version=status.target_schema_version,
        migrated=status.migrated,
        backup_created=status.backup_created,
        backup_path=str(status.backup_path) if status.backup_path else None,
    )


def task_model(record: object) -> TaskModel:
    return TaskModel(**asdict(record))


def device_summary(device: DeviceSnapshot) -> DeviceSummary:
    return DeviceSummary(
        id=device.id,
        row_id=device.row_id,
        board_id=device.board_id,
        name=device.name,
        domain=device.domain,
        device_type=device.device_type,
        cpu=device.cpu,
        status=device.status,
        owner=device.owner,
        vendor=device.vendor,
        model=device.model,
        site=device.site,
        rack=device.rack,
        board_type=device.board_type,
        slot=device.slot,
        status_text=device.status_text,
        tooltip=device.tooltip,
        version=device.version,
        ssh_endpoint=device.ssh_endpoint,
        telnet_endpoint=device.telnet_endpoint,
        serial_endpoint=device.serial_endpoint,
        serial_display=device.serial_display,
        can_connect_telnet=device.can_connect_telnet,
        can_connect_ssh=device.can_connect_ssh,
        can_connect_serial=device.can_connect_serial,
        can_claim=device.can_claim,
        can_release=device.can_release,
        can_power_off=device.can_power_off,
        is_simulated=device.is_simulated,
        is_temporary=device.is_temporary,
        is_saved_server=device.is_saved_server,
        supports_power_off=device.supports_power_off,
        source=device.source,
        kind=device.kind,
        attributes=device.attributes,
        extensions=device.extensions,
        capabilities=device.capabilities,
        parent_id=device.parent_id,
        children=list(device.children),
    )


def device_field_schema(
    service: DeviceSourceService,
) -> list[DeviceFieldDescriptorModel]:
    return [
        DeviceFieldDescriptorModel(
            key=field.key,
            label=field.label,
            kind=field.kind,
            group=field.group,
            order=field.order,
            searchable=field.searchable,
            filterable=field.filterable,
            default_visible=field.default_visible,
        )
        for field in service.registry.device_fields(service.active_source)
    ]


def device_action_response(
    result: DeviceActionResult,
    service: DeviceSourceService,
) -> DeviceActionResponse:
    return DeviceActionResponse(
        device_id=result.device_id,
        action=result.action,
        message=result.message,
        device=device_summary(result.device),
        current_user=result.inventory.current_user,
        owned_device_ids=list(result.inventory.owned_device_ids),
        devices=[device_summary(device) for device in result.inventory.devices],
        field_schema=device_field_schema(service),
    )


def profile_summary(
    desktop: DesktopApplication,
    profile: ConnectionProfile,
) -> ConnectionProfileSummary:
    def endpoint(protocol: str, value: ProfileEndpoint) -> ProfileEndpointModel:
        return ProfileEndpointModel(
            host=value.host,
            port=value.port,
            username=value.username,
            has_password=desktop.profiles.has_password(profile.id, protocol),
        )

    return ConnectionProfileSummary(
        id=profile.id,
        profile_type=profile.profile_type,
        name=profile.name,
        group=profile.group,
        notes=profile.notes,
        preferred_protocol=profile.preferred_protocol,
        telnet=endpoint("telnet", profile.telnet),
        ssh=endpoint("ssh", profile.ssh),
        serial=endpoint("serial", profile.serial),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def profile_draft(
    request: ConnectionProfileUpsertRequest,
    profile_id: str = "",
) -> ConnectionProfileDraft:
    return ConnectionProfileDraft(
        profile_type=request.profile_type,
        profile_id=profile_id,
        name=request.name,
        group=request.group,
        notes=request.notes,
        preferred_protocol=request.preferred_protocol,
        telnet=ProfileEndpoint(
            request.telnet.host,
            request.telnet.port or 23,
            request.telnet.username,
        ),
        ssh=ProfileEndpoint(
            request.ssh.host,
            request.ssh.port or 22,
            request.ssh.username,
        ),
        serial=ProfileEndpoint(
            request.serial.host,
            request.serial.port or 23,
            request.serial.username,
        ),
        passwords={
            "telnet": request.telnet_password,
            "ssh": request.ssh_password,
            "serial": request.serial_password,
        },
    )


def session_summary(session: SessionRecord) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        device_id=session.device_id,
        kind=session.kind,
        title=session.title,
        status=session.status,
        sequence=session.sequence,
        generation=session.generation,
    )


def command_group(group: CommandGroup) -> CommandGroupModel:
    return CommandGroupModel(
        id=group.id,
        name=group.name,
        content=group.content,
        sort_order=group.sort_order,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def command_workspace(desktop: DesktopApplication) -> CommandWorkspaceResponse:
    return CommandWorkspaceResponse(
        groups=[command_group(group) for group in desktop.commands.list_groups()],
        current_group_id=desktop.commands.current_group_id(),
        enter_sends=desktop.commands.enter_sends(),
        history=[
            CommandHistoryModel(
                command=item.command,
                device_id=item.device_id,
                session_kind=item.session_kind,
                count=item.count,
                last_used_at=item.last_used_at,
            )
            for item in desktop.commands.history(limit=200)
        ],
    )


def automation_workspace(desktop: DesktopApplication) -> AutomationWorkspaceResponse:
    return AutomationWorkspaceResponse(
        rules=[
            AutomationRuleModel(
                id=record.id,
                rule=desktop.automation.serialize_rule(
                    desktop.automation.public_rule(record)
                ),
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in desktop.automation.list_rules()
        ],
        sessions=[
            AutomationSessionStatusModel(
                session_id=status.session_id,
                running_rule_ids=list(status.running_rule_ids),
                waiting_rule_ids=list(status.waiting_rule_ids),
                triggered_rule_ids=list(status.triggered_rule_ids),
            )
            for status in desktop.automation.statuses()
        ],
        quick_send_buttons=[
            QuickSendButtonModel(**asdict(record))
            for record in desktop.automation.list_quick_send_buttons()
        ],
        activity=[
            AutomationActivityModel(**asdict(record))
            for record in desktop.automation.activities(limit=100)
        ],
    )


def transfer_settings(desktop: DesktopApplication) -> TransferSettingsModel:
    return TransferSettingsModel(**asdict(desktop.transfers.settings()))


def session_log_settings(
    hub: SessionHub,
    *,
    moved_count: int = 0,
) -> SessionLogSettingsModel:
    configuration = hub.log_configuration()
    if configuration is None:
        return SessionLogSettingsModel(
            directory="",
            rotate_size_mb=24,
            backup_count=5,
            configurable=False,
        )
    return SessionLogSettingsModel(
        directory=str(configuration["root"]),
        rotate_size_mb=max(
            1,
            int(configuration["max_bytes"]) // (1024 * 1024),
        ),
        backup_count=int(configuration["backup_count"]),
        configurable=True,
        moved_active_logs=moved_count,
    )


def device_source_status_model(
    service: DeviceSourceService,
) -> DeviceSourceStatusModel:
    metadata = service.imported_store.imported_device_metadata()
    source_ids = set(service.source_ids())
    descriptors = service.registry.descriptors()
    if service.product_profile.source_locked:
        descriptors = tuple(
            descriptor
            for descriptor in descriptors
            if descriptor.id == service.active_source
        )
    options: list[DeviceSourceOptionModel] = []
    for descriptor in descriptors:
        available = descriptor.id in source_ids
        reason = service.registry.unavailable_reason(descriptor.id)
        if (
            descriptor.supports_import
            and metadata.row_count <= 0
            and service.product_profile.mode != "spreadsheet"
        ):
            available = False
            reason = reason or "尚未导入设备文件。"
        options.append(
            DeviceSourceOptionModel(
                id=descriptor.id,
                label=descriptor.label,
                description=descriptor.description,
                icon=descriptor.icon,
                available=available,
                unavailable_reason=reason,
                requires_login=descriptor.requires_login,
                supports_import=descriptor.supports_import,
            )
        )
    return DeviceSourceStatusModel(
        product_mode=service.product_profile.mode,
        allow_source_switch=service.product_profile.allow_source_switch,
        allow_plugin_management=service.product_profile.allow_plugin_management,
        allow_import=service.product_profile.allow_import,
        active_source=service.active_source,
        default_source=service.default_source,
        sources=options,
        plugin_warnings=list(service.registry.warnings()),
        imported_count=metadata.row_count,
        imported_file=metadata.source_name,
        imported_sheet=metadata.sheet_name,
        imported_at=metadata.imported_at,
    )


def device_source_plugin_model(
    source_id: str,
    service: DeviceSourceService,
) -> DeviceSourcePluginModel:
    registration = service.registry.registration(source_id)
    descriptor = registration.descriptor
    values = service.registry.configuration(source_id)
    fields = [
        PluginConfigFieldModel(
            key=item.key,
            label=item.label,
            kind=item.kind,
            value=None if item.kind == "secret" else values.get(item.key),
            description=item.description,
            placeholder=item.placeholder,
            required=item.required,
            advanced=item.advanced,
            minimum=item.minimum,
            maximum=item.maximum,
            options=[
                PluginConfigOptionModel(value=option.value, label=option.label)
                for option in item.options
            ],
            secret_configured=(
                service.registry.secret_configured(source_id, item.key)
                if item.kind == "secret"
                else False
            ),
        )
        for item in registration.config_fields
    ]
    return DeviceSourcePluginModel(
        id=descriptor.id,
        label=descriptor.label,
        description=descriptor.description,
        icon=descriptor.icon,
        version=descriptor.version,
        publisher=descriptor.publisher,
        built_in=registration.built_in,
        enabled=service.registry.enabled(source_id),
        available=source_id in service.source_ids(),
        unavailable_reason=service.registry.unavailable_reason(source_id),
        active=source_id == service.active_source,
        default=source_id == service.default_source,
        requires_login=descriptor.requires_login,
        supports_import=descriptor.supports_import,
        config_fields=fields,
    )


def internal_auth_status_model(
    repository: DeviceRepository,
    settings: SettingsStore,
    secrets: SecretStore,
    status: InternalAuthStatus | None = None,
    *,
    credential_warning: str = "",
    source_id: str,
) -> InternalAuthStatusModel:
    current = status or repository.internal_auth_status()
    username_key = f"internal_auth.username.{source_id}"
    cid_key = f"internal_auth.cid.{source_id}"
    auto_key = f"internal_auth.auto_login.{source_id}"
    error_key = f"internal_auth.auto_login_error.{source_id}"
    password_key = f"internal-auth/{source_id}/password"
    warning = credential_warning
    try:
        remembered = bool(secrets.get(password_key))
    except ApplicationError as exc:
        remembered = False
        warning = warning or exc.message
    return InternalAuthStatusModel(
        available=current.available,
        configured=current.configured,
        authenticated=current.authenticated,
        username=current.username or str(settings.get(username_key, "") or ""),
        cid=current.cid or str(settings.get(cid_key, "") or ""),
        remembered=remembered,
        auto_login=bool(settings.get(auto_key, False)) and remembered,
        auto_login_error=str(settings.get(error_key, "") or ""),
        credential_warning=warning,
    )


def attempt_internal_auto_login(
    repository: DeviceRepository,
    settings: SettingsStore,
    secrets: SecretStore,
    source_id: str,
) -> None:
    username_key = f"internal_auth.username.{source_id}"
    cid_key = f"internal_auth.cid.{source_id}"
    auto_key = f"internal_auth.auto_login.{source_id}"
    error_key = f"internal_auth.auto_login_error.{source_id}"
    password_key = f"internal-auth/{source_id}/password"
    if not bool(settings.get(auto_key, False)):
        return
    username = str(settings.get(username_key, "") or "").strip()
    cid = str(settings.get(cid_key, "") or "").strip()
    try:
        status = repository.internal_auth_status()
        password = secrets.get(password_key)
        if (
            not status.available
            or not status.configured
            or not username
            or not cid
            or not password
        ):
            return
        repository.login_internal(username, password, cid)
        settings.delete(error_key)
    except (ApplicationError, RepositoryError) as exc:
        message = exc.message if isinstance(exc, ApplicationError) else str(exc)
        settings.set(error_key, message[:500])
