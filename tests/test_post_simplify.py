from __future__ import annotations

import math

import numpy as np

from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory


def _straight_trajectory(n: int = 40, step: float = 2.0) -> Trajectory:
    xy = np.array([[i * step, 0.0] for i in range(n)], dtype=np.float64)
    ts = np.arange(n, dtype=np.float64)
    return Trajectory(timestamps=ts, xy=xy)


def test_post_simplify_collapses_straight_edge_to_two_vertices():
    # A straight 78 m trajectory becomes a single edge — after post-simplify
    # the polyline should collapse to just its two endpoints because RDP
    # drops every colinear intermediate within tolerance.
    traj = _straight_trajectory()
    g = build_graph_from_trajectory(
        traj,
        BuildParams(max_step_m=5.0, post_simplify_tolerance_m=0.3),
    )
    assert len(g.edges) >= 1
    for e in g.edges:
        assert len(e.polyline) == 2, f"expected straight edge to collapse to 2 pts, got {len(e.polyline)}"


def test_post_simplify_disabled_keeps_all_vertices():
    traj = _straight_trajectory()
    g = build_graph_from_trajectory(
        traj,
        BuildParams(max_step_m=5.0, post_simplify_tolerance_m=None),
    )
    assert any(len(e.polyline) > 2 for e in g.edges)


def test_post_simplify_preserves_curvature():
    # A semicircle — RDP at 0.3 m should NOT collapse it to two points.
    n = 60
    thetas = np.linspace(0.0, math.pi, n)
    xy = np.stack([50.0 * np.cos(thetas), 50.0 * np.sin(thetas)], axis=1)
    ts = np.arange(n, dtype=np.float64)
    traj = Trajectory(timestamps=ts, xy=xy)
    g = build_graph_from_trajectory(
        traj,
        BuildParams(max_step_m=10.0, post_simplify_tolerance_m=0.3),
    )
    assert len(g.edges) >= 1
    longest = max(g.edges, key=lambda e: len(e.polyline))
    # Should keep enough vertices to approximate the arc (≥ 10 but far less
    # than the original 32 resample bins × sample-density for the curve).
    assert len(longest.polyline) >= 10
