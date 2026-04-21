#!/usr/bin/env python3
"""Build float64/float32 bundles and compare geometry drift.

This is a release-gate friendly version of the one-off float32 drift checks
recorded in ``docs/float32_drift_report.md``.  It builds two bundles from the
same trajectory CSV, then compares topology and coordinate drift across:

- ``sim/road_graph.json``
- ``nav/sd_nav.json``
- ``sim/map.geojson``
- ``lanelet/map.osm``

The script is intentionally conservative: default trajectory loading remains
float64 elsewhere; this command only exercises the opt-in float32 path.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Allow running directly from the repo root without installing.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_EARTH_RADIUS_M = 6_371_000.0
_DTYPE_CHOICES = ("float64", "float32")


def _xy_distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def _lonlat_distance_m(
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    """Approximate distance between two lon/lat coordinates in meters."""
    lon1, lat1 = a
    lon2, lat2 = b
    lat_mid = math.radians((lat1 + lat2) * 0.5)
    dx = math.radians(lon2 - lon1) * _EARTH_RADIUS_M * math.cos(lat_mid)
    dy = math.radians(lat2 - lat1) * _EARTH_RADIUS_M
    return math.hypot(dx, dy)


def _polyline_length_m(polyline: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(len(polyline) - 1):
        total += _xy_distance_m(polyline[i], polyline[i + 1])
    return total


def _limited(items: list[str], limit: int = 20) -> list[str]:
    return sorted(items)[:limit]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _prepare_bundle_dir(path: Path, *, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"{path} is not empty; pass --overwrite to replace it")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def build_dtype_bundle(
    csv_path: str | Path,
    out_dir: str | Path,
    *,
    trajectory_dtype: str,
    origin_lat: float = 48.86,
    origin_lon: float = 2.34,
    dataset_name: str = "float32_drift",
    lane_width_m: float = 3.5,
    max_step_m: float = 25.0,
    merge_endpoint_m: float = 8.0,
    centerline_bins: int = 32,
    overwrite: bool = False,
) -> Path:
    """Build one export bundle for a trajectory XY dtype."""
    if trajectory_dtype not in _DTYPE_CHOICES:
        raise ValueError("trajectory_dtype must be float64 or float32")

    csv_path = Path(csv_path)
    out_dir = Path(out_dir)
    _prepare_bundle_dir(out_dir, overwrite=overwrite)

    from roadgraph_builder.io.export.bundle import export_map_bundle
    from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory

    traj = load_trajectory_csv(str(csv_path), xy_dtype=trajectory_dtype)
    params = BuildParams(
        max_step_m=max_step_m,
        merge_endpoint_m=merge_endpoint_m,
        centerline_bins=centerline_bins,
        trajectory_xy_dtype=trajectory_dtype,
    )
    graph = build_graph_from_trajectory(traj, params)
    export_map_bundle(
        graph,
        traj.xy,
        csv_path,
        out_dir,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dataset_name=dataset_name,
        lane_width_m=lane_width_m,
    )
    return out_dir


def _compare_graphs(float64_path: Path, float32_path: Path) -> dict[str, Any]:
    from roadgraph_builder.core.graph.graph import Graph

    graph64 = Graph.from_dict(_load_json(float64_path))
    graph32 = Graph.from_dict(_load_json(float32_path))

    nodes64 = {n.id: n for n in graph64.nodes}
    nodes32 = {n.id: n for n in graph32.nodes}
    edges64 = {e.id: e for e in graph64.edges}
    edges32 = {e.id: e for e in graph32.edges}

    missing_nodes = sorted(set(nodes64) - set(nodes32))
    extra_nodes = sorted(set(nodes32) - set(nodes64))
    missing_edges = sorted(set(edges64) - set(edges32))
    extra_edges = sorted(set(edges32) - set(edges64))

    max_node_drift = 0.0
    for node_id in set(nodes64) & set(nodes32):
        max_node_drift = max(
            max_node_drift,
            _xy_distance_m(nodes64[node_id].position, nodes32[node_id].position),
        )

    endpoint_mismatches: list[str] = []
    vertex_count_mismatches: list[str] = []
    max_edge_vertex_drift = 0.0
    edge_vertex_drift_total = 0.0
    edge_vertex_drift_count = 0
    max_per_edge_length_drift = 0.0
    total_length64 = 0.0
    total_length32 = 0.0

    for edge_id in sorted(set(edges64) & set(edges32)):
        edge64 = edges64[edge_id]
        edge32 = edges32[edge_id]
        if (
            edge64.start_node_id != edge32.start_node_id
            or edge64.end_node_id != edge32.end_node_id
        ):
            endpoint_mismatches.append(edge_id)

        length64 = _polyline_length_m(edge64.polyline)
        length32 = _polyline_length_m(edge32.polyline)
        total_length64 += length64
        total_length32 += length32
        max_per_edge_length_drift = max(
            max_per_edge_length_drift,
            abs(length32 - length64),
        )

        if len(edge64.polyline) != len(edge32.polyline):
            vertex_count_mismatches.append(edge_id)
            continue

        for p64, p32 in zip(edge64.polyline, edge32.polyline):
            drift = _xy_distance_m(p64, p32)
            max_edge_vertex_drift = max(max_edge_vertex_drift, drift)
            edge_vertex_drift_total += drift
            edge_vertex_drift_count += 1

    topology_changed = bool(
        missing_nodes
        or extra_nodes
        or missing_edges
        or extra_edges
        or endpoint_mismatches
        or vertex_count_mismatches
    )

    return {
        "node_count_float64": len(nodes64),
        "node_count_float32": len(nodes32),
        "edge_count_float64": len(edges64),
        "edge_count_float32": len(edges32),
        "missing_node_ids_in_float32": _limited(missing_nodes),
        "extra_node_ids_in_float32": _limited(extra_nodes),
        "missing_edge_ids_in_float32": _limited(missing_edges),
        "extra_edge_ids_in_float32": _limited(extra_edges),
        "edge_endpoint_mismatches": len(endpoint_mismatches),
        "edge_endpoint_mismatch_ids": _limited(endpoint_mismatches),
        "edge_vertex_count_mismatches": len(vertex_count_mismatches),
        "edge_vertex_count_mismatch_ids": _limited(vertex_count_mismatches),
        "max_node_xy_drift_m": max_node_drift,
        "max_edge_vertex_xy_drift_m": max_edge_vertex_drift,
        "mean_edge_vertex_xy_drift_m": (
            edge_vertex_drift_total / edge_vertex_drift_count
            if edge_vertex_drift_count
            else 0.0
        ),
        "total_edge_length_float64_m": total_length64,
        "total_edge_length_float32_m": total_length32,
        "total_edge_length_drift_m": total_length32 - total_length64,
        "max_per_edge_length_drift_m": max_per_edge_length_drift,
        "topology_changed": topology_changed,
    }


def _nav_edges_by_id(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    edges = doc.get("edges", [])
    if not isinstance(edges, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in edges:
        if isinstance(entry, dict) and "id" in entry:
            out[str(entry["id"])] = entry
    return out


def _nav_nodes_by_id(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    nodes = doc.get("nodes", [])
    if not isinstance(nodes, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for entry in nodes:
        if isinstance(entry, dict) and "id" in entry:
            out[str(entry["id"])] = entry
    return out


def _compare_sd_nav(float64_path: Path, float32_path: Path) -> dict[str, Any]:
    nav64 = _load_json(float64_path)
    nav32 = _load_json(float32_path)
    if not isinstance(nav64, dict) or not isinstance(nav32, dict):
        raise TypeError("sd_nav JSON root must be an object")

    nodes64 = _nav_nodes_by_id(nav64)
    nodes32 = _nav_nodes_by_id(nav32)
    edges64 = _nav_edges_by_id(nav64)
    edges32 = _nav_edges_by_id(nav32)

    missing_nodes = sorted(set(nodes64) - set(nodes32))
    extra_nodes = sorted(set(nodes32) - set(nodes64))
    missing_edges = sorted(set(edges64) - set(edges32))
    extra_edges = sorted(set(edges32) - set(edges64))

    max_node_drift = 0.0
    for node_id in set(nodes64) & set(nodes32):
        n64 = nodes64[node_id]
        n32 = nodes32[node_id]
        max_node_drift = max(
            max_node_drift,
            _xy_distance_m(
                (float(n64["x_m"]), float(n64["y_m"])),
                (float(n32["x_m"]), float(n32["y_m"])),
            ),
        )

    endpoint_mismatches: list[str] = []
    max_edge_length_drift = 0.0
    total_length64 = 0.0
    total_length32 = 0.0
    for edge_id in sorted(set(edges64) & set(edges32)):
        e64 = edges64[edge_id]
        e32 = edges32[edge_id]
        if (
            e64.get("start_node_id") != e32.get("start_node_id")
            or e64.get("end_node_id") != e32.get("end_node_id")
        ):
            endpoint_mismatches.append(edge_id)
        length64 = float(e64.get("length_m", 0.0))
        length32 = float(e32.get("length_m", 0.0))
        total_length64 += length64
        total_length32 += length32
        max_edge_length_drift = max(max_edge_length_drift, abs(length32 - length64))

    topology_changed = bool(
        missing_nodes or extra_nodes or missing_edges or extra_edges or endpoint_mismatches
    )
    return {
        "node_count_float64": len(nodes64),
        "node_count_float32": len(nodes32),
        "edge_count_float64": len(edges64),
        "edge_count_float32": len(edges32),
        "missing_node_ids_in_float32": _limited(missing_nodes),
        "extra_node_ids_in_float32": _limited(extra_nodes),
        "missing_edge_ids_in_float32": _limited(missing_edges),
        "extra_edge_ids_in_float32": _limited(extra_edges),
        "edge_endpoint_mismatches": len(endpoint_mismatches),
        "edge_endpoint_mismatch_ids": _limited(endpoint_mismatches),
        "max_node_xy_drift_m": max_node_drift,
        "total_edge_length_float64_m": total_length64,
        "total_edge_length_float32_m": total_length32,
        "total_edge_length_drift_m": total_length32 - total_length64,
        "max_edge_length_drift_m": max_edge_length_drift,
        "topology_changed": topology_changed,
    }


def _feature_key(feature: dict[str, Any], index: int) -> str:
    props = feature.get("properties", {})
    if not isinstance(props, dict):
        return f"feature:{index}"
    kind = str(props.get("kind", "feature"))
    edge_id = props.get("edge_id")
    node_id = props.get("node_id")
    side = props.get("side")
    if edge_id is not None and side is not None:
        return f"{kind}:edge:{edge_id}:side:{side}"
    if edge_id is not None:
        return f"{kind}:edge:{edge_id}"
    if node_id is not None:
        return f"{kind}:node:{node_id}"
    return f"{kind}:{index}"


def _features_by_key(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_features = doc.get("features", [])
    if not isinstance(raw_features, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for index, feature in enumerate(raw_features):
        if not isinstance(feature, dict):
            continue
        key = _feature_key(feature, index)
        seen = counts.get(key, 0)
        counts[key] = seen + 1
        if seen:
            key = f"{key}#{seen}"
        out[key] = feature
    return out


def _flatten_lonlat_coordinates(coords: Any) -> list[tuple[float, float]]:
    if (
        isinstance(coords, list)
        and len(coords) >= 2
        and isinstance(coords[0], (int, float))
        and isinstance(coords[1], (int, float))
    ):
        return [(float(coords[0]), float(coords[1]))]
    if not isinstance(coords, list):
        return []
    out: list[tuple[float, float]] = []
    for item in coords:
        out.extend(_flatten_lonlat_coordinates(item))
    return out


def _compare_geojson(float64_path: Path, float32_path: Path) -> dict[str, Any]:
    geo64 = _load_json(float64_path)
    geo32 = _load_json(float32_path)
    if not isinstance(geo64, dict) or not isinstance(geo32, dict):
        raise TypeError("GeoJSON root must be an object")

    features64 = _features_by_key(geo64)
    features32 = _features_by_key(geo32)
    missing_features = sorted(set(features64) - set(features32))
    extra_features = sorted(set(features32) - set(features64))
    geometry_type_mismatches: list[str] = []
    coordinate_count_mismatches: list[str] = []
    max_coordinate_drift = 0.0
    coordinate_drift_total = 0.0
    coordinate_drift_count = 0

    for key in sorted(set(features64) & set(features32)):
        geom64 = features64[key].get("geometry", {})
        geom32 = features32[key].get("geometry", {})
        if not isinstance(geom64, dict) or not isinstance(geom32, dict):
            geometry_type_mismatches.append(key)
            continue
        if geom64.get("type") != geom32.get("type"):
            geometry_type_mismatches.append(key)
            continue
        coords64 = _flatten_lonlat_coordinates(geom64.get("coordinates"))
        coords32 = _flatten_lonlat_coordinates(geom32.get("coordinates"))
        if len(coords64) != len(coords32):
            coordinate_count_mismatches.append(key)
            continue
        for c64, c32 in zip(coords64, coords32):
            drift = _lonlat_distance_m(c64, c32)
            max_coordinate_drift = max(max_coordinate_drift, drift)
            coordinate_drift_total += drift
            coordinate_drift_count += 1

    topology_changed = bool(
        missing_features
        or extra_features
        or geometry_type_mismatches
        or coordinate_count_mismatches
    )
    return {
        "feature_count_float64": len(features64),
        "feature_count_float32": len(features32),
        "missing_feature_keys_in_float32": _limited(missing_features),
        "extra_feature_keys_in_float32": _limited(extra_features),
        "geometry_type_mismatches": len(geometry_type_mismatches),
        "geometry_type_mismatch_keys": _limited(geometry_type_mismatches),
        "coordinate_count_mismatches": len(coordinate_count_mismatches),
        "coordinate_count_mismatch_keys": _limited(coordinate_count_mismatches),
        "max_coordinate_drift_m": max_coordinate_drift,
        "mean_coordinate_drift_m": (
            coordinate_drift_total / coordinate_drift_count
            if coordinate_drift_count
            else 0.0
        ),
        "topology_changed": topology_changed,
    }


def _lanelet_parts(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    nodes: dict[str, tuple[float, float]] = {}
    ways: dict[str, list[str]] = {}
    relations: dict[str, list[tuple[str, str, str]]] = {}

    for node in root.findall("node"):
        node_id = str(node.attrib["id"])
        lat = float(node.attrib["lat"])
        lon = float(node.attrib["lon"])
        nodes[node_id] = (lon, lat)
    for way in root.findall("way"):
        way_id = str(way.attrib["id"])
        ways[way_id] = [str(nd.attrib["ref"]) for nd in way.findall("nd")]
    for relation in root.findall("relation"):
        rel_id = str(relation.attrib["id"])
        relations[rel_id] = [
            (
                str(member.attrib.get("type", "")),
                str(member.attrib.get("ref", "")),
                str(member.attrib.get("role", "")),
            )
            for member in relation.findall("member")
        ]

    return {"nodes": nodes, "ways": ways, "relations": relations}


def _compare_lanelet(float64_path: Path, float32_path: Path) -> dict[str, Any]:
    parts64 = _lanelet_parts(float64_path)
    parts32 = _lanelet_parts(float32_path)
    nodes64: dict[str, tuple[float, float]] = parts64["nodes"]
    nodes32: dict[str, tuple[float, float]] = parts32["nodes"]
    ways64: dict[str, list[str]] = parts64["ways"]
    ways32: dict[str, list[str]] = parts32["ways"]
    rels64: dict[str, list[tuple[str, str, str]]] = parts64["relations"]
    rels32: dict[str, list[tuple[str, str, str]]] = parts32["relations"]

    missing_nodes = sorted(set(nodes64) - set(nodes32))
    extra_nodes = sorted(set(nodes32) - set(nodes64))
    missing_ways = sorted(set(ways64) - set(ways32))
    extra_ways = sorted(set(ways32) - set(ways64))
    missing_rels = sorted(set(rels64) - set(rels32))
    extra_rels = sorted(set(rels32) - set(rels64))

    max_node_drift = 0.0
    for node_id in set(nodes64) & set(nodes32):
        max_node_drift = max(
            max_node_drift,
            _lonlat_distance_m(nodes64[node_id], nodes32[node_id]),
        )

    way_ref_mismatches = [
        way_id
        for way_id in sorted(set(ways64) & set(ways32))
        if ways64[way_id] != ways32[way_id]
    ]
    relation_member_mismatches = [
        rel_id
        for rel_id in sorted(set(rels64) & set(rels32))
        if rels64[rel_id] != rels32[rel_id]
    ]

    topology_changed = bool(
        missing_nodes
        or extra_nodes
        or missing_ways
        or extra_ways
        or missing_rels
        or extra_rels
        or way_ref_mismatches
        or relation_member_mismatches
    )
    return {
        "node_count_float64": len(nodes64),
        "node_count_float32": len(nodes32),
        "way_count_float64": len(ways64),
        "way_count_float32": len(ways32),
        "relation_count_float64": len(rels64),
        "relation_count_float32": len(rels32),
        "missing_node_ids_in_float32": _limited(missing_nodes),
        "extra_node_ids_in_float32": _limited(extra_nodes),
        "missing_way_ids_in_float32": _limited(missing_ways),
        "extra_way_ids_in_float32": _limited(extra_ways),
        "missing_relation_ids_in_float32": _limited(missing_rels),
        "extra_relation_ids_in_float32": _limited(extra_rels),
        "way_ref_mismatches": len(way_ref_mismatches),
        "way_ref_mismatch_ids": _limited(way_ref_mismatches),
        "relation_member_mismatches": len(relation_member_mismatches),
        "relation_member_mismatch_ids": _limited(relation_member_mismatches),
        "max_node_drift_m": max_node_drift,
        "topology_changed": topology_changed,
    }


def compare_bundles(float64_dir: str | Path, float32_dir: str | Path) -> dict[str, Any]:
    """Compare two already-built export bundles."""
    float64_dir = Path(float64_dir)
    float32_dir = Path(float32_dir)
    graph = _compare_graphs(
        float64_dir / "sim" / "road_graph.json",
        float32_dir / "sim" / "road_graph.json",
    )
    sd_nav = _compare_sd_nav(
        float64_dir / "nav" / "sd_nav.json",
        float32_dir / "nav" / "sd_nav.json",
    )
    geojson = _compare_geojson(
        float64_dir / "sim" / "map.geojson",
        float32_dir / "sim" / "map.geojson",
    )
    lanelet = _compare_lanelet(
        float64_dir / "lanelet" / "map.osm",
        float32_dir / "lanelet" / "map.osm",
    )
    trajectory_csv_byte_identical = (
        (float64_dir / "sim" / "trajectory.csv").read_bytes()
        == (float32_dir / "sim" / "trajectory.csv").read_bytes()
    )
    topology_changed = any(
        section["topology_changed"] for section in (graph, sd_nav, geojson, lanelet)
    )
    max_coordinate_drift = max(
        graph["max_node_xy_drift_m"],
        graph["max_edge_vertex_xy_drift_m"],
        sd_nav["max_node_xy_drift_m"],
        geojson["max_coordinate_drift_m"],
        lanelet["max_node_drift_m"],
    )
    return {
        "float64_dir": str(float64_dir),
        "float32_dir": str(float32_dir),
        "trajectory_csv_byte_identical": trajectory_csv_byte_identical,
        "topology_changed": topology_changed,
        "max_coordinate_drift_m": max_coordinate_drift,
        "graph": graph,
        "sd_nav": sd_nav,
        "geojson": geojson,
        "lanelet": lanelet,
    }


def compare_float32_drift(
    csv_path: str | Path,
    out_dir: str | Path,
    *,
    origin_lat: float = 48.86,
    origin_lon: float = 2.34,
    dataset_name: str = "float32_drift",
    lane_width_m: float = 3.5,
    max_step_m: float = 25.0,
    merge_endpoint_m: float = 8.0,
    centerline_bins: int = 32,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Build float64 and float32 bundles, then return a drift report."""
    csv_path = Path(csv_path)
    out_dir = Path(out_dir)
    float64_dir = build_dtype_bundle(
        csv_path,
        out_dir / "float64",
        trajectory_dtype="float64",
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dataset_name=dataset_name,
        lane_width_m=lane_width_m,
        max_step_m=max_step_m,
        merge_endpoint_m=merge_endpoint_m,
        centerline_bins=centerline_bins,
        overwrite=overwrite,
    )
    float32_dir = build_dtype_bundle(
        csv_path,
        out_dir / "float32",
        trajectory_dtype="float32",
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dataset_name=dataset_name,
        lane_width_m=lane_width_m,
        max_step_m=max_step_m,
        merge_endpoint_m=merge_endpoint_m,
        centerline_bins=centerline_bins,
        overwrite=overwrite,
    )
    report = compare_bundles(float64_dir, float32_dir)
    report.update(
        {
            "csv_path": str(csv_path),
            "out_dir": str(out_dir),
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "dataset_name": dataset_name,
            "lane_width_m": lane_width_m,
            "max_step_m": max_step_m,
            "merge_endpoint_m": merge_endpoint_m,
            "centerline_bins": centerline_bins,
        }
    )
    return report


def _render_markdown(report: dict[str, Any]) -> str:
    graph = report["graph"]
    sd_nav = report["sd_nav"]
    geojson = report["geojson"]
    lanelet = report["lanelet"]
    lines = [
        "# Float32 Drift Comparison",
        "",
        f"Input: `{report.get('csv_path', '')}`",
        f"float64 bundle: `{report['float64_dir']}`",
        f"float32 bundle: `{report['float32_dir']}`",
        "",
        "## Summary",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Topology changed | {report['topology_changed']} |",
        f"| Max coordinate drift (m) | {report['max_coordinate_drift_m']:.9f} |",
        f"| Trajectory CSV byte-identical | {report['trajectory_csv_byte_identical']} |",
        "",
        "## Graph",
        "",
        "| Metric | float64 | float32 | Drift |",
        "| --- | ---: | ---: | ---: |",
        (
            f"| Nodes | {graph['node_count_float64']} | "
            f"{graph['node_count_float32']} | - |"
        ),
        (
            f"| Edges | {graph['edge_count_float64']} | "
            f"{graph['edge_count_float32']} | - |"
        ),
        (
            f"| Total edge length (m) | {graph['total_edge_length_float64_m']:.9f} | "
            f"{graph['total_edge_length_float32_m']:.9f} | "
            f"{graph['total_edge_length_drift_m']:+.9f} |"
        ),
        f"| Max node XY drift (m) | - | - | {graph['max_node_xy_drift_m']:.9f} |",
        (
            "| Max edge-vertex XY drift (m) | - | - | "
            f"{graph['max_edge_vertex_xy_drift_m']:.9f} |"
        ),
        (
            "| Mean edge-vertex XY drift (m) | - | - | "
            f"{graph['mean_edge_vertex_xy_drift_m']:.9f} |"
        ),
        (
            "| Max per-edge length drift (m) | - | - | "
            f"{graph['max_per_edge_length_drift_m']:.9f} |"
        ),
        "",
        "## Export Surfaces",
        "",
        "| Surface | Topology changed | Max drift (m) | Notes |",
        "| --- | ---: | ---: | --- |",
        (
            f"| sd_nav | {sd_nav['topology_changed']} | "
            f"{sd_nav['max_node_xy_drift_m']:.9f} | "
            f"max edge length drift {sd_nav['max_edge_length_drift_m']:.9f} m |"
        ),
        (
            f"| GeoJSON | {geojson['topology_changed']} | "
            f"{geojson['max_coordinate_drift_m']:.9f} | "
            f"{geojson['feature_count_float64']} -> {geojson['feature_count_float32']} features |"
        ),
        (
            f"| Lanelet2 OSM | {lanelet['topology_changed']} | "
            f"{lanelet['max_node_drift_m']:.9f} | "
            f"{lanelet['node_count_float64']} nodes / {lanelet['way_count_float64']} ways / "
            f"{lanelet['relation_count_float64']} relations |"
        ),
        "",
    ]
    return "\n".join(lines)


def _print_summary(report: dict[str, Any]) -> None:
    graph = report["graph"]
    lanelet = report["lanelet"]
    print(f"Topology changed: {report['topology_changed']}")
    print(f"Max coordinate drift: {report['max_coordinate_drift_m']:.9f} m")
    print(
        "Graph: "
        f"{graph['node_count_float64']}->{graph['node_count_float32']} nodes, "
        f"{graph['edge_count_float64']}->{graph['edge_count_float32']} edges, "
        f"max edge drift {graph['max_edge_vertex_xy_drift_m']:.9f} m"
    )
    print(
        "Lanelet2: "
        f"{lanelet['node_count_float64']}->{lanelet['node_count_float32']} nodes, "
        f"{lanelet['way_count_float64']}->{lanelet['way_count_float32']} ways, "
        f"{lanelet['relation_count_float64']}->{lanelet['relation_count_float32']} relations"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build float64/float32 bundles and compare topology plus coordinate drift."
    )
    parser.add_argument("csv_path", type=Path, help="Trajectory CSV to build twice.")
    parser.add_argument("out_dir", type=Path, help="Directory that will contain float64/ and float32/.")
    parser.add_argument("--origin-lat", type=float, default=48.86, help="Origin latitude.")
    parser.add_argument("--origin-lon", type=float, default=2.34, help="Origin longitude.")
    parser.add_argument("--dataset-name", default="float32_drift", help="Dataset name for bundle metadata.")
    parser.add_argument("--lane-width-m", type=float, default=3.5, help="Lane width passed to export-bundle.")
    parser.add_argument("--max-step-m", type=float, default=25.0, help="BuildParams max_step_m.")
    parser.add_argument("--merge-endpoint-m", type=float, default=8.0, help="BuildParams merge_endpoint_m.")
    parser.add_argument("--centerline-bins", type=int, default=32, help="BuildParams centerline_bins.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing float64/float32 output dirs.")
    parser.add_argument("--output-json", type=Path, default=None, help="Write the full report as JSON.")
    parser.add_argument("--output-md", type=Path, default=None, help="Write the report as Markdown.")
    parser.add_argument(
        "--fail-on-topology-change",
        action="store_true",
        help="Exit non-zero when topology differs between float64 and float32 outputs.",
    )
    parser.add_argument(
        "--max-coordinate-drift-m",
        type=float,
        default=None,
        help="Exit non-zero when max coordinate drift exceeds this tolerance.",
    )
    args = parser.parse_args()

    if not args.csv_path.is_file():
        print(f"File not found: {args.csv_path}", file=sys.stderr)
        return 1

    try:
        report = compare_float32_drift(
            args.csv_path,
            args.out_dir,
            origin_lat=args.origin_lat,
            origin_lon=args.origin_lon,
            dataset_name=args.dataset_name,
            lane_width_m=args.lane_width_m,
            max_step_m=args.max_step_m,
            merge_endpoint_m=args.merge_endpoint_m,
            centerline_bins=args.centerline_bins,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(f"compare_float32_drift failed: {exc}", file=sys.stderr)
        return 1

    _print_summary(report)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"JSON: {args.output_json}")

    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(_render_markdown(report), encoding="utf-8")
        print(f"Markdown: {args.output_md}")

    failed = False
    if args.fail_on_topology_change and report["topology_changed"]:
        print("Topology changed between float64 and float32 outputs.", file=sys.stderr)
        failed = True
    if (
        args.max_coordinate_drift_m is not None
        and report["max_coordinate_drift_m"] > args.max_coordinate_drift_m
    ):
        print(
            "Max coordinate drift exceeded tolerance: "
            f"{report['max_coordinate_drift_m']:.9f} m > {args.max_coordinate_drift_m:.9f} m",
            file=sys.stderr,
        )
        failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
