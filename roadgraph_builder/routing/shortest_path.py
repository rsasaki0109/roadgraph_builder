"""Shortest path across a :class:`Graph` using edge centerline lengths.

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

Route searches use an A* priority when straight-line node distance is a safe
lower bound for the configured edge costs, and otherwise fall back to Dijkstra
by using a zero heuristic. Omitting ``turn_restrictions`` (or passing ``None``)
keeps the classic undirected-shortest-path behaviour.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable

from roadgraph_builder.routing._core import (
    DirectedAdjacency,
    RoutingCostOptions,
    RoutingIndex,
    TurnPolicy,
    build_weighted_adjacency as _build_weighted_adjacency,
    edge_cache_signature as _edge_cache_signature,
    get_routing_index as _get_routing_index,
    lane_count_for_edge as _lane_count_for_edge,
    parse_turn_policy as _parse_turn_policy,
    routing_signature as _routing_signature,
)

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


_DEFAULT_PLANNER_EXACT_NODE_LIMIT = 512
_DEFAULT_PLANNER_EXACT_EDGE_LIMIT = 1024
_DEFAULT_PLANNER_SAMPLE_COUNT = 96


def _zero_heuristic(_: str) -> float:
    return 0.0


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


@dataclass(frozen=True)
class RouteDiagnostics:
    """Search metadata captured for the most recent ``RoutePlanner`` query."""

    search_engine: str
    heuristic_enabled: bool
    fallback_reason: str | None
    expanded_states: int
    queued_states: int
    route_edge_count: int
    total_length_m: float

    def to_dict(self) -> dict[str, object]:
        return {
            "search_engine": self.search_engine,
            "heuristic_enabled": self.heuristic_enabled,
            "fallback_reason": self.fallback_reason,
            "expanded_states": self.expanded_states,
            "queued_states": self.queued_states,
            "route_edge_count": self.route_edge_count,
            "total_length_m": self.total_length_m,
        }


class RoutePlanner:
    """Prepared shortest-path planner for repeated queries on one graph.

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

    The planner captures the graph topology and weighted adjacency at
    construction time. Create a new planner after mutating graph nodes, edges,
    edge geometry, or routing-relevant attributes.
    """

    def __init__(
        self,
        graph: "Graph",
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
    ) -> None:
        self.graph = graph
        self.index: RoutingIndex = _get_routing_index(graph)
        self.min_confidence = min_confidence
        self.allow_lane_change = allow_lane_change
        self.lane_change_cost_m = lane_change_cost_m
        self.last_diagnostics: RouteDiagnostics | None = None

        cost_options = RoutingCostOptions(
            prefer_observed=prefer_observed,
            min_confidence=min_confidence,
            observed_bonus=observed_bonus,
            unobserved_penalty=unobserved_penalty,
            uphill_penalty=uphill_penalty,
            downhill_bonus=downhill_bonus,
        )
        self.adj: DirectedAdjacency = _build_weighted_adjacency(graph, self.index, cost_options)
        self.turn_policy: TurnPolicy = _parse_turn_policy(turn_restrictions)
        self._heuristic_fallback_reason = self._straight_line_heuristic_fallback_reason(
            cost_options
        )
        self._use_straight_line_heuristic = self._heuristic_fallback_reason is None
        self.edge_lane_count: dict[str, int] = (
            {edge.id: _lane_count_for_edge(edge) for edge in graph.edges}
            if allow_lane_change
            else {}
        )

    def shortest_path(self, from_node: str, to_node: str) -> Route:
        """Return the shortest :class:`Route` between two node ids.

        Raises:
            KeyError: ``from_node`` or ``to_node`` is not in the graph.
            ValueError: No path exists under the supplied restrictions (or confidence filter).
        """
        self._validate_endpoints(from_node, to_node)
        if from_node == to_node:
            return self._empty_route(from_node, to_node)

        if self.allow_lane_change:
            return self._shortest_path_lane_level(from_node, to_node)
        if self.turn_policy.is_empty:
            return self._shortest_path_unrestricted(from_node, to_node)
        return self._shortest_path_restricted(from_node, to_node)

    def _validate_endpoints(self, from_node: str, to_node: str) -> None:
        node_ids = self.index.node_ids
        if from_node not in node_ids:
            raise KeyError(f"from_node {from_node!r} is not in the graph")
        if to_node not in node_ids:
            raise KeyError(f"to_node {to_node!r} is not in the graph")

    def _empty_route(self, from_node: str, to_node: str) -> Route:
        route = Route(
            from_node=from_node,
            to_node=to_node,
            node_sequence=[from_node],
            edge_sequence=[],
            edge_directions=[],
            total_length_m=0.0,
        )
        self._record_diagnostics(
            expanded_states=0,
            queued_states=0,
            route=route,
            fallback_reason="trivial_route",
            search_engine="trivial",
        )
        return route

    def _actual_length(self, edge_ids: Iterable[str]) -> float:
        edge_by_id = self.index.edge_by_id
        return sum(self.index.base_lengths[eid] for eid in edge_ids if eid in edge_by_id)

    def _node_distance(self, from_node: str, to_node: str) -> float:
        from_xy = self.index.node_positions.get(from_node)
        to_xy = self.index.node_positions.get(to_node)
        if from_xy is None or to_xy is None:
            return math.inf
        return math.hypot(to_xy[0] - from_xy[0], to_xy[1] - from_xy[1])

    def _heuristic(self, node_id: str, to_node: str) -> float:
        if not self._use_straight_line_heuristic:
            return 0.0
        return self._node_distance(node_id, to_node)

    def _straight_line_heuristic_fallback_reason(
        self,
        cost_options: RoutingCostOptions,
    ) -> str | None:
        if self.allow_lane_change:
            return "lane_level"
        if not cost_options.preserves_base_metric_lower_bound:
            return "cost_discount"
        return self._node_distance_lower_bound_violation_reason()

    def _node_distance_lower_bound_violation_reason(self) -> str | None:
        for from_node, steps in self.adj.items():
            for _, _, to_node, cost_m in steps:
                distance = self._node_distance(from_node, to_node)
                if math.isinf(distance):
                    return "dangling_node"
                if cost_m + 1e-9 < distance:
                    return "non_metric_geometry"
        return None

    def _record_diagnostics(
        self,
        *,
        expanded_states: int,
        queued_states: int,
        route: Route,
        fallback_reason: str | None = None,
        search_engine: str | None = None,
    ) -> None:
        reason = self._heuristic_fallback_reason if fallback_reason is None else fallback_reason
        engine = search_engine or ("astar" if self._use_straight_line_heuristic else "dijkstra")
        self.last_diagnostics = RouteDiagnostics(
            search_engine=engine,
            heuristic_enabled=self._use_straight_line_heuristic,
            fallback_reason=reason,
            expanded_states=expanded_states,
            queued_states=queued_states,
            route_edge_count=len(route.edge_sequence),
            total_length_m=route.total_length_m,
        )

    def _heuristic_for_target(self, to_node: str) -> Callable[[str], float]:
        if not self._use_straight_line_heuristic:
            return _zero_heuristic

        positions = self.index.node_positions
        to_xy = positions[to_node]
        cache: dict[str, float] = {to_node: 0.0}
        hypot = math.hypot

        def heuristic(node_id: str) -> float:
            if node_id in cache:
                return cache[node_id]
            xy = positions.get(node_id)
            if xy is None:
                return 0.0
            distance = hypot(to_xy[0] - xy[0], to_xy[1] - xy[1])
            cache[node_id] = distance
            return distance

        return heuristic

    def _no_path_error(self, from_node: str, to_node: str) -> ValueError:
        if self.min_confidence is not None:
            return ValueError(
                f"no path from {from_node!r} to {to_node!r} "
                f"(some edges may be excluded by --min-confidence {self.min_confidence})"
            )
        return ValueError(f"no path from {from_node!r} to {to_node!r}")

    def _shortest_path_lane_level(self, from_node: str, to_node: str) -> Route:
        # State = (node, incoming_edge_id or None, incoming_direction or None,
        #          lane_index or None).
        LState = tuple[str, str | None, str | None, int | None]
        l_start: LState = (from_node, None, None, None)
        l_dist: dict[LState, float] = {l_start: 0.0}
        l_prev: dict[LState, LState] = {}
        l_queue: list[tuple[float, str, str | None, str | None, int | None]] = [
            (0.0, from_node, None, None, None)
        ]
        expanded_states = 0
        queued_states = 1
        best_l_state: LState | None = None
        best_cost = math.inf

        while l_queue:
            d, u, inc_edge, inc_dir, inc_lane = heapq.heappop(l_queue)
            l_state: LState = (u, inc_edge, inc_dir, inc_lane)
            if d > l_dist.get(l_state, math.inf):
                continue
            expanded_states += 1
            if u == to_node:
                best_l_state = l_state
                best_cost = d
                break

            # Expand cross-edge transitions (same as standard routing).
            for out_edge_id, out_dir, neighbor, w in self.adj.get(u, []):
                if not self.turn_policy.allows_transition(u, inc_edge, inc_dir, out_edge_id, out_dir):
                    continue
                out_lane_count = self.edge_lane_count.get(out_edge_id, 1)
                # Enter each lane of the outgoing edge.
                for out_lane in range(out_lane_count):
                    nd = d + w
                    # If incoming lane is defined and the outgoing edge has multiple
                    # lanes, add a lane-change cost for misaligned lanes.
                    if inc_lane is not None and out_lane_count > 1 and out_lane != inc_lane:
                        nd += self.lane_change_cost_m
                    new_l_state: LState = (neighbor, out_edge_id, out_dir, out_lane)
                    if nd < l_dist.get(new_l_state, math.inf):
                        l_dist[new_l_state] = nd
                        l_prev[new_l_state] = l_state
                        heapq.heappush(l_queue, (nd, neighbor, out_edge_id, out_dir, out_lane))
                        queued_states += 1

            # Expand intra-edge lane swaps: stay at the same node, same edge.
            if inc_edge is not None and inc_lane is not None:
                lc = self.edge_lane_count.get(inc_edge, 1)
                for swap_lane in range(lc):
                    if swap_lane == inc_lane:
                        continue
                    nd = d + self.lane_change_cost_m
                    swap_state: LState = (u, inc_edge, inc_dir, swap_lane)
                    if nd < l_dist.get(swap_state, math.inf):
                        l_dist[swap_state] = nd
                        l_prev[swap_state] = l_state
                        heapq.heappush(l_queue, (nd, u, inc_edge, inc_dir, swap_lane))
                        queued_states += 1

        if best_l_state is None or best_cost == math.inf:
            raise ValueError(f"no path from {from_node!r} to {to_node!r} (lane-level search)")

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

        route = Route(
            from_node=from_node,
            to_node=to_node,
            node_sequence=l_nodes,
            edge_sequence=l_edges,
            edge_directions=l_dirs,
            total_length_m=self._actual_length(l_edges),
            lane_sequence=l_lanes,
        )
        self._record_diagnostics(
            expanded_states=expanded_states,
            queued_states=queued_states,
            route=route,
        )
        return route

    def _shortest_path_unrestricted(self, from_node: str, to_node: str) -> Route:
        heuristic = self._heuristic_for_target(to_node)
        start_h = heuristic(from_node)
        node_dist: dict[str, float] = {from_node: 0.0}
        node_prev: dict[str, tuple[str, str, str]] = {}
        node_queue: list[tuple[float, float, float, str]] = [
            (start_h, start_h, 0.0, from_node)
        ]
        expanded_states = 0
        queued_states = 1

        while node_queue:
            _, _, d, u = heapq.heappop(node_queue)
            if d > node_dist.get(u, math.inf):
                continue
            expanded_states += 1
            if u == to_node:
                break

            for out_edge_id, out_dir, neighbor, w in self.adj.get(u, []):
                nd = d + w
                if nd < node_dist.get(neighbor, math.inf):
                    node_dist[neighbor] = nd
                    node_prev[neighbor] = (u, out_edge_id, out_dir)
                    h = heuristic(neighbor)
                    heapq.heappush(node_queue, (nd + h, h, nd, neighbor))
                    queued_states += 1

        if to_node not in node_dist:
            raise self._no_path_error(from_node, to_node)

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

        route = Route(
            from_node=from_node,
            to_node=to_node,
            node_sequence=nodes,
            edge_sequence=edges,
            edge_directions=dirs,
            total_length_m=self._actual_length(edges),
        )
        self._record_diagnostics(
            expanded_states=expanded_states,
            queued_states=queued_states,
            route=route,
        )
        return route

    def _shortest_path_restricted(self, from_node: str, to_node: str) -> Route:
        heuristic = self._heuristic_for_target(to_node)
        start_h = heuristic(from_node)
        # State = (node, incoming_edge_id or None, incoming_direction or None).
        State = tuple[str, str | None, str | None]
        start: State = (from_node, None, None)
        dist: dict[State, float] = {start: 0.0}
        prev: dict[State, State] = {}
        queue: list[tuple[float, float, float, str, str | None, str | None]] = [
            (start_h, start_h, 0.0, from_node, None, None)
        ]
        expanded_states = 0
        queued_states = 1
        best_state: State | None = None
        best_cost = math.inf

        while queue:
            _, _, d, u, inc_edge, inc_dir = heapq.heappop(queue)
            state: State = (u, inc_edge, inc_dir)
            if d > dist.get(state, math.inf):
                continue
            expanded_states += 1
            if u == to_node:
                best_state = state
                best_cost = d
                break

            for out_edge_id, out_dir, neighbor, w in self.adj.get(u, []):
                if not self.turn_policy.allows_transition(u, inc_edge, inc_dir, out_edge_id, out_dir):
                    continue
                nd = d + w
                new_state: State = (neighbor, out_edge_id, out_dir)
                if nd < dist.get(new_state, math.inf):
                    dist[new_state] = nd
                    prev[new_state] = state
                    h = heuristic(neighbor)
                    heapq.heappush(queue, (nd + h, h, nd, neighbor, out_edge_id, out_dir))
                    queued_states += 1

        if best_state is None or best_cost == math.inf:
            raise self._no_path_error(from_node, to_node)

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

        route = Route(
            from_node=from_node,
            to_node=to_node,
            node_sequence=nodes,
            edge_sequence=edges,
            edge_directions=dirs,
            total_length_m=self._actual_length(edges),
        )
        self._record_diagnostics(
            expanded_states=expanded_states,
            queued_states=queued_states,
            route=route,
        )
        return route


def _can_use_default_planner_cache(
    *,
    turn_restrictions: Iterable[dict] | None,
    prefer_observed: bool,
    min_confidence: float | None,
    observed_bonus: float,
    unobserved_penalty: float,
    uphill_penalty: float | None,
    downhill_bonus: float | None,
    allow_lane_change: bool,
    lane_change_cost_m: float,
) -> bool:
    """Return True when ``shortest_path`` can safely reuse a graph-local planner."""

    return (
        turn_restrictions is None
        and not prefer_observed
        and min_confidence is None
        and observed_bonus == 0.5
        and unobserved_penalty == 2.0
        and uphill_penalty is None
        and downhill_bonus is None
        and not allow_lane_change
        and lane_change_cost_m == 50.0
    )


def _sample_indices(length: int, max_count: int = _DEFAULT_PLANNER_SAMPLE_COUNT) -> tuple[int, ...]:
    if length <= max_count:
        return tuple(range(length))
    last = length - 1
    return tuple(sorted({round(i * last / (max_count - 1)) for i in range(max_count)}))


def _sampled_default_planner_signature(graph: "Graph") -> tuple[object, ...]:
    """Return a lightweight validation signature for default wrapper caching.

    Small graphs keep the exact routing signature. Large graphs use stable
    samples to avoid making every ``shortest_path(...)`` wrapper call scan all
    nodes and edge polylines. The full ``RoutingIndex`` still uses the exact
    signature when it is built or explicitly requested.
    """

    node_count = len(graph.nodes)
    edge_count = len(graph.edges)
    if (
        node_count <= _DEFAULT_PLANNER_EXACT_NODE_LIMIT
        and edge_count <= _DEFAULT_PLANNER_EXACT_EDGE_LIMIT
    ):
        return ("exact", _routing_signature(graph))

    node_samples = tuple(
        (
            i,
            graph.nodes[i].id,
            float(graph.nodes[i].position[0]),
            float(graph.nodes[i].position[1]),
        )
        for i in _sample_indices(node_count)
    )
    edge_samples = tuple(
        (i, _edge_cache_signature(graph.edges[i]))
        for i in _sample_indices(edge_count)
    )
    return (
        "sampled",
        id(graph.nodes),
        node_count,
        node_samples,
        id(graph.edges),
        edge_count,
        edge_samples,
    )


def _cached_default_planner(graph: "Graph") -> RoutePlanner:
    """Return a default ``RoutePlanner`` cached on ``graph`` when still valid."""

    signature = _sampled_default_planner_signature(graph)
    cached = getattr(graph, "_shortest_path_default_planner_cache", None)
    cached_signature = getattr(cached, "_default_planner_cache_signature", None)
    if isinstance(cached, RoutePlanner) and cached_signature == signature:
        return cached
    planner = RoutePlanner(graph)
    try:
        setattr(planner, "_default_planner_cache_signature", signature)
    except Exception:
        pass
    try:
        setattr(graph, "_shortest_path_default_planner_cache", planner)
    except Exception:
        pass
    return planner


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
    if _can_use_default_planner_cache(
        turn_restrictions=turn_restrictions,
        prefer_observed=prefer_observed,
        min_confidence=min_confidence,
        observed_bonus=observed_bonus,
        unobserved_penalty=unobserved_penalty,
        uphill_penalty=uphill_penalty,
        downhill_bonus=downhill_bonus,
        allow_lane_change=allow_lane_change,
        lane_change_cost_m=lane_change_cost_m,
    ):
        planner = _cached_default_planner(graph)
    else:
        planner = RoutePlanner(
            graph,
            turn_restrictions=turn_restrictions,
            prefer_observed=prefer_observed,
            min_confidence=min_confidence,
            observed_bonus=observed_bonus,
            unobserved_penalty=unobserved_penalty,
            uphill_penalty=uphill_penalty,
            downhill_bonus=downhill_bonus,
            allow_lane_change=allow_lane_change,
            lane_change_cost_m=lane_change_cost_m,
        )
    return planner.shortest_path(from_node, to_node)
