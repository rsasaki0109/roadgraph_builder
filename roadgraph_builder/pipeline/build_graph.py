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
from roadgraph_builder.pipeline.junction_topology import annotate_junction_types
from roadgraph_builder.utils.geometry import (
    centerline_from_points,
    merge_endpoints_union_find,
    simplify_polyline_rdp,
    split_indices_by_step,
    split_polylines_at_crossings,
    split_polylines_at_t_junctions,
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


def _resample_polyline_at_arclen(
    poly: list[tuple[float, float]], n_samples: int
) -> list[tuple[float, float]]:
    """Resample ``poly`` at ``n_samples`` uniformly-spaced arc-length positions."""
    if len(poly) < 2 or n_samples < 2:
        return list(poly)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    seg_len = [
        math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) for i in range(len(poly) - 1)
    ]
    cum = [0.0]
    for s in seg_len:
        cum.append(cum[-1] + s)
    total = cum[-1]
    if total < 1e-9:
        return [poly[0]] * n_samples
    out: list[tuple[float, float]] = []
    j = 0
    for i in range(n_samples):
        target = total * i / (n_samples - 1)
        while j + 1 < len(cum) and cum[j + 1] < target:
            j += 1
        if j + 1 >= len(cum):
            out.append((xs[-1], ys[-1]))
            continue
        span = cum[j + 1] - cum[j]
        if span < 1e-12:
            out.append((xs[j], ys[j]))
        else:
            t = (target - cum[j]) / span
            out.append((xs[j] + t * (xs[j + 1] - xs[j]), ys[j] + t * (ys[j + 1] - ys[j])))
    return out


def merge_duplicate_edges(graph: Graph, *, resample_bins: int = 32) -> int:
    """Collapse edges that share the **same endpoint pair** into one averaged edge.

    A GPS trip that traverses the same road more than once produces several
    polylines with the same start/end nodes after endpoint union-find. Instead
    of shipping them as parallel duplicates we resample each polyline at
    ``resample_bins`` arc-length-uniform samples, reorient those that were
    walked in the opposite direction, and average to get one cleaner centerline.
    Returns the number of edges removed by merging.
    """
    from collections import defaultdict

    groups: dict[tuple[str, str], list[Edge]] = defaultdict(list)
    for e in graph.edges:
        key = tuple(sorted((e.start_node_id, e.end_node_id)))
        groups[key].append(e)

    merged_removed = 0
    kept: list[Edge] = []
    for key, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        # Merge: reorient every polyline to match the canonical direction of the
        # first edge in the group, resample to a common length, and average.
        primary = group[0]
        canonical_start, canonical_end = primary.start_node_id, primary.end_node_id
        resampled: list[list[tuple[float, float]]] = []
        saw_reverse = False
        saw_forward = False
        for e in group:
            pl = list(e.polyline)
            was_reverse = (e.start_node_id, e.end_node_id) != (canonical_start, canonical_end)
            if was_reverse:
                pl = list(reversed(pl))
                saw_reverse = True
            else:
                saw_forward = True
            # Carry through any prior bidirectional marker (from an earlier pass).
            prev_dir = e.attributes.get("direction_observed")
            if prev_dir == "bidirectional":
                saw_forward = True
                saw_reverse = True
            resampled.append(_resample_polyline_at_arclen(pl, resample_bins))

        avg = [
            (
                sum(pl[i][0] for pl in resampled) / len(resampled),
                sum(pl[i][1] for pl in resampled) / len(resampled),
            )
            for i in range(resample_bins)
        ]
        # Preserve the attributes of the first edge; note how many originals merged.
        attrs = dict(primary.attributes)
        attrs["merged_edge_count"] = len(group)
        attrs["direction_observed"] = (
            "bidirectional" if saw_forward and saw_reverse else "forward_only"
        )
        merged_removed += len(group) - 1
        kept.append(
            Edge(
                id=primary.id,  # renumbered below
                start_node_id=canonical_start,
                end_node_id=canonical_end,
                polyline=avg,
                attributes=attrs,
            )
        )

    if merged_removed == 0:
        return 0

    # Renumber sequentially.
    for i, e in enumerate(kept):
        e.id = f"e{i}"
    graph.edges = kept
    return merged_removed


def consolidate_clustered_junctions(
    graph: Graph, *, tolerance_m: float, resample_bins: int = 32
) -> int:
    """Unify ``multi_branch`` nodes that sit within ``tolerance_m`` of each other.

    After the split / endpoint-merge / duplicate-merge passes, a single real
    intersection can still be represented by two or three ``multi_branch``
    nodes a couple of meters apart — each anchored by a different polyline
    that entered the junction from a slightly different offset. This pass
    finds those small clusters via union-find on pairwise distance, collapses
    each cluster to a single node at the centroid, rewrites every incident
    edge, and re-runs :func:`merge_duplicate_edges` to fold any pair that now
    shares the same endpoint set.

    Returns the number of multi_branch nodes absorbed (cluster_size − 1 per
    cluster).
    """
    if tolerance_m <= 0:
        return 0
    mb_nodes = [n for n in graph.nodes if n.attributes.get("junction_hint") == "multi_branch"]
    if len(mb_nodes) < 2:
        return 0

    parent: dict[str, str] = {n.id: n.id for n in mb_nodes}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(mb_nodes)):
        a = mb_nodes[i]
        for j in range(i + 1, len(mb_nodes)):
            b = mb_nodes[j]
            dx = a.position[0] - b.position[0]
            dy = a.position[1] - b.position[1]
            if math.hypot(dx, dy) < tolerance_m:
                _union(a.id, b.id)

    # Group by cluster root.
    from collections import defaultdict

    clusters: dict[str, list[str]] = defaultdict(list)
    for nid in parent:
        clusters[_find(nid)].append(nid)
    absorbed = sum(len(m) - 1 for m in clusters.values() if len(m) > 1)
    if absorbed == 0:
        return 0

    # Pick canonical + centroid for each cluster with >1 members.
    id_to_node = {n.id: n for n in graph.nodes}
    canonical: dict[str, str] = {}
    new_positions: dict[str, tuple[float, float]] = {}
    for root, members in clusters.items():
        if len(members) == 1:
            continue
        canon = min(members)
        xs = [id_to_node[m].position[0] for m in members]
        ys = [id_to_node[m].position[1] for m in members]
        pos = (sum(xs) / len(xs), sum(ys) / len(ys))
        for m in members:
            canonical[m] = canon
        new_positions[canon] = pos

    if not canonical:
        return 0

    # Rebuild node list: drop absorbed members, update canonical positions.
    keep_nodes: list[Node] = []
    dropped_ids = {m for members in clusters.values() if len(members) > 1 for m in members if m != min(members)}
    for n in graph.nodes:
        if n.id in dropped_ids:
            continue
        if n.id in new_positions:
            keep_nodes.append(Node(id=n.id, position=new_positions[n.id], attributes=dict(n.attributes)))
        else:
            keep_nodes.append(n)

    # Rewrite edges.
    new_edges: list[Edge] = []
    for e in graph.edges:
        sn = canonical.get(e.start_node_id, e.start_node_id)
        en = canonical.get(e.end_node_id, e.end_node_id)
        new_edges.append(
            Edge(
                id=e.id,
                start_node_id=sn,
                end_node_id=en,
                polyline=list(e.polyline),
                attributes=dict(e.attributes),
            )
        )
    graph.nodes = keep_nodes
    graph.edges = new_edges

    # Fresh duplicate merge in case the cluster collapse produced new duplicates.
    merge_duplicate_edges(graph, resample_bins=resample_bins)
    return absorbed


def merge_near_parallel_edges(
    graph: Graph, *, tolerance_m: float, resample_bins: int = 32
) -> int:
    """Merge edges whose endpoint *pairs* are both within ``tolerance_m``.

    Duplicate-edge folding only catches pairs that already share the exact same
    two node ids. After the T / X split passes, many trajectories still produce
    pairs of edges whose endpoints land on **nearby but distinct** nodes —
    essentially the same road walked twice, but with each pass anchoring to a
    slightly different junction cluster.

    For every edge pair ``(a, b)`` where the sum of endpoint-to-endpoint
    distances is below ``2 * tolerance_m`` (trying both forward and reversed
    pairings), this function unifies the corresponding node ids via union-find,
    picks a single canonical id per cluster, collapses the Graph to one node
    per cluster at the centroid position, rewrites every edge to the canonical
    ids, and finally calls :func:`merge_duplicate_edges` to average what are
    now identical endpoint pairs.

    Returns the number of edges removed by the follow-up merge.
    """
    if tolerance_m <= 0 or len(graph.edges) < 2:
        return 0

    node_pos: dict[str, tuple[float, float]] = {n.id: tuple(n.position) for n in graph.nodes}

    parent: dict[str, str] = {nid: nid for nid in node_pos}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    def _dist(a: str, b: str) -> float:
        ax, ay = node_pos[a]
        bx, by = node_pos[b]
        return math.hypot(ax - bx, ay - by)

    edges = list(graph.edges)
    threshold_total = 2.0 * tolerance_m

    for i in range(len(edges)):
        ea = edges[i]
        for j in range(i + 1, len(edges)):
            eb = edges[j]
            # Already identical endpoint sets — handled by merge_duplicate_edges.
            same_pair = {ea.start_node_id, ea.end_node_id} == {eb.start_node_id, eb.end_node_id}
            if same_pair:
                continue
            fwd = _dist(ea.start_node_id, eb.start_node_id) + _dist(ea.end_node_id, eb.end_node_id)
            rev = _dist(ea.start_node_id, eb.end_node_id) + _dist(ea.end_node_id, eb.start_node_id)
            if min(fwd, rev) >= threshold_total:
                continue
            if fwd <= rev:
                _union(ea.start_node_id, eb.start_node_id)
                _union(ea.end_node_id, eb.end_node_id)
            else:
                _union(ea.start_node_id, eb.end_node_id)
                _union(ea.end_node_id, eb.start_node_id)

    # Group nodes by cluster root; skip clusters of size 1 (nothing to do).
    clusters: dict[str, list[str]] = {}
    for nid in node_pos:
        clusters.setdefault(_find(nid), []).append(nid)
    changed = any(len(members) > 1 for members in clusters.values())
    if not changed:
        return 0

    # Canonical id per cluster: smallest original id (stable). Position: centroid.
    canonical: dict[str, str] = {}
    new_positions: dict[str, tuple[float, float]] = {}
    for root, members in clusters.items():
        canon = min(members)
        xs = [node_pos[m][0] for m in members]
        ys = [node_pos[m][1] for m in members]
        pos = (sum(xs) / len(xs), sum(ys) / len(ys))
        for m in members:
            canonical[m] = canon
        new_positions[canon] = pos

    # Rewrite edges. Preserve existing Node.attributes for the canonical id.
    canon_attrs: dict[str, dict] = {}
    for n in graph.nodes:
        c = canonical[n.id]
        if c == n.id:
            canon_attrs[c] = dict(n.attributes)
    new_nodes = [
        Node(id=canon, position=new_positions[canon], attributes=canon_attrs.get(canon, {}))
        for canon in sorted(new_positions.keys())
    ]

    new_edges: list[Edge] = []
    for e in graph.edges:
        sn = canonical[e.start_node_id]
        en = canonical[e.end_node_id]
        new_edges.append(
            Edge(
                id=e.id,
                start_node_id=sn,
                end_node_id=en,
                polyline=list(e.polyline),
                attributes=dict(e.attributes),
            )
        )
    graph.nodes = new_nodes
    graph.edges = new_edges

    # After unification the previously near-parallel edges now share the same
    # endpoint set and can be averaged by merge_duplicate_edges.
    return merge_duplicate_edges(graph, resample_bins=resample_bins)


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

    # Detect X-junctions (two polylines crossing in space). Split both at the
    # intersection so endpoint union-find can fuse them into a shared junction.
    work = split_polylines_at_crossings(work)

    # Detect T-junctions: if one polyline's endpoint lands near another's
    # interior, split the second so the pair can be merged into a junction
    # node in the union-find below.
    work = split_polylines_at_t_junctions(work, params.merge_endpoint_m)

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
                    # Polyline is already time-ordered, so start → end matches
                    # the direction the trajectory traversed the segment.
                    "direction_observed": "forward_only",
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
    # Fuse multiple passes over the same (start, end) node pair — averaged
    # centerline instead of several parallel duplicates.
    merge_duplicate_edges(graph, resample_bins=params.centerline_bins)
    # Then catch near-parallel pairs whose endpoints are close-but-distinct,
    # by unifying their node ids and re-running the duplicate merge. Uses the
    # same endpoint-merge threshold as the initial union-find.
    merge_near_parallel_edges(
        graph,
        tolerance_m=params.merge_endpoint_m,
        resample_bins=params.centerline_bins,
    )
    # annotate_node_degrees needs to run before junction consolidation so we
    # know which nodes are multi_branch.
    annotate_node_degrees(graph)
    # Collapse small clusters of multi_branch nodes (same intersection split
    # across multiple anchor points). Use a slightly larger tolerance than the
    # endpoint-merge to catch junction-class drift the earlier passes missed.
    consolidate_clustered_junctions(
        graph,
        tolerance_m=1.75 * params.merge_endpoint_m,
        resample_bins=params.centerline_bins,
    )
    annotate_node_degrees(graph)
    annotate_junction_types(graph)
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
