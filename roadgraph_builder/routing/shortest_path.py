"""Dijkstra shortest path across a :class:`Graph` using edge centerline lengths.

Edges are treated as **undirected** — the graph this project produces is a
geometry/topology seed, not a routable network with lane-level direction. Turn
restrictions in ``nav/sd_nav.json`` are intentionally **not** applied here;
the purpose is a quick "can I reach X from Y, and how far?" answer.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
        total_length_m: Sum of ``polyline`` arc lengths for the traversed edges.
    """

    from_node: str
    to_node: str
    node_sequence: list[str]
    edge_sequence: list[str]
    total_length_m: float


def _edge_length_m(edge) -> float:  # type: ignore[no-untyped-def]
    pl = edge.polyline
    total = 0.0
    for i in range(len(pl) - 1):
        dx = float(pl[i + 1][0]) - float(pl[i][0])
        dy = float(pl[i + 1][1]) - float(pl[i][1])
        total += math.hypot(dx, dy)
    return total


def shortest_path(graph: Graph, from_node: str, to_node: str) -> Route:
    """Return the shortest :class:`Route` between two node ids.

    Raises:
        KeyError: ``from_node`` or ``to_node`` is not in the graph.
        ValueError: No path exists (the nodes are in disjoint components).
    """
    node_ids = {n.id for n in graph.nodes}
    if from_node not in node_ids:
        raise KeyError(f"from_node {from_node!r} is not in the graph")
    if to_node not in node_ids:
        raise KeyError(f"to_node {to_node!r} is not in the graph")

    # Adjacency: for each node, list of (neighbor_node_id, edge_id, length_m).
    adj: dict[str, list[tuple[str, str, float]]] = {nid: [] for nid in node_ids}
    for e in graph.edges:
        length_m = _edge_length_m(e)
        adj.setdefault(e.start_node_id, []).append((e.end_node_id, e.id, length_m))
        if e.start_node_id != e.end_node_id:
            adj.setdefault(e.end_node_id, []).append((e.start_node_id, e.id, length_m))

    if from_node == to_node:
        return Route(
            from_node=from_node,
            to_node=to_node,
            node_sequence=[from_node],
            edge_sequence=[],
            total_length_m=0.0,
        )

    dist: dict[str, float] = {from_node: 0.0}
    prev_node: dict[str, str] = {}
    prev_edge: dict[str, str] = {}
    queue: list[tuple[float, str]] = [(0.0, from_node)]
    while queue:
        d, u = heapq.heappop(queue)
        if u == to_node:
            break
        if d > dist.get(u, math.inf):
            continue
        for v, eid, w in adj.get(u, []):
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev_node[v] = u
                prev_edge[v] = eid
                heapq.heappush(queue, (nd, v))

    if to_node not in dist:
        raise ValueError(f"no path from {from_node!r} to {to_node!r}")

    nodes: list[str] = [to_node]
    edges: list[str] = []
    cur = to_node
    while cur != from_node:
        edges.append(prev_edge[cur])
        cur = prev_node[cur]
        nodes.append(cur)
    nodes.reverse()
    edges.reverse()
    return Route(
        from_node=from_node,
        to_node=to_node,
        node_sequence=nodes,
        edge_sequence=edges,
        total_length_m=dist[to_node],
    )
