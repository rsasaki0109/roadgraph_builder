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
    attribution: str | None = None,
    license_name: str | None = None,
    license_url: str | None = None,
) -> dict[str, Any]:
    """FeatureCollection: trajectory LineString, edge LineStrings, node Points.

    When ``attribution`` / ``license_name`` / ``license_url`` are provided they
    are embedded in the FeatureCollection's top-level ``properties`` so the
    file self-documents its source and license even when handed out alone.
    Pass them for OSM-derived outputs (``© OpenStreetMap contributors`` /
    ``ODbL-1.0`` / ``https://opendatacommons.org/licenses/odbl/1-0/``).
    """
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
        length_m = 0.0
        pl = e.polyline
        for i in range(len(pl) - 1):
            dx = float(pl[i + 1][0]) - float(pl[i][0])
            dy = float(pl[i + 1][1]) - float(pl[i][1])
            length_m += (dx * dx + dy * dy) ** 0.5
        cl_props: dict[str, Any] = {
            **{k: v for k, v in e.attributes.items()},
            "kind": "centerline",
            "dataset": dataset_name,
            "edge_id": e.id,
            "start_node_id": e.start_node_id,
            "end_node_id": e.end_node_id,
            "length_m": length_m,
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

    props: dict[str, Any] = {
        "origin_lat": origin_lat,
        "origin_lon": origin_lon,
        "crs_note": "Local meters projected from this WGS84 origin; see utils/geo.py",
    }
    if attribution:
        props["attribution"] = attribution
    if license_name:
        props["license"] = license_name
    if license_url:
        props["license_url"] = license_url

    return {
        "type": "FeatureCollection",
        "name": dataset_name,
        "properties": props,
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
    attribution: str | None = None,
    license_name: str | None = None,
    license_url: str | None = None,
) -> None:
    data = build_map_geojson(
        graph,
        traj_xy,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dataset_name=dataset_name,
        attribution=attribution,
        license_name=license_name,
        license_url=license_url,
    )
    path = Path(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
