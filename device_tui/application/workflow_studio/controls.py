"""Platform-neutral control registry for workflow variable contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ControlDefinition:
    id: str
    primitive_types: frozenset[str]
    semantic_types: frozenset[str] = frozenset()
    default_props: dict[str, Any] = field(default_factory=dict)

    def supports(self, variable: Any) -> bool:
        legacy = str(getattr(variable, "type", "string") or "string").casefold()
        primitive = str(getattr(variable, "primitive_type", "") or ("array" if legacy == "devices" else ("string" if legacy in {"file", "device"} else legacy))).casefold()
        semantic = str(getattr(variable, "semantic_type", "") or {"file": "file", "device": "device", "devices": "device_list"}.get(legacy, "text" if legacy == "string" else legacy)).casefold()
        return primitive in self.primitive_types and (not self.semantic_types or semantic in self.semantic_types)


class ControlRegistry:
    def __init__(self, definitions: Iterable[ControlDefinition] = ()) -> None:
        self._definitions: dict[str, ControlDefinition] = {definition.id: definition for definition in definitions}

    def register(self, definition: ControlDefinition) -> None:
        if not definition.id.strip():
            raise ValueError("control id is required")
        self._definitions[definition.id] = definition

    def get(self, control_id: str) -> ControlDefinition | None:
        return self._definitions.get(control_id)

    def resolve(self, variable: Any) -> dict[str, Any]:
        hints = getattr(variable, "ui_hints", {}) or {}
        requested = str(hints.get("control") or "").strip()
        if requested:
            definition = self.get(requested)
            if definition is None or not definition.supports(variable):
                raise ValueError(f"unsupported control {requested} for variable {getattr(variable, 'name', '')}")
        else:
            definition = self._select_default(variable)
        props = dict(definition.default_props)
        props.update(hints.get("props") or {})
        constraints = getattr(variable, "constraints", {}) or {}
        props.update(constraints)
        if getattr(variable, "multiple", False):
            props["multiple"] = True
        return {"id": definition.id, "props": props}

    def _select_default(self, variable: Any) -> ControlDefinition:
        legacy = str(getattr(variable, "type", "string") or "string").casefold()
        semantic = str(getattr(variable, "semantic_type", "") or {"file": "file", "device": "device", "devices": "device_list"}.get(legacy, "text" if legacy == "string" else legacy)).casefold()
        primitive = str(getattr(variable, "primitive_type", "") or ("array" if legacy == "devices" else ("string" if legacy in {"file", "device"} else legacy))).casefold()
        preferred = {
            "file": "file-picker", "file_path": "file-picker", "directory": "directory-picker",
            "device": "device-picker", "device_list": "device-list-picker", "enum": "select",
            "json": "json-editor", "image": "file-picker", "date": "date-picker", "time": "time-picker",
        }.get(semantic)
        if preferred and self.get(preferred) is not None:
            return self.get(preferred)  # type: ignore[return-value]
        fallback = {"boolean": "switch", "number": "number-input", "integer": "number-input", "object": "json-editor", "array": "json-editor"}.get(primitive, "text-input")
        definition = self.get(fallback) or self.get("text-input")
        if definition is None:
            raise ValueError("control registry has no compatible default control")
        return definition


def build_control_registry() -> ControlRegistry:
    registry = ControlRegistry()
    registry.register(ControlDefinition("text-input", frozenset({"string"}), frozenset({"text", "url"})))
    registry.register(ControlDefinition("text-area", frozenset({"string"}), frozenset({"text"})))
    registry.register(ControlDefinition("number-input", frozenset({"number", "integer"})))
    registry.register(ControlDefinition("file-picker", frozenset({"string"}), frozenset({"file", "file_path", "image"})))
    registry.register(ControlDefinition("directory-picker", frozenset({"string"}), frozenset({"directory"})))
    registry.register(ControlDefinition("device-picker", frozenset({"string"}), frozenset({"device"})))
    registry.register(ControlDefinition("device-list-picker", frozenset({"array"}), frozenset({"device_list"})))
    registry.register(ControlDefinition("select", frozenset({"string", "number", "integer"}), frozenset({"enum"})))
    registry.register(ControlDefinition("switch", frozenset({"boolean"})))
    registry.register(ControlDefinition("date-picker", frozenset({"string"}), frozenset({"date"})))
    registry.register(ControlDefinition("time-picker", frozenset({"string"}), frozenset({"time"})))
    registry.register(ControlDefinition("json-editor", frozenset({"string", "object", "array"}), frozenset({"json"})))
    return registry


def resolve_control(variable: Any, registry: ControlRegistry | None = None) -> dict[str, Any]:
    return (registry or build_control_registry()).resolve(variable)


__all__ = ["ControlDefinition", "ControlRegistry", "build_control_registry", "resolve_control"]
