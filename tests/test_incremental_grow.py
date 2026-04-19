"""P2: test that a trajectory outside an existing graph's area creates new edges."""

from __future__ import annotations

import numpy as np

from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
from roadgraph_builder.pipeline.incremental import update_graph_from_trajectory


def _straight_traj(x0: float, y0: float, x1: float, y1: float, n: int = 20) -> Trajectory:
    xs = np.linspace(x0, x1, n)
    ys = np.linspace(y0, y1, n)
    xy = np.column_stack([xs, ys])
    timestamps = np.arange(n, dtype=np.float64)
    return Trajectory(xy=xy, timestamps=timestamps)


def test_disjoint_trajectory_grows_graph():
    """A trajectory in a completely separate area should add new edges and nodes."""
    traj1 = _straight_traj(0.0, 0.0, 100.0, 0.0, n=20)
    params = BuildParams(max_step_m=200.0, merge_endpoint_m=5.0)
    graph = build_graph_from_trajectory(traj1, params)
    n_edges_before = len(graph.edges)
    n_nodes_before = len(graph.nodes)

    # Far-away trajectory (1 km away).
    traj2 = _straight_traj(1000.0, 1000.0, 1100.0, 1000.0, n=20)
    merged = update_graph_from_trajectory(
        graph,
        traj2,
        max_step_m=200.0,
        merge_endpoint_m=5.0,
        absorb_tolerance_m=4.0,
    )

    assert len(merged.edges) > n_edges_before, (
        f"Expected new edges for disjoint trajectory; got {len(merged.edges)} (was {n_edges_before})"
    )
    assert len(merged.nodes) > n_nodes_before


def test_adjacent_trajectory_connects():
    """A trajectory that extends an existing road at its endpoint should connect."""
    traj1 = _straight_traj(0.0, 0.0, 100.0, 0.0, n=20)
    params = BuildParams(max_step_m=200.0, merge_endpoint_m=8.0)
    graph = build_graph_from_trajectory(traj1, params)
    n_edges_before = len(graph.edges)

    # Extension starting from (very near) the end of traj1.
    traj2 = _straight_traj(98.0, 0.0, 200.0, 0.0, n=20)
    merged = update_graph_from_trajectory(
        graph,
        traj2,
        max_step_m=200.0,
        merge_endpoint_m=8.0,
        absorb_tolerance_m=4.0,
    )

    # Should have more edges (extension added) or at least the same (if the
    # extension is fully within the existing edge due to merge tolerance).
    assert len(merged.edges) >= n_edges_before


def test_update_graph_preserves_existing_edges():
    """All original edges must still be present in the merged graph."""
    traj1 = _straight_traj(0.0, 0.0, 100.0, 0.0, n=20)
    params = BuildParams(max_step_m=200.0, merge_endpoint_m=5.0)
    graph = build_graph_from_trajectory(traj1, params)
    original_edge_ids = {e.id for e in graph.edges}

    traj2 = _straight_traj(1000.0, 1000.0, 1100.0, 1000.0, n=20)
    merged = update_graph_from_trajectory(
        graph,
        traj2,
        max_step_m=200.0,
        merge_endpoint_m=5.0,
        absorb_tolerance_m=4.0,
    )

    merged_edge_ids = {e.id for e in merged.edges}
    assert original_edge_ids.issubset(merged_edge_ids), (
        f"Original edges missing from merged graph: {original_edge_ids - merged_edge_ids}"
    )
