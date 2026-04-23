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
meters. Candidates on the same edge use along-edge projection distance.

Heavier than ``snap_trajectory_to_graph`` but still O(N · K²) with
``K = candidate_count`` after a spatial-index candidate lookup.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from roadgraph_builder.routing._core import DirectedAdjacency, get_routing_index
from roadgraph_builder.routing.edge_index import get_edge_projection_index

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


@dataclass(frozen=True)
class HmmMatch:
    """One sample's Viterbi pick."""

    index: int
    edge_id: str
    projection_xy_m: tuple[float, float]
    distance_m: float


@dataclass(frozen=True)
class _Candidate:
    edge_id: str
    distance_m: float
    projection_xy_m: tuple[float, float]
    arc_length_m: float
    edge_length_m: float


def _node_distances(
    adj: DirectedAdjacency,
    start_node: str,
    limit: float,
) -> dict[str, float]:
    """Dijkstra from ``start_node`` over cached base adjacency, stopping at ``limit``."""

    dist = {start_node: 0.0}
    heap = [(0.0, start_node)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > limit:
            continue
        if d > dist.get(u, math.inf):
            continue
        for _, _, v, w in adj.get(u, []):
            nd = d + w
            if nd <= limit and nd < dist.get(v, math.inf):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist


def _endpoint_tail_costs(edge, candidate: _Candidate) -> dict[str, float]:  # type: ignore[no-untyped-def]
    """Distance from a candidate projection to each endpoint along its edge."""

    to_start = max(candidate.arc_length_m, 0.0)
    to_end = max(candidate.edge_length_m - candidate.arc_length_m, 0.0)
    if edge.start_node_id == edge.end_node_id:
        return {edge.start_node_id: min(to_start, to_end)}
    return {
        edge.start_node_id: to_start,
        edge.end_node_id: to_end,
    }


def _transition_graph_distance(
    prev: _Candidate,
    cur: _Candidate,
    *,
    edge_by_id: dict[str, object],
    node_dists,
    transition_limit_m: float,
) -> float:
    """Shortest graph distance between two candidate projections."""

    if prev.edge_id == cur.edge_id:
        graph_dist = abs(cur.arc_length_m - prev.arc_length_m)
        return graph_dist if graph_dist <= transition_limit_m else math.inf

    prev_edge = edge_by_id[prev.edge_id]
    cur_edge = edge_by_id[cur.edge_id]
    prev_tails = _endpoint_tail_costs(prev_edge, prev)
    cur_tails = _endpoint_tail_costs(cur_edge, cur)
    best_link = math.inf
    for pnode, prev_tail in prev_tails.items():
        dists = node_dists(pnode)
        for cnode, cur_tail in cur_tails.items():
            if cnode in dists:
                total = prev_tail + dists[cnode] + cur_tail
                if total < best_link:
                    best_link = total
    return best_link if best_link <= transition_limit_m else math.inf


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
    edge_by_id = {str(e.id): e for e in edges}

    edge_index = get_edge_projection_index(graph)

    candidates: list[list[_Candidate]] = []
    for px, py in xy:
        cand = [
            _Candidate(
                edge_id=projection.edge_id,
                distance_m=projection.distance_m,
                projection_xy_m=projection.projection_xy_m,
                arc_length_m=projection.arc_length_m,
                edge_length_m=projection.edge_length_m,
            )
            for projection in edge_index.candidate_projections(
                float(px),
                float(py),
                candidate_radius_m,
                limit=5,
            )
        ]
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
    scores[0] = [emission_cost(c.distance_m) for c in candidates[0]]
    back[0] = [-1] * len(candidates[0])

    # Cache node-distance Dijkstra by start_node_id of the candidate edge to
    # amortise across all candidates at the next sample.
    dist_cache: dict[str, dict[str, float]] = {}
    base_adj: DirectedAdjacency | None = None

    def node_dists(node: str) -> dict[str, float]:
        nonlocal base_adj
        if node not in dist_cache:
            if base_adj is None:
                base_adj = get_routing_index(graph).base_adj
            dist_cache[node] = _node_distances(base_adj, node, transition_limit_m)
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
            scores[t] = [emission_cost(c.distance_m) for c in cur_cands]
            back[t] = [-1] * len(cur_cands)
            continue

        dx = float(xy[t][0] - xy[t - 1][0])
        dy = float(xy[t][1] - xy[t - 1][1])
        step_gps = math.hypot(dx, dy)

        sc_t: list[float] = []
        bk_t: list[int] = []
        for cur_cand in cur_cands:
            best_total = math.inf
            best_prev = -1
            for pi, prev_cand in enumerate(prev_cands):
                if scores[t - 1][pi] == math.inf:
                    continue
                graph_dist = _transition_graph_distance(
                    prev_cand,
                    cur_cand,
                    edge_by_id=edge_by_id,
                    node_dists=node_dists,
                    transition_limit_m=transition_limit_m,
                )
                if not math.isfinite(graph_dist):
                    continue
                trans = abs(step_gps - graph_dist)
                total = scores[t - 1][pi] + trans + emission_cost(cur_cand.distance_m)
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
                c = cand[0]
                result[i] = HmmMatch(
                    index=i,
                    edge_id=c.edge_id,
                    projection_xy_m=c.projection_xy_m,
                    distance_m=c.distance_m,
                )
        return result

    cur_idx = int(min(range(len(scores[-1])), key=lambda k: scores[-1][k]))
    for i in range(n - 1, -1, -1):
        if cur_idx < 0 or cur_idx >= len(candidates[i]):
            result[i] = None
            if i > 0:
                # Find a fallback for the previous sample.
                cur_idx = int(min(range(len(scores[i - 1])), key=lambda k: scores[i - 1][k])) if scores[i - 1] else -1
            continue
        c = candidates[i][cur_idx]
        result[i] = HmmMatch(
            index=i,
            edge_id=c.edge_id,
            projection_xy_m=c.projection_xy_m,
            distance_m=c.distance_m,
        )
        cur_idx = back[i][cur_idx] if back[i] else -1
    return result


__all__ = ["HmmMatch", "hmm_match_trajectory"]
