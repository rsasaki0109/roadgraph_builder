from __future__ import annotations

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.semantics.signals import (
    detect_stop_events,
    infer_signalized_junctions,
)


def _t_junction_graph():
    return Graph(
        nodes=[
            Node(id="j", position=(0.0, 0.0), attributes={"junction_hint": "multi_branch"}),
            Node(id="w", position=(-50.0, 0.0), attributes={"junction_hint": "dead_end"}),
            Node(id="e", position=(50.0, 0.0), attributes={"junction_hint": "dead_end"}),
            Node(id="s", position=(0.0, -50.0), attributes={"junction_hint": "dead_end"}),
        ],
        edges=[
            Edge(id="eW", start_node_id="w", end_node_id="j", polyline=[(-50, 0), (0, 0)], attributes={}),
            Edge(id="eE", start_node_id="j", end_node_id="e", polyline=[(0, 0), (50, 0)], attributes={}),
            Edge(id="eS", start_node_id="j", end_node_id="s", polyline=[(0, 0), (0, -50)], attributes={}),
        ],
    )


def _trajectory_with_two_stops_at_junction(junction_xy=(0.0, 0.0)) -> Trajectory:
    # Approach, stop 60 s at junction, leave, come back later, stop 60 s again.
    samples: list[tuple[float, float, float]] = []
    jx, jy = junction_xy
    # Approach from -40 m → junction over 10 s
    for i, t in enumerate(np.linspace(0.0, 10.0, 5)):
        frac = i / 4.0
        samples.append((float(t), -40.0 + 40.0 * frac + jx, jy))
    # Stop at junction 60 s
    for t in np.linspace(10.0, 70.0, 30):
        samples.append((float(t), jx, jy))
    # Depart + drive away
    for i, t in enumerate(np.linspace(70.0, 90.0, 10)):
        samples.append((float(t), jx + (i + 1) * 5.0, jy))
    # Long time gap
    # Come back and stop again
    for i, t in enumerate(np.linspace(500.0, 510.0, 5)):
        samples.append((float(t), -40.0 + (i + 1) * 8.0 + jx, jy))
    for t in np.linspace(510.0, 570.0, 30):
        samples.append((float(t), jx, jy))
    for i, t in enumerate(np.linspace(570.0, 590.0, 10)):
        samples.append((float(t), jx + (i + 1) * 5.0, jy))
    ts = np.array([s[0] for s in samples], dtype=np.float64)
    xy = np.array([[s[1], s[2]] for s in samples], dtype=np.float64)
    return Trajectory(timestamps=ts, xy=xy)


def test_detect_stop_events_finds_two_stops_at_junction():
    g = _t_junction_graph()
    traj = _trajectory_with_two_stops_at_junction()
    events = detect_stop_events(g, traj, stop_min_duration_s=30.0, max_distance_m=5.0)
    assert len(events) == 2
    # Both stops should anchor at the junction node j.
    assert all(ev.node_id == "j" for ev in events)
    for ev in events:
        assert ev.duration_s >= 30.0
        assert ev.distance_m < 2.0


def test_infer_signalized_junctions_labels_node():
    g = _t_junction_graph()
    traj = _trajectory_with_two_stops_at_junction()
    labelled = infer_signalized_junctions(
        g, traj, stop_min_duration_s=30.0, max_distance_m=5.0, min_stops=2
    )
    assert labelled == {"j": 2}
    node = next(n for n in g.nodes if n.id == "j")
    assert node.attributes.get("signalized_candidate") is True
    assert node.attributes.get("stop_event_count") == 2
    assert node.attributes.get("stop_event_total_seconds", 0) >= 60.0


def test_single_stop_below_threshold_leaves_node_unlabelled():
    g = _t_junction_graph()
    traj = _trajectory_with_two_stops_at_junction()
    # Require 5 stops but there are only 2.
    labelled = infer_signalized_junctions(g, traj, stop_min_duration_s=30.0, min_stops=5)
    assert labelled == {}
    node = next(n for n in g.nodes if n.id == "j")
    assert node.attributes.get("signalized_candidate") is None


def test_stop_far_from_any_node_is_ignored():
    g = _t_junction_graph()
    # Stop in a location 60 m from any node — outside default max_distance_m=20.
    samples = []
    for i, t in enumerate(np.linspace(0.0, 60.0, 30)):
        samples.append((float(t), 200.0, 200.0))
    ts = np.array([s[0] for s in samples])
    xy = np.array([[s[1], s[2]] for s in samples])
    traj = Trajectory(timestamps=ts, xy=xy)
    events = detect_stop_events(g, traj, max_distance_m=10.0)
    assert events == []
