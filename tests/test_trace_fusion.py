from __future__ import annotations

import numpy as np

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.trajectory.loader import Trajectory
from roadgraph_builder.semantics.trace_fusion import (
    coverage_buckets,
    fuse_traces_into_graph,
)


def _straight_graph():
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
                polyline=[(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)],
                attributes={},
            )
        ],
    )


def _traj_along_edge(start_ts: float, n: int = 11) -> Trajectory:
    xy = np.array([[i * 10.0, 0.2] for i in range(n)], dtype=np.float64)
    ts = np.arange(n, dtype=np.float64) + start_ts
    return Trajectory(timestamps=ts, xy=xy)


def test_single_trace_records_matched_samples():
    g = _straight_graph()
    traj = _traj_along_edge(0.0)
    stats = fuse_traces_into_graph(g, [traj])
    assert stats["e0"].trace_observation_count == 1
    assert stats["e0"].matched_samples == 11
    assert g.edges[0].attributes["trace_stats"]["trace_observation_count"] == 1


def test_multiple_traces_accumulate_and_hour_bins():
    g = _straight_graph()
    # Epoch-like timestamps so hour/weekday bins fire.
    # 2026-04-19 09:00 UTC = 1776416400
    t1 = _traj_along_edge(1_776_416_400.0, n=5)  # 09:00 UTC
    # 2026-04-19 20:00 UTC = 1776456000
    t2 = _traj_along_edge(1_776_456_000.0, n=5)
    stats = fuse_traces_into_graph(g, [t1, t2])
    s = stats["e0"]
    assert s.trace_observation_count == 2
    assert s.matched_samples == 10
    assert set(s.observed_hour_bins.keys()) == {9, 20}
    # Two distinct traces → 2 observations at both hours in total.
    assert sum(s.observed_hour_bins.values()) == 10


def test_first_last_timestamps_track_envelope():
    g = _straight_graph()
    t1 = _traj_along_edge(100.0, n=3)
    t2 = _traj_along_edge(5000.0, n=3)
    stats = fuse_traces_into_graph(g, [t1, t2])
    s = stats["e0"]
    assert s.first_observed_timestamp == 100.0
    assert s.last_observed_timestamp == 5002.0


def test_coverage_buckets_partitions_edges():
    nodes = [
        Node(id="a", position=(0.0, 0.0)),
        Node(id="b", position=(100.0, 0.0)),
        Node(id="c", position=(200.0, 0.0)),
    ]
    edges = [
        Edge(id="e0", start_node_id="a", end_node_id="b", polyline=[(0, 0), (100, 0)]),
        Edge(id="e1", start_node_id="b", end_node_id="c", polyline=[(100, 0), (200, 0)]),
    ]
    g = Graph(nodes=nodes, edges=edges)
    # Trace only covers e0.
    traj = _traj_along_edge(0.0, n=5)
    stats = fuse_traces_into_graph(g, [traj])
    buckets = coverage_buckets(stats)
    assert buckets["1"] == 1
    assert buckets["0"] == 1
    assert buckets["2_plus"] == 0


def test_trace_touches_counted_once_per_trace_even_with_many_samples():
    g = _straight_graph()
    # 100 samples, all on the same single edge — should count as 1 trace
    # observation for that edge.
    xy = np.array([[i * 1.0, 0.1] for i in range(100)], dtype=np.float64)
    ts = np.arange(100, dtype=np.float64)
    traj = Trajectory(timestamps=ts, xy=xy)
    stats = fuse_traces_into_graph(g, [traj])
    assert stats["e0"].trace_observation_count == 1
    assert stats["e0"].matched_samples == 100


def test_fuse_traces_cli(tmp_path, capsys):
    from pathlib import Path
    from roadgraph_builder.cli.main import main
    from roadgraph_builder.io.export.json_exporter import export_graph_json

    g = _straight_graph()
    gjson = tmp_path / "g.json"
    export_graph_json(g, gjson)

    csv_paths = []
    for idx, start_ts in enumerate([0.0, 10000.0]):
        p = tmp_path / f"t{idx}.csv"
        p.write_text(
            "timestamp,x,y\n"
            + "\n".join(f"{start_ts + i:.1f},{i * 10.0:.1f},0.0" for i in range(11))
            + "\n",
            encoding="utf-8",
        )
        csv_paths.append(str(p))

    out_json = tmp_path / "fused.json"
    rc = main(["fuse-traces", str(gjson), *csv_paths, str(out_json)])
    assert rc == 0
    import json

    doc = json.loads(out_json.read_text(encoding="utf-8"))
    e0_stats = doc["edges"][0]["attributes"]["trace_stats"]
    assert e0_stats["trace_observation_count"] == 2
    assert e0_stats["matched_samples"] == 22
