from __future__ import annotations

from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
from roadgraph_builder.viz.svg_export import write_trajectory_graph_svg


def test_write_svg(tmp_path, sample_csv_path):
    traj = load_trajectory_csv(sample_csv_path)
    g = build_graph_from_trajectory(traj, BuildParams(max_step_m=25.0))
    out = tmp_path / "out.svg"
    write_trajectory_graph_svg(traj, g, out)
    text = out.read_text(encoding="utf-8")
    assert "<svg" in text
    assert "path d=" in text or "circle" in text
