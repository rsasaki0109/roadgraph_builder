"""Build a :class:`Graph` from OSM highway ways (Overpass response).

Each OSM ``way`` becomes one polyline of ``(x, y)`` meters in the local ENU
frame at ``(origin_lat, origin_lon)``. The list is handed to
:func:`~roadgraph_builder.pipeline.build_graph.polylines_to_graph`, which runs
the usual X/T-split + endpoint union-find passes. The resulting graph has a
topologically honest junction node at every OSM intersection, which is what
OSM ``type=restriction`` relations assume.

Unlike ``build_graph_from_trajectory``, this path does **not** go through
arc-length resampling — the OSM node polyline is preserved verbatim (modulo
the later simplification pass in ``polylines_to_graph``), because OSM ways are
already clean geometries rather than noisy GPS traces.
"""

from __future__ import annotations

from typing import Any, cast

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.pipeline.build_graph import BuildParams, polylines_to_graph
from roadgraph_builder.utils.geo import lonlat_to_meters


_DEFAULT_DRIVABLE = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "living_street",
    "service",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
}


def overpass_highways_to_polylines(
    overpass: dict[str, object],
    origin_lat: float,
    origin_lon: float,
    *,
    highway_filter: set[str] | None = None,
) -> list[list[tuple[float, float]]]:
    """Convert every ``way`` element in ``overpass`` to an ``(x, y)`` polyline.

    ``highway_filter`` defaults to the drivable class set. Ways without a
    ``highway`` tag, without a ``nodes`` list, or shorter than 2 vertices are
    dropped. Nodes referenced by a way but missing from the ``node`` elements
    are silently skipped (matches Overpass ``out skel qt`` truncations).
    """
    elements = overpass.get("elements", [])
    if not isinstance(elements, list):
        raise TypeError("Overpass 'elements' must be a list")

    wanted = highway_filter if highway_filter is not None else _DEFAULT_DRIVABLE

    nodes_ll: dict[int, tuple[float, float]] = {}
    ways: list[dict[str, Any]] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        kind = el.get("type")
        if kind == "node":
            nid = el.get("id")
            lat = el.get("lat")
            lon = el.get("lon")
            if isinstance(nid, int) and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                nodes_ll[nid] = (float(lon), float(lat))
        elif kind == "way":
            ways.append(cast(dict[str, Any], el))

    polylines: list[list[tuple[float, float]]] = []
    for way in ways:
        tags = way.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}
        hwy = tags.get("highway")
        if not isinstance(hwy, str) or hwy not in wanted:
            continue
        refs = way.get("nodes")
        if not isinstance(refs, list):
            continue
        poly: list[tuple[float, float]] = []
        for r in refs:
            if not isinstance(r, int):
                continue
            ll = nodes_ll.get(r)
            if ll is None:
                continue
            x, y = lonlat_to_meters(ll[0], ll[1], origin_lat, origin_lon)
            poly.append((x, y))
        if len(poly) >= 2:
            polylines.append(poly)
    return polylines


def build_graph_from_overpass_highways(
    overpass: dict[str, object],
    origin_lat: float,
    origin_lon: float,
    *,
    params: BuildParams | None = None,
    highway_filter: set[str] | None = None,
) -> Graph:
    """Convert Overpass highways → :class:`Graph` (with ``metadata.map_origin``)."""
    p = params or BuildParams()
    polys = overpass_highways_to_polylines(
        overpass, origin_lat, origin_lon, highway_filter=highway_filter
    )
    graph = polylines_to_graph(polys, p)
    graph.metadata["map_origin"] = {"lat0": float(origin_lat), "lon0": float(origin_lon)}
    graph.metadata["source"] = {"kind": "osm_highways", "way_count": len(polys)}
    return graph


__all__ = [
    "build_graph_from_overpass_highways",
    "overpass_highways_to_polylines",
]
