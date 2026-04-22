"""Dijkstra shortest path across a :class:`Graph` using edge centerline lengths.

Edges are bidirectional at the geometry level — the graph this project produces
is a topology seed, not a lane-level directed network. The search is carried
out over directed states ``(node, incoming_edge_id, incoming_direction)`` so
optional ``turn_restrictions`` entries (same shape as the ``turn_restrictions``
array inside ``nav/sd_nav.json``) can forbid or whitelist specific transitions
at a junction.

Restriction semantics:

- ``no_left_turn`` / ``no_right_turn`` / ``no_straight`` / ``no_u_turn`` —
  the exact ``(junction, from_edge, from_direction, to_edge, to_direction)``
  tuple is forbidden.
- ``only_left`` / ``only_right`` / ``only_straight`` — at this junction,
  when arriving via ``(from_edge, from_direction)``, the only allowed
  outgoing ``(to_edge, to_direction)`` is the listed tuple. Everything else
  from the same approach is forbidden.

Omitting ``turn_restrictions`` (or passing ``None``) keeps the classic
undirected-shortest-path behaviour.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from roadgraph_builder.routing._core import (
    RoutingCostOptions,
    build_weighted_adjacency as _build_weighted_adjacency,
    get_routing_index as _get_routing_index,
    lane_count_for_edge as _lane_count_for_edge,
    parse_turn_policy as _parse_turn_policy,
)

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


@dataclass(frozen=True)
class Route:
    """Result of ``shortest_path``.

    Attributes:
        from_node: Starting node id.
        to_node: Destination node id.
        node_sequence: Node ids along the route (length ≥ 1; starts with
            ``from_node``, ends with ``to_node``).
        edge_sequence: Edge ids traversed in order (``len == len(node_sequence) - 1``).
        edge_directions: Direction each edge was traversed in (``forward`` follows
            digitization, ``reverse`` goes end → start). Same length as
            ``edge_sequence``.
        total_length_m: Sum of ``polyline`` arc lengths for the traversed edges.
        lane_sequence: Optional list of lane indices when ``allow_lane_change`` routing
            is used (A3). None when routing without lane-level detail.
    """

    from_node: str
    to_node: str
    node_sequence: list[str]
    edge_sequence: list[str]
    edge_directions: list[str]
    total_length_m: float
    lane_sequence: list[int | None] | None = None


def shortest_path(
    graph: "Graph",
    from_node: str,
    to_node: str,
    *,
    turn_restrictions: Iterable[dict] | None = None,
    # 0.6.0 optional cost hooks
    prefer_observed: bool = False,
    min_confidence: float | None = None,
    observed_bonus: float = 0.5,
    unobserved_penalty: float = 2.0,
    # 3D1 optional elevation cost hooks
    uphill_penalty: float | None = None,
    downhill_bonus: float | None = None,
    # A3 lane-change routing
    allow_lane_change: bool = False,
    lane_change_cost_m: float = 50.0,
) -> Route:
    """Return the shortest :class:`Route` between two node ids.

    With ``turn_restrictions`` supplied, the search respects both the forbid
    semantics of ``no_*`` entries and the whitelist semantics of ``only_*``
    entries at the specified junction / incoming approach.

    0.6.0 uncertainty-aware cost hooks:
    - ``prefer_observed=True``: multiply edge cost by ``observed_bonus`` when
      ``trace_observation_count > 0`` else by ``unobserved_penalty``.
    - ``min_confidence=X``: exclude edges whose ``hd_refinement.confidence < X``
      from the search (they are skipped during expansion).

    3D1 elevation cost hooks (both default to None = disabled):
    - ``uphill_penalty``: multiply cost of uphill edges by this factor
      (applied when ``slope_deg > 0``; ``>1.0`` discourages climbs).
    - ``downhill_bonus``: multiply cost of downhill edges by this factor
      (applied when ``slope_deg < 0``; ``<1.0`` favours descents).
      Factor is applied relative to the absolute slope magnitude; only active
      when the edge has elevation data.

    A3 lane-level routing:
    - ``allow_lane_change=True``: extend the state space to
      ``(node, incoming_edge, direction, lane_index)``. Transitions within the
      same edge (lane swap) cost ``lane_change_cost_m`` (default 50 m).
      The returned ``Route.lane_sequence`` carries the per-step lane index.
      Without this flag behaviour is identical to 0.6.0 / 3D1.

    When all hooks are None/False, behavior is identical to 0.5.0.

    Raises:
        KeyError: ``from_node`` or ``to_node`` is not in the graph.
        ValueError: No path exists under the supplied restrictions (or confidence filter).
    """
    index = _get_routing_index(graph)
    node_ids = index.node_ids
    if from_node not in node_ids:
        raise KeyError(f"from_node {from_node!r} is not in the graph")
    if to_node not in node_ids:
        raise KeyError(f"to_node {to_node!r} is not in the graph")

    if from_node == to_node:
        return Route(
            from_node=from_node,
            to_node=to_node,
            node_sequence=[from_node],
            edge_sequence=[],
            edge_directions=[],
            total_length_m=0.0,
        )

    cost_options = RoutingCostOptions(
        prefer_observed=prefer_observed,
        min_confidence=min_confidence,
        observed_bonus=observed_bonus,
        unobserved_penalty=unobserved_penalty,
        uphill_penalty=uphill_penalty,
        downhill_bonus=downhill_bonus,
    )
    adj = _build_weighted_adjacency(graph, index, cost_options)
    turn_policy = _parse_turn_policy(turn_restrictions)

    # -----------------------------------------------------------------------
    # A3: lane-level Dijkstra (allow_lane_change=True).
    # State = (node, incoming_edge_id or None, incoming_direction or None,
    #          lane_index or None).
    # Within the same edge, lane swaps are possible by adding lane_change_cost_m.
    # -----------------------------------------------------------------------
    if allow_lane_change:
        # Build per-edge lane count.
        edge_by_id = index.edge_by_id
        edge_lane_count: dict[str, int] = {e.id: _lane_count_for_edge(e) for e in graph.edges}

        # Lane state = (node, inc_edge, inc_dir, lane_idx).
        LState = tuple[str, str | None, str | None, int | None]
        l_start: LState = (from_node, None, None, None)
        l_dist: dict[LState, float] = {l_start: 0.0}
        l_prev: dict[LState, LState] = {}
        l_queue: list[tuple[float, str, str | None, str | None, int | None]] = [
            (0.0, from_node, None, None, None)
        ]
        best_l_state: LState | None = None
        best_cost = math.inf

        while l_queue:
            d, u, inc_edge, inc_dir, inc_lane = heapq.heappop(l_queue)
            l_state: LState = (u, inc_edge, inc_dir, inc_lane)
            if d > l_dist.get(l_state, math.inf):
                continue
            if u == to_node:
                best_l_state = l_state
                best_cost = d
                break

            # Expand cross-edge transitions (same as standard routing).
            for out_edge_id, out_dir, neighbor, w in adj.get(u, []):
                if not turn_policy.allows_transition(u, inc_edge, inc_dir, out_edge_id, out_dir):
                    continue
                out_lane_count = edge_lane_count.get(out_edge_id, 1)
                # Enter each lane of the outgoing edge.
                for out_lane in range(out_lane_count):
                    nd = d + w
                    # If incoming lane is defined and the outgoing edge has multiple
                    # lanes, add a lane-change cost for misaligned lanes.
                    if inc_lane is not None and out_lane_count > 1 and out_lane != inc_lane:
                        nd += lane_change_cost_m
                    new_l_state: LState = (neighbor, out_edge_id, out_dir, out_lane)
                    if nd < l_dist.get(new_l_state, math.inf):
                        l_dist[new_l_state] = nd
                        l_prev[new_l_state] = l_state
                        heapq.heappush(l_queue, (nd, neighbor, out_edge_id, out_dir, out_lane))

            # Expand intra-edge lane swaps: stay at the same node, same edge.
            if inc_edge is not None and inc_lane is not None:
                lc = edge_lane_count.get(inc_edge, 1)
                for swap_lane in range(lc):
                    if swap_lane == inc_lane:
                        continue
                    nd = d + lane_change_cost_m
                    swap_state: LState = (u, inc_edge, inc_dir, swap_lane)
                    if nd < l_dist.get(swap_state, math.inf):
                        l_dist[swap_state] = nd
                        l_prev[swap_state] = l_state
                        heapq.heappush(l_queue, (nd, u, inc_edge, inc_dir, swap_lane))

        if best_l_state is None or best_cost == math.inf:
            raise ValueError(f"no path from {from_node!r} to {to_node!r} (lane-level search)")

        # Reconstruct path.
        l_nodes: list[str] = [to_node]
        l_edges: list[str] = []
        l_dirs: list[str] = []
        l_lanes: list[int | None] = []
        l_cur = best_l_state
        while l_cur[1] is not None:
            l_edges.append(l_cur[1])
            l_dirs.append(l_cur[2])  # type: ignore[arg-type]
            l_lanes.append(l_cur[3])
            l_cur = l_prev[l_cur]
            l_nodes.append(l_cur[0])
        l_nodes.reverse()
        l_edges.reverse()
        l_dirs.reverse()
        l_lanes.reverse()

        actual_length = sum(index.base_lengths[eid] for eid in l_edges if eid in edge_by_id)
        return Route(
            from_node=from_node,
            to_node=to_node,
            node_sequence=l_nodes,
            edge_sequence=l_edges,
            edge_directions=l_dirs,
            total_length_m=actual_length,
            lane_sequence=l_lanes,
        )

    # -----------------------------------------------------------------------
    # Standard edge-level Dijkstra (allow_lane_change=False, default).
    # State = (node, incoming_edge_id or None, incoming_direction or None).
    # -----------------------------------------------------------------------

    if turn_policy.is_empty:
        node_dist: dict[str, float] = {from_node: 0.0}
        node_prev: dict[str, tuple[str, str, str]] = {}
        node_queue: list[tuple[float, str]] = [(0.0, from_node)]

        while node_queue:
            d, u = heapq.heappop(node_queue)
            if d > node_dist.get(u, math.inf):
                continue
            if u == to_node:
                break

            for out_edge_id, out_dir, neighbor, w in adj.get(u, []):
                nd = d + w
                if nd < node_dist.get(neighbor, math.inf):
                    node_dist[neighbor] = nd
                    node_prev[neighbor] = (u, out_edge_id, out_dir)
                    heapq.heappush(node_queue, (nd, neighbor))

        if to_node not in node_dist:
            if min_confidence is not None:
                raise ValueError(
                    f"no path from {from_node!r} to {to_node!r} "
                    f"(some edges may be excluded by --min-confidence {min_confidence})"
                )
            raise ValueError(f"no path from {from_node!r} to {to_node!r}")

        nodes: list[str] = [to_node]
        edges: list[str] = []
        dirs: list[str] = []
        cur_node = to_node
        while cur_node != from_node:
            prev_node, edge_id, edge_dir = node_prev[cur_node]
            edges.append(edge_id)
            dirs.append(edge_dir)
            cur_node = prev_node
            nodes.append(cur_node)
        nodes.reverse()
        edges.reverse()
        dirs.reverse()

        edge_by_id = index.edge_by_id
        actual_length = sum(index.base_lengths[eid] for eid in edges if eid in edge_by_id)
        return Route(
            from_node=from_node,
            to_node=to_node,
            node_sequence=nodes,
            edge_sequence=edges,
            edge_directions=dirs,
            total_length_m=actual_length,
        )

    # State = (node, incoming_edge_id or None, incoming_direction or None).
    State = tuple[str, str | None, str | None]
    start: State = (from_node, None, None)
    dist: dict[State, float] = {start: 0.0}
    prev: dict[State, State] = {}
    queue: list[tuple[float, str, str | None, str | None]] = [(0.0, from_node, None, None)]
    best_state: State | None = None
    best_cost = math.inf

    while queue:
        d, u, inc_edge, inc_dir = heapq.heappop(queue)
        state: State = (u, inc_edge, inc_dir)
        if d > dist.get(state, math.inf):
            continue
        if u == to_node:
            best_state = state
            best_cost = d
            break

        for out_edge_id, out_dir, neighbor, w in adj.get(u, []):
            if not turn_policy.allows_transition(u, inc_edge, inc_dir, out_edge_id, out_dir):
                continue
            nd = d + w
            new_state: State = (neighbor, out_edge_id, out_dir)
            if nd < dist.get(new_state, math.inf):
                dist[new_state] = nd
                prev[new_state] = state
                heapq.heappush(queue, (nd, neighbor, out_edge_id, out_dir))

    if best_state is None or best_cost == math.inf:
        if min_confidence is not None:
            raise ValueError(
                f"no path from {from_node!r} to {to_node!r} "
                f"(some edges may be excluded by --min-confidence {min_confidence})"
            )
        raise ValueError(f"no path from {from_node!r} to {to_node!r}")

    nodes: list[str] = [to_node]
    edges: list[str] = []
    dirs: list[str] = []
    cur = best_state
    while cur[1] is not None:
        edges.append(cur[1])
        dirs.append(cur[2])  # type: ignore[arg-type]
        cur = prev[cur]
        nodes.append(cur[0])
    nodes.reverse()
    edges.reverse()
    dirs.reverse()

    # total_length_m: when cost hooks are active, the Dijkstra dist is weighted
    # (not the true arc length). Reconstruct the actual arc length from the
    # chosen edge sequence so the returned value is always in real meters.
    edge_by_id = index.edge_by_id
    actual_length = sum(index.base_lengths[eid] for eid in edges if eid in edge_by_id)

    return Route(
        from_node=from_node,
        to_node=to_node,
        node_sequence=nodes,
        edge_sequence=edges,
        edge_directions=dirs,
        total_length_m=actual_length,
    )
