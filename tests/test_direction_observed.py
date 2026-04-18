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


def test_sd_nav_emits_empty_reverse_for_forward_only_edge():
    from roadgraph_builder.io.export.bundle import build_sd_nav_document

    # Three-arm T-junction: south → center, and side branches east / west at center.
    g = Graph(
        nodes=[
            Node(id="nc", position=(0.0, 0.0), attributes={"junction_hint": "multi_branch", "degree": 3}),
            Node(id="ns", position=(0.0, -10.0), attributes={"junction_hint": "dead_end", "degree": 1}),
            Node(id="ne", position=(10.0, 0.0), attributes={"junction_hint": "dead_end", "degree": 1}),
            Node(id="nw", position=(-10.0, 0.0), attributes={"junction_hint": "dead_end", "degree": 1}),
        ],
        edges=[
            Edge(
                id="e_south",
                start_node_id="ns",
                end_node_id="nc",
                polyline=[(0.0, -10.0), (0.0, 0.0)],
                attributes={"direction_observed": "forward_only"},
            ),
            Edge(
                id="e_east",
                start_node_id="nc",
                end_node_id="ne",
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                attributes={"direction_observed": "bidirectional"},
            ),
            Edge(
                id="e_west",
                start_node_id="nc",
                end_node_id="nw",
                polyline=[(0.0, 0.0), (-10.0, 0.0)],
                attributes={"direction_observed": "forward_only"},
            ),
        ],
    )
    doc = build_sd_nav_document(g)
    south = next(e for e in doc["edges"] if e["id"] == "e_south")
    east = next(e for e in doc["edges"] if e["id"] == "e_east")
    assert south["direction_observed"] == "forward_only"
    assert south["allowed_maneuvers_reverse"] == []
    assert east["direction_observed"] == "bidirectional"
    assert east["allowed_maneuvers_reverse"] != []


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
