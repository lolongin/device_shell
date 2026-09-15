from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any, Mapping
from .models import WorkflowDraft
from .catalog import ActionCatalog
from .expression import validate_expression


_LOOP_DISALLOWED_ACTIONS = frozenset({"loop.for_each", "loop.until", "utility.condition", "utility.confirm"})

# 配置字段的修复建议
_CONFIG_SUGGESTIONS = {
    "device.command": {
        "command": "请输入要执行的命令，例如 'display version' 或 'display interface'",
    },
    "device.reboot": {},
    "file.upload": {
        "source": "请指定本地文件路径，例如 'C:\\upgrades\\firmware.bin'",
        "destination": "请指定设备上的目标路径，例如 '/flash/firmware.bin'",
    },
    "utility.wait": {
        "seconds": "请输入等待秒数，例如 10",
    },
    "utility.condition": {
        "expression": "请输入条件表达式，例如 '${device.software_version} < \"8.200\"'",
    },
    "loop.for_each": {
        "items": "请输入要遍历的列表或引用前置节点的输出，例如 ['item1', 'item2']",
        "action_id": "请选择循环体要执行的操作",
    },
    "terminal.wait": {
        "pattern": "请输入要等待的终端文本，例如 'Password:' 或 'completed'",
    },
    "loop.until": {
        "action_id": "请选择每轮要执行的操作",
        "condition": "请输入停止条件，例如 result.status == 'succeeded'",
    },
}

def _get_config_suggestion(action_id: str, field: str) -> str:
    """获取配置字段的修复建议"""
    action_suggestions = _CONFIG_SUGGESTIONS.get(action_id, {})
    return action_suggestions.get(field, f"请为字段 '{field}' 提供有效的值")

@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str
    node_id: str | None = None
    severity: str = "error"  # "error", "warning", "info"
    fix_suggestion: str | None = None
    doc_link: str | None = None
    affected_nodes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "severity": self.severity,
            "fix_suggestion": self.fix_suggestion,
            "doc_link": self.doc_link,
            "affected_nodes": list(self.affected_nodes) if self.affected_nodes else []
        }

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

def _create_issue(code: str, message: str, node_id: str | None = None, fix_suggestion: str | None = None, doc_link: str | None = None, affected_nodes: tuple[str, ...] = ()) -> ValidationIssue:
    """Helper to create ValidationIssue with enhanced information."""
    return ValidationIssue(code, message, node_id, "error", fix_suggestion, doc_link, affected_nodes)


def _is_exact_reference(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"\$\{[^}]+\}", value))


def _matches_schema_type(value: Any, schema: Mapping[str, Any]) -> bool:
    """Validate the JSON-compatible types used by the action catalog.

    Exact references are intentionally accepted here.  Their concrete type is
    only knowable after upstream nodes run, while embedded references remain
    rejected by the reference scanner below.
    """
    if _is_exact_reference(value):
        return True
    schema_type = schema.get("type")
    types = schema_type if isinstance(schema_type, (list, tuple)) else (schema_type,)
    for item in types:
        if item == "string" and isinstance(value, str):
            return True
        if item == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if item == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if item == "boolean" and isinstance(value, bool):
            return True
        if item == "object" and isinstance(value, Mapping):
            return True
        if item == "array" and isinstance(value, (list, tuple)):
            return True
        if item == "null" and value is None:
            return True
    return False


def _schema_from_value(value: Any) -> dict[str, Any] | None:
    """Return a small JSON-schema fragment for an already-known value."""
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, Mapping):
        return {"type": "object"}
    if isinstance(value, (list, tuple)):
        return {"type": "array"}
    if value is None:
        return {"type": "null"}
    return None


def _schema_types(schema: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(schema, Mapping):
        return ()
    raw_type = schema.get("type")
    if isinstance(raw_type, (list, tuple)):
        return tuple(str(item) for item in raw_type)
    if raw_type is None:
        return ()
    return (str(raw_type),)


def _schemas_compatible(
    expected: Mapping[str, Any] | None,
    actual: Mapping[str, Any] | None,
) -> bool:
    """Check compatibility when a reference's source type is statically known."""
    expected_types = set(_schema_types(expected))
    actual_types = set(_schema_types(actual))
    if not expected_types or not actual_types:
        # Empty schemas represent a value whose type is intentionally dynamic.
        return True
    if "number" in expected_types and "integer" in actual_types:
        actual_types.add("number")
    return bool(expected_types & actual_types)


_SUPPORTED_BRANCH_LABELS = frozenset({"true", "then", "yes", "1", "真", "是", "false", "else", "no", "0", "假", "否"})


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

    def node_settings(node: Any) -> dict[str, Any]:
        return {**dict(node.config), **dict(node.input_mapping)}

    for node in workflow.nodes:
        spec = catalog.get(node.action_id)
        if spec is None:
            errors.append(_create_issue(
                "unknown_action",
                f"unknown action: {node.action_id}",
                node.id,
                fix_suggestion="请从节点库中选择有效的操作类型",
                doc_link="/docs/nodes/available-actions"
            ))
            continue
        settings = node_settings(node)

        def has_config_value(key: str) -> bool:
            aliases = (key,)
            if node.action_id in {"file.upload", "file.download"}:
                if key == "source":
                    aliases = ("source", "source_path")
                elif key == "destination":
                    aliases = ("destination", "destination_path")
            for alias in aliases:
                if alias not in settings:
                    continue
                value = settings[alias]
                if value is not None and not (isinstance(value, str) and not value.strip()):
                    return True
            return False

        properties = spec.input_schema.get("properties")
        if isinstance(properties, Mapping):
            for key, schema in properties.items():
                if key not in settings or not isinstance(schema, Mapping):
                    continue
                value = settings[key]
                if value in (None, ""):
                    continue
                if not _matches_schema_type(value, schema):
                    errors.append(ValidationIssue(
                        "invalid_config_type",
                        f"config {key} must be of type {schema.get('type')}",
                        node.id,
                        fix_suggestion=_get_config_suggestion(node.action_id, str(key)),
                    ))

        for key in spec.required_inputs:
            if not has_config_value(key):
                suggestion = _get_config_suggestion(node.action_id, key)
                errors.append(_create_issue(
                    "missing_required_config",
                    f"required config is missing: {key}",
                    node.id,
                    fix_suggestion=suggestion,
                    doc_link=f"/docs/nodes/{node.action_id.replace('.', '-')}"
                ))
        if node.action_id == "utility.condition":
            expression = settings.get("expression")
            rules = settings.get("rules")
            has_rules = isinstance(rules, (list, tuple)) and any(isinstance(rule, Mapping) and str(rule.get("field", "")).strip() and str(rule.get("operator", "")).strip() for rule in rules)
            if (not isinstance(expression, str) or not expression.strip()) and not has_rules:
                errors.append(ValidationIssue("invalid_condition", "visual condition rules are required", node.id))
            elif isinstance(expression, str) and expression.strip():
                try:
                    validate_expression(expression)
                except ValueError as exc:
                    errors.append(ValidationIssue("invalid_expression", str(exc), node.id))
            logical = str(settings.get("logical_operator") or "AND").upper()
            if logical not in {"AND", "OR"}:
                errors.append(ValidationIssue("invalid_condition_operator", "condition logical operator must be AND or OR", node.id))
        if node.action_id == "terminal.wait":
            mode = str(settings.get("mode") or "contains").strip().lower()
            if mode not in {"contains", "regex"}:
                errors.append(ValidationIssue("invalid_terminal_match_mode", "terminal match mode must be contains or regex", node.id))
            timeout = settings.get("timeout_seconds", 30)
            try:
                timeout_value = float(timeout)
            except (TypeError, ValueError):
                errors.append(ValidationIssue("invalid_number", "timeout_seconds must be a number", node.id))
            else:
                if timeout_value <= 0 or timeout_value > 86_400:
                    errors.append(ValidationIssue("number_out_of_range", "timeout_seconds must be between 0 and 86400", node.id))
            if mode == "regex":
                pattern = str(settings.get("pattern") or "")
                try:
                    re.compile(pattern)
                except re.error as exc:
                    errors.append(ValidationIssue("invalid_terminal_pattern", f"terminal regex is invalid: {exc}", node.id))
        if node.action_id == "utility.confirm" and not str(settings.get("prompt") or "").strip():
            errors.append(ValidationIssue("missing_confirmation_prompt", "人工确认步骤需要填写提示语", node.id))
        if node.action_id == "variable.set" and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(settings.get("name") or "")):
            errors.append(ValidationIssue("invalid_variable_name", "variable name must contain letters, numbers, and underscores", node.id))
        if node.action_id == "variable.set":
            extract = settings.get("extract")
            if extract is not None:
                if not isinstance(extract, Mapping):
                    errors.append(ValidationIssue("invalid_variable_extract", "variable extraction must be an object", node.id))
                else:
                    pattern = extract.get("pattern")
                    compiled = None
                    if not isinstance(pattern, str) or not pattern.strip():
                        errors.append(ValidationIssue("invalid_variable_extract_pattern", "variable extraction pattern is required", node.id))
                    else:
                        try:
                            compiled = re.compile(pattern)
                        except re.error as exc:
                            errors.append(ValidationIssue("invalid_variable_extract_pattern", f"variable extraction pattern is invalid: {exc}", node.id))
                    mode = str(extract.get("mode") or "match").strip().lower()
                    if mode not in {"match", "line"}:
                        errors.append(ValidationIssue("invalid_variable_extract_mode", "variable extraction mode must be match or line", node.id))
                    raw_group = extract.get("group", 0)
                    valid_group = isinstance(raw_group, int) and not isinstance(raw_group, bool) and raw_group >= 0
                    if not valid_group or (compiled is not None and int(raw_group) > compiled.groups):
                        errors.append(ValidationIssue("invalid_variable_extract_group", "variable extraction group is out of range", node.id))
        if node.action_id == "expression.evaluate":
            expression = str(settings.get("expression") or "").strip()
            if not expression:
                errors.append(ValidationIssue("invalid_expression", "expression is required", node.id))
            else:
                try:
                    validate_expression(expression)
                except ValueError as exc:
                    errors.append(ValidationIssue("invalid_expression", str(exc), node.id))
        if node.action_id == "loop.for_each":
            items = settings.get("items")
            child_action = str(settings.get("action_id") or "").strip()
            if (
                not isinstance(items, (list, tuple, str))
                or (isinstance(items, str) and (not items.strip() or not _is_exact_reference(items)))
            ):
                errors.append(ValidationIssue("invalid_loop_items", "loop items must be a list or variable reference", node.id))
            if catalog.get(child_action) is None or child_action in _LOOP_DISALLOWED_ACTIONS:
                errors.append(ValidationIssue("invalid_loop_action", "loop child action is not executable", node.id))
        if node.action_id == "loop.until":
            child_action = str(settings.get("action_id") or "").strip()
            condition = str(settings.get("condition") or "").strip()
            if catalog.get(child_action) is None or child_action in _LOOP_DISALLOWED_ACTIONS:
                errors.append(ValidationIssue("invalid_loop_action", "loop child action is not executable", node.id))
            if not condition:
                errors.append(ValidationIssue("invalid_loop_condition", "loop.until condition is required", node.id))
            else:
                try:
                    validate_expression(condition)
                except ValueError as exc:
                    errors.append(ValidationIssue("invalid_loop_condition", str(exc), node.id))
            for key, minimum, maximum in (("max_iterations", 1, 100), ("interval_seconds", 0, 86_400)):
                value = settings.get(key)
                if value in (None, ""):
                    continue
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    errors.append(ValidationIssue("invalid_number", f"{key} must be a number", node.id))
                else:
                    if number != int(number) if key == "max_iterations" else False:
                        errors.append(ValidationIssue("invalid_number", f"{key} must be an integer", node.id))
                    elif number < minimum or number > maximum:
                        errors.append(ValidationIssue("number_out_of_range", f"{key} must be between {minimum} and {maximum}", node.id))
        for key, upper in (("retry_attempts", 5), ("repeat_count", 20)):
            if key in settings and settings[key] not in (None, ""):
                try: value = int(settings[key])
                except (TypeError, ValueError): errors.append(ValidationIssue("invalid_number", f"{key} must be a number", node.id))
                else:
                    if value < 1 or value > upper: errors.append(ValidationIssue("number_out_of_range", f"{key} must be between 1 and {upper}", node.id))
        if "retry_backoff_seconds" in settings and settings["retry_backoff_seconds"] not in (None, ""):
            try: value = float(settings["retry_backoff_seconds"])
            except (TypeError, ValueError): errors.append(ValidationIssue("invalid_number", "retry_backoff_seconds must be a number", node.id))
            else:
                if value < 0 or value > 60: errors.append(ValidationIssue("number_out_of_range", "retry_backoff_seconds must be between 0 and 60", node.id))
    for edge in workflow.edges:
        if edge.source not in ids or edge.target not in ids:
            errors.append(ValidationIssue("invalid_edge", "edge references an unknown node", edge.source if edge.source not in ids else edge.target)); continue
        incoming[edge.target] += 1; adjacency[edge.source].append(edge.target)
        if edge.condition is not None and (not isinstance(edge.condition, str) or not edge.condition.strip()): errors.append(ValidationIssue("invalid_condition", "edge condition must be a non-empty string", edge.source))
        source_node = next((node for node in workflow.nodes if node.id == edge.source), None)
        if source_node is not None and source_node.action_id == "utility.condition":
            label = str(edge.condition or edge.source_handle or "").strip().casefold()
            if label not in _SUPPORTED_BRANCH_LABELS:
                errors.append(ValidationIssue(
                    "invalid_branch_label",
                    "condition branch label must identify a true or false branch",
                    edge.source,
                ))
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
    input_by_name = {item.name: item for item in workflow.inputs}
    known_inputs = set(input_names) | {"device", "inputs", "outputs", "context"}
    condition_node_ids = {
        node.id for node in workflow.nodes if node.action_id == "utility.condition"
    }
    node_by_id = {node.id: node for node in workflow.nodes}
    variable_aliases: dict[str, tuple[str, str]] = {}
    for node in workflow.nodes:
        if node.action_id != "variable.set":
            continue
        variable_name = str(node_settings(node).get("name") or "").strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable_name):
            variable_aliases[node.id] = (variable_name, node.id)
    predecessors = {node_id: set() for node_id in ids}
    for source in ids:
        pending = list(adjacency[source]); reached: set[str] = set()
        while pending:
            target = pending.pop()
            if target in reached: continue
            reached.add(target); pending.extend(adjacency[target])
        for target in reached - {source}: predecessors[target].add(source)
    device_reference_schema: dict[str, Any] = {
        "id": {"type": "string"},
        "row_id": {"type": "string"},
        "board_id": {"type": "string"},
        "name": {"type": "string"},
        "domain": {"type": "string"},
        "device_type": {"type": "string"},
        "cpu": {"type": "string"},
        "status": {"type": "string"},
        "owner": {"type": ["string", "null"]},
        "vendor": {"type": "string"},
        "model": {"type": "string"},
        "site": {"type": "string"},
        "rack": {"type": "string"},
        "board_type": {"type": "string"},
        "slot": {"type": "string"},
        "status_text": {"type": "string"},
        "tooltip": {"type": "string"},
        "version": {"type": "string"},
        "software_version": {"type": "string"},
        "ssh_endpoint": {"type": ["string", "null"]},
        "telnet_endpoint": {"type": ["string", "null"]},
        "serial_endpoint": {"type": ["string", "null"]},
        "serial_display": {"type": "string"},
        "can_connect_telnet": {"type": "boolean"},
        "can_connect_ssh": {"type": "boolean"},
        "can_connect_serial": {"type": "boolean"},
        "can_claim": {"type": "boolean"},
        "can_release": {"type": "boolean"},
        "can_power_off": {"type": "boolean"},
        "is_simulated": {"type": "boolean"},
        "is_temporary": {"type": "boolean"},
        "is_saved_server": {"type": "boolean"},
        "supports_power_off": {"type": "boolean"},
        "source": {"type": "string"},
        "kind": {"type": "string"},
        "attributes": {"type": "object"},
        "extensions": {"type": "object"},
        "capabilities": {"type": "object"},
        "parent_id": {"type": ["string", "null"]},
        "children": {"type": "array"},
    }

    def output_schema(root: str) -> Mapping[str, Any] | None:
        node = node_by_id.get(root)
        spec = catalog.get(node.action_id) if node is not None else None
        return spec.output_schema if spec is not None else None

    def schema_property(schema: Mapping[str, Any] | None, path: list[str]) -> Mapping[str, Any] | None:
        current: Mapping[str, Any] | None = schema
        for segment in path:
            if not isinstance(current, Mapping):
                return None
            properties = current.get("properties")
            if not isinstance(properties, Mapping) or segment not in properties:
                return None
            candidate = properties[segment]
            current = candidate if isinstance(candidate, Mapping) else None
        return current

    def schema_for_input(name: str, path: list[str]) -> Mapping[str, Any] | None:
        item = input_by_name.get(name)
        if item is None:
            return None
        schema: Mapping[str, Any] = {"type": item.type}
        if not path:
            return schema
        # WorkflowInput currently stores only a top-level type. A mapping
        # default can still make nested object references statically checkable.
        if isinstance(item.default, Mapping):
            nested = item.default
            for segment in path:
                if not isinstance(nested, Mapping) or segment not in nested:
                    return None
                nested = nested[segment]
            return _schema_from_value(nested)
        return None

    def variable_schema(
        alias: str,
        visible: set[str],
        resolving: set[str] | None = None,
    ) -> Mapping[str, Any] | None:
        resolving = set(resolving or ())
        if alias in resolving:
            return None
        source_id = next(
            (
                source
                for source, (name, _node_id) in variable_aliases.items()
                if name == alias and source in visible
            ),
            None,
        )
        if source_id is None:
            return None
        source_settings = node_settings(node_by_id[source_id])
        source_value = source_settings.get("value")
        if _is_exact_reference(source_value):
            return reference_schema(source_value, visible, resolving | {alias})[0]
        return _schema_from_value(source_value)

    def reference_schema(
        ref: str,
        visible: set[str],
        resolving: set[str] | None = None,
    ) -> tuple[Mapping[str, Any] | None, str | None]:
        parts = ref.split(".")
        root = parts[0] if parts else ""
        tail = parts[1:]
        if root in node_by_id:
            if root in condition_node_ids:
                return None, f"compile-time condition node cannot be used as a runtime output reference: {ref}"
            if root not in visible:
                return None, f"missing dependency for node output reference: {ref}"
            schema = output_schema(root)
            if not tail:
                return schema or {"type": "object"}, None
            if tail[0] == "run":
                tail = tail[1:]
            resolved = schema_property(schema, tail)
            if resolved is None:
                fields = schema_property(schema, [])
                properties = fields.get("properties") if isinstance(fields, Mapping) else None
                available = ", ".join(sorted(str(key) for key in properties)) if isinstance(properties, Mapping) else ""
                suffix = f"; available fields: {available}" if available else ""
                return None, f"unknown output field reference: {ref}{suffix}"
            return resolved, None
        if any(name == root and source in visible for source, (name, _node_id) in variable_aliases.items()):
            schema = variable_schema(root, visible, resolving)
            if tail:
                resolved = schema_property(schema, tail)
                if resolved is None:
                    return None, f"unknown variable field reference: {ref}"
                return resolved, None
            return schema, None
        if root in input_by_name:
            schema = schema_for_input(root, tail)
            if tail and schema is None:
                return None, f"unknown workflow input field reference: {ref}"
            return schema, None
        if root == "inputs":
            if not tail:
                return {"type": "object"}, None
            schema = schema_for_input(tail[0], tail[1:])
            if schema is None:
                return None, f"unknown workflow input field reference: {ref}"
            return schema, None
        if root == "outputs":
            if not tail:
                return {"type": "object"}, None
            source = tail[0]
            if source in node_by_id and source not in visible:
                return None, f"missing dependency for node output reference: {ref}"
            if source not in visible and not any(
                name == source and variable_source in visible
                for variable_source, (name, _node_id) in variable_aliases.items()
            ):
                return None, f"unknown workflow output reference: {ref}"
            if source in node_by_id:
                return reference_schema(".".join([source, *tail[1:]]), visible, resolving)
            schema = variable_schema(source, visible, resolving)
            if len(tail) > 1:
                schema = schema_property(schema, tail[1:])
            return schema, None if schema is not None else f"unknown workflow output field reference: {ref}"
        if root == "device":
            if not tail:
                return {"type": "object", "properties": device_reference_schema}, None
            schema = schema_property({"type": "object", "properties": device_reference_schema}, tail)
            if schema is None:
                return None, f"unknown device field reference: {ref}"
            return schema, None
        if root == "context":
            if not tail:
                return {"type": "object"}, None
            if tail[0] == "device":
                return reference_schema("device." + ".".join(tail[1:]), visible, resolving)
            schema = schema_for_input(tail[0], tail[1:])
            if schema is None:
                return None, f"unknown context field reference: {ref}"
            return schema, None
        if root in visible:
            # Loop-local references such as ${item} and ${iteration} are
            # resolved by the loop handler at runtime, so their type is
            # intentionally dynamic at Studio validation time.
            return None, None
        return None, f"unknown or forward variable reference: {ref}"

    def scan(
        value: Any,
        node_id: str,
        visible: set[str],
        expected_schema: Mapping[str, Any] | None = None,
        local_reference_roots: frozenset[str] = frozenset(),
        allow_embedded_reference: bool = False,
    ) -> None:
        if isinstance(value, Mapping):
            properties = expected_schema.get("properties") if isinstance(expected_schema, Mapping) else None
            for key, nested in value.items():
                nested_schema = properties.get(key) if isinstance(properties, Mapping) and isinstance(properties.get(key), Mapping) else None
                nested_allows_embedded = (
                    allow_embedded_reference
                    or (
                        key == "command"
                        and node_by_id.get(node_id) is not None
                        and node_by_id[node_id].action_id == "device.command"
                    )
                )
                scan(
                    nested,
                    node_id,
                    visible,
                    nested_schema,
                    local_reference_roots,
                    nested_allows_embedded,
                )
        elif isinstance(value, (list, tuple)):
            item_schema = expected_schema.get("items") if isinstance(expected_schema, Mapping) and isinstance(expected_schema.get("items"), Mapping) else None
            for nested in value:
                scan(
                    nested,
                    node_id,
                    visible,
                    item_schema,
                    local_reference_roots,
                    allow_embedded_reference,
                )
        elif isinstance(value, str):
            found_refs = refs.findall(value)
            if found_refs and not allow_embedded_reference and re.fullmatch(r"\$\{[^}]+\}", value) is None:
                errors.append(ValidationIssue("embedded_variable_ref", "variable references must occupy the full value", node_id))
            for ref in found_refs:
                root = ref.split(".", 1)[0]
                if root in local_reference_roots:
                    source_schema, reference_error = None, None
                else:
                    source_schema, reference_error = reference_schema(ref, visible)
                if reference_error:
                    code = (
                        "missing_dependency"
                        if reference_error.startswith("missing dependency")
                        else "invalid_variable_ref"
                        if reference_error.startswith("compile-time condition")
                        else
                        "invalid_variable_ref"
                        if reference_error.startswith("unknown or forward")
                        else "invalid_variable_field"
                        if ref.split(".")[0] in known_inputs
                        or ref.split(".")[0] in node_by_id
                        or ref.split(".")[0] in {"context", "outputs"}
                        else "invalid_variable_ref"
                    )
                    errors.append(ValidationIssue(code, reference_error, node_id))
                    continue
                if re.fullmatch(r"\$\{[^}]+\}", value) and expected_schema is not None:
                    if not _schemas_compatible(expected_schema, source_schema):
                        errors.append(ValidationIssue(
                            "invalid_config_type",
                            f"config value reference {value} resolves to {source_schema.get('type') if isinstance(source_schema, Mapping) else 'an unknown type'}, expected {expected_schema.get('type')}",
                            node_id,
                        ))
    for node in workflow.nodes:
        visible_nodes = predecessors[node.id] - condition_node_ids
        visible = known_inputs | visible_nodes | {
            alias_name
            for source, (alias_name, _node_id) in variable_aliases.items()
            if source in visible_nodes
        }
        settings = node_settings(node)
        spec = catalog.get(node.action_id)
        input_schema = spec.input_schema if spec is not None else None
        if node.action_id in {"loop.for_each", "loop.until"}:
            local_refs = {"item", "index"} if node.action_id == "loop.for_each" else {"iteration", "result", "outputs"}
            base_config = {key: value for key, value in settings.items() if key != "action_inputs"}
            scan(base_config, node.id, visible, input_schema)
            child_action = str(settings.get("action_id") or "").strip()
            child_spec = catalog.get(child_action)
            child_schema = child_spec.input_schema if child_spec is not None else None
            scan(
                settings.get("action_inputs"),
                node.id,
                visible | local_refs,
                child_schema,
                frozenset(local_refs),
            )
        else:
            scan(settings, node.id, visible, input_schema)
        for edge in workflow.edges:
            if edge.source == node.id: scan(edge.condition, node.id, visible | {node.id})
    return ValidationResult(tuple(errors), tuple(warnings))
