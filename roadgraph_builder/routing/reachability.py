"""Reachability analysis over a road graph.

The public entry point, :func:`reachable_within`, answers "what nodes and edge
spans can be reached from this start node within a cost budget?"  It uses the
same cached topology index, edge weighting hooks, and turn-restriction semantics
as ``shortest_path`` so route and service-area style analyses stay aligned.
"""

from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from roadgraph_builder.routing._core import (
    DirectedAdjacency,
    RoutingCostOptions,
    RoutingIndex,
    TurnPolicy,
    build_weighted_adjacency,
    get_routing_index,
    parse_turn_policy,
)

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


@dataclass(frozen=True)
class ReachableNode:
    """A graph node reached within the supplied cost budget."""

    node_id: str
    cost_m: float


@dataclass(frozen=True)
class ReachableEdge:
    """A directed edge span reached within the supplied cost budget."""

    edge_id: str
    direction: str
    from_node: str
    to_node: str
    start_cost_m: float
    reachable_cost_m: float
    reachable_fraction: float
    complete: bool
    end_cost_m: float | None


@dataclass(frozen=True)
class ReachabilityResult:
    """Result of ``reachable_within``."""

    start_node: str
    max_cost_m: float
    nodes: list[ReachableNode]
    edges: list[ReachableEdge]


def _edge_span(
    *,
    edge_id: str,
    direction: str,
    from_node: str,
    to_node: str,
    start_cost_m: float,
    edge_cost_m: float,
    max_cost_m: float,
) -> ReachableEdge | None:
    """Return the reachable span for one outgoing directed edge."""

    remaining = max_cost_m - start_cost_m
    if remaining < 0:
        return None
    if edge_cost_m <= 0:
        return ReachableEdge(
            edge_id=edge_id,
            direction=direction,
            from_node=from_node,
            to_node=to_node,
            start_cost_m=start_cost_m,
            reachable_cost_m=0.0,
            reachable_fraction=1.0,
            complete=True,
            end_cost_m=start_cost_m,
        )

    reachable_cost = min(edge_cost_m, remaining)
    if reachable_cost <= 0:
        return None
    end_cost = start_cost_m + edge_cost_m
    complete = end_cost <= max_cost_m
    return ReachableEdge(
        edge_id=edge_id,
        direction=direction,
        from_node=from_node,
        to_node=to_node,
        start_cost_m=start_cost_m,
        reachable_cost_m=reachable_cost,
        reachable_fraction=max(0.0, min(1.0, reachable_cost / edge_cost_m)),
        complete=complete,
        end_cost_m=end_cost if complete else None,
    )


def _better_edge_span(candidate: ReachableEdge, current: ReachableEdge | None) -> bool:
    if current is None:
        return True
    if candidate.reachable_fraction > current.reachable_fraction + 1e-12:
        return True
    if math.isclose(candidate.reachable_fraction, current.reachable_fraction):
        return candidate.start_cost_m < current.start_cost_m
    return False


def _build_result(
    *,
    start_node: str,
    max_cost_m: float,
    best_node_cost: dict[str, float],
    edge_spans: dict[tuple[str, str], ReachableEdge],
) -> ReachabilityResult:
    nodes = [
        ReachableNode(node_id=node_id, cost_m=cost)
        for node_id, cost in sorted(best_node_cost.items(), key=lambda item: (item[1], item[0]))
    ]
    edges = sorted(
        edge_spans.values(),
        key=lambda e: (e.start_cost_m, e.edge_id, e.direction),
    )
    return ReachabilityResult(
        start_node=start_node,
        max_cost_m=max_cost_m,
        nodes=nodes,
        edges=edges,
    )


def _reachable_within_prepared(
    start_node: str,
    *,
    max_cost_m: float,
    index: RoutingIndex,
    adj: DirectedAdjacency,
    turn_policy: TurnPolicy,
) -> ReachabilityResult:
    if max_cost_m < 0:
        raise ValueError("max_cost_m must be non-negative")

    if start_node not in index.node_ids:
        raise KeyError(f"start_node {start_node!r} is not in the graph")

    if turn_policy.is_empty:
        best_node_cost: dict[str, float] = {start_node: 0.0}
        edge_spans: dict[tuple[str, str], ReachableEdge] = {}
        queue: list[tuple[float, str]] = [(0.0, start_node)]

        while queue:
            cost, node_id = heapq.heappop(queue)
            if cost > best_node_cost.get(node_id, math.inf):
                continue
            if cost > max_cost_m:
                continue

            for edge_id, direction, neighbor, edge_cost in adj.get(node_id, []):
                span = _edge_span(
                    edge_id=edge_id,
                    direction=direction,
                    from_node=node_id,
                    to_node=neighbor,
                    start_cost_m=cost,
                    edge_cost_m=edge_cost,
                    max_cost_m=max_cost_m,
                )
                span_key = (edge_id, direction)
                if span is not None and _better_edge_span(span, edge_spans.get(span_key)):
                    edge_spans[span_key] = span

                next_cost = cost + edge_cost
                if next_cost > max_cost_m:
                    continue
                if next_cost < best_node_cost.get(neighbor, math.inf):
                    best_node_cost[neighbor] = next_cost
                    heapq.heappush(queue, (next_cost, neighbor))

        return _build_result(
            start_node=start_node,
            max_cost_m=max_cost_m,
            best_node_cost=best_node_cost,
            edge_spans=edge_spans,
        )

    State = tuple[str, str | None, str | None]
    start: State = (start_node, None, None)
    dist: dict[State, float] = {start: 0.0}
    best_node_cost: dict[str, float] = {start_node: 0.0}
    edge_spans: dict[tuple[str, str], ReachableEdge] = {}
    counter = itertools.count()
    queue: list[tuple[float, int, State]] = [(0.0, next(counter), start)]

    while queue:
        cost, _, state = heapq.heappop(queue)
        if cost > dist.get(state, math.inf):
            continue
        if cost > max_cost_m:
            continue

        node_id, incoming_edge, incoming_direction = state
        for edge_id, direction, neighbor, edge_cost in adj.get(node_id, []):
            if not turn_policy.allows_transition(
                node_id,
                incoming_edge,
                incoming_direction,
                edge_id,
                direction,
            ):
                continue

            span = _edge_span(
                edge_id=edge_id,
                direction=direction,
                from_node=node_id,
                to_node=neighbor,
                start_cost_m=cost,
                edge_cost_m=edge_cost,
                max_cost_m=max_cost_m,
            )
            span_key = (edge_id, direction)
            if span is not None and _better_edge_span(span, edge_spans.get(span_key)):
                edge_spans[span_key] = span

            next_cost = cost + edge_cost
            if next_cost > max_cost_m:
                continue
            next_state: State = (neighbor, edge_id, direction)
            if next_cost < dist.get(next_state, math.inf):
                dist[next_state] = next_cost
                best_node_cost[neighbor] = min(best_node_cost.get(neighbor, math.inf), next_cost)
                heapq.heappush(queue, (next_cost, next(counter), next_state))

    return _build_result(
        start_node=start_node,
        max_cost_m=max_cost_m,
        best_node_cost=best_node_cost,
        edge_spans=edge_spans,
    )


class ReachabilityAnalyzer:
    """Reusable reachability runner for many queries on one graph and policy.

    Constructing the analyzer prepares the routing index, weighted adjacency,
    and turn-restriction policy once. If the graph is mutated, create a fresh
    analyzer so cached topology and edge lengths match the new graph state.
    """

    def __init__(
        self,
        graph: "Graph",
        *,
        turn_restrictions: Iterable[dict] | None = None,
        prefer_observed: bool = False,
        min_confidence: float | None = None,
        observed_bonus: float = 0.5,
        unobserved_penalty: float = 2.0,
        uphill_penalty: float | None = None,
        downhill_bonus: float | None = None,
    ) -> None:
        index = get_routing_index(graph)
        self._index = index
        self._cost_options = RoutingCostOptions(
            prefer_observed=prefer_observed,
            min_confidence=min_confidence,
            observed_bonus=observed_bonus,
            unobserved_penalty=unobserved_penalty,
            uphill_penalty=uphill_penalty,
            downhill_bonus=downhill_bonus,
        )
        self._adj = build_weighted_adjacency(
            graph,
            index,
            self._cost_options,
        )
        self._turn_policy = parse_turn_policy(turn_restrictions)

    def reachable_within(self, start_node: str, *, max_cost_m: float) -> ReachabilityResult:
        """Return nodes and directed edge spans reachable within ``max_cost_m``."""

        return _reachable_within_prepared(
            start_node,
            max_cost_m=max_cost_m,
            index=self._index,
            adj=self._adj,
            turn_policy=self._turn_policy,
        )


def reachable_within(
    graph: "Graph",
    start_node: str,
    *,
    max_cost_m: float,
    turn_restrictions: Iterable[dict] | None = None,
    prefer_observed: bool = False,
    min_confidence: float | None = None,
    observed_bonus: float = 0.5,
    unobserved_penalty: float = 2.0,
    uphill_penalty: float | None = None,
    downhill_bonus: float | None = None,
) -> ReachabilityResult:
    """Return nodes and directed edge spans reachable within ``max_cost_m``.

    The budget is expressed in the same cost units as ``shortest_path``.  With
    default options this is physical centerline length in meters; when optional
    observation/confidence/slope hooks are supplied it is the weighted routing
    cost. For many queries over the same graph and policy, use
    :class:`ReachabilityAnalyzer` to reuse the prepared topology and adjacency.

    Raises:
        KeyError: ``start_node`` is not in the graph.
        ValueError: ``max_cost_m`` is negative.
    """

    if max_cost_m < 0:
        raise ValueError("max_cost_m must be non-negative")

    return ReachabilityAnalyzer(
        graph,
        turn_restrictions=turn_restrictions,
        prefer_observed=prefer_observed,
        min_confidence=min_confidence,
        observed_bonus=observed_bonus,
        unobserved_penalty=unobserved_penalty,
        uphill_penalty=uphill_penalty,
        downhill_bonus=downhill_bonus,
    ).reachable_within(start_node, max_cost_m=max_cost_m)


__all__ = [
    "ReachabilityAnalyzer",
    "ReachabilityResult",
    "ReachableEdge",
    "ReachableNode",
    "reachable_within",
]
