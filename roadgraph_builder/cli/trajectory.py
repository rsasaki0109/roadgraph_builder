"""CLI parser and command handlers for trajectory analysis commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.io.trajectory.loader import Trajectory


LoadGraph = Callable[[str], "Graph"]


def add_trajectory_parsers(sub) -> None:  # type: ignore[no-untyped-def]
    """Register trajectory analysis, map matching, and graph stats subcommands."""

    rtp = sub.add_parser(
        "reconstruct-trips",
        help="Partition a long trajectory into discrete trips (gaps + stops + graph snap).",
    )
    rtp.add_argument("input_json", help="Road graph JSON.")
    rtp.add_argument("input_csv", help="Trajectory CSV (timestamp, x, y) in the graph's meter frame.")
    rtp.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional JSON path to write {stats, trips}.",
    )
    rtp.add_argument("--max-time-gap-s", type=float, default=300.0, metavar="S")
    rtp.add_argument("--max-spatial-gap-m", type=float, default=200.0, metavar="M")
    rtp.add_argument("--stop-speed-mps", type=float, default=0.8, metavar="M/S")
    rtp.add_argument("--stop-min-duration-s", type=float, default=60.0, metavar="S")
    rtp.add_argument("--min-trip-samples", type=int, default=3, metavar="N")
    rtp.add_argument("--min-trip-distance-m", type=float, default=10.0, metavar="M")
    rtp.add_argument("--snap-max-distance-m", type=float, default=20.0, metavar="M")

    irc = sub.add_parser(
        "infer-road-class",
        help="Classify every edge as highway/arterial/residential from observed GPS speed.",
    )
    irc.add_argument("input_json", help="Road graph JSON.")
    irc.add_argument("input_csv", help="Trajectory CSV (timestamp, x, y).")
    irc.add_argument("output_json", help="Output JSON path.")
    irc.add_argument(
        "--max-distance-m",
        type=float,
        default=15.0,
        metavar="M",
        help="Samples farther than this from any edge are skipped.",
    )
    irc.add_argument(
        "--min-samples",
        type=int,
        default=3,
        metavar="N",
        help="Minimum consecutive-sample observations per edge before labelling.",
    )
    irc.add_argument(
        "--highway-mps",
        type=float,
        default=20.0,
        metavar="M/S",
        help="Lower bound on median speed for the 'highway' class.",
    )
    irc.add_argument(
        "--arterial-mps",
        type=float,
        default=10.0,
        metavar="M/S",
        help="Lower bound on median speed for the 'arterial' class.",
    )

    sig = sub.add_parser(
        "infer-signalized-junctions",
        help="Tag graph nodes as signalized candidates from stop-window patterns in a GPS trace.",
    )
    sig.add_argument("input_json", help="Road graph JSON.")
    sig.add_argument("input_csv", help="Trajectory CSV (timestamp, x, y).")
    sig.add_argument("output_json", help="Output JSON path.")
    sig.add_argument("--stop-speed-mps", type=float, default=0.8, metavar="M/S")
    sig.add_argument("--stop-min-duration-s", type=float, default=30.0, metavar="S")
    sig.add_argument("--max-distance-m", type=float, default=20.0, metavar="M")
    sig.add_argument("--min-stops", type=int, default=2, metavar="N")

    ft = sub.add_parser(
        "fuse-traces",
        help="Overlay multiple trajectories onto a fixed graph; record per-edge observation stats.",
    )
    ft.add_argument("input_json", help="Road graph JSON (e.g. sim/road_graph.json).")
    ft.add_argument(
        "trajectory_csvs",
        nargs="+",
        help="One or more trajectory CSVs in the graph's meter frame.",
    )
    ft.add_argument("output_json", help="Enriched road graph JSON path.")
    ft.add_argument(
        "--snap-max-distance-m",
        type=float,
        default=15.0,
        metavar="M",
        help="Samples farther than this are ignored per trajectory.",
    )

    mt = sub.add_parser(
        "match-trajectory",
        help="Snap a trajectory CSV to the graph (per-sample nearest-edge projection).",
    )
    mt.add_argument("input_json", help="Road graph JSON.")
    mt.add_argument("input_csv", help="Trajectory CSV (timestamp, x, y) in the graph's meter frame.")
    mt.add_argument(
        "--max-distance-m",
        type=float,
        default=15.0,
        metavar="M",
        help="Samples farther than this from any edge are reported as unmatched.",
    )
    mt.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional JSON path to write the per-sample snap details.",
    )
    mt.add_argument(
        "--hmm",
        action="store_true",
        help=(
            "Viterbi-decode over candidate edges (prefers sequences consistent with the graph topology) "
            "instead of per-sample nearest-edge."
        ),
    )
    mt.add_argument(
        "--gps-sigma-m",
        type=float,
        default=5.0,
        metavar="M",
        help="Gaussian GPS-noise sigma for the HMM emission score (only with --hmm).",
    )
    mt.add_argument(
        "--transition-limit-m",
        type=float,
        default=200.0,
        metavar="M",
        help="Cap on Dijkstra transition distance between consecutive HMM candidates (only with --hmm).",
    )

    st = sub.add_parser(
        "stats",
        help="Print graph_stats + junction breakdown for a road graph JSON.",
    )
    st.add_argument("input_json", help="Road graph JSON (e.g. sim/road_graph.json).")
    st.add_argument(
        "--origin-lat",
        type=float,
        default=None,
        metavar="DEG",
        help="WGS84 origin latitude. Omit to read metadata.map_origin, or skip bbox_wgs84_deg.",
    )
    st.add_argument(
        "--origin-lon",
        type=float,
        default=None,
        metavar="DEG",
        help="WGS84 origin longitude. Omit to read metadata.map_origin, or skip bbox_wgs84_deg.",
    )


def trips_to_document(trips, summary: dict[str, object]) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Serialize reconstructed trips to the CLI JSON shape."""

    return {
        "stats": summary,
        "trips": [
            {
                "trip_id": t.trip_id,
                "start_index": t.start_index,
                "end_index": t.end_index,
                "start_timestamp": t.start_timestamp,
                "end_timestamp": t.end_timestamp,
                "duration_s": t.duration_s,
                "start_xy_m": list(t.start_xy_m),
                "end_xy_m": list(t.end_xy_m),
                "start_edge_id": t.start_edge_id,
                "end_edge_id": t.end_edge_id,
                "edge_sequence": t.edge_sequence,
                "sample_count": t.sample_count,
                "matched_sample_count": t.matched_sample_count,
                "total_distance_m": t.total_distance_m,
                "mean_speed_mps": t.mean_speed_mps,
            }
            for t in trips
        ],
    }


def fuse_trace_summary(stats: dict[str, object], trajectory_count: int) -> dict[str, object]:
    """Build the printed summary for ``fuse-traces``."""

    from roadgraph_builder.semantics.trace_fusion import coverage_buckets

    return {
        "trajectories": trajectory_count,
        "edges_with_observations": sum(1 for s in stats.values() if s.trace_observation_count > 0),
        "total_matched_samples": sum(s.matched_samples for s in stats.values()),
        "total_trace_edge_hits": sum(s.trace_observation_count for s in stats.values()),
        "coverage_buckets": coverage_buckets(stats),  # type: ignore[arg-type]
    }


def signalized_junctions_document(labelled: dict[str, int]) -> dict[str, object]:
    """Build the printed summary for ``infer-signalized-junctions``."""

    return {"signalized_candidates": len(labelled), "details": labelled}


def road_class_counts_document(counts: dict[str, int], total_edges: int) -> dict[str, object]:
    """Build the printed summary for ``infer-road-class``."""

    return {"road_class_counts": counts, "total_edges": total_edges}


def hmm_matches_to_document(hmm_result: list[object | None]) -> dict[str, object]:
    """Serialize HMM map-matching results to the CLI JSON shape."""

    total = len(hmm_result)
    matched = [h for h in hmm_result if h is not None]
    edges_touched = {h.edge_id for h in matched}
    dists = [h.distance_m for h in matched]
    return {
        "stats": {
            "samples": total,
            "matched": len(matched),
            "matched_ratio": (len(matched) / total) if total else 0.0,
            "edges_touched": len(edges_touched),
            "mean_distance_m": float(sum(dists) / len(dists)) if dists else 0.0,
            "max_distance_m": float(max(dists)) if dists else 0.0,
            "algorithm": "hmm_viterbi",
        },
        "samples": [
            {
                "index": h.index,
                "edge_id": h.edge_id,
                "distance_m": h.distance_m,
                "projection_xy_m": list(h.projection_xy_m),
            }
            if h is not None
            else {"index": i, "unmatched": True}
            for i, h in enumerate(hmm_result)
        ],
    }


def snapped_matches_to_document(
    snapped: list[object | None],
    *,
    coverage_stats_func: Callable[[list[object | None]], dict[str, object]],
) -> dict[str, object]:
    """Serialize nearest-edge map-matching results to the CLI JSON shape."""

    return {
        "stats": {**coverage_stats_func(snapped), "algorithm": "nearest_edge"},
        "samples": [
            {
                "index": s.index,
                "edge_id": s.edge_id,
                "distance_m": s.distance_m,
                "arc_length_m": s.arc_length_m,
                "edge_length_m": s.edge_length_m,
                "t": s.t,
                "projection_xy_m": list(s.projection_xy_m),
            }
            if s is not None
            else {"index": i, "unmatched": True}
            for i, s in enumerate(snapped)
        ],
    }


def write_optional_json(path: str | None, document: dict[str, object]) -> None:
    """Write ``document`` when an output path is set."""

    if path:
        Path(path).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_reconstruct_trips(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    load_trajectory_csv_func: Callable[..., "Trajectory"] | None = None,
    reconstruct_trips_func: Callable[..., object] | None = None,
    trip_stats_summary_func: Callable[..., dict[str, object]] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``reconstruct-trips`` from parsed args."""

    if load_trajectory_csv_func is None:
        from roadgraph_builder.io.trajectory.loader import load_trajectory_csv as load_trajectory_csv_func
    if reconstruct_trips_func is None:
        from roadgraph_builder.routing.trip_reconstruction import reconstruct_trips as reconstruct_trips_func
    if trip_stats_summary_func is None:
        from roadgraph_builder.routing.trip_reconstruction import trip_stats_summary as trip_stats_summary_func

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)
    try:
        traj = load_trajectory_csv_func(args.input_csv)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    trips = reconstruct_trips_func(
        graph,
        traj,
        max_time_gap_s=args.max_time_gap_s,
        max_spatial_gap_m=args.max_spatial_gap_m,
        stop_speed_mps=args.stop_speed_mps,
        stop_min_duration_s=args.stop_min_duration_s,
        min_trip_samples=args.min_trip_samples,
        min_trip_distance_m=args.min_trip_distance_m,
        snap_max_distance_m=args.snap_max_distance_m,
    )
    summary = trip_stats_summary_func(trips)
    doc = trips_to_document(trips, summary)
    write_optional_json(args.output, doc)
    print(json.dumps(summary, ensure_ascii=False, indent=2), file=out)
    return 0


def run_fuse_traces(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    export_graph_json_func: Callable[..., object] | None = None,
    load_trajectory_csv_func: Callable[..., "Trajectory"] | None = None,
    fuse_traces_into_graph_func: Callable[..., dict[str, object]] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``fuse-traces`` from parsed args."""

    if export_graph_json_func is None:
        from roadgraph_builder.io.export.json_exporter import export_graph_json as export_graph_json_func
    if load_trajectory_csv_func is None:
        from roadgraph_builder.io.trajectory.loader import load_trajectory_csv as load_trajectory_csv_func
    if fuse_traces_into_graph_func is None:
        from roadgraph_builder.semantics.trace_fusion import fuse_traces_into_graph as fuse_traces_into_graph_func

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)
    trajectories = []
    for p in args.trajectory_csvs:
        try:
            trajectories.append(load_trajectory_csv_func(p))
        except FileNotFoundError as exc:
            print(f"File not found: {exc.filename}", file=err)
            return 1
    stats = fuse_traces_into_graph_func(
        graph,
        trajectories,
        snap_max_distance_m=args.snap_max_distance_m,
    )
    export_graph_json_func(graph, args.output_json)
    print(json.dumps(fuse_trace_summary(stats, len(trajectories)), ensure_ascii=False, indent=2), file=out)
    return 0


def run_infer_signalized_junctions(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    export_graph_json_func: Callable[..., object] | None = None,
    load_trajectory_csv_func: Callable[..., "Trajectory"] | None = None,
    infer_signalized_junctions_func: Callable[..., dict[str, int]] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``infer-signalized-junctions`` from parsed args."""

    if export_graph_json_func is None:
        from roadgraph_builder.io.export.json_exporter import export_graph_json as export_graph_json_func
    if load_trajectory_csv_func is None:
        from roadgraph_builder.io.trajectory.loader import load_trajectory_csv as load_trajectory_csv_func
    if infer_signalized_junctions_func is None:
        from roadgraph_builder.semantics.signals import infer_signalized_junctions as infer_signalized_junctions_func

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)
    try:
        traj = load_trajectory_csv_func(args.input_csv)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    labelled = infer_signalized_junctions_func(
        graph,
        traj,
        stop_speed_mps=args.stop_speed_mps,
        stop_min_duration_s=args.stop_min_duration_s,
        max_distance_m=args.max_distance_m,
        min_stops=args.min_stops,
    )
    export_graph_json_func(graph, args.output_json)
    print(json.dumps(signalized_junctions_document(labelled), ensure_ascii=False, indent=2), file=out)
    return 0


def run_infer_road_class(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    export_graph_json_func: Callable[..., object] | None = None,
    load_trajectory_csv_func: Callable[..., "Trajectory"] | None = None,
    infer_road_class_func: Callable[..., dict[str, int]] | None = None,
    thresholds_factory: Callable[..., object] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``infer-road-class`` from parsed args."""

    if export_graph_json_func is None:
        from roadgraph_builder.io.export.json_exporter import export_graph_json as export_graph_json_func
    if load_trajectory_csv_func is None:
        from roadgraph_builder.io.trajectory.loader import load_trajectory_csv as load_trajectory_csv_func
    if infer_road_class_func is None:
        from roadgraph_builder.semantics.road_class import infer_road_class as infer_road_class_func
    if thresholds_factory is None:
        from roadgraph_builder.semantics.road_class import RoadClassThresholds as thresholds_factory

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)
    try:
        traj = load_trajectory_csv_func(args.input_csv)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    counts = infer_road_class_func(
        graph,
        traj,
        max_distance_m=args.max_distance_m,
        min_samples=args.min_samples,
        thresholds=thresholds_factory(
            highway_mps=args.highway_mps,
            arterial_mps=args.arterial_mps,
        ),
    )
    export_graph_json_func(graph, args.output_json)
    print(json.dumps(road_class_counts_document(counts, len(graph.edges)), ensure_ascii=False, indent=2), file=out)
    return 0


def run_match_trajectory(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    load_trajectory_csv_func: Callable[..., "Trajectory"] | None = None,
    hmm_match_trajectory_func: Callable[..., list[object | None]] | None = None,
    snap_trajectory_to_graph_func: Callable[..., list[object | None]] | None = None,
    coverage_stats_func: Callable[[list[object | None]], dict[str, object]] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``match-trajectory`` from parsed args."""

    if load_trajectory_csv_func is None:
        from roadgraph_builder.io.trajectory.loader import load_trajectory_csv as load_trajectory_csv_func
    if hmm_match_trajectory_func is None:
        from roadgraph_builder.routing.hmm_match import hmm_match_trajectory as hmm_match_trajectory_func
    if snap_trajectory_to_graph_func is None:
        from roadgraph_builder.routing.map_match import snap_trajectory_to_graph as snap_trajectory_to_graph_func
    if coverage_stats_func is None:
        from roadgraph_builder.routing.map_match import coverage_stats as coverage_stats_func

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)
    try:
        traj = load_trajectory_csv_func(args.input_csv)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    if args.hmm:
        doc = hmm_matches_to_document(
            hmm_match_trajectory_func(
                graph,
                traj.xy,
                candidate_radius_m=args.max_distance_m,
                gps_sigma_m=args.gps_sigma_m,
                transition_limit_m=args.transition_limit_m,
            )
        )
    else:
        doc = snapped_matches_to_document(
            snap_trajectory_to_graph_func(graph, traj.xy, max_distance_m=args.max_distance_m),
            coverage_stats_func=coverage_stats_func,
        )
    write_optional_json(args.output, doc)
    print(json.dumps(doc["stats"], ensure_ascii=False, indent=2), file=out)
    return 0


def run_stats(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    graph_stats_func: Callable[..., dict[str, object]] | None = None,
    junction_stats_func: Callable[..., dict[str, object]] | None = None,
    stdout: TextIO | None = None,
) -> int:
    """Execute ``stats`` from parsed args."""

    if graph_stats_func is None:
        from roadgraph_builder.core.graph.stats import graph_stats as graph_stats_func
    if junction_stats_func is None:
        from roadgraph_builder.core.graph.stats import junction_stats as junction_stats_func

    out = stdout if stdout is not None else sys.stdout
    graph = load_graph(args.input_json)
    doc = {
        "graph_stats": graph_stats_func(
            graph,
            origin_lat=args.origin_lat,
            origin_lon=args.origin_lon,
        ),
        "junctions": junction_stats_func(graph),
    }
    print(json.dumps(doc, ensure_ascii=False, indent=2), file=out)
    return 0
