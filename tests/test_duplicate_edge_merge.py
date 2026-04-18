from __future__ import annotations

import math

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.pipeline.build_graph import merge_duplicate_edges


def _graph_with_duplicate_edges():
    """Two edges between n0 ↔ n1 — one offset +1 m, one offset −1 m in y."""
    return Graph(
        nodes=[
            Node(id="n0", position=(0.0, 0.0)),
            Node(id="n1", position=(10.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 1.0), (5.0, 1.0), (10.0, 1.0)],
                attributes={"kind": "lane_centerline", "source": "trajectory_mvp"},
            ),
            Edge(
                id="e1",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, -1.0), (5.0, -1.0), (10.0, -1.0)],
                attributes={"kind": "lane_centerline", "source": "trajectory_mvp"},
            ),
        ],
    )


def test_merge_duplicate_edges_folds_two_into_one():
    g = _graph_with_duplicate_edges()
    removed = merge_duplicate_edges(g, resample_bins=5)
    assert removed == 1
    assert len(g.edges) == 1
    e = g.edges[0]
    assert e.start_node_id == "n0" and e.end_node_id == "n1"
    assert e.attributes["merged_edge_count"] == 2
    # Averaged polyline should sit on the centerline y = 0.
    for x, y in e.polyline:
        assert math.isclose(y, 0.0, abs_tol=1e-9)


def test_merge_duplicate_edges_reorients_reversed_polyline():
    # Second edge goes n1 → n0 (reverse direction), offset sideways; should
    # still average with the first to the centerline.
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
                polyline=[(0.0, 2.0), (10.0, 2.0)],
                attributes={"kind": "lane_centerline", "source": "trajectory_mvp"},
            ),
            Edge(
                id="e1",
                start_node_id="n1",
                end_node_id="n0",
                polyline=[(10.0, -2.0), (0.0, -2.0)],
                attributes={"kind": "lane_centerline", "source": "trajectory_mvp"},
            ),
        ],
    )
    removed = merge_duplicate_edges(g, resample_bins=5)
    assert removed == 1
    e = g.edges[0]
    assert e.start_node_id == "n0" and e.end_node_id == "n1"
    # Averaged y = 0 after reorienting the reversed polyline.
    for _x, y in e.polyline:
        assert math.isclose(y, 0.0, abs_tol=1e-9)


def test_merge_duplicate_edges_leaves_unique_edges_alone():
    g = Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(10.0, 0.0)),
            Node(id="c", position=(20.0, 0.0)),
        ],
        edges=[
            Edge(id="e0", start_node_id="a", end_node_id="b", polyline=[(0, 0), (10, 0)]),
            Edge(id="e1", start_node_id="b", end_node_id="c", polyline=[(10, 0), (20, 0)]),
        ],
    )
    removed = merge_duplicate_edges(g)
    assert removed == 0
    assert len(g.edges) == 2
