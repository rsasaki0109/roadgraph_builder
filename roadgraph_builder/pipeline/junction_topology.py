"""Classify multi-branch junctions by incident-edge geometry.

Layered on top of ``annotate_node_degrees``. For every node whose
``junction_hint`` is ``"multi_branch"`` we inspect the tangent directions of
the edges leaving the node and assign a finer ``junction_type``:

- ``t_junction`` — degree 3, two edges roughly collinear (through line) and the
  third near-perpendicular branch.
- ``y_junction`` — degree 3, no pair of edges collinear enough for a through
  line (the three branches fan out at similar angles).
- ``crossroads`` — degree 4, two through lines that are roughly perpendicular
  (the usual ``+`` intersection).
- ``x_junction`` — degree 4 with two through lines that are not perpendicular
  (an X / skewed cross).
- ``complex_junction`` — degree ≥ 5 or anything not covered above.

These are geometry heuristics only; they do not imply legal or regulatory
behaviour. Degenerate self-loop nodes and dead ends are handled by
``annotate_node_degrees`` and skipped here.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from roadgraph_builder.navigation.sd_maneuvers import _outgoing_unit_from_node

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


# Two edges are considered "collinear" if the angle between their outgoing
# tangents is within this many radians of 180°.
_COLLINEAR_TOLERANCE_RAD = math.radians(25.0)
# Perpendicularity window for T-junctions and crossroads (90° ± this).
_PERPENDICULAR_TOLERANCE_RAD = math.radians(25.0)


def _signed_angle(v_ref: tuple[float, float], v: tuple[float, float]) -> float:
    cross = v_ref[0] * v[1] - v_ref[1] * v[0]
    dot = v_ref[0] * v[0] + v_ref[1] * v[1]
    return math.atan2(cross, dot)


def _outgoing_tangents_at(graph: Graph, node_id: str) -> list[tuple[float, float]]:
    """Unit tangents of every incident edge leaving ``node_id``.

    A self-loop contributes two tangents (one at each end of its polyline).
    """
    out: list[tuple[float, float]] = []
    for e in graph.edges:
        if e.start_node_id == node_id:
            out.append(_outgoing_unit_from_node(e, node_id))
        if e.end_node_id == node_id and e.start_node_id != node_id:
            out.append(_outgoing_unit_from_node(e, node_id))
        elif e.start_node_id == node_id and e.end_node_id == node_id:
            # Self-loop: the first append above handled the start side; add the
            # end-side outgoing tangent (which leaves the node moving into the
            # polyline from the *end*).
            pl = e.polyline
            if len(pl) >= 2:
                bx, by = pl[-2]
                ax, ay = pl[-1]
                L = math.hypot(bx - ax, by - ay)
                if L > 1e-12:
                    out.append(((bx - ax) / L, (by - ay) / L))
    return out


def _pairwise_angles(tangents: list[tuple[float, float]]) -> list[tuple[int, int, float]]:
    """Absolute angle (radians) between every pair of tangents."""
    pairs: list[tuple[int, int, float]] = []
    for i in range(len(tangents)):
        for j in range(i + 1, len(tangents)):
            pairs.append((i, j, abs(_signed_angle(tangents[i], tangents[j]))))
    return pairs


def _is_collinear_pair(angle_rad: float) -> bool:
    return abs(angle_rad - math.pi) <= _COLLINEAR_TOLERANCE_RAD


def classify_multi_branch_node(graph: Graph, node_id: str) -> str:
    """Return the ``junction_type`` string for a degree ≥ 3 node."""
    tangents = _outgoing_tangents_at(graph, node_id)
    degree = len(tangents)

    if degree == 3:
        pairs = _pairwise_angles(tangents)
        collinear = [(i, j, ang) for i, j, ang in pairs if _is_collinear_pair(ang)]
        if collinear:
            # Pick the pair closest to 180° as the through line.
            i, j, _ = min(collinear, key=lambda p: abs(p[2] - math.pi))
            branch_idx = next(k for k in range(3) if k not in (i, j))
            through_dir = tangents[i]
            branch_dir = tangents[branch_idx]
            angle_to_through = abs(_signed_angle(through_dir, branch_dir))
            perp_offset = abs(angle_to_through - math.pi / 2.0)
            if perp_offset <= _PERPENDICULAR_TOLERANCE_RAD:
                return "t_junction"
            return "y_junction"
        return "y_junction"

    if degree == 4:
        pairs = _pairwise_angles(tangents)
        collinear_pairs = [(i, j, ang) for i, j, ang in pairs if _is_collinear_pair(ang)]
        # Need two disjoint collinear pairs for a through-through intersection.
        disjoint: list[tuple[int, int]] = []
        used: set[int] = set()
        for i, j, ang in sorted(collinear_pairs, key=lambda p: abs(p[2] - math.pi)):
            if i in used or j in used:
                continue
            disjoint.append((i, j))
            used.update({i, j})
            if len(disjoint) == 2:
                break
        if len(disjoint) == 2:
            line_a = tangents[disjoint[0][0]]
            line_b = tangents[disjoint[1][0]]
            between = abs(_signed_angle(line_a, line_b))
            # Fold onto [0, π/2] since the two lines are undirected here.
            if between > math.pi / 2.0:
                between = math.pi - between
            if abs(between - math.pi / 2.0) <= _PERPENDICULAR_TOLERANCE_RAD:
                return "crossroads"
            return "x_junction"
        return "complex_junction"

    return "complex_junction"


def annotate_junction_types(graph: Graph) -> None:
    """Tag every ``multi_branch`` node with a geometry-derived ``junction_type``."""
    for n in graph.nodes:
        if n.attributes.get("junction_hint") != "multi_branch":
            continue
        n.attributes["junction_type"] = classify_multi_branch_node(graph, n.id)


__all__ = ["annotate_junction_types", "classify_multi_branch_node"]
