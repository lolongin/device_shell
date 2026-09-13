from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any, Mapping
from .models import WorkflowDraft
from .catalog import ActionCatalog
from .expression import validate_expression


_LOOP_DISALLOWED_ACTIONS = frozenset({"loop.for_each", "utility.condition", "utility.confirm"})

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


def validate_workflow_inputs(workflow: WorkflowDraft, supplied: Mapping[str, Any]) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    for item in workflow.inputs:
        value = supplied.get(item.name, item.default)
        if item.required and (value is None or (isinstance(value, str) and not value.strip())):
            issues.append(ValidationIssue("missing_workflow_input", f"required workflow input is missing: {item.name}"))
            continue
        if value is None:
            continue
        valid = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, Mapping),
            "array": isinstance(value, (list, tuple)),
        }.get(item.type, True)
        if not valid:
            issues.append(ValidationIssue("invalid_workflow_input_type", f"workflow input {item.name} must be {item.type}"))
    return tuple(issues)

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
        if node.action_id == "utility.condition":
            expression = node.config.get("expression") or node.input_mapping.get("expression")
            rules = node.config.get("rules") or node.input_mapping.get("rules")
            has_rules = isinstance(rules, (list, tuple)) and any(isinstance(rule, Mapping) and str(rule.get("field", "")).strip() and str(rule.get("operator", "")).strip() for rule in rules)
            if (not isinstance(expression, str) or not expression.strip()) and not has_rules:
                errors.append(ValidationIssue("invalid_condition", "visual condition rules are required", node.id))
            elif isinstance(expression, str) and expression.strip():
                try:
                    validate_expression(expression)
                except ValueError as exc:
                    errors.append(ValidationIssue("invalid_expression", str(exc), node.id))
            logical = str(node.config.get("logical_operator") or "AND").upper()
            if logical not in {"AND", "OR"}:
                errors.append(ValidationIssue("invalid_condition_operator", "condition logical operator must be AND or OR", node.id))
        if node.action_id == "utility.confirm" and not str(node.config.get("prompt") or node.input_mapping.get("prompt") or "").strip():
            errors.append(ValidationIssue("missing_confirmation_prompt", "人工确认步骤需要填写提示语", node.id))
        if node.action_id == "variable.set" and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(node.config.get("name") or node.input_mapping.get("name") or "")):
            errors.append(ValidationIssue("invalid_variable_name", "variable name must contain letters, numbers, and underscores", node.id))
        if node.action_id == "expression.evaluate":
            expression = str(node.config.get("expression") or node.input_mapping.get("expression") or "").strip()
            if not expression:
                errors.append(ValidationIssue("invalid_expression", "expression is required", node.id))
            else:
                try:
                    validate_expression(expression)
                except ValueError as exc:
                    errors.append(ValidationIssue("invalid_expression", str(exc), node.id))
        if node.action_id == "loop.for_each":
            items = node.config.get("items", node.input_mapping.get("items"))
            child_action = str(node.config.get("action_id") or node.input_mapping.get("action_id") or "").strip()
            if not isinstance(items, (list, tuple, str)) or (isinstance(items, str) and not items.strip()):
                errors.append(ValidationIssue("invalid_loop_items", "loop items must be a list or variable reference", node.id))
            if catalog.get(child_action) is None or child_action in _LOOP_DISALLOWED_ACTIONS:
                errors.append(ValidationIssue("invalid_loop_action", "loop child action is not executable", node.id))
        for key, upper in (("retry_attempts", 5), ("repeat_count", 20)):
            if key in node.config and node.config[key] not in (None, ""):
                try: value = int(node.config[key])
                except (TypeError, ValueError): errors.append(ValidationIssue("invalid_number", f"{key} must be a number", node.id))
                else:
                    if value < 1 or value > upper: errors.append(ValidationIssue("number_out_of_range", f"{key} must be between 1 and {upper}", node.id))
        if "retry_backoff_seconds" in node.config and node.config["retry_backoff_seconds"] not in (None, ""):
            try: value = float(node.config["retry_backoff_seconds"])
            except (TypeError, ValueError): errors.append(ValidationIssue("invalid_number", "retry_backoff_seconds must be a number", node.id))
            else:
                if value < 0 or value > 60: errors.append(ValidationIssue("number_out_of_range", "retry_backoff_seconds must be between 0 and 60", node.id))
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
            found_refs = refs.findall(value)
            if found_refs and re.fullmatch(r"\$\{[^}]+\}", value) is None:
                errors.append(ValidationIssue("embedded_variable_ref", "variable references must occupy the full value", node_id))
            for ref in found_refs:
                root = ref.split(".", 1)[0]
                if root not in visible and root not in known_inputs:
                    errors.append(ValidationIssue("invalid_variable_ref", f"unknown or forward variable reference: {ref}", node_id))
    for node in workflow.nodes:
        visible = known_inputs | predecessors[node.id]
        if node.action_id == "loop.for_each" and isinstance(node.config, Mapping):
            base_config = {key: value for key, value in node.config.items() if key != "action_inputs"}
            scan(base_config, node.id, visible)
            scan(node.config.get("action_inputs"), node.id, visible | {"item", "index"})
        else:
            scan(node.config, node.id, visible)
        scan(node.input_mapping, node.id, visible)
        for edge in workflow.edges:
            if edge.source == node.id: scan(edge.condition, node.id, visible | {node.id})
    return ValidationResult(tuple(errors), tuple(warnings))
