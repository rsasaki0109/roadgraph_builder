"""Regression tests for the fast crossing-splitter implementations.

Builds the Paris real-data graph with the fast (grid-hash) splitters and
asserts the topology matches the known-good golden fixture pickled from the
same code path.  The aggregate length check allows a small runtime-dependent
floating-point drift. Both the legacy (O(N²)) functions from utils.geometry
and the new fast functions from pipeline.crossing_splitters are exercised,
and their polyline-level outputs are compared directly.
"""

from __future__ import annotations

import math
import pickle
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_PATH = FIXTURES / "paris_splitter_golden.pkl"
PARIS_CSV = Path(__file__).parent.parent / "examples" / "osm_public_trackpoints.csv"
# Python / NumPy / platform combinations can shift the final smoothed Paris
# aggregate length by a few meters while preserving graph topology and IDs.
TOTAL_LENGTH_TOLERANCE_M = 5.0


def _total_length(graph) -> float:
    total = 0.0
    for e in graph.edges:
        for i in range(len(e.polyline) - 1):
            dx = e.polyline[i + 1][0] - e.polyline[i][0]
            dy = e.polyline[i + 1][1] - e.polyline[i][1]
            total += math.hypot(dx, dy)
    return total


@pytest.mark.skipif(not PARIS_CSV.is_file(), reason="Paris CSV not present")
def test_fast_splitter_matches_golden():
    """Fast splitter topology matches golden and length stays bounded."""
    from roadgraph_builder.pipeline.build_graph import BuildParams, build_graph_from_csv

    if not GOLDEN_PATH.is_file():
        pytest.skip("Golden fixture not found; run the fixture generator first.")

    with open(GOLDEN_PATH, "rb") as f:
        golden = pickle.load(f)

    params = BuildParams(max_step_m=40.0, merge_endpoint_m=8.0)
    graph = build_graph_from_csv(str(PARIS_CSV), params)

    assert len(graph.edges) == golden["n_edges"], (
        f"Edge count mismatch: got {len(graph.edges)}, expected {golden['n_edges']}"
    )
    assert len(graph.nodes) == golden["n_nodes"], (
        f"Node count mismatch: got {len(graph.nodes)}, expected {golden['n_nodes']}"
    )
    assert sorted(e.id for e in graph.edges) == golden["edge_ids"]
    assert sorted(n.id for n in graph.nodes) == golden["node_ids"]

    total = _total_length(graph)
    assert abs(total - golden["total_length_m"]) < TOTAL_LENGTH_TOLERANCE_M, (
        f"Total length mismatch: got {total}, expected {golden['total_length_m']}"
    )


@pytest.mark.skipif(not PARIS_CSV.is_file(), reason="Paris CSV not present")
def test_fast_splitter_matches_legacy_splitter():
    """Fast (grid-hash) X/T splitters produce identical polyline outputs to
    the legacy O(N²) implementations from utils.geometry."""
    from roadgraph_builder.pipeline.build_graph import BuildParams, trajectory_to_polylines
    from roadgraph_builder.io.trajectory.loader import load_trajectory_csv

    # Legacy implementations.
    from roadgraph_builder.utils.geometry import (
        split_polylines_at_crossings as legacy_crossings,
        split_polylines_at_t_junctions as legacy_tjunc,
    )

    # Fast implementations.
    from roadgraph_builder.pipeline.crossing_splitters import (
        split_polylines_at_crossings_fast,
        split_polylines_at_t_junctions_fast,
    )

    params = BuildParams(max_step_m=40.0, merge_endpoint_m=8.0)
    traj = load_trajectory_csv(str(PARIS_CSV))
    polylines = trajectory_to_polylines(traj, params)

    # Legacy path.
    legacy_after_cross = legacy_crossings(list(polylines))
    legacy_after_tjunc = legacy_tjunc(legacy_after_cross, params.merge_endpoint_m)

    # Fast path.
    fast_after_cross = split_polylines_at_crossings_fast(list(polylines))
    fast_after_tjunc = split_polylines_at_t_junctions_fast(fast_after_cross, params.merge_endpoint_m)

    assert fast_after_cross == legacy_after_cross, (
        f"X-crossing output mismatch: "
        f"fast={len(fast_after_cross)} polylines, legacy={len(legacy_after_cross)}"
    )
    assert fast_after_tjunc == legacy_after_tjunc, (
        f"T-junction output mismatch: "
        f"fast={len(fast_after_tjunc)} polylines, legacy={len(legacy_after_tjunc)}"
    )


def test_fast_crossings_synthetic_x():
    """Fast X-crossing splitter produces 4 halves from a simple cross pattern."""
    from roadgraph_builder.pipeline.crossing_splitters import split_polylines_at_crossings_fast

    horiz = [(-50.0, 0.0), (-10.0, 0.0), (10.0, 0.0), (50.0, 0.0)]
    vert = [(0.0, -50.0), (0.0, -10.0), (0.0, 10.0), (0.0, 50.0)]
    out = split_polylines_at_crossings_fast([horiz, vert])
    assert len(out) == 4
    for sub in out:
        assert (0.0, 0.0) in sub


def test_fast_crossings_synthetic_no_cross():
    """Fast X-crossing splitter leaves non-crossing polylines unchanged."""
    from roadgraph_builder.pipeline.crossing_splitters import split_polylines_at_crossings_fast

    a = [(0.0, 0.0), (10.0, 0.0)]
    b = [(0.0, 1.0), (10.0, 1.0)]
    out = split_polylines_at_crossings_fast([a, b])
    assert out == [a, b]


def test_fast_tjunction_synthetic():
    """Fast T-junction splitter creates 3 sub-polylines from a T shape."""
    from roadgraph_builder.pipeline.crossing_splitters import split_polylines_at_t_junctions_fast

    main = [(float(x), 0.0) for x in range(-50, 51, 5)]  # 21 pts
    branch = [(0.0, float(y)) for y in range(-30, 1, 3)]  # 11 pts, endpoint at (0,0)
    out = split_polylines_at_t_junctions_fast([main, branch], merge_threshold_m=5.0)
    assert len(out) == 3
    has_split = sum(
        1 for pl in out if any(abs(p[0]) < 0.5 and abs(p[1]) < 0.5 for p in pl)
    )
    assert has_split >= 2


def test_fast_tjunction_no_split_beyond_threshold():
    """Fast T-junction splitter does not split when endpoint is too far."""
    from roadgraph_builder.pipeline.crossing_splitters import split_polylines_at_t_junctions_fast

    main = [(float(x), 0.0) for x in range(-50, 51, 5)]
    branch = [(0.0, float(y)) for y in range(-30, -19, 3)]  # endpoint at (0, -20)
    out = split_polylines_at_t_junctions_fast([main, branch], merge_threshold_m=5.0)
    assert len(out) == 2
