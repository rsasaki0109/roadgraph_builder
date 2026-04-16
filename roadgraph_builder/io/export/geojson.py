"""GeoJSON for web maps (WGS84). Graph polyline points are assumed local meters vs origin."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.utils.geo import meters_to_lonlat


def _meter_polyline_from_json(pts: object) -> list[tuple[float, float]] | None:
    """Parse ``[{"x":..,"y":..}, ...]`` from ``attributes.hd.lane_boundaries``."""
    if not isinstance(pts, list) or len(pts) < 2:
        return None
    out: list[tuple[float, float]] = []
    for p in pts:
        if not isinstance(p, dict):
            return None
        out.append((float(p["x"]), float(p["y"])))
    return out


def _semantic_summary_from_hd(hd: object) -> str | None:
    """Short string for GeoJSON popups from ``hd.semantic_rules``."""
    if not isinstance(hd, dict):
        return None
    rules = hd.get("semantic_rules")
    if not isinstance(rules, list) or not rules:
        return None
    parts: list[str] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        kind = r.get("kind")
        if kind == "speed_limit" and "value_kmh" in r:
            try:
                parts.append(f"speed_limit {int(float(r['value_kmh']))} km/h")
            except (TypeError, ValueError):
                parts.append("speed_limit")
        elif kind:
            parts.append(str(kind))
    return "; ".join(parts) if parts else None


def _append_hd_lane_boundary_features(
    features: list[dict[str, Any]],
    edge_id: str,
    dataset_name: str,
    hd: dict[str, Any],
    origin_lat: float,
    origin_lon: float,
) -> None:
    lb = hd.get("lane_boundaries")
    if not isinstance(lb, dict):
        return
    for side, kind in (("left", "lane_boundary_left"), ("right", "lane_boundary_right")):
        raw = lb.get(side)
        mp = _meter_polyline_from_json(raw)
        if mp is None:
            continue
        coords: list[list[float]] = []
        for x, y in mp:
            lon, lat = meters_to_lonlat(float(x), float(y), origin_lat, origin_lon)
            coords.append([lon, lat])
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "kind": kind,
                    "dataset": dataset_name,
                    "edge_id": edge_id,
                    "side": side,
                },
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        )


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
        cl_props: dict[str, Any] = {
            "kind": "centerline",
            "dataset": dataset_name,
            "edge_id": e.id,
            **{k: v for k, v in e.attributes.items()},
        }
        hd = e.attributes.get("hd")
        if isinstance(hd, dict):
            summ = _semantic_summary_from_hd(hd)
            if summ:
                cl_props["semantic_summary"] = summ

        features.append(
            {
                "type": "Feature",
                "properties": cl_props,
                "geometry": {"type": "LineString", "coordinates": coords},
            }
        )

        if isinstance(hd, dict):
            _append_hd_lane_boundary_features(features, e.id, dataset_name, hd, origin_lat, origin_lon)

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
