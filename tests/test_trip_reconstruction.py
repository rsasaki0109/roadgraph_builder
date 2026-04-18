from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.routing.trip_reconstruction import (
    reconstruct_trips,
    trip_stats_summary,
)


def _straight_graph():
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


def test_single_continuous_trajectory_becomes_one_trip():
    g = _straight_graph()
    xy = np.array([[i * 10.0, 0.0] for i in range(11)], dtype=np.float64)
    ts = np.arange(11, dtype=np.float64)
    traj = Trajectory(timestamps=ts, xy=xy)
    trips = reconstruct_trips(g, traj, min_trip_distance_m=1.0, min_trip_samples=3)
    assert len(trips) == 1
    t = trips[0]
    assert t.sample_count == 11
    assert t.matched_sample_count == 11
    assert t.edge_sequence == ["e0"]
    assert t.start_edge_id == "e0"
    assert t.end_edge_id == "e0"
    assert t.total_distance_m == 100.0


def test_time_gap_splits_into_two_trips():
    g = _straight_graph()
    # First half samples at t=0..5, then a 400 s gap, then samples at t=405..410.
    xy = np.concatenate([
        np.array([[i * 10.0, 0.0] for i in range(6)]),
        np.array([[500.0 + i * 10.0, 0.0] for i in range(6)]),
    ])
    ts = np.concatenate([
        np.arange(6, dtype=np.float64),
        np.arange(405.0, 411.0),
    ])
    traj = Trajectory(timestamps=ts, xy=xy)
    trips = reconstruct_trips(
        g,
        traj,
        max_time_gap_s=60.0,
        min_trip_samples=3,
        min_trip_distance_m=1.0,
    )
    assert len(trips) == 2
    assert trips[0].trip_id == 0
    assert trips[1].trip_id == 1
    # Continuity within each trip.
    assert trips[0].sample_count == 6
    assert trips[1].sample_count == 6


def test_stop_window_splits_into_two_trips():
    g = _straight_graph()
    # Drive for 6 samples, stop for 90 s (samples 6-14 at y=0.0, x fixed),
    # then drive another 6 samples.
    moving1 = [(i * 10.0, 0.0) for i in range(6)]
    stop = [(50.0, 0.0)] * 9  # 9 samples 10 s apart → 90 s of standing still
    moving2 = [(50.0 + i * 10.0, 0.0) for i in range(6)]
    xy = np.array(moving1 + stop + moving2, dtype=np.float64)
    ts = np.array(
        list(range(6))
        + [6 + i * 10.0 for i in range(9)]
        + [96 + i for i in range(6)],
        dtype=np.float64,
    )
    traj = Trajectory(timestamps=ts, xy=xy)
    trips = reconstruct_trips(
        g,
        traj,
        stop_speed_mps=0.5,
        stop_min_duration_s=30.0,
        min_trip_samples=3,
        min_trip_distance_m=1.0,
    )
    assert len(trips) == 2


def test_trip_stats_summary_aggregates():
    g = _straight_graph()
    xy = np.array([[i * 10.0, 0.0] for i in range(11)], dtype=np.float64)
    ts = np.arange(11, dtype=np.float64)
    traj = Trajectory(timestamps=ts, xy=xy)
    trips = reconstruct_trips(g, traj, min_trip_distance_m=1.0)
    s = trip_stats_summary(trips)
    assert s["trip_count"] == 1
    assert s["total_distance_m"] == 100.0
    assert s["total_samples"] == 11


def test_reconstruct_trips_cli(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    g = _straight_graph()
    gjson = tmp_path / "g.json"
    export_graph_json(g, gjson)

    csv = tmp_path / "t.csv"
    lines = ["timestamp,x,y\n"]
    for i in range(11):
        lines.append(f"{i},{i * 10.0:.1f},0.0\n")
    csv.write_text("".join(lines), encoding="utf-8")

    out_json = tmp_path / "trips.json"
    rc = main(
        [
            "reconstruct-trips",
            str(gjson),
            str(csv),
            "--output",
            str(out_json),
            "--min-trip-distance-m",
            "1",
        ]
    )
    assert rc == 0
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert doc["stats"]["trip_count"] == 1
    assert doc["trips"][0]["edge_sequence"] == ["e0"]
