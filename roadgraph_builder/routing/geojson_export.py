"""Export a :class:`Route` as a small GeoJSON FeatureCollection.

Produces one LineString (``kind="route"``) concatenating every traversed
edge's centerline in travel order (polylines are reversed when the edge was
walked in ``reverse`` direction), one LineString per edge with the edge id
and direction (``kind="route_edge"``), and two ``Point`` features for the
start and end nodes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from roadgraph_builder.utils.geo import meters_to_lonlat

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.routing.reachability import ReachabilityResult
    from roadgraph_builder.routing.shortest_path import Route


def _edges_by_id(graph: "Graph") -> dict[str, Any]:
    return {e.id: e for e in graph.edges}


def _nodes_by_id(graph: "Graph") -> dict[str, Any]:
    return {n.id: n for n in graph.nodes}


def _polyline_in_travel_order(polyline: list[tuple[float, float]], direction: str) -> list[tuple[float, float]]:
    if direction == "reverse":
        return list(reversed(polyline))
    return list(polyline)


def _clip_polyline_fraction(
    polyline: list[tuple[float, float]],
    fraction: float,
) -> list[tuple[float, float]]:
    """Return the prefix of ``polyline`` covered by ``fraction`` of its length."""

    if not polyline:
        return []
    if fraction >= 1.0:
        return list(polyline)
    if fraction <= 0.0:
        return [polyline[0]]

    total = 0.0
    for i in range(len(polyline) - 1):
        x0, y0 = polyline[i]
        x1, y1 = polyline[i + 1]
        total += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if total <= 0.0:
        return list(polyline)

    target = total * fraction
    out: list[tuple[float, float]] = [polyline[0]]
    walked = 0.0
    for i in range(len(polyline) - 1):
        x0, y0 = polyline[i]
        x1, y1 = polyline[i + 1]
        segment = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if segment <= 0.0:
            continue
        if walked + segment >= target:
            t = (target - walked) / segment
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            return out
        out.append(polyline[i + 1])
        walked += segment
    return out


def build_route_geojson(
    graph: "Graph",
    route: "Route",
    *,
    origin_lat: float,
    origin_lon: float,
    attribution: str | None = None,
    license_name: str | None = None,
    license_url: str | None = None,
) -> dict[str, Any]:
    edges_by_id = _edges_by_id(graph)
    nodes_by_id = _nodes_by_id(graph)

    def to_lonlat(xy: tuple[float, float]) -> list[float]:
        lon, lat = meters_to_lonlat(float(xy[0]), float(xy[1]), origin_lat, origin_lon)
        return [lon, lat]

    per_edge_features: list[dict[str, Any]] = []
    merged_coords: list[list[float]] = []

    for step, (edge_id, direction) in enumerate(zip(route.edge_sequence, route.edge_directions)):
        edge = edges_by_id[edge_id]
        pl_m = _polyline_in_travel_order(edge.polyline, direction)
        coords = [to_lonlat(p) for p in pl_m]
        per_edge_features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "route_edge",
                    "step": step,
                    "edge_id": edge_id,
                    "direction": direction,
                    "from_node": route.node_sequence[step],
                    "to_node": route.node_sequence[step + 1],
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        )
        if not merged_coords:
            merged_coords.extend(coords)
        else:
            # Avoid duplicating the shared junction vertex between consecutive edges.
            merged_coords.extend(coords[1:])

    features: list[dict[str, Any]] = []
    if merged_coords:
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "route",
                    "from_node": route.from_node,
                    "to_node": route.to_node,
                    "total_length_m": route.total_length_m,
                    "edge_count": len(route.edge_sequence),
                },
                "geometry": {"type": "LineString", "coordinates": merged_coords},
            }
        )
    features.extend(per_edge_features)

    start_node = nodes_by_id[route.from_node]
    end_node = nodes_by_id[route.to_node]
    features.append(
        {
            "type": "Feature",
            "properties": {"kind": "route_start", "node_id": route.from_node},
            "geometry": {"type": "Point", "coordinates": to_lonlat(start_node.position)},
        }
    )
    features.append(
        {
            "type": "Feature",
            "properties": {"kind": "route_end", "node_id": route.to_node},
            "geometry": {"type": "Point", "coordinates": to_lonlat(end_node.position)},
        }
    )

    props: dict[str, Any] = {
        "origin_lat": origin_lat,
        "origin_lon": origin_lon,
        "from_node": route.from_node,
        "to_node": route.to_node,
        "total_length_m": route.total_length_m,
        "edge_count": len(route.edge_sequence),
    }
    if attribution:
        props["attribution"] = attribution
    if license_name:
        props["license"] = license_name
    if license_url:
        props["license_url"] = license_url

    return {
        "type": "FeatureCollection",
        "name": f"route_{route.from_node}_to_{route.to_node}",
        "properties": props,
        "features": features,
    }


def write_route_geojson(
    path: str | Path,
    graph: "Graph",
    route: "Route",
    *,
    origin_lat: float,
    origin_lon: float,
    attribution: str | None = None,
    license_name: str | None = None,
    license_url: str | None = None,
) -> None:
    doc = build_route_geojson(
        graph,
        route,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        attribution=attribution,
        license_name=license_name,
        license_url=license_url,
    )
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_reachability_geojson(
    graph: "Graph",
    reachability: "ReachabilityResult",
    *,
    origin_lat: float,
    origin_lon: float,
    attribution: str | None = None,
    license_name: str | None = None,
    license_url: str | None = None,
) -> dict[str, Any]:
    """Build a GeoJSON FeatureCollection for a reachability result."""

    edges_by_id = _edges_by_id(graph)
    nodes_by_id = _nodes_by_id(graph)

    def to_lonlat(xy: tuple[float, float]) -> list[float]:
        lon, lat = meters_to_lonlat(float(xy[0]), float(xy[1]), origin_lat, origin_lon)
        return [lon, lat]

    features: list[dict[str, Any]] = []
    for edge in reachability.edges:
        graph_edge = edges_by_id[edge.edge_id]
        pl_m = _polyline_in_travel_order(graph_edge.polyline, edge.direction)
        clipped = _clip_polyline_fraction(pl_m, edge.reachable_fraction)
        if len(clipped) < 2:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "reachable_edge",
                    "edge_id": edge.edge_id,
                    "direction": edge.direction,
                    "from_node": edge.from_node,
                    "to_node": edge.to_node,
                    "start_cost_m": edge.start_cost_m,
                    "end_cost_m": edge.end_cost_m,
                    "reachable_cost_m": edge.reachable_cost_m,
                    "reachable_fraction": edge.reachable_fraction,
                    "complete": edge.complete,
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [to_lonlat(p) for p in clipped],
                },
            }
        )

    for node in reachability.nodes:
        graph_node = nodes_by_id[node.node_id]
        kind = "reachability_start" if node.node_id == reachability.start_node else "reachable_node"
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": kind,
                    "node_id": node.node_id,
                    "cost_m": node.cost_m,
                },
                "geometry": {"type": "Point", "coordinates": to_lonlat(graph_node.position)},
            }
        )

    props: dict[str, Any] = {
        "origin_lat": origin_lat,
        "origin_lon": origin_lon,
        "start_node": reachability.start_node,
        "max_cost_m": reachability.max_cost_m,
        "node_count": len(reachability.nodes),
        "edge_count": len(reachability.edges),
    }
    if attribution:
        props["attribution"] = attribution
    if license_name:
        props["license"] = license_name
    if license_url:
        props["license_url"] = license_url

    return {
        "type": "FeatureCollection",
        "name": f"reachability_{reachability.start_node}_{reachability.max_cost_m:g}m",
        "properties": props,
        "features": features,
    }


def write_reachability_geojson(
    path: str | Path,
    graph: "Graph",
    reachability: "ReachabilityResult",
    *,
    origin_lat: float,
    origin_lon: float,
    attribution: str | None = None,
    license_name: str | None = None,
    license_url: str | None = None,
) -> None:
    doc = build_reachability_geojson(
        graph,
        reachability,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        attribution=attribution,
        license_name=license_name,
        license_url=license_url,
    )
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "build_reachability_geojson",
    "build_route_geojson",
    "write_reachability_geojson",
    "write_route_geojson",
]
