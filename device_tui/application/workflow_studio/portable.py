"""Portable, human- and AI-friendly workflow configuration format."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .models import WorkflowDraft, WorkflowEdge, WorkflowInput, WorkflowNode

FORMAT = "device-tui.workflow"
SCHEMA_VERSION = 1


class PortableWorkflowError(ValueError):
    """Raised when a portable workflow cannot be parsed or converted."""


@dataclass(frozen=True, slots=True)
class PortableWorkflow:
    draft: WorkflowDraft
    required_actions: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def _yaml_load(content: str) -> Mapping[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PortableWorkflowError("YAML import requires the PyYAML package; use JSON or install PyYAML") from exc
    try:
        value = yaml.safe_load(content)
    except Exception as exc:
        raise PortableWorkflowError(f"invalid YAML: {exc}") from exc
    if not isinstance(value, Mapping):
        raise PortableWorkflowError("workflow document must be an object")
    return value


def parse_document(content: str, *, filename: str = "") -> Mapping[str, Any]:
    if not isinstance(content, str) or not content.strip():
        raise PortableWorkflowError("workflow document is empty")
    if filename.casefold().endswith(".json"):
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PortableWorkflowError(f"invalid JSON: {exc.msg}") from exc
        if not isinstance(value, Mapping):
            raise PortableWorkflowError("workflow document must be an object")
        return value
    return _yaml_load(content)


def _as_inputs(values: Any) -> tuple[WorkflowInput, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise PortableWorkflowError("workflow.inputs must be a list")
    return tuple(WorkflowInput.from_dict(item) for item in values if isinstance(item, Mapping))


def _as_nodes(values: Any) -> tuple[WorkflowNode, ...]:
    if not isinstance(values, (list, tuple)):
        raise PortableWorkflowError("workflow.steps must be a list")
    nodes: list[WorkflowNode] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, Mapping):
            raise PortableWorkflowError("each workflow step must be an object")
        node_id = str(item.get("id") or "").strip()
        action_id = str(item.get("action") or item.get("action_id") or "").strip()
        if not node_id or not action_id:
            raise PortableWorkflowError("each workflow step requires id and action")
        if node_id in seen:
            raise PortableWorkflowError(f"duplicate workflow step id: {node_id}")
        seen.add(node_id)
        config = dict(item.get("with") or item.get("config") or {})
        retry = item.get("retry")
        if isinstance(retry, Mapping):
            if "attempts" in retry:
                config["retry_attempts"] = retry["attempts"]
            if "backoff_seconds" in retry:
                config["retry_backoff_seconds"] = retry["backoff_seconds"]
        nodes.append(WorkflowNode(node_id, action_id, config=config, input_mapping=dict(item.get("inputs") or item.get("input_mapping") or {}), position=dict(item.get("position") or {})))
    return tuple(nodes)


def _as_edges(values: Any, node_ids: set[str]) -> tuple[WorkflowEdge, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise PortableWorkflowError("workflow.edges must be a list")
    edges: list[WorkflowEdge] = []
    for item in values:
        if not isinstance(item, Mapping):
            raise PortableWorkflowError("each workflow edge must be an object")
        source = str(item.get("from") or item.get("source") or "").strip()
        target = str(item.get("to") or item.get("target") or "").strip()
        if source not in node_ids or target not in node_ids:
            raise PortableWorkflowError(f"edge references an unknown step: {source}->{target}")
        edges.append(WorkflowEdge(source, target, item.get("condition"), item.get("source_handle")))
    return tuple(edges)


def from_document(document: Mapping[str, Any]) -> PortableWorkflow:
    if document.get("format") != FORMAT:
        raise PortableWorkflowError(f"format must be {FORMAT}")
    try:
        version = int(document.get("schema_version", 0))
    except (TypeError, ValueError) as exc:
        raise PortableWorkflowError("schema_version must be an integer") from exc
    if version != SCHEMA_VERSION:
        raise PortableWorkflowError(f"unsupported workflow schema_version: {version}")
    body = document.get("workflow")
    if not isinstance(body, Mapping):
        raise PortableWorkflowError("workflow is required")
    nodes = _as_nodes(body.get("steps", body.get("nodes")))
    edges = _as_edges(body.get("edges"), {node.id for node in nodes})
    name = str(body.get("name") or "").strip()
    if not name:
        raise PortableWorkflowError("workflow.name is required")
    draft = WorkflowDraft(id="", name=name, description=str(body.get("description") or ""), inputs=_as_inputs(body.get("inputs")), nodes=nodes, edges=edges)
    return PortableWorkflow(draft=draft, required_actions=tuple(dict.fromkeys(node.action_id for node in nodes)))


def export_document(workflow: WorkflowDraft | Any) -> dict[str, Any]:
    nodes = []
    for node in workflow.nodes:
        step: dict[str, Any] = {"id": node.id, "action": node.action_id}
        if node.config:
            step["with"] = dict(node.config)
        if node.input_mapping:
            step["inputs"] = dict(node.input_mapping)
        if node.position:
            step["position"] = dict(node.position)
        retry = {}
        if "retry_attempts" in node.config:
            retry["attempts"] = node.config["retry_attempts"]
        if "retry_backoff_seconds" in node.config:
            retry["backoff_seconds"] = node.config["retry_backoff_seconds"]
        if retry:
            step["retry"] = retry
        nodes.append(step)
    body = {
        "name": workflow.name,
        "description": getattr(workflow, "description", ""),
        "inputs": [item.to_dict() for item in workflow.inputs],
        "steps": nodes,
        "edges": [
            {
                "from": edge.source,
                "to": edge.target,
                **{key: value for key, value in edge.to_dict().items() if key not in {"source", "target"}},
            }
            for edge in workflow.edges
        ],
    }
    return {"format": FORMAT, "schema_version": SCHEMA_VERSION, "workflow": body}


def dump_document(document: Mapping[str, Any], *, fmt: str = "yaml") -> str:
    if fmt == "json":
        return json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PortableWorkflowError("YAML export requires the PyYAML package; use JSON instead") from exc
    return yaml.safe_dump(dict(document), allow_unicode=True, sort_keys=False)


__all__ = ["FORMAT", "SCHEMA_VERSION", "PortableWorkflow", "PortableWorkflowError", "dump_document", "export_document", "from_document", "parse_document"]
