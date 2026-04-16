"""MVP pipeline: trajectory -> clustered segments -> centerlines -> graph.

Separation note:
- This file is structure (graph) composition; lane semantics live in attributes/TODO modules.
- TODO: LiDAR — feed boundary polylines as edge geometry overlays / constraints.
- TODO: camera — attach semantic tags to edges/nodes after fusion.
- TODO: graph fusion — merge this graph with graphs from other modalities / tiles.
- TODO: intersection topology — classify node degree and turn movements.
- TODO: routing graph — collapse geometry for turn-by-turn / nav.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.trajectory.loader import Trajectory, load_trajectory_csv
from roadgraph_builder.utils.geometry import (
    centerline_from_points,
    merge_endpoints_union_find,
    simplify_polyline_rdp,
    split_indices_by_step,
)


@dataclass(frozen=True)
class BuildParams:
    """Tunable MVP parameters."""

    max_step_m: float = 25.0
    merge_endpoint_m: float = 8.0
    centerline_bins: int = 32
    #: Douglas–Peucker tolerance (meters); None disables simplification.
    simplify_tolerance_m: float | None = None


def _orient_polyline_to_trajectory(
    poly: list[tuple[float, float]],
    segment_xy: np.ndarray,
) -> list[tuple[float, float]]:
    """Match polyline direction to the time-ordered segment (PCA may reverse)."""
    if len(poly) < 2 or segment_xy.shape[0] == 0:
        return poly
    head = np.asarray(poly[0], dtype=np.float64)
    tail = np.asarray(poly[-1], dtype=np.float64)
    start = segment_xy[0]
    if float(np.linalg.norm(head - start)) > float(np.linalg.norm(tail - start)):
        return list(reversed(poly))
    return poly


def trajectory_to_polylines(traj: Trajectory, params: BuildParams) -> list[list[tuple[float, float]]]:
    """Cluster/segment trajectory and fit a centerline polyline per segment.

    MVP clustering: split the time-ordered path when consecutive points jump farther than
    `max_step_m` (e.g., GPS gap, teleports). Replace with DBSCAN/meanshift later.
    """
    xy = traj.xy
    ranges = split_indices_by_step(xy, params.max_step_m)
    polylines: list[list[tuple[float, float]]] = []
    for lo, hi in ranges:
        seg = xy[lo:hi]
        if seg.shape[0] == 0:
            continue
        poly = centerline_from_points(seg, num_bins=params.centerline_bins)
        poly = _orient_polyline_to_trajectory(poly, seg)
        if len(poly) >= 2:
            polylines.append(poly)
    return polylines


def annotate_node_degrees(graph: Graph) -> None:
    """Set node `attributes`: `degree` (undirected) and `junction_hint`.

    ``junction_hint`` values:

    - ``multi_branch`` — degree ≥ 3
    - ``dead_end`` — degree == 1
    - ``self_loop`` — the only incident edge is a self-loop (start == end);
      legitimate round-trip / circuit loops land here, since degenerate
      zero-length self-loops are already dropped in ``polylines_to_graph``.
    - ``through_or_corner`` — anything else (typically degree 2 straight-through).
    """
    deg: dict[str, int] = {n.id: 0 for n in graph.nodes}
    selfloop_only: dict[str, bool] = {n.id: False for n in graph.nodes}
    incident_count: dict[str, int] = {n.id: 0 for n in graph.nodes}
    for e in graph.edges:
        a, b = e.start_node_id, e.end_node_id
        if a == b:
            deg[a] = deg.get(a, 0) + 2
            incident_count[a] = incident_count.get(a, 0) + 1
            # Mark as self-loop candidate; cleared below if any non-loop edge also touches it.
            if incident_count[a] == 1:
                selfloop_only[a] = True
        else:
            deg[a] = deg.get(a, 0) + 1
            deg[b] = deg.get(b, 0) + 1
            incident_count[a] = incident_count.get(a, 0) + 1
            incident_count[b] = incident_count.get(b, 0) + 1
            selfloop_only[a] = False
            selfloop_only[b] = False
    for n in graph.nodes:
        d = deg.get(n.id, 0)
        n.attributes["degree"] = d
        if selfloop_only.get(n.id, False) and incident_count.get(n.id, 0) == 1:
            n.attributes["junction_hint"] = "self_loop"
        elif d >= 3:
            n.attributes["junction_hint"] = "multi_branch"
        elif d == 1:
            n.attributes["junction_hint"] = "dead_end"
        else:
            n.attributes["junction_hint"] = "through_or_corner"


def _polyline_length_m(poly: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(len(poly) - 1):
        dx = poly[i + 1][0] - poly[i][0]
        dy = poly[i + 1][1] - poly[i][1]
        total += math.hypot(dx, dy)
    return total


def polylines_to_graph(polylines: list[list[tuple[float, float]]], params: BuildParams) -> Graph:
    """Create nodes (merged endpoints) and edges (centerline polylines).

    Edges whose endpoints collapse onto a single node **and** whose polyline
    arc-length stays within ``2 * merge_endpoint_m`` are dropped as merge
    artefacts — they encode no direction and no length, yet would otherwise
    appear as zero-length self-loops in downstream consumers. Legitimate loops
    (round trips, block circuits) trace longer polylines and survive.
    """
    work: list[list[tuple[float, float]]] = list(polylines)
    tol = params.simplify_tolerance_m
    if tol is not None and tol > 0:
        work = []
        for poly in polylines:
            if len(poly) < 2:
                continue
            sp = simplify_polyline_rdp(poly, tol)
            if len(sp) >= 2:
                work.append(sp)

    endpoints: list[tuple[float, float]] = []
    for poly in work:
        endpoints.append(poly[0])
        endpoints.append(poly[-1])

    node_positions, idx_to_node = merge_endpoints_union_find(endpoints, params.merge_endpoint_m)

    selfloop_min_length = 2.0 * params.merge_endpoint_m
    edges: list[Edge] = []
    used_nodes: set[str] = set()
    next_eid = 0
    for poly_idx, poly in enumerate(work):
        sn = idx_to_node[2 * poly_idx]
        en = idx_to_node[2 * poly_idx + 1]
        if sn == en and _polyline_length_m(poly) < selfloop_min_length:
            continue
        edges.append(
            Edge(
                id=f"e{next_eid}",
                start_node_id=sn,
                end_node_id=en,
                polyline=list(poly),
                attributes={
                    "kind": "lane_centerline",
                    "source": "trajectory_mvp",
                },
            )
        )
        used_nodes.add(sn)
        used_nodes.add(en)
        next_eid += 1

    nodes = [
        Node(id=nid, position=node_positions[nid])
        for nid in sorted(node_positions.keys())
        if nid in used_nodes
    ]

    graph = Graph(nodes=nodes, edges=edges)
    annotate_node_degrees(graph)
    return graph


def build_graph_from_trajectory(traj: Trajectory, params: BuildParams | None = None) -> Graph:
    """Build a road graph from an in-memory trajectory."""
    p = params or BuildParams()
    polylines = trajectory_to_polylines(traj, p)
    graph = polylines_to_graph(polylines, p)
    if not graph.edges:
        raise ValueError(
            "Built graph has no edges: the trajectory produced no usable centerline segments "
            "(each segment needs enough samples to form a polyline with at least two vertices). "
            "Try adding more points, lowering --max-step-m if gaps split the path too much, "
            "or check for collapsed/duplicate coordinates."
        )
    return graph


def build_graph_from_csv(path: str, params: BuildParams | None = None) -> Graph:
    """Load CSV trajectory and build a road graph."""
    traj = load_trajectory_csv(path)
    return build_graph_from_trajectory(traj, params)
