from __future__ import annotations

from pathlib import Path

import numpy as np

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.io.lidar.fusion import attach_lidar_points_metadata
from roadgraph_builder.io.lidar.points import load_points_xy_csv

ROOT = Path(__file__).resolve().parent.parent


def test_load_points_xy_csv(tmp_path):
    p = tmp_path / "p.csv"
    p.write_text("x y\n0 1\n2 3\n", encoding="utf-8")
    arr = load_points_xy_csv(p)
    assert arr.shape == (2, 2)
    assert arr[0, 0] == 0.0 and arr[1, 1] == 3.0


def test_load_bundled_example_csv():
    arr = load_points_xy_csv(ROOT / "examples" / "sample_lidar_points.csv")
    assert arr.shape == (4, 2)


def test_attach_lidar_metadata():
    g = Graph()
    pts = np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float64)
    attach_lidar_points_metadata(g, pts)
    lidar = g.metadata["lidar"]
    assert isinstance(lidar, dict)
    assert lidar["point_count"] == 2
    assert lidar["status"] == "loaded_not_fused"
