"""Snap a query point to the closest :class:`Node` in a :class:`Graph`.

Accepts either the same meter frame as the graph (``x_m`` / ``y_m``) or a
WGS84 lat/lon pair plus an origin. Returns the node id and the straight-line
distance in meters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


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

    best_id = graph.nodes[0].id
    best_dist = math.inf
    for n in graph.nodes:
        dx = float(n.position[0]) - x
        dy = float(n.position[1]) - y
        d = math.hypot(dx, dy)
        if d < best_dist:
            best_dist = d
            best_id = n.id

    return NearestNode(node_id=best_id, distance_m=best_dist, query_xy_m=(x, y))


__all__ = ["NearestNode", "nearest_node"]
