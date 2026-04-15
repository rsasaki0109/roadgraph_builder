"""GeoJSON for web maps (WGS84). Graph polyline points are assumed local meters vs origin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.utils.geo import meters_to_lonlat


def build_map_geojson(
    graph: Graph,
    traj_xy: np.ndarray,
    *,
    origin_lat: float,
    origin_lon: float,
    dataset_name: str,
) -> dict[str, Any]:
    """FeatureCollection: trajectory LineString, edge LineStrings, node Points."""
    features: list[dict[str, Any]] = []

    if traj_xy.shape[0] >= 2:
        traj_coords: list[list[float]] = []
        for i in range(traj_xy.shape[0]):
            lon, lat = meters_to_lonlat(float(traj_xy[i, 0]), float(traj_xy[i, 1]), origin_lat, origin_lon)
            traj_coords.append([lon, lat])
        features.append(
            {
                "type": "Feature",
                "properties": {"kind": "trajectory", "dataset": dataset_name},
                "geometry": {"type": "LineString", "coordinates": traj_coords},
            }
        )

    for e in graph.edges:
        if len(e.polyline) < 2:
            continue
        coords = []
        for x, y in e.polyline:
            lon, lat = meters_to_lonlat(float(x), float(y), origin_lat, origin_lon)
            coords.append([lon, lat])
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": "centerline",
                    "dataset": dataset_name,
                    "edge_id": e.id,
                    **{k: v for k, v in e.attributes.items()},
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        )

    for n in graph.nodes:
        lon, lat = meters_to_lonlat(float(n.position[0]), float(n.position[1]), origin_lat, origin_lon)
        props = {"kind": "node", "dataset": dataset_name, "node_id": n.id, **dict(n.attributes)}
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
        )

    return {
        "type": "FeatureCollection",
        "name": dataset_name,
        "properties": {
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "crs_note": "Local meters projected from this WGS84 origin; see utils/geo.py",
        },
        "features": features,
    }


def export_map_geojson(
    graph: Graph,
    traj_xy: np.ndarray,
    path: str | Path,
    *,
    origin_lat: float,
    origin_lon: float,
    dataset_name: str,
) -> None:
    data = build_map_geojson(graph, traj_xy, origin_lat=origin_lat, origin_lon=origin_lon, dataset_name=dataset_name)
    path = Path(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
