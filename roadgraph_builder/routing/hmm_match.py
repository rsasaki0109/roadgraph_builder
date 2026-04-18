"""HMM (Viterbi) map matching over the graph's edges.

``snap_trajectory_to_graph`` picks the nearest edge per sample independently,
which aliases between parallel streets when lanes run close together. This
module runs a Viterbi decoder over ``(sample, candidate_edge)`` states so the
decoded sequence prefers edges that are (a) close to the sample and (b)
reachable from the previous sample's matched edge with a short graph walk.

State: at sample ``i``, the candidate set is every edge within
``candidate_radius_m`` of the sample. Each candidate carries an **emission
penalty** proportional to its projection distance (Gaussian on the GPS error).
The **transition penalty** between consecutive candidates is the absolute
difference between (a) the ``(i, i+1)`` Euclidean distance and (b) the
shortest-path distance between the candidate projections, measured in graph
meters. Candidates on the same edge pay zero transition.

Heavier than ``snap_trajectory_to_graph`` but still O(N · K²) with
``K = candidate_count``; OK for SD-scale graphs / demos.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.edge import Edge
    from roadgraph_builder.core.graph.graph import Graph


@dataclass(frozen=True)
class HmmMatch:
    """One sample's Viterbi pick."""

    index: int
    edge_id: str
    projection_xy_m: tuple[float, float]
    distance_m: float


def _project_point_on_polyline(
    px: float, py: float, poly
) -> tuple[float, tuple[float, float]]:
    best_d = float("inf")
    best_pt = (0.0, 0.0)
    for i in range(len(poly) - 1):
        ax, ay = poly[i]
        bx, by = poly[i + 1]
        abx, aby = bx - ax, by - ay
        ab2 = abx * abx + aby * aby
        if ab2 < 1e-18:
            qx, qy = ax, ay
        else:
            t = ((px - ax) * abx + (py - ay) * aby) / ab2
            t = max(0.0, min(1.0, t))
            qx = ax + t * abx
            qy = ay + t * aby
        d = math.hypot(px - qx, py - qy)
        if d < best_d:
            best_d = d
            best_pt = (qx, qy)
    return best_d, best_pt


def _node_distances(graph: "Graph", start_node: str, limit: float) -> dict[str, float]:
    """Dijkstra from ``start_node`` on undirected edges, stopping at ``limit``."""
    adj: dict[str, list[tuple[str, float]]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        L = 0.0
        pl = e.polyline
        for i in range(len(pl) - 1):
            L += math.hypot(pl[i + 1][0] - pl[i][0], pl[i + 1][1] - pl[i][1])
        adj[e.start_node_id].append((e.end_node_id, L))
        if e.start_node_id != e.end_node_id:
            adj[e.end_node_id].append((e.start_node_id, L))
    dist = {start_node: 0.0}
    heap = [(0.0, start_node)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > limit:
            continue
        if d > dist.get(u, math.inf):
            continue
        for v, w in adj.get(u, []):
            nd = d + w
            if nd <= limit and nd < dist.get(v, math.inf):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist


def hmm_match_trajectory(
    graph: "Graph",
    traj_xy,
    *,
    candidate_radius_m: float = 20.0,
    gps_sigma_m: float = 5.0,
    transition_limit_m: float = 200.0,
) -> list[HmmMatch | None]:
    """Viterbi-decode a trajectory onto ``graph`` edges.

    Args:
        graph: Target road graph.
        traj_xy: Iterable of ``(x, y)`` tuples in the graph's meter frame.
        candidate_radius_m: Maximum perpendicular distance for an edge to be
            considered at a sample.
        gps_sigma_m: Standard deviation used for the Gaussian emission penalty
            (`distance / sigma` squared scaled). Tighter values prefer the
            nearest edge; looser values let the transition prior pull.
        transition_limit_m: Cap on Dijkstra expansion used for transition
            penalties. Candidates more than this apart get an infinite penalty
            and will never link in a single hop.
    """
    xy = list(traj_xy) if not hasattr(traj_xy, "shape") else [tuple(row) for row in traj_xy]
    edges = list(graph.edges)
    if not edges or not xy:
        return [None] * len(xy)

    # Per-edge endpoint index.
    edge_by_id = {e.id: e for e in edges}

    # Per-sample candidate list: [(edge_id, distance, projection_xy)].
    candidates: list[list[tuple[str, float, tuple[float, float]]]] = []
    for px, py in xy:
        cand: list[tuple[str, float, tuple[float, float]]] = []
        for e in edges:
            d, proj = _project_point_on_polyline(float(px), float(py), e.polyline)
            if d < candidate_radius_m:
                cand.append((e.id, d, proj))
        cand.sort(key=lambda c: c[1])
        # Keep top-k to bound cost.
        if len(cand) > 5:
            cand = cand[:5]
        candidates.append(cand)

    # Viterbi (min-cost). State score = emission + best transition from prev.
    n = len(xy)
    scores: list[list[float]] = [[] for _ in range(n)]
    back: list[list[int]] = [[] for _ in range(n)]

    def emission_cost(distance: float) -> float:
        return 0.5 * (distance / gps_sigma_m) ** 2

    # Initial sample: emission only; no candidate → unmatched.
    if not candidates[0]:
        return [None] * n
    scores[0] = [emission_cost(d) for _eid, d, _p in candidates[0]]
    back[0] = [-1] * len(candidates[0])

    # Cache node-distance Dijkstra by start_node_id of the candidate edge to
    # amortise across all candidates at the next sample.
    dist_cache: dict[str, dict[str, float]] = {}

    def node_dists(node: str) -> dict[str, float]:
        if node not in dist_cache:
            dist_cache[node] = _node_distances(graph, node, transition_limit_m)
        return dist_cache[node]

    for t in range(1, n):
        prev_cands = candidates[t - 1]
        cur_cands = candidates[t]
        if not cur_cands:
            scores[t] = []
            back[t] = []
            continue
        if not prev_cands:
            # Restart: independent emission.
            scores[t] = [emission_cost(d) for _eid, d, _p in cur_cands]
            back[t] = [-1] * len(cur_cands)
            continue

        dx = float(xy[t][0] - xy[t - 1][0])
        dy = float(xy[t][1] - xy[t - 1][1])
        step_gps = math.hypot(dx, dy)

        sc_t: list[float] = []
        bk_t: list[int] = []
        for ci, (cur_edge_id, cur_d, cur_proj) in enumerate(cur_cands):
            cur_edge = edge_by_id[cur_edge_id]
            best_total = math.inf
            best_prev = -1
            for pi, (prev_edge_id, prev_d, prev_proj) in enumerate(prev_cands):
                if scores[t - 1][pi] == math.inf:
                    continue
                if prev_edge_id == cur_edge_id:
                    # Same edge → graph distance is along-edge chord approximated by projection.
                    graph_dist = math.hypot(
                        cur_proj[0] - prev_proj[0], cur_proj[1] - prev_proj[1]
                    )
                else:
                    # Use the best of (prev_start, prev_end) → (cur_start, cur_end)
                    prev_edge = edge_by_id[prev_edge_id]
                    best_link = math.inf
                    for pnode in (prev_edge.start_node_id, prev_edge.end_node_id):
                        dists = node_dists(pnode)
                        for cnode in (cur_edge.start_node_id, cur_edge.end_node_id):
                            if cnode in dists:
                                # Approximate: prev_proj → pnode along prev_edge,
                                # plus graph-to-graph, plus cnode → cur_proj along cur_edge.
                                # We do not re-compute the along-edge tail distances
                                # (cheap approximation; tuning knob if needed).
                                best_link = min(best_link, dists[cnode])
                    graph_dist = best_link
                if not math.isfinite(graph_dist):
                    continue
                trans = abs(step_gps - graph_dist)
                total = scores[t - 1][pi] + trans + emission_cost(cur_d)
                if total < best_total:
                    best_total = total
                    best_prev = pi
            sc_t.append(best_total if best_total < math.inf else math.inf)
            bk_t.append(best_prev)
        scores[t] = sc_t
        back[t] = bk_t

    # Backtrack from the last sample with any finite score.
    result: list[HmmMatch | None] = [None] * n
    if not scores[-1] or all(math.isinf(s) for s in scores[-1]):
        # Try fallback: pick best per-sample by emission alone.
        for i in range(n):
            cand = candidates[i]
            if cand:
                eid, d, proj = cand[0]
                result[i] = HmmMatch(index=i, edge_id=eid, projection_xy_m=proj, distance_m=d)
        return result

    cur_idx = int(min(range(len(scores[-1])), key=lambda k: scores[-1][k]))
    for i in range(n - 1, -1, -1):
        if cur_idx < 0 or cur_idx >= len(candidates[i]):
            result[i] = None
            if i > 0:
                # Find a fallback for the previous sample.
                cur_idx = int(min(range(len(scores[i - 1])), key=lambda k: scores[i - 1][k])) if scores[i - 1] else -1
            continue
        eid, d, proj = candidates[i][cur_idx]
        result[i] = HmmMatch(index=i, edge_id=eid, projection_xy_m=proj, distance_m=d)
        cur_idx = back[i][cur_idx] if back[i] else -1
    return result


__all__ = ["HmmMatch", "hmm_match_trajectory"]
