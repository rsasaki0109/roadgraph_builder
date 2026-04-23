from __future__ import annotations

import argparse
import io
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from roadgraph_builder.cli.trajectory import (
    add_match_diagnostics,
    fuse_trace_summary,
    hmm_matches_to_document,
    match_trajectory_diagnostics,
    road_class_counts_document,
    run_fuse_traces,
    run_infer_road_class,
    run_match_trajectory,
    run_reconstruct_trips,
    run_stats,
    signalized_junctions_document,
    snapped_matches_to_document,
    trips_to_document,
)


@dataclass
class _Trip:
    trip_id: int
    start_index: int
    end_index: int
    start_timestamp: float
    end_timestamp: float
    duration_s: float
    start_xy_m: tuple[float, float]
    end_xy_m: tuple[float, float]
    start_edge_id: str
    end_edge_id: str
    edge_sequence: list[str]
    sample_count: int
    matched_sample_count: int
    total_distance_m: float
    mean_speed_mps: float


@dataclass
class _EdgeStats:
    trace_observation_count: int
    matched_samples: int


@dataclass
class _HmmHit:
    index: int
    edge_id: str
    distance_m: float
    projection_xy_m: tuple[float, float]


@dataclass
class _SnapHit:
    index: int
    edge_id: str
    distance_m: float
    arc_length_m: float
    edge_length_m: float
    t: float
    projection_xy_m: tuple[float, float]


def _trip() -> _Trip:
    return _Trip(
        trip_id=7,
        start_index=1,
        end_index=3,
        start_timestamp=10.0,
        end_timestamp=20.0,
        duration_s=10.0,
        start_xy_m=(0.0, 1.0),
        end_xy_m=(2.0, 3.0),
        start_edge_id="e0",
        end_edge_id="e1",
        edge_sequence=["e0", "e1"],
        sample_count=3,
        matched_sample_count=2,
        total_distance_m=12.0,
        mean_speed_mps=1.2,
    )


def test_trip_and_summary_documents_keep_cli_shape():
    doc = trips_to_document([_trip()], {"trip_count": 1})

    assert doc["stats"] == {"trip_count": 1}
    assert doc["trips"][0]["trip_id"] == 7
    assert doc["trips"][0]["start_xy_m"] == [0.0, 1.0]
    assert signalized_junctions_document({"n1": 2}) == {
        "signalized_candidates": 1,
        "details": {"n1": 2},
    }
    assert road_class_counts_document({"highway": 2}, total_edges=3) == {
        "road_class_counts": {"highway": 2},
        "total_edges": 3,
    }


def test_fuse_trace_summary_counts_observations():
    stats = {
        "e0": _EdgeStats(trace_observation_count=0, matched_samples=0),
        "e1": _EdgeStats(trace_observation_count=2, matched_samples=7),
    }

    assert fuse_trace_summary(stats, trajectory_count=3) == {
        "trajectories": 3,
        "edges_with_observations": 1,
        "total_matched_samples": 7,
        "total_trace_edge_hits": 2,
        "coverage_buckets": {"0": 1, "1": 0, "2_plus": 1, "5_plus": 0},
    }


def test_match_serializers_keep_hmm_and_nearest_shapes():
    hmm_doc = hmm_matches_to_document([_HmmHit(0, "e0", 1.5, (1.0, 2.0)), None])
    assert hmm_doc["stats"]["algorithm"] == "hmm_viterbi"
    assert hmm_doc["stats"]["matched_ratio"] == 0.5
    assert hmm_doc["samples"] == [
        {"index": 0, "edge_id": "e0", "distance_m": 1.5, "projection_xy_m": [1.0, 2.0]},
        {"index": 1, "unmatched": True},
    ]

    snap_doc = snapped_matches_to_document(
        [_SnapHit(0, "e1", 0.5, 4.0, 10.0, 0.4, (4.0, 0.0)), None],
        coverage_stats_func=lambda snapped: {"samples": 2, "matched": 1},
    )
    assert snap_doc["stats"] == {"samples": 2, "matched": 1, "algorithm": "nearest_edge"}
    assert snap_doc["samples"][0]["arc_length_m"] == 4.0
    assert snap_doc["samples"][1] == {"index": 1, "unmatched": True}


def test_add_match_diagnostics_is_optional_and_nested_in_stats():
    doc = {"stats": {"algorithm": "nearest_edge"}, "samples": []}

    assert add_match_diagnostics(doc, None) is doc
    add_match_diagnostics(doc, {"elapsed_ms": 1.25, "edge_index": {"enabled": True}})

    assert doc["stats"]["diagnostics"] == {
        "elapsed_ms": 1.25,
        "edge_index": {"enabled": True},
    }


def test_match_trajectory_diagnostics_reports_edge_index_stats():
    from roadgraph_builder.core.graph.edge import Edge
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.core.graph.node import Node

    graph = Graph(
        nodes=[
            Node(id="a", position=(0.0, 0.0)),
            Node(id="b", position=(10.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="a",
                end_node_id="b",
                polyline=[(0.0, 0.0), (10.0, 0.0)],
            )
        ],
    )

    diag = match_trajectory_diagnostics(
        graph,
        algorithm="nearest_edge",
        sample_count=3,
        matched_count=2,
        max_distance_m=5.0,
        elapsed_s=0.012,
    )

    assert diag["projection_queries"] == 3
    assert diag["elapsed_ms"] == 12.0
    assert diag["edge_index"]["enabled"] is True
    assert diag["edge_index"]["segment_count"] == 1


def test_run_reconstruct_trips_injects_logic_and_writes_output(tmp_path: Path):
    output = tmp_path / "trips.json"
    stdout = io.StringIO()

    rc = run_reconstruct_trips(
        argparse.Namespace(
            input_json="graph.json",
            input_csv="trace.csv",
            output=str(output),
            max_time_gap_s=1.0,
            max_spatial_gap_m=2.0,
            stop_speed_mps=3.0,
            stop_min_duration_s=4.0,
            min_trip_samples=5,
            min_trip_distance_m=6.0,
            snap_max_distance_m=7.0,
        ),
        load_graph=lambda path: "graph",  # type: ignore[return-value]
        load_trajectory_csv_func=lambda path: "traj",
        reconstruct_trips_func=lambda graph, traj, **kwargs: [_trip()],
        trip_stats_summary_func=lambda trips: {"trip_count": len(trips)},
        stdout=stdout,
    )

    assert rc == 0
    assert json.loads(stdout.getvalue()) == {"trip_count": 1}
    assert json.loads(output.read_text(encoding="utf-8"))["trips"][0]["edge_sequence"] == ["e0", "e1"]


def test_run_fuse_traces_injects_loaders_exporter_and_summary():
    calls: list[tuple[object, ...]] = []
    stdout = io.StringIO()

    rc = run_fuse_traces(
        argparse.Namespace(
            input_json="graph.json",
            trajectory_csvs=["a.csv", "b.csv"],
            output_json="out.json",
            snap_max_distance_m=9.0,
        ),
        load_graph=lambda path: "graph",  # type: ignore[return-value]
        load_trajectory_csv_func=lambda path: f"traj:{path}",
        fuse_traces_into_graph_func=lambda graph, trajectories, **kwargs: calls.append(
            ("fuse", graph, trajectories, kwargs)
        )
        or {"e0": _EdgeStats(trace_observation_count=2, matched_samples=4)},
        export_graph_json_func=lambda graph, path: calls.append(("export", graph, path)),
        stdout=stdout,
    )

    assert rc == 0
    assert calls == [
        ("fuse", "graph", ["traj:a.csv", "traj:b.csv"], {"snap_max_distance_m": 9.0}),
        ("export", "graph", "out.json"),
    ]
    assert json.loads(stdout.getvalue())["total_matched_samples"] == 4


def test_run_infer_road_class_injects_thresholds_and_exports():
    calls: list[tuple[object, ...]] = []
    stdout = io.StringIO()
    graph = SimpleNamespace(edges=[object(), object()])

    rc = run_infer_road_class(
        argparse.Namespace(
            input_json="graph.json",
            input_csv="trace.csv",
            output_json="out.json",
            max_distance_m=8.0,
            min_samples=3,
            highway_mps=20.0,
            arterial_mps=10.0,
        ),
        load_graph=lambda path: graph,  # type: ignore[return-value]
        load_trajectory_csv_func=lambda path: "traj",
        thresholds_factory=lambda **kwargs: {"thresholds": kwargs},
        infer_road_class_func=lambda graph_arg, traj, **kwargs: calls.append(
            ("infer", graph_arg, traj, kwargs)
        )
        or {"arterial": 1},
        export_graph_json_func=lambda graph_arg, path: calls.append(("export", graph_arg, path)),
        stdout=stdout,
    )

    assert rc == 0
    assert calls[0][0] == "infer"
    assert calls[0][3]["thresholds"] == {"thresholds": {"highway_mps": 20.0, "arterial_mps": 10.0}}
    assert calls[1] == ("export", graph, "out.json")
    assert json.loads(stdout.getvalue()) == {"road_class_counts": {"arterial": 1}, "total_edges": 2}


def test_run_match_trajectory_injects_nearest_path(tmp_path: Path):
    output = tmp_path / "match.json"
    stdout = io.StringIO()
    traj = SimpleNamespace(xy="xy")

    rc = run_match_trajectory(
        argparse.Namespace(
            input_json="graph.json",
            input_csv="trace.csv",
            output=str(output),
            hmm=False,
            max_distance_m=6.0,
            gps_sigma_m=5.0,
            transition_limit_m=200.0,
        ),
        load_graph=lambda path: "graph",  # type: ignore[return-value]
        load_trajectory_csv_func=lambda path: traj,
        snap_trajectory_to_graph_func=lambda graph, xy, **kwargs: [
            _SnapHit(0, "e0", 0.5, 1.0, 2.0, 0.5, (1.0, 0.0))
        ],
        coverage_stats_func=lambda snapped: {"samples": 1, "matched": 1},
        stdout=stdout,
    )

    assert rc == 0
    assert json.loads(stdout.getvalue())["algorithm"] == "nearest_edge"
    assert json.loads(output.read_text(encoding="utf-8"))["samples"][0]["edge_id"] == "e0"


def test_run_match_trajectory_explain_includes_diagnostics(tmp_path: Path):
    output = tmp_path / "match.json"
    stdout = io.StringIO()
    traj = SimpleNamespace(xy=[(0.0, 0.0), (1.0, 0.0)])
    calls: list[dict[str, object]] = []

    rc = run_match_trajectory(
        argparse.Namespace(
            input_json="graph.json",
            input_csv="trace.csv",
            output=str(output),
            explain=True,
            hmm=False,
            max_distance_m=6.0,
            gps_sigma_m=5.0,
            transition_limit_m=200.0,
        ),
        load_graph=lambda path: "graph",  # type: ignore[return-value]
        load_trajectory_csv_func=lambda path: traj,
        snap_trajectory_to_graph_func=lambda graph, xy, **kwargs: [
            _SnapHit(0, "e0", 0.5, 1.0, 2.0, 0.5, (1.0, 0.0)),
            None,
        ],
        coverage_stats_func=lambda snapped: {"samples": 2, "matched": 1},
        match_trajectory_diagnostics_func=lambda graph, **kwargs: calls.append(kwargs)
        or {
            "projection_queries": kwargs["sample_count"],
            "edge_index": {"enabled": True},
        },
        stdout=stdout,
    )

    assert rc == 0
    stats_stdout = json.loads(stdout.getvalue())
    stats_file = json.loads(output.read_text(encoding="utf-8"))["stats"]
    assert stats_stdout["diagnostics"]["projection_queries"] == 2
    assert stats_file["diagnostics"]["edge_index"] == {"enabled": True}
    assert calls[0]["algorithm"] == "nearest_edge"
    assert calls[0]["matched_count"] == 1


def test_run_stats_injects_graph_and_junction_stats():
    stdout = io.StringIO()

    rc = run_stats(
        argparse.Namespace(input_json="graph.json", origin_lat=1.0, origin_lon=2.0),
        load_graph=lambda path: "graph",  # type: ignore[return-value]
        graph_stats_func=lambda graph, **kwargs: {"graph": graph, **kwargs},
        junction_stats_func=lambda graph: {"junctions_for": graph},
        stdout=stdout,
    )

    assert rc == 0
    assert json.loads(stdout.getvalue()) == {
        "graph_stats": {"graph": "graph", "origin_lat": 1.0, "origin_lon": 2.0},
        "junctions": {"junctions_for": "graph"},
    }
