"""Snap a query point to the closest :class:`Node` in a :class:`Graph`.

Accepts either the same meter frame as the graph (``x_m`` / ``y_m``) or a
WGS84 lat/lon pair plus an origin. Returns the node id and the straight-line
distance in meters.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph

_FULL_SIGNATURE_NODE_LIMIT = 4096
_SIGNATURE_SAMPLE_COUNT = 65


@dataclass(frozen=True)
class NearestNode:
    """Result of :func:`nearest_node`.

    Attributes:
        node_id: Id of the closest node.
        distance_m: Straight-line (Euclidean, local meters) distance from the
            query point to the matched node.
        query_xy_m: Query projected into the graph's meter frame.
    """

    node_id: str
    distance_m: float
    query_xy_m: tuple[float, float]


@dataclass(frozen=True)
class _NearestNodeIndex:
    """Spatial hash cache for repeated nearest-node lookups."""

    signature: tuple[object, ...]
    cell_size_m: float
    min_x: float
    min_y: float
    min_ix: int
    max_ix: int
    min_iy: int
    max_iy: int
    cells: dict[tuple[int, int], list[tuple[int, str, float, float]]]


def _nearest_signature(graph: "Graph") -> tuple[object, ...]:
    """Return a cheap mutation signature for the graph node list.

    ``Graph`` is mutable, but nearest-node lookups normally operate on a built
    graph whose node list is stable. Small/medium graphs use an exact node
    signature. Very large graphs use evenly spaced samples so repeated snap
    queries do not fall back to an O(N) cache check before the spatial lookup.
    """
    node_count = len(graph.nodes)
    if node_count == 0:
        return (id(graph.nodes), 0)
    if node_count <= _FULL_SIGNATURE_NODE_LIMIT:
        indices = range(node_count)
        mode = "full"
    else:
        sample_count = min(_SIGNATURE_SAMPLE_COUNT, node_count)
        indices = sorted({round(i * (node_count - 1) / (sample_count - 1)) for i in range(sample_count)})
        mode = "sample"

    sampled_nodes = tuple(
        (
            idx,
            graph.nodes[idx].id,
            id(graph.nodes[idx].position),
            float(graph.nodes[idx].position[0]),
            float(graph.nodes[idx].position[1]),
        )
        for idx in indices
    )
    return (
        id(graph.nodes),
        node_count,
        mode,
        sampled_nodes,
    )


def _build_nearest_index(graph: "Graph", signature: tuple[object, ...]) -> _NearestNodeIndex:
    coords = [
        (i, n.id, float(n.position[0]), float(n.position[1]))
        for i, n in enumerate(graph.nodes)
    ]
    min_x = min(p[2] for p in coords)
    max_x = max(p[2] for p in coords)
    min_y = min(p[3] for p in coords)
    max_y = max(p[3] for p in coords)
    width = max_x - min_x
    height = max_y - min_y
    if width <= 0.0 and height <= 0.0:
        cell_size_m = 1.0
    else:
        area = max(width * height, 1.0)
        nominal_spacing = math.sqrt(area / max(len(coords), 1))
        cell_size_m = max(nominal_spacing * 4.0, 1.0)

    cells: dict[tuple[int, int], list[tuple[int, str, float, float]]] = {}
    min_ix = min_iy = math.inf
    max_ix = max_iy = -math.inf
    for order, node_id, x, y in coords:
        ix = math.floor((x - min_x) / cell_size_m)
        iy = math.floor((y - min_y) / cell_size_m)
        cells.setdefault((ix, iy), []).append((order, node_id, x, y))
        min_ix = min(min_ix, ix)
        max_ix = max(max_ix, ix)
        min_iy = min(min_iy, iy)
        max_iy = max(max_iy, iy)

    return _NearestNodeIndex(
        signature=signature,
        cell_size_m=cell_size_m,
        min_x=min_x,
        min_y=min_y,
        min_ix=int(min_ix),
        max_ix=int(max_ix),
        min_iy=int(min_iy),
        max_iy=int(max_iy),
        cells=cells,
    )


def _get_nearest_index(graph: "Graph") -> _NearestNodeIndex:
    signature = _nearest_signature(graph)
    cached = getattr(graph, "_nearest_node_index_cache", None)
    if isinstance(cached, _NearestNodeIndex) and cached.signature == signature:
        return cached
    index = _build_nearest_index(graph, signature)
    try:
        setattr(graph, "_nearest_node_index_cache", index)
    except Exception:
        pass
    return index


def _cell_distance_sq(index: _NearestNodeIndex, ix: int, iy: int, x: float, y: float) -> float:
    x0 = index.min_x + ix * index.cell_size_m
    x1 = x0 + index.cell_size_m
    y0 = index.min_y + iy * index.cell_size_m
    y1 = y0 + index.cell_size_m
    dx = 0.0
    if x < x0:
        dx = x0 - x
    elif x > x1:
        dx = x - x1
    dy = 0.0
    if y < y0:
        dy = y0 - y
    elif y > y1:
        dy = y - y1
    return dx * dx + dy * dy


def _consider_cell(
    index: _NearestNodeIndex,
    key: tuple[int, int],
    x: float,
    y: float,
    best: tuple[float, int, str],
) -> tuple[float, int, str]:
    best_sq, best_order, best_id = best
    for order, node_id, px, py in index.cells.get(key, []):
        dx = px - x
        dy = py - y
        dist_sq = dx * dx + dy * dy
        if dist_sq < best_sq or (dist_sq == best_sq and order < best_order):
            best_sq = dist_sq
            best_order = order
            best_id = node_id
    return best_sq, best_order, best_id


def _nearest_from_heap(index: _NearestNodeIndex, x: float, y: float) -> tuple[str, float]:
    heap: list[tuple[float, tuple[int, int]]] = [
        (_cell_distance_sq(index, ix, iy, x, y), (ix, iy))
        for ix, iy in index.cells
    ]
    heapq.heapify(heap)
    best = (math.inf, math.inf, "")
    while heap:
        cell_lb, key = heapq.heappop(heap)
        if cell_lb > best[0]:
            break
        best = _consider_cell(index, key, x, y, best)
    return best[2], math.sqrt(best[0])


def _nearest_from_rings(index: _NearestNodeIndex, x: float, y: float) -> tuple[str, float]:
    q_ix = math.floor((x - index.min_x) / index.cell_size_m)
    q_iy = math.floor((y - index.min_y) / index.cell_size_m)
    max_ring = max(
        abs(q_ix - index.min_ix),
        abs(q_ix - index.max_ix),
        abs(q_iy - index.min_iy),
        abs(q_iy - index.max_iy),
    )
    # Avoid walking millions of empty cells for a query far outside the graph.
    grid_span = max(index.max_ix - index.min_ix + 1, index.max_iy - index.min_iy + 1)
    if max_ring > grid_span + 4:
        return _nearest_from_heap(index, x, y)

    best = (math.inf, math.inf, "")
    for ring in range(max_ring + 1):
        if ring == 0:
            best = _consider_cell(index, (q_ix, q_iy), x, y, best)
        else:
            for ix in range(q_ix - ring, q_ix + ring + 1):
                best = _consider_cell(index, (ix, q_iy - ring), x, y, best)
                best = _consider_cell(index, (ix, q_iy + ring), x, y, best)
            for iy in range(q_iy - ring + 1, q_iy + ring):
                best = _consider_cell(index, (q_ix - ring, iy), x, y, best)
                best = _consider_cell(index, (q_ix + ring, iy), x, y, best)

        covers_all_cells = (
            q_ix - ring <= index.min_ix
            and q_ix + ring >= index.max_ix
            and q_iy - ring <= index.min_iy
            and q_iy + ring >= index.max_iy
        )
        if covers_all_cells:
            break
        if best[2]:
            cover_min_x = index.min_x + (q_ix - ring) * index.cell_size_m
            cover_max_x = index.min_x + (q_ix + ring + 1) * index.cell_size_m
            cover_min_y = index.min_y + (q_iy - ring) * index.cell_size_m
            cover_max_y = index.min_y + (q_iy + ring + 1) * index.cell_size_m
            outside_lb = min(
                x - cover_min_x,
                cover_max_x - x,
                y - cover_min_y,
                cover_max_y - y,
            )
            if outside_lb > 0.0 and best[0] < outside_lb * outside_lb:
                break

    return best[2], math.sqrt(best[0])


def nearest_node(
    graph: "Graph",
    *,
    x_m: float | None = None,
    y_m: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    origin_lat: float | None = None,
    origin_lon: float | None = None,
) -> NearestNode:
    """Return the node closest to the query point.

    Pass either ``x_m`` / ``y_m`` (graph meter frame) **or** ``lat`` / ``lon``.
    For lat/lon input, ``origin_lat`` / ``origin_lon`` must be supplied or the
    graph must carry ``metadata.map_origin`` ``{lat0, lon0}``.

    Raises:
        ValueError: No nodes in the graph, or required arguments are missing.
    """
    if not graph.nodes:
        raise ValueError("graph has no nodes")

    coord_given = x_m is not None and y_m is not None
    ll_given = lat is not None and lon is not None
    if coord_given == ll_given:
        raise ValueError("pass exactly one of (x_m, y_m) or (lat, lon)")

    if ll_given:
        if origin_lat is None or origin_lon is None:
            mo = graph.metadata.get("map_origin") if isinstance(graph.metadata, dict) else None
            if isinstance(mo, dict) and "lat0" in mo and "lon0" in mo:
                origin_lat = float(mo["lat0"])
                origin_lon = float(mo["lon0"])
            else:
                raise ValueError(
                    "lat/lon input requires origin_lat/origin_lon or graph.metadata.map_origin"
                )
        from roadgraph_builder.utils.geo import lonlat_to_meters

        x, y = lonlat_to_meters(float(lon), float(lat), origin_lat, origin_lon)
    else:
        x, y = float(x_m), float(y_m)  # type: ignore[arg-type]

    best_id, best_dist = _nearest_from_rings(_get_nearest_index(graph), x, y)

    return NearestNode(node_id=best_id, distance_m=best_dist, query_xy_m=(x, y))


__all__ = ["NearestNode", "nearest_node"]
