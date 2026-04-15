#!/usr/bin/env python3
"""Regenerate docs/assets and docs/images from examples/ (run after changing pipeline or samples)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ASSETS = DOCS / "assets"
IMAGES = DOCS / "images"


def main() -> None:
    from roadgraph_builder.io.export.json_exporter import export_graph_json
    from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
    from roadgraph_builder.viz.svg_export import write_trajectory_graph_svg

    ASSETS.mkdir(parents=True, exist_ok=True)
    IMAGES.mkdir(parents=True, exist_ok=True)

    # Toy sample
    toy_csv = ROOT / "examples" / "sample_trajectory.csv"
    shutil.copyfile(toy_csv, ASSETS / "sample_trajectory.csv")
    toy_traj = load_trajectory_csv(toy_csv)
    toy_graph = build_graph_from_trajectory(toy_traj, BuildParams())
    export_graph_json(toy_graph, ASSETS / "sample_graph.json")
    write_trajectory_graph_svg(toy_traj, toy_graph, IMAGES / "sample_trajectory.svg", width=960, height=640)

    # OSM sample (same params as README)
    osm_csv = ROOT / "examples" / "osm_public_trackpoints.csv"
    shutil.copyfile(osm_csv, ASSETS / "osm_trajectory.csv")
    osm_traj = load_trajectory_csv(osm_csv)
    p = BuildParams(max_step_m=40.0, merge_endpoint_m=12.0, centerline_bins=32)
    osm_graph = build_graph_from_trajectory(osm_traj, p)
    export_graph_json(osm_graph, ASSETS / "osm_graph.json")
    write_trajectory_graph_svg(osm_traj, osm_graph, IMAGES / "osm_public.svg", width=960, height=640)

    # Viewer metadata (bounds hint optional)
    meta = {
        "datasets": [
            {"id": "toy", "label": "Toy trajectory", "graph": "assets/sample_graph.json", "csv": "assets/sample_trajectory.csv"},
            {"id": "osm", "label": "OSM public GPS (Berlin area sample)", "graph": "assets/osm_graph.json", "csv": "assets/osm_trajectory.csv"},
        ]
    }
    (ASSETS / "viewer_config.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print("Wrote docs/assets and docs/images")


if __name__ == "__main__":
    main()
