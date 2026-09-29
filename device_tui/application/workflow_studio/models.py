from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


def _tuple_dicts(values: Any) -> tuple[dict[str, Any], ...]:
    return tuple(dict(value) for value in (values or ()) if isinstance(value, Mapping))


@dataclass(frozen=True, slots=True)
class WorkflowInput:
    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""
    source: str = "runtime"
    presentation: str = ""
    multiple: bool = False
    accept: str = ""
    placeholder: str = ""
    options: tuple[str, ...] = ()
    primitive_type: str = ""
    semantic_type: str = ""
    scope: str = "input"
    constraints: dict[str, Any] = field(default_factory=dict)
    ui_hints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        legacy_type = str(self.type or "string").casefold()
        if not self.primitive_type:
            object.__setattr__(self, "primitive_type", "array" if legacy_type == "devices" else ("string" if legacy_type in {"file", "device"} else legacy_type))
        if not self.semantic_type:
            object.__setattr__(self, "semantic_type", {"file": "file", "device": "device", "devices": "device_list"}.get(legacy_type, "text" if legacy_type == "string" else legacy_type))

    def to_dict(self) -> dict[str, Any]:
        primitive_type = self.primitive_type or ("array" if self.type == "devices" else ("string" if self.type in {"file", "device"} else self.type))
        semantic_type = self.semantic_type or {"file": "file", "device": "device", "devices": "device_list"}.get(self.type, "text" if self.type == "string" else self.type)
        result = {"name": self.name, "type": self.type, "primitiveType": primitive_type, "semanticType": semantic_type, "scope": self.scope, "required": self.required, "default": self.default, "description": self.description, "source": self.source, "presentation": self.presentation, "multiple": self.multiple}
        if self.accept: result["accept"] = self.accept
        if self.placeholder: result["placeholder"] = self.placeholder
        if self.options: result["options"] = list(self.options)
        if self.constraints: result["constraints"] = dict(self.constraints)
        if self.ui_hints: result["uiHints"] = dict(self.ui_hints)
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowInput":
        options = payload.get("options") or ()
        legacy_type = str(payload.get("type", "string"))
        primitive_type = str(payload.get("primitiveType") or ("array" if legacy_type == "devices" else ("string" if legacy_type in {"file", "device"} else legacy_type)))
        semantic_type = str(payload.get("semanticType") or {"file": "file", "device": "device", "devices": "device_list"}.get(legacy_type, "text" if legacy_type == "string" else legacy_type))
        return cls(str(payload.get("name", "")), legacy_type, bool(payload.get("required", False)), payload.get("default"), str(payload.get("description", "")), str(payload.get("source", "runtime")), str(payload.get("presentation", "")), bool(payload.get("multiple", False)), str(payload.get("accept", "")), str(payload.get("placeholder", "")), tuple(str(value) for value in options if value is not None), primitive_type, semantic_type, str(payload.get("scope", "input")), dict(payload.get("constraints") or {}), dict(payload.get("uiHints") or {}))


@dataclass(frozen=True, slots=True)
class WorkflowOutput:
    name: str
    value: Any = None
    type: str = "any"
    description: str = ""
    presentation: str = "text"
    mime_type: str = ""
    download_name: str = ""
    primitive_type: str = ""
    semantic_type: str = ""
    scope: str = "output"
    constraints: dict[str, Any] = field(default_factory=dict)
    ui_hints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.primitive_type:
            object.__setattr__(self, "primitive_type", self.type if self.type != "any" else "object")
        if not self.semantic_type:
            object.__setattr__(self, "semantic_type", "file" if self.presentation == "download" else ("json" if self.presentation == "json" else "text"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "type": self.type,
            "description": self.description,
            "presentation": self.presentation,
            "mime_type": self.mime_type,
            "download_name": self.download_name,
            "primitiveType": self.primitive_type,
            "semanticType": self.semantic_type,
            "scope": self.scope,
            "mimeType": self.mime_type,
            "downloadName": self.download_name,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowOutput":
        return cls(
            str(payload.get("name", "")),
            payload.get("value"),
            str(payload.get("type", "any")),
            str(payload.get("description", "")),
            str(payload.get("presentation", "text")),
            str(payload.get("mime_type", payload.get("mimeType", ""))),
            str(payload.get("download_name", payload.get("downloadName", ""))),
            str(payload.get("primitiveType", payload.get("type", "any"))),
            str(payload.get("semanticType", "file" if payload.get("presentation") == "download" else "text")),
            str(payload.get("scope", "output")),
            dict(payload.get("constraints") or {}),
            dict(payload.get("uiHints") or {}),
        )


@dataclass(frozen=True, slots=True)
class WorkflowNode:
    id: str
    action_id: str
    config: dict[str, Any] = field(default_factory=dict)
    input_mapping: dict[str, Any] = field(default_factory=dict)
    position: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "action_id": self.action_id, "config": dict(self.config), "input_mapping": dict(self.input_mapping), "position": dict(self.position)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowNode":
        return cls(str(payload.get("id", "")), str(payload.get("action_id", payload.get("action", ""))), dict(payload.get("config") or payload.get("params") or {}), dict(payload.get("input_mapping") or payload.get("inputs") or {}), {str(k): float(v) for k, v in dict(payload.get("position") or {}).items()})


@dataclass(frozen=True, slots=True)
class WorkflowEdge:
    source: str
    target: str
    condition: str | None = None
    source_handle: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"source": self.source, "target": self.target}
        if self.condition is not None:
            result["condition"] = self.condition
        if self.source_handle is not None:
            result["source_handle"] = self.source_handle
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowEdge":
        return cls(str(payload.get("source", payload.get("from", ""))), str(payload.get("target", payload.get("to", ""))), payload.get("condition"), payload.get("source_handle"))


@dataclass(frozen=True, slots=True)
class WorkflowDraft:
    id: str
    name: str
    description: str = ""
    version: str = "draft"
    inputs: tuple[WorkflowInput, ...] = ()
    nodes: tuple[WorkflowNode, ...] = ()
    edges: tuple[WorkflowEdge, ...] = ()
    status: str = "draft"
    outputs: tuple[WorkflowOutput, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description, "version": self.version, "inputs": [item.to_dict() for item in self.inputs], "outputs": [item.to_dict() for item in self.outputs], "nodes": [item.to_dict() for item in self.nodes], "edges": [item.to_dict() for item in self.edges], "status": self.status}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowDraft":
        return cls(str(payload.get("id", "")), str(payload.get("name", "")), str(payload.get("description", "")), str(payload.get("version", "draft")), tuple(WorkflowInput.from_dict(v) for v in payload.get("inputs", ()) if isinstance(v, Mapping)), tuple(WorkflowNode.from_dict(v) for v in payload.get("nodes", ()) if isinstance(v, Mapping)), tuple(WorkflowEdge.from_dict(v) for v in payload.get("edges", ()) if isinstance(v, Mapping)), str(payload.get("status", "draft")), tuple(WorkflowOutput.from_dict(v) for v in payload.get("outputs", ()) if isinstance(v, Mapping)))


@dataclass(frozen=True, slots=True)
class WorkflowVersion:
    workflow_id: str
    version: int | str
    name: str
    inputs: tuple[WorkflowInput, ...] = ()
    nodes: tuple[WorkflowNode, ...] = ()
    edges: tuple[WorkflowEdge, ...] = ()
    published_at: str | None = None
    description: str = ""
    outputs: tuple[WorkflowOutput, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"workflow_id": self.workflow_id, "version": self.version, "name": self.name, "inputs": [i.to_dict() for i in self.inputs], "outputs": [i.to_dict() for i in self.outputs], "nodes": [n.to_dict() for n in self.nodes], "edges": [e.to_dict() for e in self.edges], "published_at": self.published_at, "description": self.description}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowVersion":
        return cls(str(payload.get("workflow_id", payload.get("id", ""))), payload.get("version", 1), str(payload.get("name", "")), tuple(WorkflowInput.from_dict(v) for v in payload.get("inputs", ()) if isinstance(v, Mapping)), tuple(WorkflowNode.from_dict(v) for v in payload.get("nodes", ()) if isinstance(v, Mapping)), tuple(WorkflowEdge.from_dict(v) for v in payload.get("edges", ()) if isinstance(v, Mapping)), payload.get("published_at"), str(payload.get("description", "")), tuple(WorkflowOutput.from_dict(v) for v in payload.get("outputs", ()) if isinstance(v, Mapping)))
