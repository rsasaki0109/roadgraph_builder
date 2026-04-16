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
