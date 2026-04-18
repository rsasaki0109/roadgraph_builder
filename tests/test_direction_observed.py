from __future__ import annotations

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.pipeline.build_graph import (
    BuildParams,
    build_graph_from_trajectory,
    merge_duplicate_edges,
)


def test_single_pass_edge_marked_forward_only():
    # Straight trajectory, single pass — direction_observed should be forward_only.
    xy = np.array([[float(i), 0.0] for i in range(0, 40)])
    ts = np.arange(40, dtype=np.float64)
    traj = Trajectory(timestamps=ts, xy=xy)
    g = build_graph_from_trajectory(traj, BuildParams(max_step_m=5.0))
    assert len(g.edges) >= 1
    for e in g.edges:
        assert e.attributes.get("direction_observed") == "forward_only"


def test_duplicate_merge_marks_bidirectional_on_opposite_pass():
    g = Graph(
        nodes=[
            Node(id="n0", position=(0.0, 0.0)),
            Node(id="n1", position=(10.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                attributes={
                    "kind": "lane_centerline",
                    "source": "trajectory_mvp",
                    "direction_observed": "forward_only",
                },
            ),
            Edge(
                id="e1",
                start_node_id="n1",
                end_node_id="n0",
                polyline=[(10.0, 0.0), (0.0, 0.0)],
                attributes={
                    "kind": "lane_centerline",
                    "source": "trajectory_mvp",
                    "direction_observed": "forward_only",
                },
            ),
        ],
    )
    merge_duplicate_edges(g, resample_bins=5)
    assert len(g.edges) == 1
    assert g.edges[0].attributes.get("direction_observed") == "bidirectional"


def test_duplicate_merge_keeps_forward_only_when_same_direction():
    g = Graph(
        nodes=[
            Node(id="n0", position=(0.0, 0.0)),
            Node(id="n1", position=(10.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 0.5), (10.0, 0.5)],
                attributes={
                    "kind": "lane_centerline",
                    "source": "trajectory_mvp",
                    "direction_observed": "forward_only",
                },
            ),
            Edge(
                id="e1",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, -0.5), (10.0, -0.5)],
                attributes={
                    "kind": "lane_centerline",
                    "source": "trajectory_mvp",
                    "direction_observed": "forward_only",
                },
            ),
        ],
    )
    merge_duplicate_edges(g, resample_bins=5)
    assert len(g.edges) == 1
    assert g.edges[0].attributes.get("direction_observed") == "forward_only"


def test_duplicate_merge_propagates_existing_bidirectional_flag():
    # If one input is already bidirectional from an earlier pass, the merged
    # result must stay bidirectional even when the pair has the same canonical
    # direction.
    g = Graph(
        nodes=[
            Node(id="n0", position=(0.0, 0.0)),
            Node(id="n1", position=(10.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                attributes={
                    "kind": "lane_centerline",
                    "source": "trajectory_mvp",
                    "direction_observed": "bidirectional",
                },
            ),
            Edge(
                id="e1",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 0.5), (10.0, 0.5)],
                attributes={
                    "kind": "lane_centerline",
                    "source": "trajectory_mvp",
                    "direction_observed": "forward_only",
                },
            ),
        ],
    )
    merge_duplicate_edges(g, resample_bins=5)
    assert len(g.edges) == 1
    assert g.edges[0].attributes.get("direction_observed") == "bidirectional"
