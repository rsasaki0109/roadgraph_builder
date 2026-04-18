from __future__ import annotations

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.semantics.road_class import (
    RoadClassThresholds,
    classify_speed,
    infer_road_class,
)


def _linear_graph():
    return Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(1000.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="a",
                end_node_id="b",
                polyline=[(0.0, 0.0), (500.0, 0.0), (1000.0, 0.0)],
                attributes={},
            )
        ],
    )


def test_classify_speed_default_thresholds():
    assert classify_speed(25.0) == "highway"
    assert classify_speed(15.0) == "arterial"
    assert classify_speed(5.0) == "residential"
    assert classify_speed(10.0) == "arterial"  # boundary included


def test_classify_speed_custom_thresholds():
    th = RoadClassThresholds(highway_mps=30.0, arterial_mps=15.0)
    assert classify_speed(25.0, th) == "arterial"
    assert classify_speed(35.0, th) == "highway"


def test_infer_road_class_high_speed_marks_highway():
    g = _linear_graph()
    # 25 m/s → highway. 10 samples 25 m apart covering the edge.
    xy = np.array([[i * 100.0, 0.0] for i in range(11)], dtype=np.float64)
    ts = np.arange(11, dtype=np.float64) * 4.0  # 100 m / 4 s = 25 m/s
    traj = Trajectory(timestamps=ts, xy=xy)
    counts = infer_road_class(g, traj, max_distance_m=1.0, min_samples=3)
    assert counts == {"highway": 1}
    e = g.edges[0]
    assert e.attributes["road_class_inferred"] == "highway"
    assert e.attributes["observed_speed_samples"] >= 3
    assert e.attributes["observed_speed_mps_median"] > 20.0


def test_infer_road_class_low_speed_marks_residential():
    g = _linear_graph()
    xy = np.array([[i * 5.0, 0.0] for i in range(20)], dtype=np.float64)
    ts = np.arange(20, dtype=np.float64) * 1.0  # 5 m / s
    traj = Trajectory(timestamps=ts, xy=xy)
    counts = infer_road_class(g, traj, max_distance_m=1.0, min_samples=3)
    assert counts.get("residential") == 1
    assert g.edges[0].attributes["road_class_inferred"] == "residential"


def test_infer_road_class_skips_edges_without_enough_samples():
    g = _linear_graph()
    # Only two snapped samples on the edge → below default min_samples=3.
    xy = np.array([[0.0, 0.0], [500.0, 0.0]], dtype=np.float64)
    ts = np.array([0.0, 10.0])
    traj = Trajectory(timestamps=ts, xy=xy)
    counts = infer_road_class(g, traj, max_distance_m=1.0, min_samples=3)
    assert counts == {}
    # Edge keeps its attributes clean of road_class_inferred.
    assert "road_class_inferred" not in g.edges[0].attributes
