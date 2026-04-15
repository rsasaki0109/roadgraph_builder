#!/usr/bin/env python3
"""Regenerate docs/assets and docs/images from examples/ (run after changing pipeline or samples)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ASSETS = DOCS / "assets"
IMAGES = DOCS / "images"

DEFAULT_REPO_URL = "https://github.com/rsasaki0109/roadgraph_builder"
DEFAULT_PAGES_URL = "https://rsasaki0109.github.io/roadgraph_builder/"


def _load_origin(path: Path) -> tuple[float, float]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return float(d["lat0"]), float(d["lon0"])


def main() -> None:
    from roadgraph_builder.io.export.geojson import export_map_geojson
    from roadgraph_builder.io.export.json_exporter import export_graph_json
    from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
    from roadgraph_builder.viz.svg_export import write_trajectory_graph_svg

    ASSETS.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)

    # Toy sample
    toy_csv = ROOT / "examples" / "sample_trajectory.csv"
    toy_origin = ROOT / "examples" / "toy_map_origin.json"
    shutil.copyfile(toy_csv, ASSETS / "sample_trajectory.csv")
    shutil.copyfile(toy_origin, ASSETS / "toy_map_origin.json")
    toy_traj = load_trajectory_csv(toy_csv)
    toy_graph = build_graph_from_trajectory(toy_traj, BuildParams())
    export_graph_json(toy_graph, ASSETS / "sample_graph.json")
    write_trajectory_graph_svg(toy_traj, toy_graph, IMAGES / "sample_trajectory.svg", width=960, height=640)
    tlat, tlon = _load_origin(toy_origin)
    export_map_geojson(
        toy_graph,
        toy_traj.xy,
        ASSETS / "map_toy.geojson",
        origin_lat=tlat,
        origin_lon=tlon,
        dataset_name="toy",
    )

    # OSM sample (same params as README)
    osm_csv = ROOT / "examples" / "osm_public_trackpoints.csv"
    osm_origin_file = ROOT / "examples" / "osm_public_trackpoints_origin.json"
    shutil.copyfile(osm_csv, ASSETS / "osm_trajectory.csv")
    if (ROOT / "examples" / "osm_public_trackpoints_wgs84.csv").is_file():
        shutil.copyfile(ROOT / "examples" / "osm_public_trackpoints_wgs84.csv", ASSETS / "osm_wgs84.csv")
    shutil.copyfile(osm_origin_file, ASSETS / "osm_origin.json")
    osm_traj = load_trajectory_csv(osm_csv)
    p = BuildParams(max_step_m=40.0, merge_endpoint_m=12.0, centerline_bins=32)
    osm_graph = build_graph_from_trajectory(osm_traj, p)
    export_graph_json(osm_graph, ASSETS / "osm_graph.json")
    write_trajectory_graph_svg(osm_traj, osm_graph, IMAGES / "osm_public.svg", width=960, height=640)
    olat, olon = _load_origin(osm_origin_file)
    export_map_geojson(
        osm_graph,
        osm_traj.xy,
        ASSETS / "map_osm.geojson",
        origin_lat=olat,
        origin_lon=olon,
        dataset_name="osm",
    )

    # Viewer metadata (bounds hint optional)
    meta = {
        "datasets": [
            {"id": "toy", "label": "Toy trajectory", "graph": "assets/sample_graph.json", "csv": "assets/sample_trajectory.csv"},
            {"id": "osm", "label": "OSM public GPS (Berlin area sample)", "graph": "assets/osm_graph.json", "csv": "assets/osm_trajectory.csv"},
        ]
    }
    (ASSETS / "viewer_config.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    repo_url = os.environ.get("ROADGRAPH_REPO_URL", DEFAULT_REPO_URL).rstrip("/")
    pages_url = os.environ.get("ROADGRAPH_PAGES_URL", DEFAULT_PAGES_URL).rstrip("/") + "/"
    site = {"repository_url": repo_url + "/", "pages_url": pages_url, "map_url": pages_url + "map.html"}
    (ASSETS / "site.json").write_text(json.dumps(site, indent=2) + "\n", encoding="utf-8")
    print("Wrote docs/assets and docs/images")


if __name__ == "__main__":
    main()
