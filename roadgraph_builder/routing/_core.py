"""Shared routing topology, cost, and turn-policy helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


DirectedStep = tuple[str, str, str, float]
DirectedAdjacency = dict[str, list[DirectedStep]]
ForbiddenTurn = tuple[str, str, str, str, str]
MandatoryTurnKey = tuple[str, str, str]
MandatoryTurn = tuple[str, str]


@dataclass(frozen=True)
class RoutingIndex:
    """Topology and base metric cache for repeated routing queries."""

    signature: tuple[object, ...]
    node_ids: set[str]
    node_positions: dict[str, tuple[float, float]]
    edge_by_id: dict[str, object]
    base_lengths: dict[str, float]
    base_adj: DirectedAdjacency


@dataclass(frozen=True)
class RoutingCostOptions:
    """Optional edge-cost hooks shared by routing and reachability."""

    prefer_observed: bool = False
    min_confidence: float | None = None
    observed_bonus: float = 0.5
    unobserved_penalty: float = 2.0
    uphill_penalty: float | None = None
    downhill_bonus: float | None = None

    @property
    def uses_slope_cost(self) -> bool:
        return self.uphill_penalty is not None or self.downhill_bonus is not None

    @property
    def uses_default_weights(self) -> bool:
        return (
            self.min_confidence is None
            and not self.prefer_observed
            and not self.uses_slope_cost
        )

    @property
    def preserves_base_metric_lower_bound(self) -> bool:
        """Return True when weighted edge costs never drop below base lengths."""

        if self.prefer_observed and (
            self.observed_bonus < 1.0 or self.unobserved_penalty < 1.0
        ):
            return False
        if self.uphill_penalty is not None and self.uphill_penalty < 1.0:
            return False
        if self.downhill_bonus is not None and self.downhill_bonus < 1.0:
            return False
        return True


@dataclass(frozen=True)
class TurnPolicy:
    """Parsed turn-restriction policy for directed edge transitions."""

    forbidden: set[ForbiddenTurn]
    mandatory: dict[MandatoryTurnKey, set[MandatoryTurn]]

    @property
    def is_empty(self) -> bool:
        return not self.forbidden and not self.mandatory

    def allowed_outs(
        self,
        node_id: str,
        incoming_edge: str | None,
        incoming_direction: str | None,
    ) -> set[MandatoryTurn] | None:
        if incoming_edge is None or incoming_direction is None:
            return None
        return self.mandatory.get((node_id, incoming_edge, incoming_direction))

    def allows_transition(
        self,
        node_id: str,
        incoming_edge: str | None,
        incoming_direction: str | None,
        outgoing_edge: str,
        outgoing_direction: str,
    ) -> bool:
        if incoming_edge is None or incoming_direction is None:
            return True
        if (
            node_id,
            incoming_edge,
            incoming_direction,
            outgoing_edge,
            outgoing_direction,
        ) in self.forbidden:
            return False
        allowed = self.mandatory.get((node_id, incoming_edge, incoming_direction))
        return allowed is None or (outgoing_edge, outgoing_direction) in allowed


def routing_signature(graph: "Graph") -> tuple[object, ...]:
    """Return a mutation signature for topology, node positions, and edge geometry."""

    return (
        id(graph.nodes),
        len(graph.nodes),
        tuple((n.id, float(n.position[0]), float(n.position[1])) for n in graph.nodes),
        id(graph.edges),
        len(graph.edges),
        tuple(edge_cache_signature(e) for e in graph.edges),
    )


def polyline_cache_signature(polyline) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    acc = 1469598103934665603
    for x_raw, y_raw in polyline:
        point_hash = hash((float(x_raw), float(y_raw)))
        acc ^= point_hash & 0xFFFFFFFFFFFFFFFF
        acc = (acc * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return (id(polyline), len(polyline), acc)


def edge_cache_signature(edge) -> tuple[object, ...]:  # type: ignore[no-untyped-def]
    return (
        edge.id,
        edge.start_node_id,
        edge.end_node_id,
        polyline_cache_signature(edge.polyline),
    )


def edge_length_m(edge) -> float:  # type: ignore[no-untyped-def]
    pl = edge.polyline
    total = 0.0
    for i in range(len(pl) - 1):
        dx = float(pl[i + 1][0]) - float(pl[i][0])
        dy = float(pl[i + 1][1]) - float(pl[i][1])
        total += math.hypot(dx, dy)
    return total


def build_routing_index(graph: "Graph", signature: tuple[object, ...]) -> RoutingIndex:
    node_ids = {n.id for n in graph.nodes}
    node_positions = {
        n.id: (float(n.position[0]), float(n.position[1]))
        for n in graph.nodes
    }
    edge_by_id: dict[str, object] = {}
    base_lengths: dict[str, float] = {}
    base_adj: DirectedAdjacency = {nid: [] for nid in node_ids}
    for edge in graph.edges:
        edge_by_id[edge.id] = edge
        base_length_m = edge_length_m(edge)
        base_lengths[edge.id] = base_length_m
        base_adj.setdefault(edge.start_node_id, []).append(
            (edge.id, "forward", edge.end_node_id, base_length_m)
        )
        if edge.start_node_id != edge.end_node_id:
            base_adj.setdefault(edge.end_node_id, []).append(
                (edge.id, "reverse", edge.start_node_id, base_length_m)
            )
    return RoutingIndex(
        signature=signature,
        node_ids=node_ids,
        node_positions=node_positions,
        edge_by_id=edge_by_id,
        base_lengths=base_lengths,
        base_adj=base_adj,
    )


def get_routing_index(graph: "Graph") -> RoutingIndex:
    signature = routing_signature(graph)
    cached = getattr(graph, "_routing_index_cache", None)
    if isinstance(cached, RoutingIndex) and cached.signature == signature:
        return cached
    index = build_routing_index(graph, signature)
    try:
        setattr(graph, "_routing_index_cache", index)
    except Exception:
        pass
    return index


def parse_turn_policy(entries: Iterable[dict] | None) -> TurnPolicy:
    forbidden: set[ForbiddenTurn] = set()
    mandatory: dict[MandatoryTurnKey, set[MandatoryTurn]] = {}
    if entries is None:
        return TurnPolicy(forbidden=forbidden, mandatory=mandatory)
    for restriction in entries:
        junction = str(restriction["junction_node_id"])
        from_edge = str(restriction["from_edge_id"])
        from_dir = str(restriction.get("from_direction", "forward"))
        to_edge = str(restriction["to_edge_id"])
        to_dir = str(restriction.get("to_direction", "forward"))
        restriction_type = str(restriction["restriction"])
        if restriction_type.startswith("no_"):
            forbidden.add((junction, from_edge, from_dir, to_edge, to_dir))
        elif restriction_type.startswith("only_"):
            key = (junction, from_edge, from_dir)
            mandatory.setdefault(key, set()).add((to_edge, to_dir))
    return TurnPolicy(forbidden=forbidden, mandatory=mandatory)


def observation_count(edge) -> int:  # type: ignore[no-untyped-def]
    """Return trace_observation_count from edge.attributes.trace_stats, or 0."""

    attrs = edge.attributes if isinstance(edge.attributes, dict) else {}
    trace_stats = attrs.get("trace_stats")
    if isinstance(trace_stats, dict):
        value = trace_stats.get("trace_observation_count", 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0


def hd_confidence(edge) -> float | None:  # type: ignore[no-untyped-def]
    """Return hd_refinement.confidence from edge.attributes.hd, or None."""

    attrs = edge.attributes if isinstance(edge.attributes, dict) else {}
    hd = attrs.get("hd")
    if isinstance(hd, dict):
        refinement = hd.get("hd_refinement")
        if isinstance(refinement, dict):
            confidence = refinement.get("confidence")
            if confidence is not None:
                try:
                    return float(confidence)
                except (TypeError, ValueError):
                    pass
    return None


def slope_deg(edge, direction: str) -> float:  # type: ignore[no-untyped-def]
    """Return edge slope in degrees for one traversal direction."""

    attrs = edge.attributes if isinstance(edge.attributes, dict) else {}
    slope = attrs.get("slope_deg")
    if slope is None:
        hd = attrs.get("hd")
        if isinstance(hd, dict):
            slope = hd.get("slope_deg")
    if slope is None:
        return 0.0
    try:
        value = float(slope)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return value if direction == "forward" else -value


def lane_count_for_edge(edge) -> int:  # type: ignore[no-untyped-def]
    """Return hd.lane_count from edge.attributes, or 1 as fallback."""

    attrs = edge.attributes if isinstance(edge.attributes, dict) else {}
    hd = attrs.get("hd")
    if isinstance(hd, dict):
        lane_count = hd.get("lane_count")
        if lane_count is not None:
            try:
                return max(1, int(lane_count))
            except (TypeError, ValueError):
                pass
    return 1


def build_weighted_adjacency(
    graph: "Graph",
    index: RoutingIndex,
    options: RoutingCostOptions,
) -> DirectedAdjacency:
    """Build directed adjacency with optional observation/confidence/slope costs."""

    if options.uses_default_weights:
        return index.base_adj

    adj: DirectedAdjacency = {nid: [] for nid in index.node_ids}
    for edge in graph.edges:
        if options.min_confidence is not None:
            confidence = hd_confidence(edge)
            if confidence is not None and confidence < options.min_confidence:
                continue

        base_length_m = index.base_lengths.get(edge.id)
        if base_length_m is None:
            base_length_m = edge_length_m(edge)

        length_fwd = base_length_m
        if options.prefer_observed:
            observations = observation_count(edge)
            multiplier = options.observed_bonus if observations > 0 else options.unobserved_penalty
            length_fwd *= multiplier
        length_rev = length_fwd

        if options.uses_slope_cost:
            slope_fwd = slope_deg(edge, "forward")
            slope_rev = -slope_fwd
            if slope_fwd > 0 and options.uphill_penalty is not None:
                length_fwd *= options.uphill_penalty
            elif slope_fwd < 0 and options.downhill_bonus is not None:
                length_fwd *= options.downhill_bonus
            if slope_rev > 0 and options.uphill_penalty is not None:
                length_rev *= options.uphill_penalty
            elif slope_rev < 0 and options.downhill_bonus is not None:
                length_rev *= options.downhill_bonus

        adj.setdefault(edge.start_node_id, []).append(
            (edge.id, "forward", edge.end_node_id, length_fwd)
        )
        if edge.start_node_id != edge.end_node_id:
            adj.setdefault(edge.end_node_id, []).append(
                (edge.id, "reverse", edge.start_node_id, length_rev)
            )
    return adj


__all__ = [
    "DirectedAdjacency",
    "DirectedStep",
    "RoutingCostOptions",
    "RoutingIndex",
    "TurnPolicy",
    "build_weighted_adjacency",
    "edge_length_m",
    "get_routing_index",
    "lane_count_for_edge",
    "parse_turn_policy",
]
