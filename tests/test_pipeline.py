from __future__ import annotations

import numpy as np

import roadgraph_builder.pipeline.build_graph as build_graph
from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_csv


def test_build_from_sample_csv(sample_csv_path):
    g = build_graph_from_csv(
        str(sample_csv_path),
        BuildParams(max_step_m=25.0, merge_endpoint_m=8.0, centerline_bins=16),
    )
    assert len(g.edges) >= 1
    assert len(g.nodes) >= 2
    for e in g.edges:
        assert len(e.polyline) >= 2


def test_build_from_csv_forwards_trajectory_xy_dtype(monkeypatch):
    seen: dict[str, np.dtype] = {}

    def fake_load(path, *, load_z=False, xy_dtype=np.float64):
        seen["xy_dtype"] = np.dtype(xy_dtype)
        return Trajectory(
            timestamps=np.asarray([0.0, 1.0, 2.0], dtype=np.float64),
            xy=np.asarray([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]], dtype=xy_dtype),
        )

    monkeypatch.setattr(build_graph, "load_trajectory_csv", fake_load)

    g = build_graph.build_graph_from_csv(
        "synthetic.csv",
        build_graph.BuildParams(centerline_bins=2, trajectory_xy_dtype="float32"),
    )

    assert seen["xy_dtype"] == np.dtype(np.float32)
    assert len(g.edges) >= 1
