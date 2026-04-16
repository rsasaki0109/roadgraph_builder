from __future__ import annotations

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.lidar_fusion import closest_point_on_polyline, fuse_lane_boundaries_from_points
from roadgraph_builder.validation import validate_road_graph_document


def test_closest_point_on_horizontal_segment():
    pl = [(0.0, 0.0), (10.0, 0.0)]
    d, arc, c, tan = closest_point_on_polyline(5.0, 1.0, pl)
    assert d == 1.0
    assert abs(arc - 5.0) < 1e-9
    assert abs(c[1]) < 1e-9
    assert tan == (1.0, 0.0)


def test_fuse_straight_edge_left_right():
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0)), Node(id="n1", position=(10.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                attributes={},
            )
        ],
    )
    rows = []
    for x in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]:
        rows.append([x, 0.9])
        rows.append([x, -0.9])
    pts = np.asarray(rows, dtype=np.float64)
    fuse_lane_boundaries_from_points(g, pts, max_dist_m=2.0, bins=16)
    lb = g.edges[0].attributes["hd"]["lane_boundaries"]
    assert len(lb["left"]) >= 2
    assert len(lb["right"]) >= 2
    assert g.metadata["lidar"]["edges_updated"] == 1
    validate_road_graph_document(g.to_dict())


def test_fuse_skips_edge_when_no_points_nearby():
    g = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n0",
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                attributes={},
            )
        ],
    )
    pts = np.array([[1000.0, 1000.0]], dtype=np.float64)
    fuse_lane_boundaries_from_points(g, pts, max_dist_m=0.5, bins=8)
    assert "hd" not in g.edges[0].attributes
    assert g.metadata["lidar"]["edges_updated"] == 0
