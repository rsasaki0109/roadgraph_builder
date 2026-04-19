"""P2: test that an identical trajectory is absorbed (edge count unchanged,
trace_observation_count bumped) rather than creating a new edge."""

from __future__ import annotations

import numpy as np
import pytest

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_trajectory
from roadgraph_builder.pipeline.incremental import update_graph_from_trajectory


def _straight_traj(x0: float, y0: float, x1: float, y1: float, n: int = 20) -> Trajectory:
    """Build a simple straight-line trajectory from (x0,y0) to (x1,y1)."""
    xs = np.linspace(x0, x1, n)
    ys = np.linspace(y0, y1, n)
    xy = np.column_stack([xs, ys])
    timestamps = np.arange(n, dtype=np.float64)
    return Trajectory(xy=xy, timestamps=timestamps)


def test_identical_trajectory_absorbed():
    """Re-submitting the same trajectory bumps observation count, not edge count."""
    traj = _straight_traj(0.0, 0.0, 100.0, 0.0, n=20)
    params = BuildParams(max_step_m=200.0, merge_endpoint_m=5.0)
    graph = build_graph_from_trajectory(traj, params)
    n_edges_before = len(graph.edges)
    n_nodes_before = len(graph.nodes)

    # Same trajectory again.
    merged = update_graph_from_trajectory(
        graph,
        traj,
        max_step_m=200.0,
        merge_endpoint_m=5.0,
        absorb_tolerance_m=4.0,
    )

    assert len(merged.edges) == n_edges_before, (
        f"Edge count changed on re-submission: {len(merged.edges)} != {n_edges_before}"
    )
    assert len(merged.nodes) == n_nodes_before

    # At least one edge should have a bumped trace_observation_count.
    counts = [e.attributes.get("trace_observation_count", 0) for e in merged.edges]
    assert any(c > 0 for c in counts), (
        "Expected at least one edge to have trace_observation_count > 0 after absorb"
    )


def test_absorbed_does_not_modify_input():
    """update_graph_from_trajectory must not mutate the input graph."""
    traj = _straight_traj(0.0, 0.0, 100.0, 0.0, n=20)
    params = BuildParams(max_step_m=200.0, merge_endpoint_m=5.0)
    graph = build_graph_from_trajectory(traj, params)

    edge_count_before = len(graph.edges)
    counts_before = [e.attributes.get("trace_observation_count", 0) for e in graph.edges]

    update_graph_from_trajectory(
        graph,
        traj,
        max_step_m=200.0,
        merge_endpoint_m=5.0,
        absorb_tolerance_m=4.0,
    )

    assert len(graph.edges) == edge_count_before
    counts_after = [e.attributes.get("trace_observation_count", 0) for e in graph.edges]
    assert counts_before == counts_after, "Input graph edges were mutated"


def test_parallel_offset_not_absorbed():
    """A trajectory offset laterally beyond absorb_tolerance_m creates a new edge."""
    traj = _straight_traj(0.0, 0.0, 100.0, 0.0, n=20)
    params = BuildParams(max_step_m=200.0, merge_endpoint_m=5.0)
    graph = build_graph_from_trajectory(traj, params)
    n_edges_before = len(graph.edges)

    # Offset by 10 m laterally — beyond absorb_tolerance_m=4.
    traj2 = _straight_traj(0.0, 10.0, 100.0, 10.0, n=20)
    merged = update_graph_from_trajectory(
        graph,
        traj2,
        max_step_m=200.0,
        merge_endpoint_m=5.0,
        absorb_tolerance_m=4.0,
    )

    assert len(merged.edges) > n_edges_before, (
        "Expected new edges for a laterally offset trajectory"
    )
