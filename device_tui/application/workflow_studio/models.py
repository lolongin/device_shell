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

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "required": self.required, "default": self.default, "description": self.description}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowInput":
        return cls(str(payload.get("name", "")), str(payload.get("type", "string")), bool(payload.get("required", False)), payload.get("default"), str(payload.get("description", "")))


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

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description, "version": self.version, "inputs": [item.to_dict() for item in self.inputs], "nodes": [item.to_dict() for item in self.nodes], "edges": [item.to_dict() for item in self.edges], "status": self.status}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowDraft":
        return cls(str(payload.get("id", "")), str(payload.get("name", "")), str(payload.get("description", "")), str(payload.get("version", "draft")), tuple(WorkflowInput.from_dict(v) for v in payload.get("inputs", ()) if isinstance(v, Mapping)), tuple(WorkflowNode.from_dict(v) for v in payload.get("nodes", ()) if isinstance(v, Mapping)), tuple(WorkflowEdge.from_dict(v) for v in payload.get("edges", ()) if isinstance(v, Mapping)), str(payload.get("status", "draft")))


@dataclass(frozen=True, slots=True)
class WorkflowVersion:
    workflow_id: str
    version: int | str
    name: str
    inputs: tuple[WorkflowInput, ...] = ()
    nodes: tuple[WorkflowNode, ...] = ()
    edges: tuple[WorkflowEdge, ...] = ()
    published_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"workflow_id": self.workflow_id, "version": self.version, "name": self.name, "inputs": [i.to_dict() for i in self.inputs], "nodes": [n.to_dict() for n in self.nodes], "edges": [e.to_dict() for e in self.edges], "published_at": self.published_at}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowVersion":
        return cls(str(payload.get("workflow_id", payload.get("id", ""))), payload.get("version", 1), str(payload.get("name", "")), tuple(WorkflowInput.from_dict(v) for v in payload.get("inputs", ()) if isinstance(v, Mapping)), tuple(WorkflowNode.from_dict(v) for v in payload.get("nodes", ()) if isinstance(v, Mapping)), tuple(WorkflowEdge.from_dict(v) for v in payload.get("edges", ()) if isinstance(v, Mapping)), payload.get("published_at"))
