"""Infer coarse ``allowed_maneuvers`` per edge from 2D junction geometry (SD seed)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.edge import Edge
    from roadgraph_builder.core.graph.graph import Graph

_MANEUVER_ORDER = ("straight", "left", "right", "u_turn")

# Treat as continuation (no extra left/right bucket).
_STRAIGHT_TURN_RAD = 0.26  # ~15°
# Near 180° → u-turn onto another edge.
_UTURN_RAD = math.pi - 0.52  # ~150°


def _unit(dx: float, dy: float) -> tuple[float, float]:
    L = math.hypot(dx, dy)
    if L < 1e-12:
        return (1.0, 0.0)
    return (dx / L, dy / L)


def _incoming_unit_at_end(edge: Edge) -> tuple[float, float]:
    """Unit vector along travel direction **into** ``end_node_id`` (digitized forward)."""
    pl = edge.polyline
    if len(pl) < 2:
        return (1.0, 0.0)
    ax, ay = pl[-2]
    bx, by = pl[-1]
    return _unit(bx - ax, by - ay)


def _incoming_unit_at_start_reverse(edge: Edge) -> tuple[float, float]:
    """Unit vector **into** ``start_node_id`` when traversing the edge from end → start."""
    pl = edge.polyline
    if len(pl) < 2:
        return (1.0, 0.0)
    ax, ay = pl[1]
    bx, by = pl[0]
    return _unit(bx - ax, by - ay)


def _outgoing_unit_from_node(edge: Edge, node_id: str) -> tuple[float, float]:
    """Unit vector **leaving** ``node_id`` along ``edge`` (away from junction)."""
    pl = edge.polyline
    if len(pl) < 2:
        return (1.0, 0.0)
    if edge.start_node_id == node_id:
        ax, ay = pl[0]
        bx, by = pl[1]
        return _unit(bx - ax, by - ay)
    if edge.end_node_id == node_id:
        ax, ay = pl[-2]
        bx, by = pl[-1]
        return _unit(ax - bx, ay - by)
    raise ValueError(f"node {node_id!r} not incident to edge {edge.id!r}")


def _node_degree(graph: Graph, node_id: str) -> int:
    n = 0
    for e in graph.edges:
        if e.start_node_id == node_id:
            n += 1
        if e.end_node_id == node_id:
            n += 1
    return n


def _incident_edges_excluding(graph: Graph, node_id: str, exclude: Edge) -> list[Edge]:
    return [
        e
        for e in graph.edges
        if e is not exclude and (e.start_node_id == node_id or e.end_node_id == node_id)
    ]


def _degree_at_node(graph: Graph, node_id: str) -> int:
    for n in graph.nodes:
        if n.id == node_id:
            d = n.attributes.get("degree")
            if isinstance(d, int):
                return d
            break
    return _node_degree(graph, node_id)


def _maneuvers_at_junction(
    graph: Graph,
    edge: Edge,
    junction_node_id: str,
    v_in: tuple[float, float],
) -> list[str]:
    """Maneuvers when arriving at ``junction_node_id`` along ``edge`` with incoming heading ``v_in``."""
    out: set[str] = {"straight"}
    deg = _degree_at_node(graph, junction_node_id)
    others = _incident_edges_excluding(graph, junction_node_id, edge)
    saw_straight_continuation = False

    if not others:
        if deg <= 1:
            out.add("u_turn")
        return _sort_maneuvers(out)

    for e2 in others:
        try:
            v_out = _outgoing_unit_from_node(e2, junction_node_id)
        except ValueError:
            continue
        cross = v_in[0] * v_out[1] - v_in[1] * v_out[0]
        dot = v_in[0] * v_out[0] + v_in[1] * v_out[1]
        angle = math.atan2(cross, dot)
        if abs(angle) < _STRAIGHT_TURN_RAD:
            saw_straight_continuation = True
            continue
        if abs(angle) >= _UTURN_RAD:
            out.add("u_turn")
            continue
        if angle > 0:
            out.add("left")
        else:
            out.add("right")

    # sd_nav is a regulation-free routing seed. At a T/Y junction, an approach
    # with a straight continuation plus one side branch should remain permissive
    # instead of encoding a one-sided turn restriction from sparse geometry.
    if deg >= 3 and saw_straight_continuation:
        if "left" in out and "right" not in out:
            out.add("right")
        elif "right" in out and "left" not in out:
            out.add("left")

    return _sort_maneuvers(out)


def allowed_maneuvers_for_edge(graph: Graph, edge: Edge) -> list[str]:
    """Digitized **forward** direction: maneuvers at ``end_node_id``.

    Heuristic only; not a substitute for surveyed turn restrictions.
    """
    return _maneuvers_at_junction(graph, edge, edge.end_node_id, _incoming_unit_at_end(edge))


def allowed_maneuvers_for_edge_reverse(graph: Graph, edge: Edge) -> list[str]:
    """Opposite of digitization: travel end → start; maneuvers at ``start_node_id``."""
    return _maneuvers_at_junction(
        graph,
        edge,
        edge.start_node_id,
        _incoming_unit_at_start_reverse(edge),
    )


def _sort_maneuvers(m: set[str]) -> list[str]:
    return [x for x in _MANEUVER_ORDER if x in m]
