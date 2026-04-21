from __future__ import annotations

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.pipeline.build_graph import merge_near_parallel_edges


def test_merge_near_parallel_unifies_close_endpoint_nodes():
    # Two edges along the same road but each anchoring to slightly different
    # junction nodes (within 2 m of each other at both ends).
    g = Graph(
        nodes=[
            Node(id="a0", position=(0.0, 0.0)),
            Node(id="a1", position=(1.0, 0.0)),
            Node(id="b0", position=(30.0, 0.0)),
            Node(id="b1", position=(31.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="a0",
                end_node_id="b0",
                polyline=[(0.0, 0.0), (15.0, 0.5), (30.0, 0.0)],
                attributes={"kind": "lane_centerline", "source": "trajectory_mvp"},
            ),
            Edge(
                id="e1",
                start_node_id="a1",
                end_node_id="b1",
                polyline=[(1.0, -0.5), (15.0, -0.3), (31.0, 0.0)],
                attributes={"kind": "lane_centerline", "source": "trajectory_mvp"},
            ),
        ],
    )
    removed = merge_near_parallel_edges(g, tolerance_m=5.0, resample_bins=8)
    assert removed == 1
    assert len(g.edges) == 1
    assert len(g.nodes) == 2
    # Merged centerline should follow the road, not either original polyline.
    merged = g.edges[0]
    assert merged.attributes.get("merged_edge_count") == 2


def test_merge_near_parallel_handles_opposite_direction():
    g = Graph(
        nodes=[
            Node(id="a0", position=(0.0, 0.0)),
            Node(id="b0", position=(30.0, 0.0)),
            Node(id="a1", position=(31.0, 0.0)),  # near b0
            Node(id="b1", position=(1.0, 0.0)),  # near a0
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="a0",
                end_node_id="b0",
                polyline=[(0.0, 0.0), (15.0, 0.5), (30.0, 0.0)],
                attributes={"kind": "lane_centerline", "source": "trajectory_mvp"},
            ),
            Edge(
                id="e1",
                start_node_id="a1",
                end_node_id="b1",
                polyline=[(31.0, 0.0), (15.0, -0.3), (1.0, 0.0)],
                attributes={"kind": "lane_centerline", "source": "trajectory_mvp"},
            ),
        ],
    )
    removed = merge_near_parallel_edges(g, tolerance_m=5.0, resample_bins=8)
    assert removed == 1
    assert len(g.edges) == 1


def test_merge_near_parallel_leaves_distinct_edges_alone():
    g = Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(30.0, 0.0)),
            Node(id="c", position=(100.0, 0.0)),
        ],
        edges=[
            Edge(id="e0", start_node_id="a", end_node_id="b", polyline=[(0, 0), (30, 0)]),
            Edge(id="e1", start_node_id="b", end_node_id="c", polyline=[(30, 0), (100, 0)]),
        ],
    )
    removed = merge_near_parallel_edges(g, tolerance_m=5.0)
    assert removed == 0
    assert len(g.edges) == 2
    assert len(g.nodes) == 3


def test_merge_near_parallel_finds_cross_cell_candidates():
    # The spatial index uses threshold-sized cells internally; this case keeps
    # both endpoint pairs close while placing them across cell boundaries.
    g = Graph(
        nodes=[
            Node(id="a0", position=(9.8, 0.0)),
            Node(id="a1", position=(10.2, 0.0)),
            Node(id="b0", position=(39.8, 0.0)),
            Node(id="b1", position=(40.2, 0.0)),
        ],
        edges=[
            Edge(id="e0", start_node_id="a0", end_node_id="b0", polyline=[(9.8, 0.0), (39.8, 0.0)]),
            Edge(id="e1", start_node_id="a1", end_node_id="b1", polyline=[(10.2, 0.0), (40.2, 0.0)]),
        ],
    )
    removed = merge_near_parallel_edges(g, tolerance_m=5.0)
    assert removed == 1
    assert len(g.edges) == 1


def test_merge_near_parallel_requires_total_endpoint_distance_under_threshold():
    # Both endpoints are within the broad candidate radius, but the exact
    # existing fwd/rev sum check should still reject the pair.
    g = Graph(
        nodes=[
            Node(id="a0", position=(0.0, 0.0)),
            Node(id="a1", position=(6.0, 0.0)),
            Node(id="b0", position=(30.0, 0.0)),
            Node(id="b1", position=(36.0, 0.0)),
        ],
        edges=[
            Edge(id="e0", start_node_id="a0", end_node_id="b0", polyline=[(0.0, 0.0), (30.0, 0.0)]),
            Edge(id="e1", start_node_id="a1", end_node_id="b1", polyline=[(6.0, 0.0), (36.0, 0.0)]),
        ],
    )
    removed = merge_near_parallel_edges(g, tolerance_m=5.0)
    assert removed == 0
    assert len(g.edges) == 2


def test_merge_near_parallel_beyond_threshold_ignores():
    # Endpoints ~20 m apart on one side — outside the 2 × tol = 10 m window.
    g = Graph(
        nodes=[
            Node(id="a0", position=(0.0, 0.0)),
            Node(id="a1", position=(20.0, 0.0)),
            Node(id="b0", position=(60.0, 0.0)),
            Node(id="b1", position=(61.0, 0.0)),
        ],
        edges=[
            Edge(id="e0", start_node_id="a0", end_node_id="b0", polyline=[(0, 0), (60, 0)]),
            Edge(id="e1", start_node_id="a1", end_node_id="b1", polyline=[(20, 0), (61, 0)]),
        ],
    )
    removed = merge_near_parallel_edges(g, tolerance_m=5.0)
    assert removed == 0
