"""One-shot export: navigation SD seed, simulation assets, Lanelet OSM."""

from __future__ import annotations

import json
import math
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

import roadgraph_builder
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
from roadgraph_builder.io.camera.detections import apply_camera_detections_to_graph, load_camera_detections_json
from roadgraph_builder.io.export.geojson import export_map_geojson
from roadgraph_builder.io.export.json_exporter import export_graph_json
from roadgraph_builder.io.export.lanelet2 import export_lanelet2
from roadgraph_builder.navigation.sd_maneuvers import allowed_maneuvers_for_edge, allowed_maneuvers_for_edge_reverse
from roadgraph_builder.navigation.turn_restrictions import (
    load_turn_restrictions_json,
    merge_turn_restrictions,
    turn_restrictions_from_camera_detections,
)
from roadgraph_builder.utils.geo import meters_to_lonlat


def _graph_stats(graph: Graph, origin_lat: float, origin_lon: float) -> dict[str, Any]:
    """Summary that downstream tools can read without parsing the full graph."""
    edge_count = len(graph.edges)
    lengths: list[float] = []
    for e in graph.edges:
        pl = e.polyline
        total = 0.0
        for i in range(len(pl) - 1):
            dx = float(pl[i + 1][0]) - float(pl[i][0])
            dy = float(pl[i + 1][1]) - float(pl[i][1])
            total += math.hypot(dx, dy)
        lengths.append(total)

    if lengths:
        srt = sorted(lengths)
        mid = len(srt) // 2
        if len(srt) % 2:
            median_len = float(srt[mid])
        else:
            median_len = 0.5 * float(srt[mid - 1] + srt[mid])
        edge_length = {
            "min_m": float(min(lengths)),
            "median_m": median_len,
            "max_m": float(max(lengths)),
            "total_m": float(sum(lengths)),
        }
    else:
        edge_length = {"min_m": 0.0, "median_m": 0.0, "max_m": 0.0, "total_m": 0.0}

    xs: list[float] = []
    ys: list[float] = []
    for n in graph.nodes:
        xs.append(float(n.position[0]))
        ys.append(float(n.position[1]))
    if xs and ys:
        bbox_m = {
            "x_min_m": min(xs),
            "y_min_m": min(ys),
            "x_max_m": max(xs),
            "y_max_m": max(ys),
        }
        sw_lon, sw_lat = meters_to_lonlat(bbox_m["x_min_m"], bbox_m["y_min_m"], origin_lat, origin_lon)
        ne_lon, ne_lat = meters_to_lonlat(bbox_m["x_max_m"], bbox_m["y_max_m"], origin_lat, origin_lon)
        bbox_wgs84 = {
            "sw_lon": sw_lon,
            "sw_lat": sw_lat,
            "ne_lon": ne_lon,
            "ne_lat": ne_lat,
        }
    else:
        bbox_m = {"x_min_m": 0.0, "y_min_m": 0.0, "x_max_m": 0.0, "y_max_m": 0.0}
        bbox_wgs84 = {"sw_lon": origin_lon, "sw_lat": origin_lat, "ne_lon": origin_lon, "ne_lat": origin_lat}

    return {
        "edge_count": edge_count,
        "node_count": len(graph.nodes),
        "edge_length": edge_length,
        "bbox_m": bbox_m,
        "bbox_wgs84_deg": bbox_wgs84,
    }


def build_sd_nav_document(
    graph: Graph,
    *,
    turn_restrictions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Lightweight topology + edge lengths (meters) for SD / routing-style consumers."""
    nodes: list[dict[str, Any]] = []
    for n in graph.nodes:
        nodes.append(
            {
                "id": n.id,
                "x_m": float(n.position[0]),
                "y_m": float(n.position[1]),
            }
        )
    edges: list[dict[str, Any]] = []
    for e in graph.edges:
        pl = e.polyline
        length_m = 0.0
        for i in range(len(pl) - 1):
            dx = float(pl[i + 1][0]) - float(pl[i][0])
            dy = float(pl[i + 1][1]) - float(pl[i][1])
            length_m += math.hypot(dx, dy)
        edges.append(
            {
                "id": e.id,
                "start_node_id": e.start_node_id,
                "end_node_id": e.end_node_id,
                "length_m": length_m,
                "polyline_vertex_count": len(pl),
                "allowed_maneuvers": allowed_maneuvers_for_edge(graph, e),
                "allowed_maneuvers_reverse": allowed_maneuvers_for_edge_reverse(graph, e),
            }
        )
    doc: dict[str, Any] = {
        "role": "navigation_sd_seed",
        "schema_version": 1,
        "description": (
            "Topology and centerline lengths in the same meter frame as the trajectory CSV. "
            "allowed_maneuvers / allowed_maneuvers_reverse are geometry heuristics at the digitized "
            "end node and start node (reverse travel along the centerline); not surveyed turn restrictions."
        ),
        "nodes": nodes,
        "edges": edges,
    }
    if turn_restrictions:
        doc["turn_restrictions"] = list(turn_restrictions)
    return doc


def export_map_bundle(
    graph: Graph,
    traj_xy: np.ndarray,
    input_csv_path: str | Path,
    out_dir: str | Path,
    *,
    origin_lat: float,
    origin_lon: float,
    dataset_name: str = "bundle",
    lane_width_m: float | None = 3.5,
    detections_json: str | Path | None = None,
    turn_restrictions_json: str | Path | None = None,
    lidar_points: str | Path | None = None,
    fuse_max_dist_m: float = 5.0,
    fuse_bins: int = 32,
    origin_json_path: str | Path | None = None,
) -> None:
    """Write ``nav/``, ``sim/``, ``lanelet/`` under ``out_dir``.

    - **nav/sd_nav.json** — SD-style routing seed (lengths + topology).
    - **sim/** — full ``road_graph.json``, ``map.geojson``, copied ``trajectory.csv``.
    - **lanelet/map.osm** — OSM XML for Lanelet2 / JOSM.

    Optionally runs HD-lite ``enrich``, LiDAR point fusion, and
    ``apply-camera`` before exporting.
    """
    out = Path(out_dir)
    (out / "nav").mkdir(parents=True, exist_ok=True)
    (out / "sim").mkdir(parents=True, exist_ok=True)
    (out / "lanelet").mkdir(parents=True, exist_ok=True)

    if lane_width_m is not None and lane_width_m > 0:
        enrich_sd_to_hd(graph, SDToHDConfig(lane_width_m=lane_width_m))

    lidar_path = Path(lidar_points) if lidar_points else None
    lidar_point_count: int | None = None
    if lidar_path is not None and lidar_path.is_file():
        from roadgraph_builder.hd.lidar_fusion import fuse_lane_boundaries_from_points
        from roadgraph_builder.io.lidar.las import load_points_xy_from_las
        from roadgraph_builder.io.lidar.points import load_points_xy_csv

        if lidar_path.suffix.lower() in {".las", ".laz"}:
            pts_xy = load_points_xy_from_las(lidar_path)
        else:
            pts_xy = load_points_xy_csv(lidar_path)
        lidar_point_count = int(pts_xy.shape[0])
        fuse_lane_boundaries_from_points(
            graph,
            pts_xy,
            max_dist_m=fuse_max_dist_m,
            bins=fuse_bins,
        )

    det_path = Path(detections_json) if detections_json else None
    camera_observations: list[dict[str, Any]] = []
    if det_path is not None and det_path.is_file():
        camera_observations = load_camera_detections_json(det_path)
        apply_camera_detections_to_graph(graph, camera_observations)

    tr_path = Path(turn_restrictions_json) if turn_restrictions_json else None
    manual_restrictions: list[dict[str, Any]] = []
    if tr_path is not None and tr_path.is_file():
        manual_restrictions = load_turn_restrictions_json(tr_path)
    camera_restrictions = turn_restrictions_from_camera_detections(camera_observations)
    merged_restrictions = merge_turn_restrictions(manual_restrictions, camera_restrictions)
    source_counts = Counter(entry["source"] for entry in merged_restrictions)

    junction_hint_counts: Counter[str] = Counter()
    junction_type_counts: Counter[str] = Counter()
    for n in graph.nodes:
        hint = n.attributes.get("junction_hint")
        if isinstance(hint, str):
            junction_hint_counts[hint] += 1
        jtype = n.attributes.get("junction_type")
        if isinstance(jtype, str):
            junction_type_counts[jtype] += 1

    lidar_fuse_info: dict[str, Any] | None = None
    if lidar_path is not None and lidar_path.is_file():
        lidar_fuse_info = {
            "path": lidar_path.name,
            "point_count": lidar_point_count,
            "max_dist_m": fuse_max_dist_m,
            "bins": fuse_bins,
        }

    graph.metadata = {
        **graph.metadata,
        "map_origin": {"lat0": origin_lat, "lon0": origin_lon},
        "export_bundle": {
            "dataset": dataset_name,
            "lane_width_m": lane_width_m,
            "detections_applied": bool(det_path and det_path.is_file()),
            "lidar_fuse": lidar_fuse_info,
            "turn_restrictions": {
                "count": len(merged_restrictions),
                "sources": dict(sorted(source_counts.items())),
            },
            "junctions": {
                "total_nodes": len(graph.nodes),
                "hints": dict(sorted(junction_hint_counts.items())),
                "multi_branch_types": dict(sorted(junction_type_counts.items())),
            },
        },
    }

    nav_doc = build_sd_nav_document(graph, turn_restrictions=merged_restrictions)
    (out / "nav" / "sd_nav.json").write_text(
        json.dumps(nav_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    export_graph_json(graph, out / "sim" / "road_graph.json")
    export_map_geojson(
        graph,
        traj_xy,
        out / "sim" / "map.geojson",
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dataset_name=dataset_name,
    )
    shutil.copy2(Path(input_csv_path), out / "sim" / "trajectory.csv")

    export_lanelet2(graph, out / "lanelet" / "map.osm", origin_lat=origin_lat, origin_lon=origin_lon)

    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "generator": "roadgraph_builder",
        "roadgraph_builder_version": roadgraph_builder.__version__,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "dataset_name": dataset_name,
        "origin_wgs84_deg": {"lat": origin_lat, "lon": origin_lon},
        "origin_source": "origin_json" if origin_json_path else "cli",
        "origin_json": Path(origin_json_path).name if origin_json_path else None,
        "input_trajectory_csv": Path(input_csv_path).name,
        "lane_width_m": lane_width_m,
        "detections_json": Path(detections_json).name if det_path and det_path.is_file() else None,
        "lidar_points": lidar_fuse_info,
        "turn_restrictions_json": Path(turn_restrictions_json).name if tr_path and tr_path.is_file() else None,
        "turn_restrictions_count": len(merged_restrictions),
        "junctions": {
            "total_nodes": len(graph.nodes),
            "hints": dict(sorted(junction_hint_counts.items())),
            "multi_branch_types": dict(sorted(junction_type_counts.items())),
        },
        "graph_stats": _graph_stats(graph, origin_lat, origin_lon),
        "outputs": {
            "nav_sd_nav": "nav/sd_nav.json",
            "sim_road_graph": "sim/road_graph.json",
            "sim_map_geojson": "sim/map.geojson",
            "sim_trajectory_csv": "sim/trajectory.csv",
            "lanelet_osm": "lanelet/map.osm",
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    (out / "sim" / "README.txt").write_text(
        "sim/: full road_graph.json (schema_version), map.geojson (WGS84), trajectory.csv copy — "
        "for simulation / visualization pipelines.\n",
        encoding="utf-8",
    )
    (out / "README.txt").write_text(
        "roadgraph_builder export-bundle — three targets in one directory:\n"
        "  manifest.json       — provenance (version, origin, inputs)\n"
        "  nav/sd_nav.json     — SD-style routing seed (lengths + topology)\n"
        "  sim/                — full graph + GeoJSON + trajectory\n"
        "  lanelet/map.osm     — Lanelet2 / JOSM interchange\n",
        encoding="utf-8",
    )
