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
    """

    from_node: str
    to_node: str
    node_sequence: list[str]
    edge_sequence: list[str]
    edge_directions: list[str]
    total_length_m: float


def _edge_length_m(edge) -> float:  # type: ignore[no-untyped-def]
    pl = edge.polyline
    total = 0.0
    for i in range(len(pl) - 1):
        dx = float(pl[i + 1][0]) - float(pl[i][0])
        dy = float(pl[i + 1][1]) - float(pl[i][1])
        total += math.hypot(dx, dy)
    return total


def _parse_restrictions(
    entries: Iterable[dict] | None,
) -> tuple[
    set[tuple[str, str, str, str, str]],
    dict[tuple[str, str, str], set[tuple[str, str]]],
]:
    """Return ``(forbidden, mandatory)``.

    ``forbidden`` is the set of disallowed
    ``(junction, from_edge, from_dir, to_edge, to_dir)`` tuples from every
    ``no_*`` restriction.

    ``mandatory`` maps ``(junction, from_edge, from_dir)`` to the set of
    ``(to_edge, to_dir)`` tuples the vehicle **must** pick at that junction
    on that approach (collected from every ``only_*`` restriction).
    """
    forbidden: set[tuple[str, str, str, str, str]] = set()
    mandatory: dict[tuple[str, str, str], set[tuple[str, str]]] = {}
    if entries is None:
        return forbidden, mandatory
    for r in entries:
        junction = str(r["junction_node_id"])
        from_edge = str(r["from_edge_id"])
        from_dir = str(r.get("from_direction", "forward"))
        to_edge = str(r["to_edge_id"])
        to_dir = str(r.get("to_direction", "forward"))
        rt = str(r["restriction"])
        if rt.startswith("no_"):
            forbidden.add((junction, from_edge, from_dir, to_edge, to_dir))
        elif rt.startswith("only_"):
            key = (junction, from_edge, from_dir)
            mandatory.setdefault(key, set()).add((to_edge, to_dir))
    return forbidden, mandatory


def shortest_path(
    graph: "Graph",
    from_node: str,
    to_node: str,
    *,
    turn_restrictions: Iterable[dict] | None = None,
) -> Route:
    """Return the shortest :class:`Route` between two node ids.

    With ``turn_restrictions`` supplied, the search respects both the forbid
    semantics of ``no_*`` entries and the whitelist semantics of ``only_*``
    entries at the specified junction / incoming approach.

    Raises:
        KeyError: ``from_node`` or ``to_node`` is not in the graph.
        ValueError: No path exists under the supplied restrictions.
    """
    node_ids = {n.id for n in graph.nodes}
    if from_node not in node_ids:
        raise KeyError(f"from_node {from_node!r} is not in the graph")
    if to_node not in node_ids:
        raise KeyError(f"to_node {to_node!r} is not in the graph")

    # Directed adjacency: node -> list of (edge_id, direction, neighbor_node_id, length_m).
    adj: dict[str, list[tuple[str, str, str, float]]] = {nid: [] for nid in node_ids}
    for e in graph.edges:
        length_m = _edge_length_m(e)
        adj.setdefault(e.start_node_id, []).append(
            (e.id, "forward", e.end_node_id, length_m)
        )
        if e.start_node_id != e.end_node_id:
            adj.setdefault(e.end_node_id, []).append(
                (e.id, "reverse", e.start_node_id, length_m)
            )

    forbidden, mandatory = _parse_restrictions(turn_restrictions)

    if from_node == to_node:
        return Route(
            from_node=from_node,
            to_node=to_node,
            node_sequence=[from_node],
            edge_sequence=[],
            edge_directions=[],
            total_length_m=0.0,
        )

    # State = (node, incoming_edge_id or None, incoming_direction or None).
    State = tuple[str, str | None, str | None]
    start: State = (from_node, None, None)
    dist: dict[State, float] = {start: 0.0}
    prev: dict[State, State] = {}
    queue: list[tuple[float, str, str | None, str | None]] = [(0.0, from_node, None, None)]

    while queue:
        d, u, inc_edge, inc_dir = heapq.heappop(queue)
        state: State = (u, inc_edge, inc_dir)
        if d > dist.get(state, math.inf):
            continue

        allowed_outs: set[tuple[str, str]] | None = None
        if inc_edge is not None:
            allowed_outs = mandatory.get((u, inc_edge, inc_dir))

        for out_edge_id, out_dir, neighbor, w in adj.get(u, []):
            if inc_edge is not None:
                if (u, inc_edge, inc_dir, out_edge_id, out_dir) in forbidden:
                    continue
                if allowed_outs is not None and (out_edge_id, out_dir) not in allowed_outs:
                    continue
            nd = d + w
            new_state: State = (neighbor, out_edge_id, out_dir)
            if nd < dist.get(new_state, math.inf):
                dist[new_state] = nd
                prev[new_state] = state
                heapq.heappush(queue, (nd, neighbor, out_edge_id, out_dir))

    # Pick the cheapest terminal state at to_node across all incoming edges.
    best_state: State | None = None
    best_cost = math.inf
    for state, cost in dist.items():
        if state[0] == to_node and cost < best_cost:
            best_cost = cost
            best_state = state

    if best_state is None or best_cost == math.inf:
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

    return Route(
        from_node=from_node,
        to_node=to_node,
        node_sequence=nodes,
        edge_sequence=edges,
        edge_directions=dirs,
        total_length_m=best_cost,
    )
