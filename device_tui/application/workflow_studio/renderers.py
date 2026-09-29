"""Platform-neutral output renderer registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class RendererDefinition:
    id: str
    presentations: frozenset[str]
    primitive_types: frozenset[str] = frozenset()

    def supports(self, output: Any) -> bool:
        presentation = str(getattr(output, "presentation", "text") or "text").casefold()
        primitive = str(getattr(output, "type", "any") or "any").casefold()
        return presentation in self.presentations and (not self.primitive_types or primitive in self.primitive_types or primitive == "any")


class OutputRendererRegistry:
    def __init__(self, definitions: Iterable[RendererDefinition] = ()) -> None:
        self._definitions = {definition.id: definition for definition in definitions}

    def register(self, definition: RendererDefinition) -> None:
        if not definition.id.strip():
            raise ValueError("renderer id is required")
        self._definitions[definition.id] = definition

    def resolve(self, output: Any) -> dict[str, Any]:
        requested = str(getattr(output, "presentation", "text") or "text").casefold()
        definition = next((item for item in self._definitions.values() if requested in item.presentations and item.supports(output)), None)
        if definition is None:
            raise ValueError(f"unsupported output presentation {requested}")
        result: dict[str, Any] = {"id": definition.id, "props": {}}
        mime_type = str(getattr(output, "mime_type", "") or "")
        download_name = str(getattr(output, "download_name", "") or "")
        if mime_type:
            result["props"]["mimeType"] = mime_type
        if download_name:
            result["props"]["downloadName"] = download_name
        return result


def build_output_renderer_registry() -> OutputRendererRegistry:
    return OutputRendererRegistry((
        RendererDefinition("text", frozenset({"text"}), frozenset({"any", "string", "number", "integer", "boolean"})),
        RendererDefinition("json", frozenset({"json"}), frozenset({"any", "string", "object", "array"})),
        RendererDefinition("table", frozenset({"table"}), frozenset({"any", "array", "object"})),
        RendererDefinition("download", frozenset({"download"}), frozenset({"any", "string", "file"})),
        RendererDefinition("device", frozenset({"device"}), frozenset({"any", "object", "array"})),
        RendererDefinition("hidden", frozenset({"hidden"})),
    ))


def resolve_output_renderer(output: Any, registry: OutputRendererRegistry | None = None) -> dict[str, Any]:
    return (registry or build_output_renderer_registry()).resolve(output)


__all__ = ["RendererDefinition", "OutputRendererRegistry", "build_output_renderer_registry", "resolve_output_renderer"]
