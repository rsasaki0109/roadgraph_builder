from __future__ import annotations

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.routing.hmm_match import (
    _Candidate,
    _transition_graph_distance,
    hmm_match_trajectory,
)


def _two_parallel_edges():
    # Two parallel horizontal edges, 3 m apart in y, sharing no nodes.
    return Graph(
        nodes=[
            Node(id="a0", position=(0.0, 0.0)),
            Node(id="a1", position=(100.0, 0.0)),
            Node(id="b0", position=(0.0, 3.0)),
            Node(id="b1", position=(100.0, 3.0)),
        ],
        edges=[
            Edge(
                id="eA",
                start_node_id="a0",
                end_node_id="a1",
                polyline=[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)],
                attributes={},
            ),
            Edge(
                id="eB",
                start_node_id="b0",
                end_node_id="b1",
                polyline=[(0.0, 3.0), (50.0, 3.0), (100.0, 3.0)],
                attributes={},
            ),
        ],
    )


def test_hmm_matches_continuous_trajectory_to_single_edge():
    g = _two_parallel_edges()
    # Trajectory running along y = 1.0 (closer to eA than eB for every sample),
    # but let one sample wobble to y = 2.0 (closer to eB) — HMM should keep
    # it on eA because snapping to eB would require a large graph-side jump.
    xy = np.array(
        [
            [10.0, 0.5],
            [20.0, 0.8],
            [30.0, 1.0],
            [40.0, 2.0],  # wobble closer to eB
            [50.0, 1.1],
            [60.0, 0.9],
            [70.0, 0.6],
        ]
    )
    out = hmm_match_trajectory(
        g,
        xy,
        candidate_radius_m=10.0,
        gps_sigma_m=5.0,
        transition_limit_m=50.0,
    )
    assert all(h is not None for h in out)
    edge_ids = {h.edge_id for h in out}
    assert edge_ids == {"eA"}, f"expected only eA, got {edge_ids}"


def test_hmm_returns_none_outside_radius():
    g = _two_parallel_edges()
    xy = np.array([[50.0, 50.0]])  # 47 m from either edge
    out = hmm_match_trajectory(g, xy, candidate_radius_m=5.0)
    assert out == [None]


def test_hmm_single_sample_equivalent_to_nearest():
    g = _two_parallel_edges()
    xy = np.array([[50.0, 0.2]])
    out = hmm_match_trajectory(g, xy, candidate_radius_m=5.0, gps_sigma_m=2.0)
    assert len(out) == 1
    assert out[0] is not None
    # Closer to eA (y=0) than eB (y=3).
    assert out[0].edge_id == "eA"


def test_hmm_transition_uses_projection_tail_distances():
    g = Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(100.0, 0.0)),
            Node(id="c", position=(200.0, 0.0)),
        ],
        edges=[
            Edge(id="e0", start_node_id="a", end_node_id="b", polyline=[(0.0, 0.0), (100.0, 0.0)]),
            Edge(id="e1", start_node_id="b", end_node_id="c", polyline=[(100.0, 0.0), (200.0, 0.0)]),
        ],
    )
    edge_by_id = {e.id: e for e in g.edges}
    prev = _Candidate("e0", 0.0, (95.0, 0.0), arc_length_m=95.0, edge_length_m=100.0)
    cur = _Candidate("e1", 0.0, (105.0, 0.0), arc_length_m=5.0, edge_length_m=100.0)

    dist = _transition_graph_distance(
        prev,
        cur,
        edge_by_id=edge_by_id,
        node_dists=lambda node: {"b": 0.0} if node == "b" else {},
        transition_limit_m=50.0,
    )

    assert dist == 10.0


def test_hmm_prefers_connected_edges_when_projection_tails_match_gps_step():
    g = Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(100.0, 0.0)),
            Node(id="c", position=(200.0, 0.0)),
            Node(id="d", position=(95.0, 0.4)),
            Node(id="e", position=(105.0, 0.4)),
        ],
        edges=[
            Edge(id="e0", start_node_id="a", end_node_id="b", polyline=[(0.0, 0.0), (100.0, 0.0)]),
            Edge(id="e1", start_node_id="b", end_node_id="c", polyline=[(100.0, 0.0), (200.0, 0.0)]),
            Edge(id="bridge", start_node_id="d", end_node_id="e", polyline=[(95.0, 0.4), (105.0, 0.4)]),
        ],
    )

    out = hmm_match_trajectory(
        g,
        np.array([[95.0, 0.0], [105.0, 0.0]]),
        candidate_radius_m=6.0,
        gps_sigma_m=10.0,
        transition_limit_m=50.0,
    )

    assert [match.edge_id if match else None for match in out] == ["e0", "e1"]
