from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_csv, build_graph_from_trajectory


def test_build_raises_when_trajectory_too_short_for_edges(tmp_path: Path):
    one_row = tmp_path / "one_point.csv"
    one_row.write_text("timestamp,x,y\n0,0,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no edges"):
        build_graph_from_csv(str(one_row), BuildParams())


def test_build_raises_for_empty_polyline_segments():
    """Single-sample trajectory yields no segment with a 2+ vertex centerline."""
    traj = Trajectory(
        timestamps=np.array([0.0], dtype=np.float64),
        xy=np.array([[0.0, 0.0]], dtype=np.float64),
    )
    with pytest.raises(ValueError, match="no edges"):
        build_graph_from_trajectory(traj, BuildParams())
