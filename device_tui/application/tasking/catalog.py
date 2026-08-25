"""Registry and parameter contracts for reusable named workflows."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol

from .protocol import WorkflowDefinition
from .workflows import device_upgrade_workflow


class WorkflowCatalogError(ValueError):
    """A named workflow cannot be resolved or built."""


@dataclass(frozen=True, slots=True)
class WorkflowTarget:
    device_id: str
    session_id: str = ""
    protocol: str = "auto"


@dataclass(frozen=True, slots=True)
class WorkflowParameter:
    name: str
    type: str = "string"
    label: str = ""
    description: str = ""
    required: bool = False
    default: Any = None
    enum: tuple[Any, ...] = ()
    enum_labels: dict[str, str] = field(default_factory=dict)
    control: str = "text"
    advanced: bool = False
    file_extensions: tuple[str, ...] = ()
    stage_to_transfer_root: bool = False

    def public_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "type": self.type,
            "label": self.label or self.name,
            "description": self.description,
            "required": self.required,
            "control": self.control,
            "advanced": self.advanced,
            "stage_to_transfer_root": self.stage_to_transfer_root,
        }
        if self.default is not None:
            payload["default"] = self.default
        if self.enum:
            payload["enum"] = list(self.enum)
            payload["enum_labels"] = dict(self.enum_labels)
        if self.file_extensions:
            payload["file_extensions"] = list(self.file_extensions)
        return payload

    def validate(self, value: Any) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            return f"{self.name} is required" if self.required else ""
        accepted = {
            "string": (str,),
            "integer": (int,),
            "boolean": (bool,),
            "array": (list, tuple),
        }.get(self.type, (object,))
        if not isinstance(value, accepted) or self.type == "integer" and isinstance(value, bool):
            return f"{self.name} must be {self.type}"
        if self.enum and value not in self.enum:
            return f"{self.name} must be one of {', '.join(str(item) for item in self.enum)}"
        if self.file_extensions and isinstance(value, str):
            normalized = value.casefold()
            if not any(normalized.endswith(item.casefold()) for item in self.file_extensions):
                return f"{self.name} must use one of: {', '.join(self.file_extensions)}"
        return ""


@dataclass(frozen=True, slots=True)
class WorkflowDescriptor:
    id: str
    version: str
    name: str
    description: str
    parameters: tuple[WorkflowParameter, ...]
    aliases: tuple[str, ...] = ()
    capability: str = ""
    capability_action: str = ""
    risk: str = "normal"
    confirmation_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "aliases": list(self.aliases),
            "capability": self.capability,
            "capability_action": self.capability_action,
            "risk": self.risk,
            "confirmation_required": self.confirmation_required,
            "parameters": [item.public_dict() for item in self.parameters],
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": [item.name for item in self.parameters if item.required],
                "properties": {item.name: item.public_dict() for item in self.parameters},
            },
            "metadata": dict(self.metadata),
        }


class WorkflowProvider(Protocol):
    descriptor: WorkflowDescriptor

    def build(self, target: WorkflowTarget, parameters: Mapping[str, Any]) -> WorkflowDefinition: ...

    def migrate_legacy(
        self,
        parameters: Mapping[str, Any],
        steps: tuple[Mapping[str, Any], ...],
    ) -> dict[str, Any]: ...


class WorkflowCatalog:
    """Application-owned catalog for named, reusable workflows."""

    def __init__(self, providers: tuple[WorkflowProvider, ...] = ()) -> None:
        self._providers: dict[str, WorkflowProvider] = {}
        self._aliases: dict[str, str] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: WorkflowProvider) -> None:
        workflow_id = provider.descriptor.id.strip()
        if not workflow_id:
            raise WorkflowCatalogError("workflow id is required")
        if workflow_id in self._providers or workflow_id in self._aliases:
            raise WorkflowCatalogError(f"workflow already registered: {workflow_id}")
        self._providers[workflow_id] = provider
        for alias in provider.descriptor.aliases:
            normalized = alias.strip()
            if not normalized or normalized in self._providers or normalized in self._aliases:
                raise WorkflowCatalogError(f"workflow alias already registered: {normalized}")
            self._aliases[normalized] = workflow_id

    def resolve_id(self, workflow_id: str) -> str:
        normalized = str(workflow_id).strip()
        if normalized in self._providers:
            return normalized
        if normalized in self._aliases:
            return self._aliases[normalized]
        raise WorkflowCatalogError(f"unknown workflow: {workflow_id}")

    def contains(self, workflow_id: str) -> bool:
        try:
            self.resolve_id(workflow_id)
        except WorkflowCatalogError:
            return False
        return True

    def descriptor(self, workflow_id: str) -> WorkflowDescriptor:
        return self._providers[self.resolve_id(workflow_id)].descriptor

    def list(self) -> tuple[WorkflowDescriptor, ...]:
        return tuple(provider.descriptor for provider in self._providers.values())

    def preview(self, workflow_id: str) -> WorkflowDefinition:
        descriptor = self.descriptor(workflow_id)
        parameters: dict[str, Any] = {}
        for definition in descriptor.parameters:
            if definition.default is not None:
                parameters[definition.name] = definition.default
            elif definition.required:
                parameters[definition.name] = (
                    f"preview{definition.file_extensions[0]}"
                    if definition.file_extensions
                    else f"<{definition.name}>"
                )
        return self.build(
            descriptor.id,
            WorkflowTarget(device_id="<device_id>"),
            parameters,
        )

    def normalize_parameters(
        self,
        workflow_id: str,
        parameters: Mapping[str, Any] | None = None,
        *,
        legacy_steps: tuple[Mapping[str, Any], ...] = (),
    ) -> dict[str, Any]:
        provider = self._providers[self.resolve_id(workflow_id)]
        migrated = provider.migrate_legacy(dict(parameters or {}), legacy_steps)
        definitions = {item.name: item for item in provider.descriptor.parameters}
        unknown = sorted(set(migrated) - set(definitions))
        if unknown:
            raise WorkflowCatalogError(f"unsupported workflow parameters: {', '.join(unknown)}")
        normalized: dict[str, Any] = {}
        errors: list[str] = []
        for name, definition in definitions.items():
            value = migrated[name] if name in migrated else definition.default
            error = definition.validate(value)
            if error:
                errors.append(error)
            elif value is not None:
                normalized[name] = value
        if errors:
            raise WorkflowCatalogError("; ".join(errors))
        return normalized

    def build(
        self,
        workflow_id: str,
        target: WorkflowTarget,
        parameters: Mapping[str, Any] | None = None,
        *,
        legacy_steps: tuple[Mapping[str, Any], ...] = (),
    ) -> WorkflowDefinition:
        resolved = self.resolve_id(workflow_id)
        if not target.device_id.strip():
            raise WorkflowCatalogError("device_id is required")
        provider = self._providers[resolved]
        normalized = self.normalize_parameters(resolved, parameters, legacy_steps=legacy_steps)
        workflow = provider.build(target, normalized)
        descriptor = provider.descriptor
        schema = descriptor.public_dict()["input_schema"]
        return replace(
            workflow,
            id=descriptor.id,
            version=descriptor.version,
            name=workflow.name or descriptor.name,
            description=workflow.description or descriptor.description,
            input_schema=dict(schema),
            metadata={**workflow.metadata, "catalog_workflow_id": descriptor.id, "catalog_parameters": normalized},
        )


class DeviceUpgradeWorkflowProvider:
    descriptor = WorkflowDescriptor(
        id="device_upgrade",
        version="2",
        name="设备系统包升级",
        description="通过设备驱动准备系统包，并按策略选择暂存或重启验证。",
        aliases=("package-upgrade",),
        capability="device.upgrade",
        capability_action="device_upgrade",
        risk="high",
        confirmation_required=True,
        parameters=(
            WorkflowParameter(
                "package_path", label="软件包", required=True, control="file",
                file_extensions=(".cc",), stage_to_transfer_root=True,
            ),
            WorkflowParameter(
                "package_source", label="软件包来源", default="local", control="select",
                enum=("local", "device"), enum_labels={"local": "本地传包", "device": "设备已有包"},
            ),
            WorkflowParameter(
                "topology_policy", label="设备拓扑", default="auto", control="select",
                enum=("auto", "single", "required"),
                enum_labels={"auto": "自动识别备控", "single": "仅升级主控", "required": "必须有备控"},
            ),
            WorkflowParameter(
                "cleanup_policy", label="旧包清理", default="never", control="select",
                enum=("never", "auto"),
                enum_labels={"never": "不自动删除", "auto": "自动清理未使用旧包"},
            ),
            WorkflowParameter(
                "activation_policy", label="激活方式", default="stage_only", control="select",
                enum=("stage_only", "reboot"),
                enum_labels={"stage_only": "只设置下次启动项", "reboot": "确认后重启并验证"},
            ),
            WorkflowParameter(
                "recovery_protocol", label="重启后恢复通道", default="same", control="select",
                enum=("same", "serial"),
                enum_labels={"same": "原管理口自动重连", "serial": "串口监控并确认上线"},
                advanced=True,
            ),
            WorkflowParameter("expected_version", label="期望版本", default="", advanced=True),
            WorkflowParameter("driver_id", label="升级驱动", default="auto", advanced=True),
            WorkflowParameter("master_storage", label="主控存储", default="", advanced=True),
            WorkflowParameter("slave_storage", label="备控存储", default="", advanced=True),
            WorkflowParameter("prepare_timeout_seconds", type="integer", label="准备超时", default=900, advanced=True),
            WorkflowParameter("reboot_timeout_seconds", type="integer", label="重启超时", default=190, advanced=True),
            WorkflowParameter("online_timeout_seconds", type="integer", label="上线超时", default=180, advanced=True),
            WorkflowParameter("version_commands", type="array", label="版本检查命令", default=("display version",), advanced=True),
            WorkflowParameter("validation_commands", type="array", label="最终验证命令", default=("display version",), advanced=True),
        ),
        metadata={"category": "upgrade", "risk": "high"},
    )

    def build(self, target: WorkflowTarget, parameters: Mapping[str, Any]) -> WorkflowDefinition:
        values = dict(parameters)
        package = str(values.pop("package_path"))
        return device_upgrade_workflow(device_id=target.device_id, package=package, options=values)

    def migrate_legacy(
        self,
        parameters: Mapping[str, Any],
        steps: tuple[Mapping[str, Any], ...],
    ) -> dict[str, Any]:
        migrated = dict(parameters)
        if "package" in migrated and "package_path" not in migrated:
            migrated["package_path"] = migrated.pop("package")
        for step in steps:
            if str(step.get("action") or "") not in {"package_upgrade", "upgrade", "prepare_upgrade"}:
                continue
            legacy = dict(step.get("params") or {})
            if legacy.get("package_path") and not migrated.get("package_path"):
                migrated["package_path"] = legacy["package_path"]
            if bool(legacy.get("reboot_after_setting")):
                migrated.setdefault("activation_policy", "reboot")
            if legacy.get("include_slave") is False:
                migrated.setdefault("topology_policy", "single")
            if bool(legacy.get("standby_required")):
                migrated.setdefault("topology_policy", "required")
            if bool(legacy.get("auto_delete_old_packages")):
                migrated.setdefault("cleanup_policy", "auto")
            for name in (
                "driver_id", "master_storage", "slave_storage", "prepare_timeout_seconds",
            ):
                if name in legacy:
                    migrated.setdefault(name, legacy[name])
            for legacy_name in (
                "wait", "reboot_after_setting", "include_slave", "standby_required",
                "auto_delete_old_packages", "approve_reboot", "timeout_seconds",
            ):
                migrated.pop(legacy_name, None)
            break
        return migrated


def build_default_workflow_catalog() -> WorkflowCatalog:
    return WorkflowCatalog((DeviceUpgradeWorkflowProvider(),))


__all__ = [
    "DeviceUpgradeWorkflowProvider",
    "WorkflowCatalog",
    "WorkflowCatalogError",
    "WorkflowDescriptor",
    "WorkflowParameter",
    "WorkflowProvider",
    "WorkflowTarget",
    "build_default_workflow_catalog",
]
