"""Identify the graph body owned by a loop node.

The studio historically inferred a loop body by walking every downstream edge
from ``device.for_each``.  Newer drafts can mark the body entry edge and set a
``body_end`` node explicitly, which mirrors Windmill's loop container while
keeping old linear drafts compatible.
"""

from __future__ import annotations

from typing import Any


DISALLOWED_BODY_ACTIONS = frozenset({
    "device.for_each", "loop.for_each", "loop.until", "utility.condition",
    "utility.confirm", "workflow.call",
})

BODY_HANDLES = frozenset({"body", "loop-body", "loop_body"})
EXIT_HANDLES = frozenset({"exit", "loop-exit", "loop_exit"})
LOOP_ACTIONS = frozenset({"device.for_each", "loop.for_each", "loop.until"})


def _edge_handle(edge: Any) -> str:
    return str(getattr(edge, "source_handle", None) or "").strip().casefold()


def device_loop_bodies(workflow: Any) -> dict[str, tuple[str, ...]]:
    nodes = {node.id: node for node in workflow.nodes}
    incoming: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    outgoing_edges: dict[str, list[Any]] = {node_id: [] for node_id in nodes}
    for edge in workflow.edges:
        if edge.source in nodes and edge.target in nodes:
            incoming[edge.target].append(edge.source)
            outgoing[edge.source].append(edge.target)
            outgoing_edges[edge.source].append(edge)
    bodies: dict[str, tuple[str, ...]] = {}
    owned: set[str] = set()
    for node in workflow.nodes:
        if node.action_id not in LOOP_ACTIONS:
            continue
        settings = {**node.config, **node.input_mapping}
        mode = settings.get("body_mode")
        explicit_start = str(settings.get("body_start") or settings.get("loop_start") or "").strip()
        explicit_end = str(
            settings.get("body_end")
            or settings.get("loop_end")
            or settings.get("loop_body_end")
            or ""
        ).strip()
        source_edges = outgoing_edges[node.id]
        body_edges = [edge for edge in source_edges if _edge_handle(edge) in BODY_HANDLES]
        exit_edges = [edge for edge in source_edges if _edge_handle(edge) in EXIT_HANDLES]
        graph_mode = mode in {"downstream", "bounded"} or bool(body_edges) or (
            node.action_id == "device.for_each"
            and mode != "action"
            and outgoing[node.id]
            and not settings.get("action_inputs")
        )
        if not graph_mode:
            continue
        if not body_edges and len(source_edges) == 1 and not exit_edges:
            body_edges = list(source_edges)
        elif not body_edges and len(source_edges) > 1:
            inferred_body_edges = [edge for edge in source_edges if _edge_handle(edge) not in EXIT_HANDLES]
            if len(inferred_body_edges) == 1:
                body_edges = inferred_body_edges
        if len(body_edges) > 1:
            raise ValueError(f"device loop {node.id} requires one loop-body entry")
        if len(exit_edges) > 1:
            raise ValueError(f"device loop {node.id} requires one loop-exit connection")
        exit_targets = {str(edge.target) for edge in exit_edges}

        body_start = explicit_start or (str(body_edges[0].target) if body_edges else "")
        if body_start and body_start not in nodes:
            raise ValueError(f"device loop {node.id} body_start references an unknown node")
        if explicit_end and explicit_end not in nodes:
            raise ValueError(f"device loop {node.id} body_end references an unknown node")

        body: list[str] = []
        current = body_start or node.id
        reached_explicit_end = False
        while outgoing[current]:
            if explicit_end and current == explicit_end:
                reached_explicit_end = True
                break
            current_edges = outgoing_edges[current]
            if len(current_edges) != 1:
                raise ValueError(f"device loop {node.id} requires a linear body; branches are not supported")
            following = current_edges[0].target
            # A loop-exit connection identifies the first node after the
            # container. Stop before that node when older drafts do not carry
            # an explicit body_end field.
            if following in exit_targets:
                break
            # A join with another graph path is outside the iteration scope.
            if len(incoming[following]) > 1:
                break
            if following == node.id or following in body or following in owned:
                raise ValueError(f"device loop {node.id} has a cycle or overlapping body")
            if nodes[following].action_id in DISALLOWED_BODY_ACTIONS:
                raise ValueError(f"device loop {node.id} cannot contain {nodes[following].action_id}")
            body.append(following)
            current = following
        if body_start:
            if body_start == explicit_end:
                body = [body_start]
                reached_explicit_end = True
            elif body_start not in body:
                body.insert(0, body_start)
            if explicit_end and explicit_end not in body:
                raise ValueError(f"device loop {node.id} body_end is not reachable from body_start")
            if explicit_end:
                end_index = body.index(explicit_end)
                body = body[: end_index + 1]
                reached_explicit_end = True
        elif explicit_end and not reached_explicit_end:
            raise ValueError(f"device loop {node.id} body_end is not reachable")
        if not body:
            raise ValueError(f"device loop {node.id} requires a downstream action")
        bodies[node.id] = tuple(body)
        owned.update(body)
    return bodies
