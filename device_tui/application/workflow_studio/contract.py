"""The stable input/output contract shared by workflow authoring and runtime.

The graph remains an implementation detail.  A published workflow exposes this
small contract so a caller can render inputs, submit values, and present outputs
without knowing which nodes implement it.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping
from .controls import resolve_control
from .renderers import resolve_output_renderer

INPUT_TYPES = frozenset({"string", "number", "integer", "boolean", "file", "device", "devices", "array", "object"})
SEMANTIC_TYPES = frozenset({"text", "string", "number", "integer", "boolean", "array", "object", "file", "file_path", "directory", "device", "device_list", "image", "enum", "date", "time", "url", "json"})
INPUT_SOURCES = frozenset({"runtime", "context", "literal"})
INPUT_PRESENTATIONS = frozenset({"text", "number", "checkbox", "file", "device", "device-list", "json", "select"})
OUTPUT_PRESENTATIONS = frozenset({"text", "json", "table", "download", "device", "hidden"})
_REFERENCE = re.compile(r"\$\{([^}]+)\}")


def input_contract(item: Any) -> dict[str, Any]:
    """Return a normalized, renderer-friendly input descriptor."""
    kind = str(getattr(item, "type", "string") or "string").casefold()
    presentation = str(getattr(item, "presentation", "") or "").casefold()
    if not presentation:
        presentation = {"file": "file", "device": "device", "devices": "device-list", "boolean": "checkbox", "number": "number", "integer": "number", "array": "json", "object": "json"}.get(kind, "text")
    result: dict[str, Any] = {
        "name": str(getattr(item, "name", "")),
        "type": kind,
        "required": bool(getattr(item, "required", False)),
        "default": getattr(item, "default", None),
        "description": str(getattr(item, "description", "") or ""),
        "source": str(getattr(item, "source", "runtime") or "runtime"),
        "presentation": presentation,
        "multiple": bool(getattr(item, "multiple", kind == "devices")),
        "primitiveType": str(getattr(item, "primitive_type", "") or ("array" if kind == "devices" else ("string" if kind in {"file", "device"} else kind))),
        "semanticType": str(getattr(item, "semantic_type", "") or {"file": "file", "device": "device", "devices": "device_list"}.get(kind, "text" if kind == "string" else kind)),
        "scope": str(getattr(item, "scope", "input") or "input"),
    }
    for key in ("accept", "placeholder", "options"):
        value = getattr(item, key, None)
        if value not in (None, "", ()):
            result[key] = list(value) if key == "options" and isinstance(value, tuple) else value
    constraints = getattr(item, "constraints", {}) or {}
    if constraints:
        result["constraints"] = dict(constraints)
    ui_hints = getattr(item, "ui_hints", {}) or {}
    if ui_hints:
        result["uiHints"] = dict(ui_hints)
    result["control"] = resolve_control(item)
    return result


def output_contract(item: Any) -> dict[str, Any]:
    """Return a normalized output descriptor for published workflow clients."""
    presentation = str(getattr(item, "presentation", "text") or "text").casefold()
    result = dict(item.to_dict())
    result["presentation"] = presentation
    result["renderer"] = resolve_output_renderer(item)
    mime_type = getattr(item, "mime_type", "")
    download_name = getattr(item, "download_name", "")
    if mime_type:
        result["mime_type"] = str(mime_type)
    if download_name:
        result["download_name"] = str(download_name)
    return result


def coerce_input_value(item: Any, value: Any) -> Any:
    """Convert form values into the JSON-compatible runtime value."""
    legacy = str(getattr(item, "type", "string") or "string").casefold()
    primitive = str(getattr(item, "primitive_type", "") or ("array" if legacy == "devices" else ("string" if legacy in {"file", "device"} else legacy))).casefold()
    semantic = str(getattr(item, "semantic_type", "") or {"file": "file", "device": "device", "devices": "device_list"}.get(legacy, "text" if legacy == "string" else legacy)).casefold()
    if value is None:
        return None
    if semantic == "device_list":
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return [str(part) for part in value] if isinstance(value, (list, tuple)) else value
    if semantic in {"file", "file_path", "device"} or primitive == "string":
        return str(value)
    if primitive == "boolean":
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return bool(value)
    if primitive == "integer":
        return int(value)
    if primitive == "number":
        return float(value)
    if primitive in {"array", "object"} and isinstance(value, str):
        return json.loads(value)
    return value


def resolve_input_values(definitions: Any, supplied: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Apply defaults and coerce values, returning values and field errors."""
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for item in definitions:
        name = str(getattr(item, "name", ""))
        raw = supplied.get(name, getattr(item, "default", None))
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            if bool(getattr(item, "required", False)):
                errors[name] = "required"
            continue
        try:
            values[name] = coerce_input_value(item, raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            errors[name] = f"invalid_{getattr(item, 'primitive_type', '') or getattr(item, 'type', 'value')}"
    return values, errors


def resolve_workflow_value(value: Any, context: Mapping[str, Any], *, strict: bool = False) -> Any:
    """Resolve a workflow reference in a scalar, mapping, or sequence.

    An exact reference returns its native value; references embedded in text are
    rendered as strings.  This is the common rule used by variable insertion,
    action configuration, and output rendering.
    """
    if isinstance(value, Mapping):
        return {key: resolve_workflow_value(item, context, strict=strict) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        resolved = [resolve_workflow_value(item, context, strict=strict) for item in value]
        return tuple(resolved) if isinstance(value, tuple) else resolved
    if not isinstance(value, str):
        return value

    def lookup(path: str) -> Any:
        current: Any = context
        for part in path.strip().split("."):
            if isinstance(current, Mapping) and part in current:
                current = current[part]
            else:
                if strict:
                    raise KeyError(path.strip())
                return ""
        return current

    exact = re.fullmatch(r"\$\{([^}]+)\}", value.strip())
    if exact:
        return lookup(exact.group(1))
    return _REFERENCE.sub(lambda match: str(lookup(match.group(1))), value)


__all__ = ["INPUT_TYPES", "SEMANTIC_TYPES", "INPUT_SOURCES", "INPUT_PRESENTATIONS", "OUTPUT_PRESENTATIONS", "input_contract", "output_contract", "coerce_input_value", "resolve_input_values", "resolve_workflow_value"]
