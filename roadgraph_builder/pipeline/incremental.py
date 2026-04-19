"""Incremental / streaming graph build — ``update-graph`` back-end.

Adds a new trajectory to an existing road graph JSON without triggering a
full rebuild.  Strategy (per ROADMAP_0.7 P2):

1. Polyline-ize the new trajectory using the same gap-split + centerline
   logic as ``build_graph``.
2. For each new polyline, test whether every point on it lies within
   ``absorb_tolerance_m`` of some existing edge (laterally).  If yes the
   route has already been observed; bump ``attributes.trace_observation_count``
   on the matching edge(s) and skip edge creation.
3. Otherwise run the fast X/T split locally on (new polylines × nearby
   existing-edge polylines only), then endpoint union-find to wire new
   endpoints into the existing node table, and append the resulting new
   edges + nodes.
4. Return a new ``Graph`` object (the caller writes it via ``--output``).

The input graph JSON is **never** modified in place; callers must write the
returned graph to a new file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.pipeline.build_graph import BuildParams, trajectory_to_polylines
from roadgraph_builder.pipeline.crossing_splitters import (
    split_polylines_at_crossings_fast,
    split_polylines_at_t_junctions_fast,
)
from roadgraph_builder.utils.geometry import merge_endpoints_union_find


# ---------------------------------------------------------------------------
# Geometric helpers
# ---------------------------------------------------------------------------


def _point_to_segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Minimum distance from point P to segment AB."""
    abx, aby = bx - ax, by - ay
    ab2 = abx * abx + aby * aby
    if ab2 < 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / ab2))
    return math.hypot(px - ax - t * abx, py - ay - t * aby)


def _polyline_length_m(poly: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(len(poly) - 1):
        total += math.hypot(poly[i + 1][0] - poly[i][0], poly[i + 1][1] - poly[i][1])
    return total


def _point_max_lateral_to_polyline(
    px: float, py: float, poly: list[tuple[float, float]]
) -> float:
    """Minimum perpendicular distance from (px, py) to the nearest segment of poly."""
    best = float("inf")
    for i in range(len(poly) - 1):
        d = _point_to_segment_distance(px, py, poly[i][0], poly[i][1], poly[i + 1][0], poly[i + 1][1])
        if d < best:
            best = d
    return best


def _polyline_absorbed_by_edge(
    new_poly: list[tuple[float, float]],
    edge_poly: list[tuple[float, float]],
    absorb_tolerance_m: float,
) -> bool:
    """Return True if every point of new_poly is within absorb_tolerance_m of edge_poly.

    Checks all points (both endpoints and interior vertices) of ``new_poly``
    against the segments of ``edge_poly``.  A True result means the new
    trajectory runs along the same road as the existing edge and we should
    only bump the observation count rather than create a new edge.
    """
    for pt in new_poly:
        d = _point_max_lateral_to_polyline(pt[0], pt[1], edge_poly)
        if d > absorb_tolerance_m:
            return False
    return True


def _edge_bbox(edge_poly: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in edge_poly]
    ys = [p[1] for p in edge_poly]
    return (min(xs), min(ys), max(xs), max(ys))


def _bboxes_overlap_expanded(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    expand: float,
) -> bool:
    return not (
        a[2] + expand < b[0]
        or b[2] + expand < a[0]
        or a[3] + expand < b[1]
        or b[3] + expand < a[1]
    )


# ---------------------------------------------------------------------------
# Core incremental update function
# ---------------------------------------------------------------------------


def update_graph_from_trajectory(
    graph: Graph,
    new_trajectory: Trajectory,
    *,
    max_step_m: float = 25.0,
    merge_endpoint_m: float = 8.0,
    absorb_tolerance_m: float = 4.0,
) -> Graph:
    """Add a new trajectory to an existing graph without a full rebuild.

    Args:
        graph: Existing road graph (read-only; a new Graph is returned).
        new_trajectory: The new trajectory to integrate.  Must share the same
            meter-frame origin as the existing graph.
        max_step_m: Gap threshold for trajectory segmentation (same as
            ``BuildParams.max_step_m``).
        merge_endpoint_m: Endpoint merge radius — new endpoints within this
            distance of existing nodes snap to them (same as
            ``BuildParams.merge_endpoint_m``).
        absorb_tolerance_m: If every point of a new polyline falls within this
            lateral distance of an existing edge, the edge absorbs the trace
            (bumps ``trace_observation_count``) instead of creating a new edge.

    Returns:
        A new :class:`~roadgraph_builder.core.graph.graph.Graph` with all
        existing edges/nodes preserved and new edges/nodes appended.  The
        caller is responsible for writing this to the output file.

    Strategy:
        1. Polyline-ize the new trajectory.
        2. For each new polyline, test absorption against nearby existing edges.
        3. For remaining unabsorbed polylines, run X/T split restricted to
           (new polylines + nearby existing-edge polylines), then merge
           endpoints and append to the graph.
    """
    params = BuildParams(
        max_step_m=max_step_m,
        merge_endpoint_m=merge_endpoint_m,
    )
    new_polylines = trajectory_to_polylines(new_trajectory, params)
    if not new_polylines:
        # Nothing to add — return the original graph unchanged.
        return Graph(
            nodes=list(graph.nodes),
            edges=list(graph.edges),
            metadata=dict(graph.metadata),
        )

    # Pre-compute existing edge bboxes for fast lookup.
    existing_edges = list(graph.edges)
    existing_nodes = list(graph.nodes)
    edge_bboxes = [_edge_bbox(e.polyline) for e in existing_edges]

    # Copy existing edge attributes so we can mutate observation counts.
    # Use a shallow copy of edges with deep-copied attributes.
    updated_edges: list[Edge] = [
        Edge(
            id=e.id,
            start_node_id=e.start_node_id,
            end_node_id=e.end_node_id,
            polyline=list(e.polyline),
            attributes=dict(e.attributes),
        )
        for e in existing_edges
    ]

    # Determine next available node/edge ids.
    next_nid = _next_int_suffix(n.id for n in existing_nodes)
    next_eid = _next_int_suffix(e.id for e in existing_edges)

    unabsorbed: list[list[tuple[float, float]]] = []

    for new_poly in new_polylines:
        new_bbox = _edge_bbox(new_poly)

        # Find candidate existing edges (bbox proximity).
        absorbed = False
        for ei, ue in enumerate(updated_edges):
            if not _bboxes_overlap_expanded(new_bbox, edge_bboxes[ei], absorb_tolerance_m):
                continue
            if _polyline_absorbed_by_edge(new_poly, ue.polyline, absorb_tolerance_m):
                # Bump observation count on the absorbing edge.
                count = int(ue.attributes.get("trace_observation_count", 0)) + 1
                ue.attributes["trace_observation_count"] = count
                absorbed = True
                break  # Absorbed by the first matching edge; stop.

        if not absorbed:
            unabsorbed.append(new_poly)

    if not unabsorbed:
        # All new polylines were absorbed — return graph with updated counts.
        return Graph(
            nodes=list(existing_nodes),
            edges=updated_edges,
            metadata=dict(graph.metadata),
        )

    # --- Build new edges from unabsorbed polylines ---

    # Gather nearby existing edges for X/T split interaction.
    # "Nearby" = bbox overlaps with any unabsorbed polyline's bbox expanded by
    # merge_endpoint_m.
    unabsorbed_super_bbox = _union_bboxes([_edge_bbox(p) for p in unabsorbed])
    nearby_existing_polys: list[list[tuple[float, float]]] = []
    nearby_edge_indices: list[int] = []
    for ei, ue in enumerate(updated_edges):
        if _bboxes_overlap_expanded(unabsorbed_super_bbox, edge_bboxes[ei], merge_endpoint_m * 2):
            nearby_existing_polys.append(list(ue.polyline))
            nearby_edge_indices.append(ei)

    # Run X/T splitting on (unabsorbed + nearby existing) together.
    combined = list(unabsorbed) + nearby_existing_polys
    n_new = len(unabsorbed)
    after_cross = split_polylines_at_crossings_fast(combined)
    after_tjunc = split_polylines_at_t_junctions_fast(after_cross, merge_endpoint_m)

    # Gather all endpoints (existing node positions + new polyline endpoints).
    existing_node_positions: list[tuple[float, float]] = [
        tuple(n.position) for n in existing_nodes  # type: ignore[misc]
    ]
    new_endpoints: list[tuple[float, float]] = []
    for poly in after_tjunc:
        new_endpoints.append(poly[0])
        new_endpoints.append(poly[-1])

    all_endpoint_candidates = existing_node_positions + new_endpoints

    # Merge endpoints.
    node_positions, idx_to_node = merge_endpoints_union_find(
        all_endpoint_candidates, merge_endpoint_m
    )

    # Build a mapping from existing node id → canonical merged node id.
    # The first len(existing_node_positions) entries in all_endpoint_candidates
    # correspond to the existing nodes.
    n_existing_pts = len(existing_node_positions)
    existing_node_ids = [n.id for n in existing_nodes]
    old_id_to_merged: dict[str, str] = {}
    for i, nid in enumerate(existing_node_ids):
        old_id_to_merged[nid] = idx_to_node[i]

    # Update existing node ids in updated_edges if any node merged.
    rewired = False
    for ue in updated_edges:
        new_sn = old_id_to_merged.get(ue.start_node_id, ue.start_node_id)
        new_en = old_id_to_merged.get(ue.end_node_id, ue.end_node_id)
        if new_sn != ue.start_node_id or new_en != ue.end_node_id:
            ue.start_node_id = new_sn
            ue.end_node_id = new_en
            rewired = True

    # Build new edges from after_tjunc polylines.  Skip edges whose endpoint
    # pair already exists in updated_edges (de-duplication of re-split existing
    # polylines that got re-projected onto the same node pair).
    existing_endpoint_pairs: set[tuple[str, str]] = set()
    for ue in updated_edges:
        pair = tuple(sorted((ue.start_node_id, ue.end_node_id)))
        existing_endpoint_pairs.add(pair)

    new_edges: list[Edge] = []
    new_nodes_map: dict[str, tuple[float, float]] = {}
    used_node_ids: set[str] = {nid for n in existing_nodes for nid in [n.id]}

    selfloop_min = 2.0 * merge_endpoint_m
    for pi, poly in enumerate(after_tjunc):
        ep_start_idx = n_existing_pts + 2 * pi
        ep_end_idx = n_existing_pts + 2 * pi + 1
        sn = idx_to_node[ep_start_idx]
        en = idx_to_node[ep_end_idx]
        if sn == en and _polyline_length_m(poly) < selfloop_min:
            continue
        # Skip if this edge's node pair is already covered by an existing edge.
        pair = tuple(sorted((sn, en)))
        if pair in existing_endpoint_pairs:
            continue
        sn_pos = node_positions[sn]
        en_pos = node_positions[en]
        new_edges.append(
            Edge(
                id=f"e{next_eid}",
                start_node_id=sn,
                end_node_id=en,
                polyline=list(poly),
                attributes={
                    "kind": "lane_centerline",
                    "source": "trajectory_incremental",
                    "direction_observed": "forward_only",
                    "trace_observation_count": 1,
                },
            )
        )
        existing_endpoint_pairs.add(pair)  # Prevent duplicates among new edges too.
        new_nodes_map[sn] = sn_pos
        new_nodes_map[en] = en_pos
        used_node_ids.add(sn)
        used_node_ids.add(en)
        next_eid += 1

    # Build final node list.
    # Start with existing nodes, updating positions where endpoint-merge moved them.
    final_nodes: list[Node] = []
    existing_node_id_set = {n.id for n in existing_nodes}
    for n in existing_nodes:
        merged_id = old_id_to_merged.get(n.id, n.id)
        pos = node_positions.get(merged_id, n.position)
        if merged_id in used_node_ids:
            final_nodes.append(Node(id=n.id, position=pos, attributes=dict(n.attributes)))

    # Add truly new nodes (those not corresponding to any existing node position).
    existing_pos_set: set[str] = {n.id for n in existing_nodes}
    for nid, pos in node_positions.items():
        if nid not in existing_pos_set and nid in used_node_ids:
            final_nodes.append(Node(id=nid, position=pos, attributes={}))

    final_edges = updated_edges + new_edges

    return Graph(
        nodes=final_nodes,
        edges=final_edges,
        metadata=dict(graph.metadata),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _next_int_suffix(ids) -> int:
    """Return max(int suffix of each id) + 1, or 0 if empty."""
    max_n = -1
    for id_str in ids:
        try:
            n = int(id_str.lstrip("abcdefghijklmnopqrstuvwxyz"))
            if n > max_n:
                max_n = n
        except ValueError:
            pass
    return max_n + 1


def _union_bboxes(
    bboxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    if not bboxes:
        return (0.0, 0.0, 0.0, 0.0)
    mn_x = min(b[0] for b in bboxes)
    mn_y = min(b[1] for b in bboxes)
    mx_x = max(b[2] for b in bboxes)
    mx_y = max(b[3] for b in bboxes)
    return (mn_x, mn_y, mx_x, mx_y)
