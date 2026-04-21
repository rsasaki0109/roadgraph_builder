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

from roadgraph_builder.routing.shortest_path import (
    _edge_length_m,
    _get_routing_index,
    _hd_confidence,
    _observation_count,
    _parse_restrictions,
    _slope_deg,
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


def _weighted_adjacency(
    graph: "Graph",
    *,
    prefer_observed: bool,
    min_confidence: float | None,
    observed_bonus: float,
    unobserved_penalty: float,
    uphill_penalty: float | None,
    downhill_bonus: float | None,
) -> dict[str, list[tuple[str, str, str, float]]]:
    """Build the weighted adjacency used by reachability.

    This mirrors the weighting hooks in ``shortest_path``.  The common default
    path reuses the cached base adjacency directly.
    """

    index = _get_routing_index(graph)
    use_slope_cost = uphill_penalty is not None or downhill_bonus is not None
    if min_confidence is None and not prefer_observed and not use_slope_cost:
        return index.base_adj

    adj: dict[str, list[tuple[str, str, str, float]]] = {nid: [] for nid in index.node_ids}
    for edge in graph.edges:
        if min_confidence is not None:
            conf = _hd_confidence(edge)
            if conf is not None and conf < min_confidence:
                continue

        base_length_m = index.base_lengths.get(edge.id)
        if base_length_m is None:
            base_length_m = _edge_length_m(edge)

        length_fwd = base_length_m
        if prefer_observed:
            obs = _observation_count(edge)
            multiplier = observed_bonus if obs > 0 else unobserved_penalty
            length_fwd *= multiplier
        length_rev = length_fwd

        if use_slope_cost:
            slope_fwd = _slope_deg(edge, "forward")
            slope_rev = -slope_fwd
            if slope_fwd > 0 and uphill_penalty is not None:
                length_fwd *= uphill_penalty
            elif slope_fwd < 0 and downhill_bonus is not None:
                length_fwd *= downhill_bonus
            if slope_rev > 0 and uphill_penalty is not None:
                length_rev *= uphill_penalty
            elif slope_rev < 0 and downhill_bonus is not None:
                length_rev *= downhill_bonus

        adj.setdefault(edge.start_node_id, []).append(
            (edge.id, "forward", edge.end_node_id, length_fwd)
        )
        if edge.start_node_id != edge.end_node_id:
            adj.setdefault(edge.end_node_id, []).append(
                (edge.id, "reverse", edge.start_node_id, length_rev)
            )
    return adj


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
    cost.

    Raises:
        KeyError: ``start_node`` is not in the graph.
        ValueError: ``max_cost_m`` is negative.
    """

    if max_cost_m < 0:
        raise ValueError("max_cost_m must be non-negative")

    index = _get_routing_index(graph)
    if start_node not in index.node_ids:
        raise KeyError(f"start_node {start_node!r} is not in the graph")

    adj = _weighted_adjacency(
        graph,
        prefer_observed=prefer_observed,
        min_confidence=min_confidence,
        observed_bonus=observed_bonus,
        unobserved_penalty=unobserved_penalty,
        uphill_penalty=uphill_penalty,
        downhill_bonus=downhill_bonus,
    )
    forbidden, mandatory = _parse_restrictions(turn_restrictions)

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
        allowed_outs: set[tuple[str, str]] | None = None
        if incoming_edge is not None:
            allowed_outs = mandatory.get((node_id, incoming_edge, incoming_direction))

        for edge_id, direction, neighbor, edge_cost in adj.get(node_id, []):
            if incoming_edge is not None:
                if (node_id, incoming_edge, incoming_direction, edge_id, direction) in forbidden:
                    continue
                if allowed_outs is not None and (edge_id, direction) not in allowed_outs:
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


__all__ = [
    "ReachabilityResult",
    "ReachableEdge",
    "ReachableNode",
    "reachable_within",
]
