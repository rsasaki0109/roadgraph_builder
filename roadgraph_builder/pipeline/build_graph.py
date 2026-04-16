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
    """Set node `attributes`: `degree` (undirected) and `junction_hint` for dead-ends / branches."""
    deg: dict[str, int] = {n.id: 0 for n in graph.nodes}
    for e in graph.edges:
        a, b = e.start_node_id, e.end_node_id
        if a == b:
            deg[a] = deg.get(a, 0) + 2
        else:
            deg[a] = deg.get(a, 0) + 1
            deg[b] = deg.get(b, 0) + 1
    for n in graph.nodes:
        d = deg.get(n.id, 0)
        n.attributes["degree"] = d
        if d >= 3:
            n.attributes["junction_hint"] = "multi_branch"
        elif d == 1:
            n.attributes["junction_hint"] = "dead_end"
        else:
            n.attributes["junction_hint"] = "through_or_corner"


def polylines_to_graph(polylines: list[list[tuple[float, float]]], params: BuildParams) -> Graph:
    """Create nodes (merged endpoints) and edges (centerline polylines)."""
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
    nodes = [Node(id=nid, position=node_positions[nid]) for nid in sorted(node_positions.keys())]

    edges: list[Edge] = []
    for eid, poly in enumerate(work):
        i0 = 2 * eid
        i1 = 2 * eid + 1
        sn = idx_to_node[i0]
        en = idx_to_node[i1]
        edges.append(
            Edge(
                id=f"e{eid}",
                start_node_id=sn,
                end_node_id=en,
                polyline=list(poly),
                attributes={
                    "kind": "lane_centerline",
                    "source": "trajectory_mvp",
                },
            )
        )
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
