"""Performance test for the fast crossing splitters.

Verifies that a large synthetic grid (50×50 = ~10 000 trajectory points,
comparable to a city block grid) completes within the wall-time budget.

CI budget: 30 s (generous; the fast O(N log N) path should be well under 10 s
on a laptop-class machine).

To run locally:
    pytest tests/test_crossing_splitters_perf.py -v -s
"""

from __future__ import annotations

import time

import numpy as np
import pytest


_WALL_TIME_BUDGET_S = 30.0


def _build_50x50_grid_graph():
    """Build a 50×50 grid trajectory graph (~10 000 points).

    50 horizontal + 50 vertical lines at 10 m spacing, each sampled every 2 m
    over 500 m length.  Total trajectory points ≈ 50×251 + 50×251 = 25 100.
    The graph itself is a regular grid with ~2500 junctions, exercising both
    the X-crossing and T-junction splitters extensively.
    """
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
    from roadgraph_builder.io.trajectory.loader import Trajectory

    rows: list[tuple[float, float, float]] = []
    t = 0.0
    # Horizontal lines
    for row in range(50):
        y = row * 10.0
        for x in np.arange(0, 501, 5, dtype=float):
            rows.append((t, float(x), float(y)))
            t += 1.0
        t += 100.0  # gap
    # Vertical lines
    for col in range(50):
        x = col * 10.0
        for y in np.arange(0, 501, 5, dtype=float):
            rows.append((t, float(x), float(y)))
            t += 1.0
        t += 100.0

    xy = np.array([[r[1], r[2]] for r in rows], dtype=np.float64)
    timestamps = np.array([r[0] for r in rows], dtype=np.float64)
    traj = Trajectory(xy=xy, timestamps=timestamps)
    params = BuildParams(max_step_m=200.0, merge_endpoint_m=8.0, centerline_bins=8)
    return build_graph_from_trajectory(traj, params)


def test_50x50_grid_within_budget():
    """50×50 synthetic grid build completes in under 30 s on CI hardware."""
    t0 = time.perf_counter()
    graph = _build_50x50_grid_graph()
    elapsed = time.perf_counter() - t0

    assert graph is not None
    assert len(graph.edges) > 0, "Graph must have edges"
    assert elapsed < _WALL_TIME_BUDGET_S, (
        f"Build took {elapsed:.1f}s, budget is {_WALL_TIME_BUDGET_S}s. "
        "The fast splitter should handle 50×50 grids comfortably."
    )
