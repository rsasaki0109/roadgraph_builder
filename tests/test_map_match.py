from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.routing.map_match import (
    SnappedPoint,
    coverage_stats,
    snap_trajectory_to_graph,
)


def _linear_graph():
    return Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(100.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="a",
                end_node_id="b",
                polyline=[(0.0, 0.0), (25.0, 0.0), (50.0, 0.0), (75.0, 0.0), (100.0, 0.0)],
                attributes={},
            )
        ],
    )


def test_snap_projects_perpendicular_sample_onto_edge():
    g = _linear_graph()
    xy = np.array([[50.0, 2.0]])  # 2 m off the x-axis edge
    out = snap_trajectory_to_graph(g, xy, max_distance_m=5.0)
    assert len(out) == 1
    s = out[0]
    assert isinstance(s, SnappedPoint)
    assert s.edge_id == "e0"
    assert s.projection_xy_m == (50.0, 0.0)
    assert abs(s.distance_m - 2.0) < 1e-9
    # The edge is 100 m, projection is at 50 m → t = 0.5.
    assert abs(s.t - 0.5) < 1e-9


def test_snap_returns_none_for_far_samples():
    g = _linear_graph()
    xy = np.array([[50.0, 20.0]])  # 20 m away, max_distance_m = 5 m
    out = snap_trajectory_to_graph(g, xy, max_distance_m=5.0)
    assert out == [None]


def test_snap_preserves_graph_order_tie_break():
    g = Graph(
        nodes=[
            Node(id="a", position=(0.0, -1.0)),
            Node(id="b", position=(10.0, -1.0)),
            Node(id="c", position=(0.0, 1.0)),
            Node(id="d", position=(10.0, 1.0)),
        ],
        edges=[
            Edge(
                id="first",
                start_node_id="a",
                end_node_id="b",
                polyline=[(0.0, -1.0), (10.0, -1.0)],
                attributes={},
            ),
            Edge(
                id="second",
                start_node_id="c",
                end_node_id="d",
                polyline=[(0.0, 1.0), (10.0, 1.0)],
                attributes={},
            ),
        ],
    )

    out = snap_trajectory_to_graph(g, np.array([[5.0, 0.0]]), max_distance_m=5.0)

    assert out[0] is not None
    assert out[0].edge_id == "first"


def test_snap_finds_long_overflow_segment_near_middle():
    g = Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(10_000.0, 0.0)),
        ],
        edges=[
            Edge(
                id="long",
                start_node_id="a",
                end_node_id="b",
                polyline=[(0.0, 0.0), (10_000.0, 0.0)],
                attributes={},
            )
        ],
    )

    out = snap_trajectory_to_graph(g, np.array([[5_000.0, 2.0]]), max_distance_m=5.0)

    assert out[0] is not None
    assert out[0].edge_id == "long"
    assert out[0].projection_xy_m == (5_000.0, 0.0)
    assert abs(out[0].t - 0.5) < 1e-9


def test_snap_edge_index_tracks_in_place_polyline_replacement():
    g = _linear_graph()
    assert snap_trajectory_to_graph(g, np.array([[50.0, 0.0]]), max_distance_m=1.0)[0] is not None

    g.edges[0].polyline[:] = [(100.0, 100.0), (200.0, 100.0)]

    out = snap_trajectory_to_graph(g, np.array([[50.0, 0.0]]), max_distance_m=1.0)

    assert out == [None]


def test_coverage_stats_summarises_matches():
    g = _linear_graph()
    xy = np.array([[25.0, 1.0], [50.0, 0.5], [999.0, 0.0]])  # 3rd is far
    snapped = snap_trajectory_to_graph(g, xy, max_distance_m=5.0)
    stats = coverage_stats(snapped)
    assert stats["samples"] == 3
    assert stats["matched"] == 2
    assert stats["edges_touched"] == 1
    assert stats["mean_distance_m"] < 1.5
    assert stats["max_distance_m"] < 2.0


def test_match_trajectory_cli_writes_output(tmp_path: Path, capsys):
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    g = _linear_graph()
    gjson = tmp_path / "g.json"
    export_graph_json(g, gjson)

    csv = tmp_path / "t.csv"
    csv.write_text(
        "timestamp,x,y\n" + "\n".join(f"{i},{25.0 + i * 10.0},0.5" for i in range(5)) + "\n",
        encoding="utf-8",
    )
    out_json = tmp_path / "match.json"
    rc = main(["match-trajectory", str(gjson), str(csv), "--output", str(out_json)])
    assert rc == 0
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert doc["stats"]["samples"] == 5
    # All 5 samples land within 0.5 m of the x-axis, default max 15 m → all matched.
    assert doc["stats"]["matched"] == 5
    assert doc["stats"]["edges_touched"] == 1
    assert all(s["edge_id"] == "e0" for s in doc["samples"])
