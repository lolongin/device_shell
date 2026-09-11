from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any, Mapping
from .models import WorkflowDraft
from .catalog import ActionCatalog

@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    node_id: str | None = None

@dataclass(frozen=True, slots=True)
class ValidationResult:
    errors: tuple[ValidationIssue, ...] = ()
    warnings: tuple[ValidationIssue, ...] = ()
    @property
    def valid(self) -> bool: return not self.errors
    @property
    def is_valid(self) -> bool: return self.valid

def validate_workflow(workflow: WorkflowDraft, catalog: ActionCatalog) -> ValidationResult:
    errors: list[ValidationIssue] = []; warnings: list[ValidationIssue] = []
    ids = {n.id for n in workflow.nodes}
    if len(ids) != len(workflow.nodes):
        seen: set[str] = set()
        for node in workflow.nodes:
            if node.id in seen: errors.append(ValidationIssue("duplicate_node_id", f"duplicate node id: {node.id}", node.id))
            seen.add(node.id)
    input_names = [item.name for item in workflow.inputs]
    if len(set(input_names)) != len(input_names):
        errors.append(ValidationIssue("duplicate_input_name", "workflow input names must be unique"))
    incoming = {n: 0 for n in ids}; adjacency = {n: [] for n in ids}
    for node in workflow.nodes:
        spec = catalog.get(node.action_id)
        if spec is None:
            errors.append(ValidationIssue("unknown_action", f"unknown action: {node.action_id}", node.id)); continue
        for key in spec.required_inputs:
            value = node.config.get(key, node.input_mapping.get(key))
            if key not in node.config and key not in node.input_mapping or value is None or (isinstance(value, str) and not value.strip()):
                errors.append(ValidationIssue("missing_required_config", f"required config is missing: {key}", node.id))
        if spec.risk in {"high", "critical"}:
            warnings.append(ValidationIssue("high_risk_action", f"high-risk action: {node.action_id}", node.id))
        if node.action_id == "utility.condition":
            expression = node.config.get("expression") or node.input_mapping.get("expression")
            if not isinstance(expression, str) or not expression.strip():
                errors.append(ValidationIssue("invalid_condition", "condition expression is required", node.id))
    for edge in workflow.edges:
        if edge.source not in ids or edge.target not in ids:
            errors.append(ValidationIssue("invalid_edge", "edge references an unknown node", edge.source if edge.source not in ids else edge.target)); continue
        incoming[edge.target] += 1; adjacency[edge.source].append(edge.target)
        if edge.condition is not None and (not isinstance(edge.condition, str) or not edge.condition.strip()): errors.append(ValidationIssue("invalid_condition", "edge condition must be a non-empty string", edge.source))
    if len(workflow.nodes) > 1:
        roots = {n for n, count in incoming.items() if count == 0}
        if len(roots) != 1:
            errors.append(ValidationIssue("disconnected_node", "workflow must have exactly one root node"))
        reachable = set(roots)
        stack = list(roots)
        while stack:
            for target in adjacency[stack.pop()]:
                if target not in reachable: reachable.add(target); stack.append(target)
        for node_id in ids - reachable: errors.append(ValidationIssue("disconnected_node", "node is disconnected from workflow", node_id))
    visiting: set[str] = set(); visited: set[str] = set()
    def visit(node_id: str) -> None:
        if node_id in visiting: errors.append(ValidationIssue("cycle", "workflow contains a cycle", node_id)); return
        if node_id in visited: return
        visiting.add(node_id)
        for target in adjacency[node_id]: visit(target)
        visiting.remove(node_id); visited.add(node_id)
    for node_id in ids: visit(node_id)
    refs = re.compile(r"\$\{([^}]+)\}")
    known_inputs = set(input_names) | {"device", "inputs"}
    predecessors = {node_id: set() for node_id in ids}
    for source in ids:
        pending = list(adjacency[source]); reached: set[str] = set()
        while pending:
            target = pending.pop()
            if target in reached: continue
            reached.add(target); pending.extend(adjacency[target])
        for target in reached - {source}: predecessors[target].add(source)
    def scan(value: Any, node_id: str, visible: set[str]) -> None:
        if isinstance(value, Mapping):
            for nested in value.values(): scan(nested, node_id, visible)
        elif isinstance(value, (list, tuple)):
            for nested in value: scan(nested, node_id, visible)
        elif isinstance(value, str):
            for ref in refs.findall(value):
                root = ref.split(".", 1)[0]
                if root not in visible and root not in known_inputs:
                    errors.append(ValidationIssue("invalid_variable_ref", f"unknown or forward variable reference: {ref}", node_id))
    for node in workflow.nodes:
        visible = known_inputs | predecessors[node.id]
        scan(node.config, node.id, visible); scan(node.input_mapping, node.id, visible)
        for edge in workflow.edges:
            if edge.source == node.id: scan(edge.condition, node.id, visible | {node.id})
    return ValidationResult(tuple(errors), tuple(warnings))
