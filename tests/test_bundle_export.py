from __future__ import annotations

import json
from pathlib import Path

from roadgraph_builder.io.export.bundle import build_sd_nav_document, export_map_bundle
from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
from roadgraph_builder.validation import (
    validate_manifest_document,
    validate_road_graph_document,
    validate_sd_nav_document,
)

ROOT = Path(__file__).resolve().parent.parent


def test_build_sd_nav_document():
    traj = load_trajectory_csv(ROOT / "examples" / "sample_trajectory.csv")
    g = build_graph_from_trajectory(traj, BuildParams())
    doc = build_sd_nav_document(g)
    assert doc["role"] == "navigation_sd_seed"
    assert len(doc["edges"]) >= 1
    assert "length_m" in doc["edges"][0]


def test_export_map_bundle_writes_nav_sim_lanelet(tmp_path: Path):
    csv_path = ROOT / "examples" / "sample_trajectory.csv"
    traj = load_trajectory_csv(csv_path)
    g = build_graph_from_trajectory(traj, BuildParams())
    export_map_bundle(
        g,
        traj.xy,
        csv_path,
        tmp_path,
        origin_lat=52.52,
        origin_lon=13.405,
        dataset_name="test_bundle",
        lane_width_m=3.5,
        detections_json=None,
    )
    assert (tmp_path / "nav" / "sd_nav.json").is_file()
    assert (tmp_path / "sim" / "road_graph.json").is_file()
    assert (tmp_path / "sim" / "map.geojson").is_file()
    assert (tmp_path / "sim" / "trajectory.csv").is_file()
    assert (tmp_path / "lanelet" / "map.osm").is_file()
    assert (tmp_path / "manifest.json").is_file()
    assert (tmp_path / "README.txt").is_file()
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert man["manifest_version"] == 1
    assert man["outputs"]["sim_road_graph"] == "sim/road_graph.json"
    validate_manifest_document(man)
    nav = json.loads((tmp_path / "nav" / "sd_nav.json").read_text(encoding="utf-8"))
    assert nav["schema_version"] == 1
    validate_sd_nav_document(nav)
    rg = json.loads((tmp_path / "sim" / "road_graph.json").read_text(encoding="utf-8"))
    validate_road_graph_document(rg)
    junctions = man["junctions"]
    assert junctions["total_nodes"] == len(rg["nodes"])
    assert sum(junctions["hints"].values()) == junctions["total_nodes"]
    if junctions["multi_branch_types"]:
        assert sum(junctions["multi_branch_types"].values()) == junctions["hints"].get("multi_branch", 0)
    gs = man["graph_stats"]
    assert gs["edge_count"] == len(rg["edges"])
    assert gs["node_count"] == len(rg["nodes"])
    assert gs["edge_length"]["min_m"] <= gs["edge_length"]["median_m"] <= gs["edge_length"]["max_m"]
    assert gs["bbox_m"]["x_min_m"] <= gs["bbox_m"]["x_max_m"]
    assert gs["bbox_m"]["y_min_m"] <= gs["bbox_m"]["y_max_m"]
    assert gs["bbox_wgs84_deg"]["sw_lon"] <= gs["bbox_wgs84_deg"]["ne_lon"]


def test_export_map_bundle_can_write_compact_geojson(tmp_path: Path):
    csv_path = ROOT / "examples" / "sample_trajectory.csv"
    traj = load_trajectory_csv(csv_path)

    pretty_dir = tmp_path / "pretty"
    compact_dir = tmp_path / "compact"
    g_pretty = build_graph_from_trajectory(traj, BuildParams())
    export_map_bundle(
        g_pretty,
        traj.xy,
        csv_path,
        pretty_dir,
        origin_lat=52.52,
        origin_lon=13.405,
        dataset_name="test_bundle",
        lane_width_m=0,
    )
    g_compact = build_graph_from_trajectory(traj, BuildParams())
    export_map_bundle(
        g_compact,
        traj.xy,
        csv_path,
        compact_dir,
        origin_lat=52.52,
        origin_lon=13.405,
        dataset_name="test_bundle",
        lane_width_m=0,
        compact_geojson=True,
    )

    pretty = pretty_dir / "sim" / "map.geojson"
    compact = compact_dir / "sim" / "map.geojson"
    assert json.loads(compact.read_text(encoding="utf-8")) == json.loads(
        pretty.read_text(encoding="utf-8")
    )
    assert compact.stat().st_size < pretty.stat().st_size


def test_export_map_bundle_fuses_lidar_from_las(tmp_path: Path):
    from roadgraph_builder.io.export.json_loader import load_graph_json

    csv_path = ROOT / "examples" / "sample_trajectory.csv"
    traj = load_trajectory_csv(csv_path)
    g = build_graph_from_trajectory(traj, BuildParams())
    export_map_bundle(
        g,
        traj.xy,
        csv_path,
        tmp_path,
        origin_lat=52.52,
        origin_lon=13.405,
        dataset_name="lidar_bundle",
        lane_width_m=3.5,
        lidar_points=ROOT / "examples" / "sample_lidar.las",
        fuse_max_dist_m=5.0,
        fuse_bins=16,
    )
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert man["lidar_points"]["path"] == "sample_lidar.las"
    assert man["lidar_points"]["point_count"] == 52
    assert man["lidar_points"]["max_dist_m"] == 5.0
    assert man["lidar_points"]["bins"] == 16
    validate_manifest_document(man)

    fused = load_graph_json(tmp_path / "sim" / "road_graph.json")
    fused_edges = [
        e for e in fused.edges
        if e.attributes.get("hd", {}).get("lane_boundaries", {}).get("left")
        and e.attributes.get("hd", {}).get("lane_boundaries", {}).get("right")
    ]
    assert fused_edges, "expected at least one edge with both lidar-fused lane boundaries"
