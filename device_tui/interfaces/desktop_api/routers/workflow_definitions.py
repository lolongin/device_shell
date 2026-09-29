"""No-code workflow definition lifecycle endpoints."""

from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import asdict
import json
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Mapping
from uuid import uuid4

from fastapi import APIRouter, Depends

from device_tui.application import DeviceTarget, TaskCreate
from device_tui.application.tasking.protocol import (
    Action,
    WorkflowDefinition as TaskWorkflowDefinition,
    WorkflowStep,
)
from device_tui.framework import TaskPlan, WorkflowNode
from device_tui.application.workflow_studio import (
    WorkflowDraft,
    WorkflowEdge as StudioWorkflowEdge,
    WorkflowNode as StudioWorkflowNode,
    build_action_catalog,
    evaluate_expression,
    validate_workflow,
    validate_workflow_inputs,
    PortableWorkflowError,
    dump_document,
    export_document,
    from_document,
    parse_document,
    input_contract,
    output_contract,
    resolve_input_values,
)
from device_tui.application.errors import ApplicationConflictError, ResourceNotFoundError, UnsupportedOperationError
from device_tui.domain.devices.repository import RepositoryError

from ..dependencies import authorize, get_context

router = APIRouter(prefix="/api/v1/workflow-definitions", tags=["workflow-definitions"], dependencies=[Depends(authorize)])


_ACTION_WORKFLOW_IDS = {
    "device.command": "terminal.command",
    "script.run": "script.run",
    "device.reboot": "device.reboot",
    "utility.wait": "utility.wait",
    "terminal.wait": "terminal.wait",
    "utility.confirm": "utility.confirm",
    "file.upload": "file.transfer",
    "file.download": "file.transfer",
    "device.select": "device.select",
    "device.connect": "device.wait_online",
    "device.info": "device.info",
    "result.save": "result.save",
    "device.ssh": "device.wait_online",
    "device.telnet": "device.wait_online",
    "variable.set": "variable.set",
    "expression.evaluate": "expression.evaluate",
    "loop.for_each": "loop.for_each",
    "device.for_each": "device.for_each",
    "loop.until": "loop.until",
    "workflow.outputs": "workflow.outputs",
}

_LOOP_DISALLOWED_ACTIONS = frozenset(
    {"loop.for_each", "device.for_each", "loop.until", "utility.condition", "utility.confirm", "workflow.call"}
)
_HIGH_RISK_WORKFLOW_IDS = frozenset({"device.reboot", "file.transfer", "script.run"})
_HIGH_RISK_ACTION_IDS = frozenset({"device.reboot", "file.upload", "file.download", "script.run"})
_CUSTOM_ACTIONS_SETTING = "workflow.custom_actions"
_CUSTOM_ACTION_LIMIT = 200
_WORKFLOW_TEMPLATES_SETTING = "workflow.templates"
_WORKFLOW_TEMPLATE_LIMIT = 100
_WORKFLOW_SCRIPTS_SETTING = "workflow.scripts"
_WORKFLOW_SCRIPT_LIMIT = 500
_REFERENCE_PATTERN = re.compile(r"\$\{([^}]+)\}")
_WORKFLOW_SCRIPT_INPUT_TYPES = frozenset({"string", "number", "boolean", "object", "array"})

_BUILT_IN_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "id": "builtin_device_inspection",
        "name": "设备信息检查",
        "description": "采集设备信息并输出型号与软件版本。",
        "built_in": True,
        "workflow": {
            "name": "设备信息检查",
            "description": "采集设备信息并输出型号与软件版本。",
            "inputs": [],
            "outputs": [
                {"name": "model", "value": "${device_info.model}", "type": "string", "description": "设备型号"},
                {"name": "software_version", "value": "${device_info.software_version}", "type": "string", "description": "软件版本"},
            ],
            "nodes": [
                {"id": "device_info", "action_id": "device.info", "config": {"fields": ["model", "software_version"]}},
            ],
            "edges": [],
        },
    },
    {
        "id": "builtin_command_result",
        "name": "执行命令并保存结果",
        "description": "执行参数化设备命令，并把标准输出作为流程结果。",
        "built_in": True,
        "workflow": {
            "name": "执行命令并保存结果",
            "description": "执行参数化设备命令，并把标准输出作为流程结果。",
            "inputs": [
                {"name": "command", "type": "string", "required": True, "default": "display version", "description": "要执行的命令"},
            ],
            "outputs": [
                {"name": "stdout", "value": "${command.stdout}", "type": "string", "description": "命令标准输出"},
                {"name": "exit_code", "value": "${command.exit_code}", "type": "integer", "description": "命令退出码"},
            ],
            "nodes": [
                {"id": "command", "action_id": "device.command", "config": {"command": "${inputs.command}", "execution_mode": "device"}},
            ],
            "edges": [],
        },
    },
)


def _workflow_id_for_action(action_id: str, params: Mapping[str, Any]) -> str | None:
    """Resolve configurable Studio actions to their concrete runtime Workflow."""
    if action_id == "device.command":
        execution_mode = str(params.get("execution_mode") or "device").strip().casefold()
        if execution_mode == "device":
            return "terminal.command"
        if execution_mode in {"shell", "bash"}:
            return "shell.command"
        return None
    return _ACTION_WORKFLOW_IDS.get(action_id)


def _requires_risk_confirmation(version: Any) -> bool:
    return any(
        node.action_id in _HIGH_RISK_ACTION_IDS
        or (
            node.action_id in {"loop.for_each", "device.for_each", "loop.until"}
            and str(
                {
                    **dict(getattr(node, "config", {}) or {}),
                    **dict(getattr(node, "input_mapping", {}) or {}),
                }.get("action_id")
                or ""
            ) in _HIGH_RISK_ACTION_IDS
        )
        for node in version.nodes
    )


def _mapped_child_input(value: Any, tail: list[str]) -> Any:
    if not tail:
        return value
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return value[:-1] + "." + ".".join(tail) + "}"
    current = value
    for segment in tail:
        if not isinstance(current, Mapping) or segment not in current:
            raise UnsupportedOperationError(f"sub-workflow input does not contain field: {'.'.join(tail)}")
        current = current[segment]
    return current


def _rewrite_child_value(
    value: Any,
    *,
    prefix: str,
    child_node_ids: set[str],
    child_inputs: Mapping[str, Any],
    variable_aliases: Mapping[str, str],
) -> Any:
    """Bind child inputs and namespace its runtime output references."""
    if isinstance(value, Mapping):
        return {
            str(key): _rewrite_child_value(
                nested,
                prefix=prefix,
                child_node_ids=child_node_ids,
                child_inputs=child_inputs,
                variable_aliases=variable_aliases,
            )
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [
            _rewrite_child_value(
                nested,
                prefix=prefix,
                child_node_ids=child_node_ids,
                child_inputs=child_inputs,
                variable_aliases=variable_aliases,
            )
            for nested in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _rewrite_child_value(
                nested,
                prefix=prefix,
                child_node_ids=child_node_ids,
                child_inputs=child_inputs,
                variable_aliases=variable_aliases,
            )
            for nested in value
        )
    if not isinstance(value, str):
        return value

    def replacement(match: re.Match[str]) -> Any:
        parts = match.group(1).split(".")
        root = parts[0] if parts else ""
        if root == "inputs" and len(parts) > 1 and parts[1] in child_inputs:
            return _mapped_child_input(child_inputs[parts[1]], parts[2:])
        if root in child_inputs:
            return _mapped_child_input(child_inputs[root], parts[1:])
        if root == "outputs" and len(parts) > 1 and parts[1] in child_node_ids:
            return "${outputs." + prefix + ".".join(parts[1:]) + "}"
        if root in child_node_ids:
            return "${" + prefix + ".".join(parts) + "}"
        if root in variable_aliases:
            return "${" + variable_aliases[root] + ("." + ".".join(parts[1:]) if len(parts) > 1 else "") + "}"
        return match.group(0)

    exact = _REFERENCE_PATTERN.fullmatch(value)
    if exact is not None:
        return replacement(exact)
    return _REFERENCE_PATTERN.sub(lambda match: str(replacement(match)), value)


def _expand_subworkflows(
    version: Any,
    workflow_resolver: Any,
    *,
    expansion_stack: tuple[tuple[str, int], ...] = (),
) -> WorkflowDraft:
    """Inline fixed published child versions into one executable Studio graph."""
    workflow_id = str(getattr(version, "workflow_id", "") or getattr(version, "id", ""))
    raw_version = getattr(version, "version", "draft")
    identity = (workflow_id, int(raw_version)) if str(raw_version).isdigit() else None
    if identity is not None and identity in expansion_stack:
        raise UnsupportedOperationError(f"recursive workflow call detected: {workflow_id}@{raw_version}")
    next_stack = (*expansion_stack, identity) if identity is not None else expansion_stack
    nodes = list(version.nodes)
    edges = list(version.edges)
    while True:
        call = next((item for item in nodes if item.action_id == "workflow.call"), None)
        if call is None:
            break
        settings = {**dict(call.config), **dict(call.input_mapping)}
        called_id = str(settings.get("workflow_id") or "").strip()
        called_version = settings.get("version")
        if not called_id or not isinstance(called_version, int) or isinstance(called_version, bool):
            raise UnsupportedOperationError(f"sub-workflow node {call.id} requires a fixed published version")
        try:
            child = workflow_resolver(called_id, called_version)
        except (KeyError, TypeError, ValueError) as exc:
            raise UnsupportedOperationError(f"published workflow version not found: {called_id}@{called_version}") from exc
        child_identity = (called_id, called_version)
        if child_identity in next_stack:
            raise UnsupportedOperationError(f"recursive workflow call detected: {called_id}@{called_version}")
        expanded_child = _expand_subworkflows(child, workflow_resolver, expansion_stack=next_stack)
        supplied = settings.get("inputs")
        supplied_inputs = dict(supplied) if isinstance(supplied, Mapping) else {}
        child_inputs = {
            item.name: supplied_inputs.get(item.name, item.default)
            for item in getattr(child, "inputs", ())
            if item.name in supplied_inputs or item.default is not None
        }
        missing = [
            item.name
            for item in getattr(child, "inputs", ())
            if item.required and item.default is None and item.name not in child_inputs
        ]
        if missing:
            raise UnsupportedOperationError(f"sub-workflow input is missing: {missing[0]}")
        prefix = f"{call.id}__"
        child_node_ids = {item.id for item in expanded_child.nodes}
        aliases = {
            str({**dict(item.config), **dict(item.input_mapping)}.get("name") or ""): prefix + str({**dict(item.config), **dict(item.input_mapping)}.get("name") or "")
            for item in expanded_child.nodes
            if item.action_id == "variable.set" and str({**dict(item.config), **dict(item.input_mapping)}.get("name") or "")
        }
        child_nodes: list[StudioWorkflowNode] = []
        for item in expanded_child.nodes:
            config = _rewrite_child_value(dict(item.config), prefix=prefix, child_node_ids=child_node_ids, child_inputs=child_inputs, variable_aliases=aliases)
            input_mapping = _rewrite_child_value(dict(item.input_mapping), prefix=prefix, child_node_ids=child_node_ids, child_inputs=child_inputs, variable_aliases=aliases)
            if item.action_id == "variable.set":
                variable_name = str({**config, **input_mapping}.get("name") or "")
                if variable_name in aliases:
                    if "name" in input_mapping:
                        input_mapping["name"] = aliases[variable_name]
                    else:
                        config["name"] = aliases[variable_name]
            child_nodes.append(StudioWorkflowNode(prefix + item.id, item.action_id, config, input_mapping, dict(item.position)))
        child_edges = [
            StudioWorkflowEdge(
                prefix + edge.source,
                prefix + edge.target,
                _rewrite_child_value(edge.condition, prefix=prefix, child_node_ids=child_node_ids, child_inputs=child_inputs, variable_aliases=aliases),
                edge.source_handle,
            )
            for edge in expanded_child.edges
        ]
        incoming_child = {edge.target for edge in expanded_child.edges}
        outgoing_child = {edge.source for edge in expanded_child.edges}
        roots = [prefix + item.id for item in expanded_child.nodes if item.id not in incoming_child]
        terminals = [prefix + item.id for item in expanded_child.nodes if item.id not in outgoing_child]
        values = {
            item.name: _rewrite_child_value(item.value, prefix=prefix, child_node_ids=child_node_ids, child_inputs=child_inputs, variable_aliases=aliases)
            for item in getattr(child, "outputs", ())
        }
        aggregate = StudioWorkflowNode(
            call.id,
            "workflow.outputs",
            {"workflow_id": called_id, "version": called_version, "values": values},
            {},
            dict(call.position),
        )
        parent_incoming = [edge for edge in edges if edge.target == call.id]
        parent_outgoing = [edge for edge in edges if edge.source == call.id]
        retained_edges = [edge for edge in edges if edge.target != call.id and edge.source != call.id]
        if roots:
            retained_edges.extend(
                StudioWorkflowEdge(edge.source, root, edge.condition, edge.source_handle)
                for edge in parent_incoming
                for root in roots
            )
            retained_edges.extend(StudioWorkflowEdge(terminal, call.id) for terminal in terminals)
        else:
            retained_edges.extend(
                StudioWorkflowEdge(edge.source, call.id, edge.condition, edge.source_handle)
                for edge in parent_incoming
            )
        retained_edges.extend(parent_outgoing)
        existing_ids = {item.id for item in nodes if item.id != call.id}
        collisions = existing_ids & {item.id for item in child_nodes}
        if collisions:
            raise UnsupportedOperationError(f"sub-workflow node id collides after expansion: {sorted(collisions)[0]}")
        index = nodes.index(call)
        nodes[index:index + 1] = [*child_nodes, aggregate]
        edges = [*retained_edges, *child_edges]
    return WorkflowDraft(
        id=workflow_id,
        name=str(getattr(version, "name", "")),
        description=str(getattr(version, "description", "")),
        version=str(raw_version),
        inputs=tuple(getattr(version, "inputs", ())),
        outputs=tuple(getattr(version, "outputs", ())),
        nodes=tuple(nodes),
        edges=tuple(edges),
        status="published" if str(raw_version).isdigit() else "draft",
    )


def _published_workflow_dependencies(
    version: Any,
    workflow_resolver: Any,
    *,
    seen: set[tuple[str, int]] | None = None,
) -> set[tuple[str, int]]:
    dependencies = set(seen or ())
    for node in getattr(version, "nodes", ()):
        if node.action_id != "workflow.call":
            continue
        settings = {**dict(node.config), **dict(node.input_mapping)}
        called_id = str(settings.get("workflow_id") or "").strip()
        called_version = settings.get("version")
        if not called_id or not isinstance(called_version, int) or isinstance(called_version, bool):
            continue
        identity = (called_id, called_version)
        if identity in dependencies:
            continue
        dependencies.add(identity)
        called = workflow_resolver(called_id, called_version)
        dependencies.update(_published_workflow_dependencies(called, workflow_resolver, seen=dependencies))
    return dependencies


def _normalize_action_inputs(action_id: str, raw_params: Mapping[str, Any]) -> dict[str, Any]:
    """Translate Studio-facing aliases into the executable workflow contract."""
    params = dict(raw_params)
    if action_id in {"device.connect", "device.ssh", "device.telnet"}:
        if "timeout" in params and "timeout_seconds" not in params:
            params["timeout_seconds"] = params.pop("timeout")
        if action_id == "device.ssh":
            params["recovery_protocol"] = "ssh"
        elif action_id == "device.telnet":
            params["recovery_protocol"] = "telnet"
        if action_id != "device.select":
            params.pop("device_id", None)
    elif action_id in {"file.upload", "file.download"}:
        params["direction"] = "upload" if action_id == "file.upload" else "download"
        source_path = params.pop("source_path", None)
        source = params.pop("source", None)
        destination_path = params.pop("destination_path", None)
        destination = params.pop("destination", None)
        params["source_path"] = source_path if source_path not in (None, "") else (source or "")
        params["destination_path"] = destination_path if destination_path not in (None, "") else (destination or "")
        # Workflow uploads are deploy/copy actions. Preserve the historical
        # user expectation that rerunning one refreshes the same device file;
        # the lower-level transfer API remains conservative by default.
        if action_id == "file.upload":
            params.setdefault("overwrite", True)
    return params


def _device_reference_context(ctx: Any, device_id: str) -> dict[str, Any]:
    """Build a credential-free context exposed to workflow expressions."""
    normalized_id = str(device_id).strip()
    try:
        snapshot = ctx.desktop.devices.require_device(normalized_id)
    except (ResourceNotFoundError, RepositoryError):
        # Draft and simulator callers may use a temporary target that is not
        # present in the inventory yet. Keep the reference resolvable without
        # inventing device metadata or touching repository credentials.
        return {"id": normalized_id}
    context = asdict(snapshot)
    context["software_version"] = snapshot.version
    context["address"] = (
        snapshot.ssh_endpoint
        or snapshot.telnet_endpoint
        or snapshot.serial_endpoint
        or ""
    )
    return context


def _compile_task_plan(version: Any, device_id: str, source_overrides: Mapping[str, str] | None = None) -> TaskPlan:
    """Compile the Studio graph into allow-listed Framework activities.

    Condition nodes are compile-time control flow. Their visual rules are
    attached to branch nodes as ``run_if`` metadata, so the generic task
    orchestrator can skip the inactive branch without executing both sides.
    """
    node_ids = {node.id for node in version.nodes}
    condition_nodes = {node.id: node for node in version.nodes if node.action_id == "utility.condition"}
    condition_specs: dict[str, dict[str, Any]] = {}
    condition_dependencies: dict[str, tuple[str, ...]] = {}
    for condition_id, condition in condition_nodes.items():
        condition_config = {**dict(condition.config), **dict(condition.input_mapping)}
        rules = condition_config.get("rules")
        expression = str(condition_config.get("expression") or "").strip()
        if (not isinstance(rules, (list, tuple)) or not any(isinstance(rule, Mapping) for rule in rules)) and not expression:
            raise UnsupportedOperationError("visual rules are required for condition branches")
        incoming = tuple(
            edge.source
            for edge in version.edges
            if edge.target == condition_id and edge.source not in condition_nodes
        )
        if any(source not in node_ids for source in incoming):
            raise UnsupportedOperationError(f"condition {condition_id} depends on an unknown node")
        condition_dependencies[condition_id] = incoming
        outgoing = [edge for edge in version.edges if edge.source == condition_id]
        if not outgoing:
            raise UnsupportedOperationError("visual rules or condition branches are required")
        condition_specs[condition_id] = {
            "rules": [dict(rule) for rule in (rules or ()) if isinstance(rule, Mapping)],
            "logical_operator": str(condition_config.get("logical_operator") or "AND"),
            "values_from": incoming[0] if len(incoming) == 1 else "",
        }
        if expression:
            condition_specs[condition_id]["expression"] = expression

    def branch_value(edge: Any) -> bool:
        raw = str(edge.condition or edge.source_handle or "").strip().casefold()
        if raw in {"true", "then", "yes", "1", "真", "是"}:
            return True
        if raw in {"false", "else", "no", "0", "假", "否"}:
            return False
        raise UnsupportedOperationError(
            f"condition edge {edge.source}->{edge.target} must identify a true or false branch"
        )

    direct_contexts: dict[str, list[dict[str, Any]]] = {}
    for edge in version.edges:
        if edge.source in condition_specs:
            context = dict(condition_specs[edge.source])
            context["expected"] = branch_value(edge)
            direct_contexts.setdefault(edge.target, []).append(context)

    incoming_regular: dict[str, tuple[str, ...]] = {
        node.id: tuple(
            edge.source
            for edge in version.edges
            if edge.target == node.id and edge.source not in condition_nodes
        )
        for node in version.nodes
        if node.id not in condition_nodes
    }

    def context_for(node_id: str, stack: set[str] | None = None) -> dict[str, Any] | None:
        stack = set(stack or ())
        if node_id in stack:
            raise UnsupportedOperationError("workflow contains a dependency cycle")
        candidates = list(direct_contexts.get(node_id, ()))
        stack.add(node_id)
        for source in incoming_regular.get(node_id, ()):
            inherited = context_for(source, stack)
            if inherited is not None:
                candidates.append(inherited)
        if not candidates:
            return None
        first = candidates[0]
        if any(candidate != first for candidate in candidates[1:]):
            raise UnsupportedOperationError(f"node {node_id} merges incompatible condition branches")
        return first

    task_nodes: list[WorkflowNode] = []
    for node in version.nodes:
        if node.id in condition_nodes:
            continue
        params = {**dict(node.config), **dict(node.input_mapping)}
        workflow_id = _workflow_id_for_action(node.action_id, params)
        if workflow_id is None:
            raise UnsupportedOperationError(f"workflow action cannot run yet: {node.action_id}")
        if node.action_id in {"device.select", "device.connect", "device.ssh", "device.telnet"}:
            configured_device = str(params.get("device_id") or "").strip()
            if configured_device and configured_device != device_id:
                raise UnsupportedOperationError(
                    f"node {node.id} selects device {configured_device}, but task target is {device_id}"
                )
            if "timeout" in params and "timeout_seconds" not in params:
                params["timeout_seconds"] = params.pop("timeout")
            if node.action_id == "device.ssh":
                params["recovery_protocol"] = "ssh"
            elif node.action_id == "device.telnet":
                params["recovery_protocol"] = "telnet"
            if node.action_id != "device.select":
                params.pop("device_id", None)
        elif node.action_id in {"file.upload", "file.download"}:
            params = _normalize_action_inputs(node.action_id, params)
            if node.action_id == "file.upload" and source_overrides and node.id in source_overrides:
                params["source_path"] = source_overrides[node.id]
        elif node.action_id == "expression.evaluate":
            params.setdefault("values", {"inputs": "${inputs}", "outputs": "${outputs}"})
        elif node.action_id in {"loop.for_each", "device.for_each", "loop.until"}:
            child_action = str(params.get("action_id") or "").strip()
            raw_action_inputs = params.get("action_inputs")
            child_inputs = dict(raw_action_inputs) if isinstance(raw_action_inputs, Mapping) else {}
            child_workflow_id = _workflow_id_for_action(child_action, child_inputs)
            if child_workflow_id is None or child_action in _LOOP_DISALLOWED_ACTIONS:
                raise UnsupportedOperationError(f"loop child action cannot run yet: {child_action}")
            if isinstance(raw_action_inputs, Mapping):
                params["action_inputs"] = _normalize_action_inputs(child_action, raw_action_inputs)
            params["action_id"] = child_workflow_id
            if node.action_id == "device.for_each":
                raw_devices = params.get("devices")
                if isinstance(raw_devices, str) and re.fullmatch(r"\$\{inputs?\.([^}]+)\}", raw_devices.strip()):
                    input_name = re.fullmatch(r"\$\{inputs?\.([^}]+)\}", raw_devices.strip()).group(1)
                    params["devices"] = f"${{inputs.{input_name}}}"
                else:
                    params["devices"] = _resolve_device_list(raw_devices)
        retry_attempts = params.pop("retry_attempts", None)
        retry_backoff_seconds = params.pop("retry_backoff_seconds", None)
        retry_policy = params.pop("retry_policy", {})
        # device.for_each consumes this policy inside its per-device loop.
        # Keep it in the Activity inputs as well as the generic node retry
        # policy so child failures can be continued/stopped at the right
        # iteration boundary.
        raw_failure_strategy = params.get("failure_strategy") if node.action_id == "device.for_each" else params.pop("failure_strategy", None)
        failure_strategy = str(raw_failure_strategy or "stop").strip().casefold()
        repeat_count = params.pop("repeat_count", None)
        repeat_policy = params.pop("repeat_policy", {})
        parallel_group = str(params.pop("parallel_group", "") or "").strip() or None
        if retry_attempts not in (None, ""):
            try:
                retry_policy = {**dict(retry_policy or {}), "max_attempts": max(1, min(5, int(retry_attempts)))}
            except (TypeError, ValueError) as exc:
                raise UnsupportedOperationError(f"node {node.id} retry_attempts must be a number") from exc
        if retry_backoff_seconds not in (None, ""):
            try:
                retry_policy = {**dict(retry_policy or {}), "backoff_seconds": max(0.0, min(60.0, float(retry_backoff_seconds)))}
            except (TypeError, ValueError) as exc:
                raise UnsupportedOperationError(f"node {node.id} retry_backoff_seconds must be a number") from exc
        if failure_strategy not in {"stop", "continue"}:
            raise UnsupportedOperationError(f"node {node.id} failure_strategy must be stop or continue")
        if raw_failure_strategy not in (None, ""):
            retry_policy = {**dict(retry_policy or {}), "on_failure": failure_strategy}
        if repeat_count not in (None, ""):
            try:
                repeat_policy = {**dict(repeat_policy or {}), "max_iterations": max(1, min(20, int(repeat_count)))}
            except (TypeError, ValueError) as exc:
                raise UnsupportedOperationError(f"node {node.id} repeat_count must be a number") from exc
        dependencies_list: list[str] = []
        for edge in version.edges:
            if edge.target != node.id:
                continue
            if edge.source in condition_dependencies:
                dependencies_list.extend(condition_dependencies[edge.source])
            else:
                dependencies_list.append(edge.source)
        dependencies = tuple(dict.fromkeys(dependencies_list))
        if any(dep not in node_ids for dep in dependencies):
            raise UnsupportedOperationError(f"node {node.id} depends on an unknown node")
        if node.action_id == "result.save" and dependencies:
            params.setdefault("value", f"${{{dependencies[-1]}}}")
        task_nodes.append(
            WorkflowNode(
                node.id,
                workflow_id,
                depends_on=dependencies,
                input_mapping=params,
                run_if=context_for(node.id),
                retry_policy=retry_policy,
                repeat_policy=repeat_policy,
                parallel_group=parallel_group,
            )
        )
    workflow_id = str(getattr(version, "workflow_id", "") or getattr(version, "id", ""))
    # Framework TaskRecord uses a numeric plan revision. Draft test runs have
    # no published version, so use revision 0 while retaining the draft
    # semantics at the API boundary.
    execution_version = str(version.version) if str(version.version).isdigit() else "0"
    plan = TaskPlan(id=f"workflow-task:{workflow_id}:{execution_version}", version=execution_version, nodes=tuple(task_nodes))
    try:
        plan.validate()
    except ValueError as exc:
        raise UnsupportedOperationError(str(exc)) from exc
    return plan


def _resolve_device_list(raw: Any) -> list[str]:
    """Normalize an explicit device list into device IDs."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(raw, (list, tuple)):
        raise UnsupportedOperationError("device.for_each devices must be a list of device IDs")
    return [str(item.get("device_id") if isinstance(item, Mapping) else item).strip() for item in raw]


def _prepare_workflow_file_inputs(
    version: Any,
    inputs: Mapping[str, Any],
    transfers: Any,
    *,
    staging_id: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Stage upload sources while keeping the executable plan portable."""
    prepared_inputs = dict(inputs)
    source_overrides: dict[str, str] = {}
    staged_inputs: set[str] = set()
    prepare = getattr(transfers, "prepare_workflow_source", None)
    if not callable(prepare):
        return prepared_inputs, source_overrides
    for node in getattr(version, "nodes", ()):
        if node.action_id != "file.upload":
            continue
        settings = {**dict(getattr(node, "config", {}) or {}), **dict(getattr(node, "input_mapping", {}) or {})}
        raw_source = settings.get("source_path", settings.get("source"))
        if not isinstance(raw_source, str) or not raw_source.strip():
            continue
        source_text = raw_source.strip()
        if source_text.startswith("${") and source_text.endswith("}") and source_text.count("${") == 1:
            reference = source_text[2:-1].strip()
            explicit_input = reference.startswith("inputs.")
            input_name = reference[7:] if explicit_input else reference
            input_def = next((item for item in getattr(version, "inputs", ()) if item.name == input_name), None)
            input_type = str(getattr(input_def, "type", "")).casefold() if input_def else ""
            is_file_input = input_name == "package_path" or input_type == "file" or (explicit_input and input_type == "string")
            if is_file_input and input_name in prepared_inputs and input_name not in staged_inputs:
                prepared_inputs[input_name] = prepare(str(prepared_inputs[input_name]), staging_id=staging_id)
                staged_inputs.add(input_name)
        elif not source_text.startswith("${"):
            source_overrides[node.id] = prepare(source_text, staging_id=staging_id)
    return prepared_inputs, source_overrides

def _derive_workflow_convenience_inputs(version: Any, inputs: Mapping[str, Any]) -> dict[str, Any]:
    """Fill legacy package-name inputs from the selected local package path.

    Studio upload nodes only need ``package_path``. Older upgrade workflows
    may still reference ``package_name`` in the device destination or later
    commands, so derive that optional value when it was not supplied.
    """
    derived = dict(inputs)
    definitions = {str(item.name): item for item in getattr(version, "inputs", ())}
    if "package_name" not in definitions:
        return derived
    current_name = derived.get("package_name")
    if current_name not in (None, ""):
        return derived
    package_path = derived.get("package_path")
    if package_path in (None, ""):
        return derived
    package_name = PurePosixPath(str(package_path).replace(chr(92), "/")).name
    if package_name:
        derived["package_name"] = package_name
    return derived


def _draft_payload(draft: WorkflowDraft) -> dict[str, Any]:
    return draft.to_dict()


def _select_plan_from_step(plan: TaskPlan, step_id: str) -> TaskPlan:
    """Keep the selected step and its prerequisites for single-step testing."""
    wanted = {step_id}
    by_id = {node.id: node for node in plan.nodes}
    pending = [step_id]
    while pending:
        current = pending.pop()
        node = by_id.get(current)
        if node is None:
            raise UnsupportedOperationError(f"unknown workflow step: {step_id}")
        for dependency in node.depends_on:
            if dependency not in wanted:
                wanted.add(dependency)
                pending.append(dependency)
    return TaskPlan(id=f"{plan.id}:step:{step_id}", version=plan.version, nodes=tuple(node for node in plan.nodes if node.id in wanted))


@router.get("")
async def list_workflow_definitions(ctx=Depends(get_context)) -> dict[str, object]:
    return {"workflows": [_draft_payload(item) for item in ctx.desktop.workflow_definitions.list()]}


@router.post("")
async def create_workflow_definition(payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    data = dict(payload)
    data["id"] = str(data.get("id") or f"workflow_{uuid4().hex[:12]}")
    draft = WorkflowDraft.from_dict(data)
    if not draft.name.strip():
        raise UnsupportedOperationError("workflow name is required")
    try:
        saved = ctx.desktop.workflow_definitions.create(draft)
    except (KeyError, ValueError) as exc:
        raise UnsupportedOperationError(str(exc)) from exc
    return {"workflow": _draft_payload(saved)}


@router.get("/actions")
async def list_workflow_actions() -> dict[str, object]:
    """Expose the allow-listed Studio actions to renderer clients."""
    return {
        "actions": [
            {
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "input_schema": item.input_schema,
                "output_schema": item.output_schema,
                "risk": item.risk,
                "executor_id": item.executor_id,
            }
            for item in build_action_catalog().list()
        ]
    }


@router.get("/scripts")
async def list_workflow_scripts(ctx=Depends(get_context)) -> dict[str, object]:
    scripts = _load_workflow_scripts(ctx.desktop.settings)
    scripts.sort(key=lambda item: (str(item.get("name") or "").casefold(), str(item.get("id") or "")))
    return {"scripts": scripts}


@router.post("/scripts")
async def create_workflow_script(payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    name = str(payload.get("name") or "未命名脚本").strip()
    if not name:
        raise UnsupportedOperationError("script name is required")
    if len(name) > 120:
        raise UnsupportedOperationError("script name is too long")
    scripts = _load_workflow_scripts(ctx.desktop.settings)
    if len(scripts) >= _WORKFLOW_SCRIPT_LIMIT:
        raise UnsupportedOperationError(f"script limit reached ({_WORKFLOW_SCRIPT_LIMIT})")
    now = datetime.now(UTC).isoformat()
    input_schema = _normalize_workflow_script_input_schema(payload.get("input_schema") or [])
    script_source = str(payload.get("script") or payload.get("content") or "")
    input_schema, entrypoint, input_schema_error = _analyze_workflow_script(
        str(payload.get("language") or "python").strip().lower(),
        script_source,
        input_schema,
    )
    script = {
        "id": str(payload.get("id") or f"script_{uuid4().hex[:12]}"),
        "name": name,
        "description": str(payload.get("description") or "").strip(),
        "language": str(payload.get("language") or "python").strip().lower(),
        "script": script_source,
        "input_schema": input_schema,
        "input_schema_source": "function" if entrypoint else "manual",
        "entrypoint": entrypoint,
        **({"input_schema_error": input_schema_error} if input_schema_error else {}),
        "created_at": now,
        "updated_at": now,
    }
    if script["language"] not in {"python", "powershell", "bash"}:
        raise UnsupportedOperationError("unsupported script language")
    scripts.append(script)
    ctx.desktop.settings.set(_WORKFLOW_SCRIPTS_SETTING, scripts)
    return {"script": script}


@router.put("/scripts/{script_id}")
async def save_workflow_script(script_id: str, payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    scripts = _load_workflow_scripts(ctx.desktop.settings)
    script = next((item for item in scripts if str(item.get("id") or "") == script_id), None)
    if script is None:
        raise ResourceNotFoundError(f"script resource not found: {script_id}")
    name = str(payload.get("name", script.get("name") or "")).strip()
    language = str(payload.get("language", script.get("language") or "python")).strip().lower()
    if not name:
        raise UnsupportedOperationError("script name is required")
    if len(name) > 120:
        raise UnsupportedOperationError("script name is too long")
    if language not in {"python", "powershell", "bash"}:
        raise UnsupportedOperationError("unsupported script language")
    input_schema = _normalize_workflow_script_input_schema(payload.get("input_schema", script.get("input_schema") or []))
    script_source = str(payload.get("script", payload.get("content", script.get("script") or "")))
    input_schema, entrypoint, input_schema_error = _analyze_workflow_script(language, script_source, input_schema)
    script.update({
        "name": name,
        "description": str(payload.get("description", script.get("description") or "")).strip(),
        "language": language,
        "script": script_source,
        "input_schema": input_schema,
        "input_schema_source": "function" if entrypoint else "manual",
        "entrypoint": entrypoint,
        "updated_at": datetime.now(UTC).isoformat(),
    })
    if input_schema_error:
        script["input_schema_error"] = input_schema_error
    else:
        script.pop("input_schema_error", None)
    ctx.desktop.settings.set(_WORKFLOW_SCRIPTS_SETTING, scripts)
    return {"script": script}


@router.delete("/scripts/{script_id}", status_code=204)
async def delete_workflow_script(script_id: str, ctx=Depends(get_context)) -> None:
    scripts = _load_workflow_scripts(ctx.desktop.settings)
    retained = [item for item in scripts if str(item.get("id") or "") != script_id]
    if len(retained) == len(scripts):
        raise ResourceNotFoundError(f"script resource not found: {script_id}")
    ctx.desktop.settings.set(_WORKFLOW_SCRIPTS_SETTING, retained)


@router.post("/scripts/{script_id}/test")
async def test_workflow_script(script_id: str, payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    script = next((item for item in _load_workflow_scripts(ctx.desktop.settings) if str(item.get("id") or "") == script_id), None)
    if script is None:
        raise ResourceNotFoundError(f"script resource not found: {script_id}")
    inputs = _validate_workflow_script_inputs(
        script.get("input_schema") or [],
        payload.get("inputs"),
    )
    temporary_id = f"script_test_{uuid4().hex[:12]}"
    draft = WorkflowDraft.from_dict({
        "id": temporary_id,
        "name": f"脚本测试：{script.get('name') or script_id}",
        "version": "draft",
        "nodes": [{
            "id": "script",
            "action_id": "script.run",
            "config": {
                "script_id": script_id,
                "input_json": json.dumps(inputs, ensure_ascii=False, separators=(",", ":")),
                "language": script.get("language") or "python",
            },
        }],
    })
    try:
        ctx.desktop.workflow_definitions.create(draft)
        return await run_workflow_definition(
            temporary_id,
            {
                **dict(payload),
                "draft": True,
                "confirmed_risks": bool(payload.get("confirmed_risks")),
            },
            ctx,
        )
    except (KeyError, ValueError) as exc:
        raise UnsupportedOperationError(str(exc)) from exc
    finally:
        try:
            ctx.desktop.workflow_definitions.delete(temporary_id)
        except (KeyError, ValueError):
            pass


def _load_custom_actions(settings: Any) -> list[dict[str, Any]]:
    raw = settings.get(_CUSTOM_ACTIONS_SETTING, [])
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _load_workflow_scripts(settings: Any) -> list[dict[str, Any]]:
    raw = settings.get(_WORKFLOW_SCRIPTS_SETTING, [])
    if not isinstance(raw, list):
        return []
    scripts: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        script = dict(item)
        language = str(script.get("language") or "python").strip().lower()
        source = str(script.get("script") or script.get("content") or "")
        fallback = _normalize_workflow_script_input_schema(script.get("input_schema") or [])
        schema, entrypoint, parse_error = _analyze_workflow_script(language, source, fallback)
        if entrypoint:
            script["input_schema"] = schema
            script["input_schema_source"] = "function"
            script["entrypoint"] = entrypoint
            script.pop("input_schema_error", None)
        elif parse_error and not script.get("input_schema_error"):
            script["input_schema_error"] = parse_error
        scripts.append(script)
    return scripts


def _normalize_workflow_script_input_schema(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise UnsupportedOperationError("script input_schema must be an array")
    if len(raw) > 100:
        raise UnsupportedOperationError("script input_schema has too many parameters")
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise UnsupportedOperationError("script input parameters must be objects")
        name = str(item.get("name") or "").strip()
        parameter_type = str(item.get("type") or "string").strip().lower()
        if not name:
            raise UnsupportedOperationError("script input parameter name is required")
        if len(name) > 80:
            raise UnsupportedOperationError("script input parameter name is too long")
        if name in names:
            raise UnsupportedOperationError(f"duplicate script input parameter: {name}")
        if parameter_type not in _WORKFLOW_SCRIPT_INPUT_TYPES:
            raise UnsupportedOperationError(f"unsupported script input type: {parameter_type}")
        names.add(name)
        parameter: dict[str, Any] = {
            "name": name,
            "type": parameter_type,
            "required": bool(item.get("required")),
        }
        if "description" in item and item.get("description") not in (None, ""):
            parameter["description"] = str(item.get("description"))[:400]
        if "default" in item:
            default = item.get("default")
            if parameter_type == "number" and (isinstance(default, bool) or not isinstance(default, (int, float))):
                raise UnsupportedOperationError(f"default for script input {name} must be a number")
            if parameter_type == "boolean" and not isinstance(default, bool):
                raise UnsupportedOperationError(f"default for script input {name} must be a boolean")
            if parameter_type == "object" and (not isinstance(default, Mapping) or isinstance(default, list)):
                raise UnsupportedOperationError(f"default for script input {name} must be an object")
            if parameter_type == "array" and not isinstance(default, list):
                raise UnsupportedOperationError(f"default for script input {name} must be an array")
            if parameter_type == "string" and not isinstance(default, str):
                raise UnsupportedOperationError(f"default for script input {name} must be a string")
            parameter["default"] = default
        normalized.append(parameter)
    return normalized


def _analyze_workflow_script(
    language: str,
    source: str,
    fallback_schema: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str, str]:
    """Derive a Windmill-style contract from a script entrypoint when possible."""
    if language != "python":
        return fallback_schema, "", ""
    try:
        tree = ast.parse(source or "")
    except SyntaxError as exc:
        return fallback_schema, "", f"无法解析 Python 入参：第 {exc.lineno or '?'} 行语法错误"
    main = next(
        (node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"),
        None,
    )
    if main is None:
        return fallback_schema, "", ""
    try:
        return _python_main_input_schema(main, fallback_schema), "main", ""
    except ValueError as exc:
        return fallback_schema, "", str(exc)


def _python_main_input_schema(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    fallback_schema: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    args = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
    if any(item.arg in {"self", "cls"} for item in args):
        raise ValueError("main 函数不能包含 self 或 cls 参数")
    if function.args.posonlyargs:
        raise ValueError("main 函数参数不能使用仅位置参数，请改为普通参数")
    defaults = [None] * (len(function.args.args) - len(function.args.defaults)) + list(function.args.defaults)
    defaults.extend(function.args.kw_defaults)
    fallback_by_name = {str(item.get("name")): item for item in fallback_schema}
    schema: list[dict[str, Any]] = []
    for argument, default in zip(args, defaults, strict=True):
        item: dict[str, Any] = {
            "name": argument.arg,
            "type": _python_annotation_type(argument.annotation),
            "required": default is None,
        }
        fallback = fallback_by_name.get(argument.arg) or {}
        if fallback.get("description"):
            item["description"] = fallback["description"]
        if default is not None:
            try:
                value = ast.literal_eval(default)
            except (ValueError, TypeError, MemoryError, RecursionError):
                value = None
            if value is not None:
                item["default"] = value
        schema.append(item)
    return _normalize_workflow_script_input_schema(schema)


def _python_annotation_type(annotation: ast.expr | None) -> str:
    if annotation is None:
        return "string"
    text = ast.unparse(annotation).replace(" ", "").lower()
    if any(token in text for token in ("bool",)):
        return "boolean"
    if any(token in text for token in ("int", "float", "number", "decimal")):
        return "number"
    if any(token in text for token in ("dict", "mapping", "object")):
        return "object"
    if any(token in text for token in ("list", "tuple", "set", "sequence", "array")):
        return "array"
    return "string"


def _validate_workflow_script_inputs(raw_schema: Any, raw_inputs: Any) -> dict[str, Any]:
    """Apply a script's Windmill-style input contract before execution."""
    if raw_inputs is None:
        inputs: dict[str, Any] = {}
    elif isinstance(raw_inputs, Mapping):
        inputs = dict(raw_inputs)
    else:
        raise UnsupportedOperationError("script inputs must be a JSON object")

    schema = _normalize_workflow_script_input_schema(raw_schema or [])
    known = {str(item["name"]): item for item in schema}
    unknown = sorted(str(name) for name in inputs if str(name) not in known)
    if unknown:
        raise UnsupportedOperationError(
            f"unknown script input: {unknown[0]}",
            details={"code": "unknown_script_input", "names": unknown},
        )

    normalized: dict[str, Any] = {}
    for name, parameter in known.items():
        if name not in inputs:
            if "default" in parameter:
                normalized[name] = parameter["default"]
            elif parameter.get("required"):
                raise UnsupportedOperationError(
                    f"required script input is missing: {name}",
                    details={"code": "missing_script_input", "name": name},
                )
            continue
        value = inputs[name]
        parameter_type = parameter["type"]
        valid = (
            isinstance(value, str) if parameter_type == "string" else
            (isinstance(value, (int, float)) and not isinstance(value, bool)) if parameter_type == "number" else
            isinstance(value, bool) if parameter_type == "boolean" else
            (isinstance(value, Mapping) and not isinstance(value, list)) if parameter_type == "object" else
            isinstance(value, list)
        )
        if not valid:
            raise UnsupportedOperationError(
                f"script input {name} must be {parameter_type}",
                details={"code": "invalid_script_input", "name": name, "type": parameter_type},
            )
        normalized[name] = value
    return normalized


def _resolve_script_references(workflow: Any, settings: Any) -> Any:
    """Materialize script resources at execution time while keeping drafts small."""
    scripts = {str(item.get("id") or ""): item for item in _load_workflow_scripts(settings)}
    changed = False
    nodes: list[dict[str, Any]] = []
    for node in getattr(workflow, "nodes", ()):
        data = node.to_dict()
        config = dict(data.get("config") or {})
        if data.get("action_id") == "script.run" and config.get("script_id"):
            script = scripts.get(str(config["script_id"]))
            if script is None:
                raise UnsupportedOperationError(f"script resource not found: {config['script_id']}")
            config["script"] = str(script.get("script") or script.get("content") or "")
            config["language"] = str(script.get("language") or "python")
            config["input_schema"] = list(script.get("input_schema") or [])
            config["input_schema_source"] = str(script.get("input_schema_source") or "manual")
            config["entrypoint"] = str(script.get("entrypoint") or "")
            changed = True
        data["config"] = config
        nodes.append(data)
    if not changed:
        return workflow
    return WorkflowDraft.from_dict({**workflow.to_dict(), "nodes": nodes})


def _action_output_schema(action_id: str, config: Mapping[str, Any], ctx: Any) -> dict[str, Any]:
    spec = build_action_catalog().get(action_id)
    if spec is None:
        return {}
    if action_id != "workflow.call":
        return deepcopy(spec.output_schema)
    try:
        called = ctx.desktop.workflow_definitions.get(
            str(config.get("workflow_id") or ""),
            config.get("version"),
        )
    except (KeyError, TypeError, ValueError):
        return deepcopy(spec.output_schema)
    declared = {
        item.name: ({} if item.type == "any" else {"type": "string" if item.type == "file" else item.type})
        for item in getattr(called, "outputs", ())
    }
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "workflow_id": {"type": "string"},
            "version": {"type": "integer"},
            "outputs": {"type": "object", "properties": declared},
            **declared,
        },
    }


@router.get("/custom-actions")
async def list_custom_workflow_actions(ctx=Depends(get_context)) -> dict[str, object]:
    return {"actions": _load_custom_actions(ctx.desktop.settings)}


@router.post("/custom-actions")
async def create_custom_workflow_action(payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    source_workflow_id = str(payload.get("workflow_id") or "").strip()
    source_workflow_version = payload.get("version")
    action_id = str(payload.get("action_id") or ("workflow.call" if source_workflow_id else "device.command")).strip()
    config_value = payload.get("config")
    if not name:
        raise UnsupportedOperationError("custom action name is required")
    if len(name) > 80 or len(description) > 400:
        raise UnsupportedOperationError("custom action name or description is too long")
    spec = build_action_catalog().get(action_id)
    if spec is None or action_id == "utility.condition":
        raise UnsupportedOperationError("custom action must use an executable catalog action")
    if source_workflow_id:
        config_value = {
            "workflow_id": source_workflow_id,
            "version": source_workflow_version,
            "inputs": dict(payload.get("inputs") or {}),
        }
    if not isinstance(config_value, Mapping):
        raise UnsupportedOperationError("custom action config must be an object")
    config = dict(config_value)
    candidate = WorkflowDraft(
        id="custom_action_validation",
        name=name,
        nodes=(StudioWorkflowNode("action", action_id, config),),
    )
    validation = validate_workflow(
        candidate,
        build_action_catalog(),
        ctx.desktop.workflow_definitions.get,
    )
    actionable_errors = [
        item
        for item in validation.errors
        if item.code not in {"invalid_variable_ref", "invalid_variable_field", "missing_dependency"}
    ]
    if actionable_errors:
        raise UnsupportedOperationError(
            "custom action config is invalid",
            details={"errors": [asdict(item) for item in actionable_errors]},
        )
    actions = _load_custom_actions(ctx.desktop.settings)
    if len(actions) >= _CUSTOM_ACTION_LIMIT:
        raise UnsupportedOperationError(f"custom action limit reached ({_CUSTOM_ACTION_LIMIT})")
    action = {
        "id": f"custom_{uuid4().hex[:12]}",
        "name": name,
        "description": description,
        "action_id": action_id,
        "config": config,
        "output_schema": _action_output_schema(action_id, config, ctx),
    }
    actions.append(action)
    ctx.desktop.settings.set(_CUSTOM_ACTIONS_SETTING, actions)
    if action_id == "workflow.call":
        mark_referenced = getattr(ctx.desktop.workflow_definitions, "mark_referenced", None)
        if callable(mark_referenced):
            mark_referenced(str(config["workflow_id"]), int(config["version"]))
    return {"action": action}


@router.delete("/custom-actions/{action_id}", status_code=204)
async def delete_custom_workflow_action(action_id: str, ctx=Depends(get_context)) -> None:
    actions = _load_custom_actions(ctx.desktop.settings)
    retained = [item for item in actions if str(item.get("id") or "") != action_id]
    if len(retained) == len(actions):
        raise ResourceNotFoundError(f"custom action not found: {action_id}")
    ctx.desktop.settings.set(_CUSTOM_ACTIONS_SETTING, retained)


def _load_workflow_templates(settings: Any) -> list[dict[str, Any]]:
    raw = settings.get(_WORKFLOW_TEMPLATES_SETTING, [])
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


@router.get("/templates")
async def list_workflow_templates(ctx=Depends(get_context)) -> dict[str, object]:
    return {
        "templates": [
            *deepcopy(list(_BUILT_IN_WORKFLOW_TEMPLATES)),
            *_load_workflow_templates(ctx.desktop.settings),
        ]
    }


@router.post("/templates")
async def create_workflow_template(payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    source_workflow_id = str(payload.get("workflow_id") or "").strip()
    workflow_value = payload.get("workflow")
    if source_workflow_id:
        try:
            source = ctx.desktop.workflow_definitions.get(source_workflow_id, payload.get("version", "draft"))
        except KeyError as exc:
            raise ResourceNotFoundError(str(exc)) from exc
        workflow_data = source.to_dict()
        name = name or source.name
        description = description or str(getattr(source, "description", ""))
    elif isinstance(workflow_value, Mapping):
        workflow_data = dict(workflow_value)
        name = name or str(workflow_data.get("name") or "").strip()
        description = description or str(workflow_data.get("description") or "").strip()
    else:
        raise UnsupportedOperationError("workflow_id or workflow snapshot is required")
    if not name:
        raise UnsupportedOperationError("template name is required")
    templates = _load_workflow_templates(ctx.desktop.settings)
    if len(templates) >= _WORKFLOW_TEMPLATE_LIMIT:
        raise UnsupportedOperationError(f"workflow template limit reached ({_WORKFLOW_TEMPLATE_LIMIT})")
    snapshot = WorkflowDraft.from_dict({**workflow_data, "id": "template_validation", "version": "draft", "status": "draft"})
    validation = validate_workflow(snapshot, build_action_catalog(), ctx.desktop.workflow_definitions.get)
    if not validation.valid:
        raise UnsupportedOperationError(
            "workflow template is invalid",
            details={"errors": [asdict(item) for item in validation.errors]},
        )
    template = {
        "id": f"template_{uuid4().hex[:12]}",
        "name": name,
        "description": description,
        "built_in": False,
        "workflow": {
            **snapshot.to_dict(),
            "id": "",
            "name": name,
            "description": description,
        },
    }
    templates.append(template)
    ctx.desktop.settings.set(_WORKFLOW_TEMPLATES_SETTING, templates)
    mark_referenced = getattr(ctx.desktop.workflow_definitions, "mark_referenced", None)
    if callable(mark_referenced):
        for called_id, called_version in _published_workflow_dependencies(snapshot, ctx.desktop.workflow_definitions.get):
            mark_referenced(called_id, called_version)
    return {"template": template}


@router.delete("/templates/{template_id}", status_code=204)
async def delete_workflow_template(template_id: str, ctx=Depends(get_context)) -> None:
    if any(item["id"] == template_id for item in _BUILT_IN_WORKFLOW_TEMPLATES):
        raise UnsupportedOperationError("built-in workflow templates cannot be deleted")
    templates = _load_workflow_templates(ctx.desktop.settings)
    retained = [item for item in templates if str(item.get("id") or "") != template_id]
    if len(retained) == len(templates):
        raise ResourceNotFoundError(f"workflow template not found: {template_id}")
    ctx.desktop.settings.set(_WORKFLOW_TEMPLATES_SETTING, retained)


@router.post("/templates/{template_id}/instantiate")
async def instantiate_workflow_template(template_id: str, payload: Mapping[str, Any] | None = None, ctx=Depends(get_context)) -> dict[str, object]:
    templates = [*deepcopy(list(_BUILT_IN_WORKFLOW_TEMPLATES)), *_load_workflow_templates(ctx.desktop.settings)]
    template = next((item for item in templates if str(item.get("id") or "") == template_id), None)
    if template is None:
        raise ResourceNotFoundError(f"workflow template not found: {template_id}")
    snapshot = template.get("workflow")
    if not isinstance(snapshot, Mapping):
        raise UnsupportedOperationError("workflow template snapshot is invalid")
    overrides = dict(payload or {})
    data = deepcopy(dict(snapshot))
    data["id"] = str(overrides.get("id") or f"workflow_{uuid4().hex[:12]}")
    data["name"] = str(overrides.get("name") or data.get("name") or template.get("name") or "").strip()
    data["description"] = str(overrides.get("description", data.get("description") or ""))
    data["version"] = "draft"
    data["status"] = "draft"
    draft = WorkflowDraft.from_dict(data)
    try:
        saved = ctx.desktop.workflow_definitions.create(draft)
    except (KeyError, ValueError) as exc:
        raise UnsupportedOperationError(str(exc)) from exc
    return {"workflow": saved.to_dict(), "template_id": template_id}


@router.get("/published")
async def list_published_workflow_definitions(ctx=Depends(get_context)) -> dict[str, object]:
    workflows = [
        {
            "id": version.workflow_id,
            "name": version.name,
            "description": version.description,
            "version": version.version,
            "published_at": version.published_at,
            "inputs": [item.to_dict() for item in version.inputs],
            "outputs": [item.to_dict() for item in version.outputs],
            "input_contract": [input_contract(item) for item in version.inputs],
            "output_contract": [output_contract(item) for item in version.outputs],
            "step_count": len(version.nodes),
            "requires_confirmation": _requires_risk_confirmation(version),
        }
        for version in ctx.desktop.workflow_definitions.list_published(latest_only=True)
    ]
    workflows.sort(key=lambda item: (str(item["name"]).casefold(), str(item["id"])))
    return {"workflows": workflows}


@router.get("/{workflow_id}")
async def get_workflow_definition(workflow_id: str, ctx=Depends(get_context)) -> dict[str, object]:
    try:
        draft = ctx.desktop.workflow_definitions.get(workflow_id)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    return {"workflow": draft.to_dict()}


@router.get("/{workflow_id}/versions")
async def list_workflow_versions(workflow_id: str, ctx=Depends(get_context)) -> dict[str, object]:
    try:
        versions = ctx.desktop.workflow_definitions.list_versions(workflow_id)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    referenced_versions = getattr(ctx.desktop.workflow_definitions, "referenced_versions", None)
    referenced = set(referenced_versions(workflow_id)) if callable(referenced_versions) else set()
    is_referenced = getattr(ctx.desktop.workflow_definitions, "is_referenced", None)
    return {
        "versions": [
            {
                "id": version.workflow_id,
                "name": version.name,
                "description": version.description,
                "version": version.version,
                "published_at": version.published_at,
                "inputs": [item.to_dict() for item in version.inputs],
                "outputs": [item.to_dict() for item in version.outputs],
                "input_contract": [input_contract(item) for item in version.inputs],
                "output_contract": [output_contract(item) for item in version.outputs],
                "step_count": len(version.nodes),
                "requires_confirmation": _requires_risk_confirmation(version),
                "referenced": int(version.version) in referenced if callable(referenced_versions) else bool(is_referenced(workflow_id, version.version)) if callable(is_referenced) else False,
            }
            for version in reversed(versions)
        ]
    }


@router.get("/{workflow_id}/export")
async def export_workflow_definition(workflow_id: str, version: str = "draft", format: str = "yaml", ctx=Depends(get_context)) -> dict[str, object]:
    if format not in {"yaml", "json"}:
        raise UnsupportedOperationError("format must be yaml or json")
    try:
        workflow = ctx.desktop.workflow_definitions.get(workflow_id, version)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    document = export_document(workflow)
    return {"filename": f"{workflow.name or workflow_id}.workflow.{format}", "format": format, "content": dump_document(document, fmt=format), "workflow": document}


def _portable_preview(content: str, filename: str, ctx: Any) -> dict[str, object]:
    try:
        portable = from_document(parse_document(content, filename=filename))
    except PortableWorkflowError as exc:
        return {"valid": False, "errors": [{"message": str(exc)}], "warnings": [], "workflow": None, "requirements": {"actions": []}}
    result = validate_workflow(portable.draft, build_action_catalog(), ctx.desktop.workflow_definitions.get)
    return {
        "valid": result.valid,
        "errors": [asdict(item) for item in result.errors],
        "warnings": [asdict(item) for item in result.warnings] + ([{"message": f"unknown action: {action}"} for action in portable.required_actions if build_action_catalog().get(action) is None]),
        "workflow": portable.draft.to_dict(),
        "requirements": {"actions": list(portable.required_actions)},
    }


@router.post("/import/preview")
async def preview_workflow_import(payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    content = str(payload.get("content") or "")
    filename = str(payload.get("filename") or "workflow.workflow.yaml")
    return _portable_preview(content, filename, ctx)


@router.post("/import")
async def import_workflow_definition(payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    content = payload.get("content")
    filename = str(payload.get("filename") or "workflow.workflow.yaml")
    if isinstance(content, str):
        preview = _portable_preview(content, filename, ctx)
        if not preview["valid"]:
            return preview
        portable = from_document(parse_document(content, filename=filename))
    elif isinstance(payload.get("workflow"), Mapping):
        portable = from_document(payload["workflow"])
        preview = _portable_preview(dump_document(payload["workflow"], fmt="json"), "workflow.json", ctx)
        if not preview["valid"]:
            return preview
    else:
        raise UnsupportedOperationError("content or workflow is required")
    draft_data = portable.draft.to_dict()
    draft_data["id"] = str(payload.get("id") or f"workflow_{uuid4().hex[:12]}")
    name = draft_data["name"]
    existing_names = {item.name for item in ctx.desktop.workflow_definitions.list()}
    if name in existing_names and payload.get("conflict_strategy", "create_copy") == "create_copy":
        draft_data["name"] = f"{name} (导入副本)"
    draft = WorkflowDraft.from_dict(draft_data)
    try:
        saved = ctx.desktop.workflow_definitions.create(draft)
    except (KeyError, ValueError) as exc:
        raise UnsupportedOperationError(str(exc)) from exc
    return {"imported": True, "workflow": saved.to_dict(), "warnings": list(portable.warnings), "requirements": {"actions": list(portable.required_actions)}}


@router.put("/{workflow_id}")
async def save_workflow_definition(workflow_id: str, payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    data = dict(payload)
    data["id"] = workflow_id
    draft = WorkflowDraft.from_dict(data)
    if not draft.name.strip():
        raise UnsupportedOperationError("workflow name is required")
    try:
        saved = ctx.desktop.workflow_definitions.save(draft)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    return {"workflow": saved.to_dict()}


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow_definition(workflow_id: str, ctx=Depends(get_context)) -> None:
    try:
        ctx.desktop.workflow_definitions.delete(workflow_id)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise ApplicationConflictError("流程存在已被任务引用的发布版本，不能删除") from exc


@router.delete("/{workflow_id}/versions/{version}", status_code=204)
async def delete_workflow_version(workflow_id: str, version: int, ctx=Depends(get_context)) -> None:
    try:
        ctx.desktop.workflow_definitions.delete(workflow_id, version)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc


@router.post("/{workflow_id}/versions/{version}/restore")
async def restore_workflow_version(workflow_id: str, version: int, ctx=Depends(get_context)) -> dict[str, object]:
    """Restore an immutable published snapshot into the editable draft."""
    try:
        published = ctx.desktop.workflow_definitions.get(workflow_id, version)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    draft = WorkflowDraft.from_dict({
        **published.to_dict(),
        "id": workflow_id,
        "version": "draft",
        "status": "draft",
    })
    try:
        saved = ctx.desktop.workflow_definitions.save(draft)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    return {"workflow": saved.to_dict(), "restored_version": version}


@router.post("/{workflow_id}/validate")
async def validate_workflow_definition(workflow_id: str, payload: Mapping[str, Any] | None = None, ctx=Depends(get_context)) -> dict[str, object]:
    try:
        draft = WorkflowDraft.from_dict({**ctx.desktop.workflow_definitions.get(workflow_id).to_dict(), **dict(payload or {})})
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    resolved_draft = _resolve_script_references(draft, ctx.desktop.settings)
    result = validate_workflow(resolved_draft, build_action_catalog(), ctx.desktop.workflow_definitions.get)
    return {"valid": result.valid, "errors": [asdict(item) for item in result.errors], "warnings": [asdict(item) for item in result.warnings]}


@router.post("/{workflow_id}/publish")
async def publish_workflow_definition(workflow_id: str, ctx=Depends(get_context)) -> dict[str, object]:
    try:
        draft = ctx.desktop.workflow_definitions.get(workflow_id)
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    resolved_draft = _resolve_script_references(draft, ctx.desktop.settings)
    result = validate_workflow(resolved_draft, build_action_catalog(), ctx.desktop.workflow_definitions.get)
    if not result.valid:
        return {"published": False, "valid": False, "errors": [asdict(item) for item in result.errors], "warnings": [asdict(item) for item in result.warnings]}
    version = ctx.desktop.workflow_definitions.publish(workflow_id)
    mark_referenced = getattr(ctx.desktop.workflow_definitions, "mark_referenced", None)
    if callable(mark_referenced):
        for called_id, called_version in _published_workflow_dependencies(
            version,
            ctx.desktop.workflow_definitions.get,
        ):
            mark_referenced(called_id, called_version)
    return {"published": True, "valid": True, "workflow": version.to_dict(), "warnings": [asdict(item) for item in result.warnings]}


@router.post("/{workflow_id}/run")
async def run_workflow_definition(workflow_id: str, payload: Mapping[str, Any], ctx=Depends(get_context)) -> dict[str, object]:
    raw_devices = payload.get("device_ids")
    device_ids = [str(item).strip() for item in raw_devices if str(item).strip()] if isinstance(raw_devices, (list, tuple)) else []
    if not device_ids:
        device_id = str(payload.get("device_id") or "").strip()
        if device_id:
            device_ids = [device_id]
    if not device_ids:
        raise UnsupportedOperationError("device_id is required")
    session_ids = payload.get("session_ids")
    session_by_device = {
        str(device_id): str(session_id).strip()
        for device_id, session_id in (session_ids.items() if isinstance(session_ids, Mapping) else ())
    }
    unknown_session_devices = set(session_by_device) - set(device_ids)
    if unknown_session_devices:
        raise UnsupportedOperationError(
            "session_ids contains devices outside device_ids",
            details={"devices": sorted(unknown_session_devices)},
        )
    version_number = payload.get("version")
    try:
        if version_number is not None:
            version = ctx.desktop.workflow_definitions.get(workflow_id, version_number)
        elif bool(payload.get("draft")):
            version = ctx.desktop.workflow_definitions.get(workflow_id, "draft")
        else:
            list_versions = getattr(ctx.desktop.workflow_definitions, "list_versions", None)
            versions = list_versions(workflow_id) if callable(list_versions) else []
            if not versions:
                raise UnsupportedOperationError("a published workflow version or explicit draft run is required")
            version = versions[-1]
    except KeyError as exc:
        raise ResourceNotFoundError(str(exc)) from exc
    version = _resolve_script_references(version, ctx.desktop.settings)
    step_id = str(payload.get("step_id") or "").strip()
    supplied_inputs = dict(payload.get("inputs") or {})
    inputs, contract_errors = resolve_input_values(getattr(version, "inputs", ()), supplied_inputs)
    inputs = _derive_workflow_convenience_inputs(version, inputs)
    if contract_errors:
        raise UnsupportedOperationError(
            "workflow inputs are invalid",
            details={"errors": [{"code": code, "field": name} for name, code in contract_errors.items()]},
        )
    input_issues = validate_workflow_inputs(version, inputs)  # type: ignore[arg-type]
    if input_issues:
        raise UnsupportedOperationError("workflow inputs are invalid", details={"errors": [asdict(item) for item in input_issues]})
    definition_issues = validate_workflow(
        version,
        build_action_catalog(),
        ctx.desktop.workflow_definitions.get,
    )  # type: ignore[arg-type]
    if not definition_issues.valid:
        raise UnsupportedOperationError(
            "workflow definition is invalid",
            details={"errors": [asdict(item) for item in definition_issues.errors]},
        )
    # Reject high-risk runs before staging any local upload sources. Staging
    # copies files into the shared root, so confirmation must precede it.
    expanded_version = _expand_subworkflows(
        version,
        ctx.desktop.workflow_definitions.get,
    )
    expanded_version = _resolve_script_references(expanded_version, ctx.desktop.settings)
    if not bool(payload.get("dry_run")) and _requires_risk_confirmation(expanded_version) and not bool(payload.get("confirmed_risks")):
        raise UnsupportedOperationError(
            "high-risk workflow run requires confirmation",
            details={"code": "risk_confirmation_required"},
        )
    staging_id = f"{workflow_id}-{uuid4().hex[:12]}"
    prepared_inputs, source_overrides = (
        _prepare_workflow_file_inputs(
            expanded_version,
            inputs,
            ctx.desktop.transfers,
            staging_id=staging_id,
        )
        if not bool(payload.get("dry_run"))
        else (dict(inputs), {})
    )
    inputs = prepared_inputs
    plans = {
        device_id: _compile_task_plan(expanded_version, device_id, source_overrides)
        for device_id in device_ids
    }
    if step_id:
        plans = {device_id: _select_plan_from_step(plan, step_id) for device_id, plan in plans.items()}
    plan = plans[device_ids[0]]
    if bool(payload.get("dry_run")):
        return {
            "dry_run": True,
            "preview": {
                "workflow_id": workflow_id,
                "workflow_version": str(version.version),
                "step_count": len(plan.nodes),
                "target_count": len(device_ids),
                "steps": [{"id": node.id, "action": node.workflow_id, "depends_on": list(node.depends_on)} for node in plan.nodes],
                "target_devices": device_ids,
            },
        }
    has_high_risk_action = any(
        node.workflow_id in _HIGH_RISK_WORKFLOW_IDS
        or str(node.input_mapping.get("action_id") or "") in _HIGH_RISK_WORKFLOW_IDS
        for plan in plans.values()
        for node in plan.nodes
    )
    if has_high_risk_action and not bool(payload.get("confirmed_risks")):
        raise UnsupportedOperationError(
            "high-risk workflow run requires confirmation",
            details={"code": "risk_confirmation_required"},
        )
    steps = [WorkflowStep(node.id, kind="tool", action=Action(node.workflow_id, parameters=dict(node.input_mapping)), depends_on=node.depends_on, params=dict(node.input_mapping), retry_policy=dict(node.retry_policy)) for node in plan.nodes]
    execution_version = str(version.version) if str(version.version).isdigit() else "0"
    workflow = TaskWorkflowDefinition(id=workflow_id, version=execution_version, name=version.name, steps=tuple(steps), metadata={"workflow_id": workflow_id, "workflow_version": str(version.version)})
    workflow_metadata = {**workflow.metadata, "framework_inputs": inputs}
    workflow = TaskWorkflowDefinition(id=workflow.id, version=workflow.version, name=workflow.name, steps=workflow.steps, metadata=workflow_metadata)
    task_payloads: list[dict[str, Any]] = []
    mark_referenced = getattr(ctx.desktop.workflow_definitions, "mark_referenced", None)
    dependency_versions = _published_workflow_dependencies(
        version,
        ctx.desktop.workflow_definitions.get,
    )
    try:
        for target_id in device_ids:
            # When a device-list workflow is launched for several targets,
            # each task represents one device. Keep device.for_each compatible
            # by feeding it only that task's target; otherwise every task
            # would iterate the entire selected list and execute N×N times.
            task_inputs = dict(inputs)
            if len(device_ids) > 1:
                for input_definition in getattr(version, "inputs", ()):
                    semantic = str(getattr(input_definition, "semantic_type", "") or "").casefold()
                    if semantic == "device_list" or str(getattr(input_definition, "type", "")).casefold() == "devices":
                        task_inputs[str(input_definition.name)] = [target_id]
            task_workflow = TaskWorkflowDefinition(
                id=workflow.id,
                version=workflow.version,
                name=workflow.name,
                steps=workflow.steps,
                metadata={**workflow.metadata, "framework_inputs": task_inputs},
            )
            task_context = {
                **task_inputs,
                "device": _device_reference_context(ctx, target_id),
                "workflow_staging_id": staging_id,
            }
            record = ctx.desktop.task_service.create(
                TaskCreate(
                    workflow=task_workflow,
                    framework_plan=plans[target_id],
                    target=DeviceTarget(
                        device_id=target_id,
                        session_id=session_by_device.get(target_id, str(payload.get("session_id") or "")),
                        protocol=str(payload.get("protocol") or "auto"),
                        host=str(payload.get("host") or ""),
                        port=int(payload.get("port") or 0),
                    ),
                    source="desktop-workflow-studio",
                    context=task_context,
                )
            )
            # Record references only after at least one task was created.
            # This avoids showing a reference when task creation fails.
            if str(getattr(version, "version", "draft")) != "draft" and callable(mark_referenced):
                mark_referenced(workflow_id, version.version)
            if callable(mark_referenced):
                for called_id, called_version in dependency_versions:
                    mark_referenced(called_id, called_version)
            record_payload = record.to_dict()
            record_payload["context"] = task_context
            task_payloads.append(record_payload)
    except Exception:
        if not task_payloads:
            cleanup = getattr(ctx.desktop.transfers, "cleanup_workflow_source", None)
            if callable(cleanup):
                cleanup(staging_id)
        raise
    return {
        "task": task_payloads[0],
        "tasks": task_payloads,
        "target_count": len(task_payloads),
    }
