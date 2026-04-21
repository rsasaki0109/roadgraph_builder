"""CLI entrypoint."""

from __future__ import annotations

import argparse
import sys

from jsonschema import ValidationError

import json
from pathlib import Path

from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
from roadgraph_builder.cli.camera import (
    add_apply_camera_parser,
    add_detect_lane_markings_camera_parser,
    add_project_camera_parser,
    run_apply_camera,
    run_detect_lane_markings_camera,
    run_project_camera,
)
from roadgraph_builder.cli.lidar import (
    add_detect_lane_markings_parser,
    add_fuse_lidar_parser,
    add_inspect_lidar_parser,
    run_detect_lane_markings,
    run_fuse_lidar,
    run_inspect_lidar,
)
from roadgraph_builder.cli.osm import (
    add_osm_parsers,
    run_build_osm_graph,
    run_convert_osm_restrictions,
)
from roadgraph_builder.cli.guidance import (
    add_guidance_parsers,
    run_guidance,
    run_validate_guidance,
)
from roadgraph_builder.cli.export import (
    add_export_bundle_parser,
    add_lanelet2_parsers,
    run_export_bundle,
    run_export_lanelet2,
    run_validate_lanelet2,
    run_validate_lanelet2_tags,
)
from roadgraph_builder.io.export.json_exporter import export_graph_json
from roadgraph_builder.io.export.json_loader import load_graph_json
from roadgraph_builder.io.trajectory.loader import load_multi_trajectory_csvs, load_trajectory_csv
from roadgraph_builder.cli.doctor import run_doctor
from roadgraph_builder.cli.routing import (
    add_nearest_node_parser,
    add_route_parser,
    run_nearest_node,
    run_route,
)
from roadgraph_builder.utils.geo import load_wgs84_origin_json
from roadgraph_builder.validation import (
    validate_camera_detections_document,
    validate_lane_markings_document,
    validate_manifest_document,
    validate_road_graph_document,
    validate_sd_nav_document,
    validate_turn_restrictions_document,
)
from roadgraph_builder.pipeline.build_graph import (
    BuildParams,
    build_graph_from_csv,
    build_graph_from_trajectory,
)
from roadgraph_builder.core.graph.stats import graph_stats, junction_stats
from roadgraph_builder.routing.hmm_match import hmm_match_trajectory
from roadgraph_builder.routing.map_match import coverage_stats, snap_trajectory_to_graph
from roadgraph_builder.routing.trip_reconstruction import reconstruct_trips, trip_stats_summary
from roadgraph_builder.semantics.road_class import RoadClassThresholds, infer_road_class
from roadgraph_builder.semantics.signals import infer_signalized_junctions
from roadgraph_builder.semantics.trace_fusion import coverage_buckets, fuse_traces_into_graph
from roadgraph_builder.viz.svg_export import write_trajectory_graph_svg


_TRAJECTORY_DTYPE_CHOICES = ("float64", "float32")


def _add_build_params(p: argparse.ArgumentParser, *, include_trajectory_dtype: bool = False) -> None:
    p.add_argument(
        "--max-step-m",
        type=float,
        default=25.0,
        help="Split trajectory when consecutive points exceed this gap (meters).",
    )
    p.add_argument(
        "--merge-endpoint-m",
        type=float,
        default=8.0,
        help="Merge graph endpoints closer than this distance (meters).",
    )
    p.add_argument(
        "--centerline-bins",
        type=int,
        default=32,
        help="PCA bin count along each segment for centerline smoothing.",
    )
    p.add_argument(
        "--simplify-tolerance",
        type=float,
        default=None,
        help="Douglas–Peucker tolerance (meters) for edge polylines; omit to skip.",
    )
    if include_trajectory_dtype:
        p.add_argument(
            "--trajectory-dtype",
            choices=_TRAJECTORY_DTYPE_CHOICES,
            default="float64",
            help=(
                "XY array dtype for trajectory loading (default float64). "
                "float32 is opt-in and may change exported coordinates slightly."
            ),
        )


def _build_params_from_args(args: argparse.Namespace) -> BuildParams:
    use_3d = getattr(args, "use_3d", False)
    return BuildParams(
        max_step_m=args.max_step_m,
        merge_endpoint_m=args.merge_endpoint_m,
        centerline_bins=args.centerline_bins,
        simplify_tolerance_m=args.simplify_tolerance,
        use_3d=use_3d,
        trajectory_xy_dtype=getattr(args, "trajectory_dtype", "float64"),
    )


def _load_json_for_cli(path_str: str) -> object:
    """Read JSON from ``path_str``; exit with code 1 if the file is missing."""
    path = Path(path_str)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"File not found: {path}", file=sys.stderr)
        raise SystemExit(1) from None


def _validation_error(path_str: str, err: ValidationError) -> None:
    print(f"{path_str}: {err.message}", file=sys.stderr)


def _cli_load_graph(path_str: str):
    """Load road graph JSON; exit 1 if the file is missing."""
    p = Path(path_str)
    if not p.is_file():
        print(f"File not found: {p}", file=sys.stderr)
        raise SystemExit(1)
    return load_graph_json(p)


def _build_parser() -> argparse.ArgumentParser:
    from roadgraph_builder import __version__ as _pkg_version

    p = argparse.ArgumentParser(prog="roadgraph_builder", description="Build a road graph from sensor exports.")
    p.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"roadgraph_builder {_pkg_version}",
        help="Print package version and exit.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Print version, Python, and whether example files exist (cwd = repo root).")

    b = sub.add_parser("build", help="Build graph from trajectory CSV and write JSON.")
    b.add_argument("input_csv", help="Input CSV with columns timestamp, x, y (and optional z for 3D builds)")
    b.add_argument("output_json", help="Output JSON path")
    b.add_argument(
        "--extra-csv",
        action="append",
        default=[],
        metavar="PATH",
        help="Additional trajectory CSV to concatenate with the primary input (same meter origin). Repeatable.",
    )
    b.add_argument(
        "--3d",
        dest="use_3d",
        action="store_true",
        default=False,
        help=(
            "Enable 3D mode: read z column from CSV and propagate elevation into the graph. "
            "Adds polyline_z, slope_deg, elevation_m attributes. "
            "Without this flag the output is byte-identical to v0.6.0."
        ),
    )
    _add_build_params(b, include_trajectory_dtype=True)

    v = sub.add_parser("visualize", help="Build graph from CSV and write trajectory+graph SVG.")
    v.add_argument("input_csv", help="Input CSV with columns timestamp, x, y")
    v.add_argument("output_svg", help="Output SVG path")
    _add_build_params(v, include_trajectory_dtype=True)
    v.add_argument(
        "--width",
        type=float,
        default=900,
        help="SVG width in pixels.",
    )
    v.add_argument(
        "--height",
        type=float,
        default=700,
        help="SVG height in pixels.",
    )

    val = sub.add_parser("validate", help="Validate a road graph JSON file against the schema.")
    val.add_argument("input_json", help="JSON file produced by `build`")

    vd = sub.add_parser(
        "validate-detections",
        help="Validate camera/perception detections JSON (camera_detections.schema.json).",
    )
    vd.add_argument("input_json", help="detections.json with observations[]")

    vsd = sub.add_parser(
        "validate-sd-nav",
        help="Validate navigation SD seed JSON (sd_nav.schema.json, e.g. export-bundle nav/sd_nav.json).",
    )
    vsd.add_argument("input_json", help="sd_nav.json")

    vm = sub.add_parser(
        "validate-manifest",
        help="Validate export-bundle manifest.json (manifest.schema.json).",
    )
    vm.add_argument("input_json", help="manifest.json")

    vtr = sub.add_parser(
        "validate-turn-restrictions",
        help="Validate a turn-restrictions JSON (turn_restrictions.schema.json).",
    )
    vtr.add_argument("input_json", help="turn_restrictions.json")

    enr = sub.add_parser(
        "enrich",
        help="Attach SD→HD metadata; optional centerline-offset lane boundaries (--lane-width-m).",
    )
    enr.add_argument("input_json", help="Road graph JSON from `build`")
    enr.add_argument("output_json", help="Output JSON path")
    enr.add_argument(
        "--lane-width-m",
        type=float,
        default=None,
        metavar="M",
        help="Lane width in meters: fill left/right boundaries by offsetting edge centerlines (HD-lite).",
    )
    enr.add_argument(
        "--lane-markings-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional lane_markings.json from detect-lane-markings for per-edge width refinement.",
    )
    enr.add_argument(
        "--camera-detections-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional camera_detections.json for per-edge width refinement.",
    )

    add_inspect_lidar_parser(sub)

    add_nearest_node_parser(sub)
    add_route_parser(sub)

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
        help="Viterbi-decode over candidate edges (prefers sequences consistent with the graph topology) instead of per-sample nearest-edge.",
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

    add_fuse_lidar_parser(sub)

    ilc = sub.add_parser(
        "infer-lane-count",
        help="Infer per-edge lane count and lane geometries; writes hd.lane_count + hd.lanes[] into the graph JSON.",
    )
    ilc.add_argument("input_json", help="Road graph JSON (e.g. from enrich or export-bundle).")
    ilc.add_argument("output_json", help="Output enriched road graph JSON path.")
    ilc.add_argument(
        "--lane-markings-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional lane_markings.json from detect-lane-markings for paint-marker clustering.",
    )
    ilc.add_argument(
        "--base-lane-width-m",
        type=float,
        default=3.5,
        metavar="M",
        help="Assumed single-lane width in meters (default 3.5).",
    )
    ilc.add_argument(
        "--split-gap-m",
        type=float,
        default=2.0,
        metavar="M",
        help="1-D agglomerative clustering gap threshold (meters, default 2.0).",
    )
    ilc.add_argument(
        "--min-lanes",
        type=int,
        default=1,
        metavar="N",
        help="Floor on inferred lane count (default 1).",
    )
    ilc.add_argument(
        "--max-lanes",
        type=int,
        default=6,
        metavar="N",
        help="Ceiling on inferred lane count (default 6).",
    )

    add_lanelet2_parsers(sub)

    add_apply_camera_parser(sub)

    add_export_bundle_parser(
        sub,
        add_build_params=lambda parser: _add_build_params(parser, include_trajectory_dtype=True),
    )

    add_osm_parsers(sub, add_build_params=_add_build_params)

    add_project_camera_parser(sub)

    add_detect_lane_markings_parser(sub)

    add_detect_lane_markings_camera_parser(sub)

    vlm = sub.add_parser(
        "validate-lane-markings",
        help="Validate a lane_markings.json against lane_markings.schema.json.",
    )
    vlm.add_argument("input_json", help="lane_markings.json produced by detect-lane-markings.")

    add_guidance_parsers(sub)

    ug = sub.add_parser(
        "update-graph",
        help="Incrementally merge a new trajectory CSV into an existing graph JSON.",
    )
    ug.add_argument("existing_json", help="Existing road graph JSON (input; never modified).")
    ug.add_argument("new_csv", help="New trajectory CSV (timestamp, x, y) to integrate.")
    ug.add_argument(
        "--output",
        type=str,
        required=True,
        metavar="PATH",
        help="Output path for the merged graph JSON (required).",
    )
    ug.add_argument(
        "--max-step-m",
        type=float,
        default=25.0,
        help="Gap threshold for trajectory segmentation (meters).",
    )
    ug.add_argument(
        "--merge-endpoint-m",
        type=float,
        default=8.0,
        help="Endpoint merge radius: new endpoints within this distance snap to existing nodes (meters).",
    )
    ug.add_argument(
        "--absorb-tolerance-m",
        type=float,
        default=4.0,
        help=(
            "If all points of a new polyline are within this lateral distance of an existing "
            "edge, the edge absorbs the trace (bumps trace_observation_count) instead of "
            "creating a new edge (meters)."
        ),
    )
    ug.add_argument(
        "--trajectory-dtype",
        choices=_TRAJECTORY_DTYPE_CHOICES,
        default="float64",
        help=(
            "XY array dtype for loading new_csv (default float64). "
            "float32 is opt-in and may change merged geometry slightly."
        ),
    )

    pd_cli = sub.add_parser(
        "process-dataset",
        help="Batch-process a directory of trajectory CSVs into per-file export-bundles.",
    )
    pd_cli.add_argument("input_dir", help="Directory containing trajectory CSV files.")
    pd_cli.add_argument("output_dir", help="Output directory (created if absent).")
    pd_cli.add_argument(
        "--origin-json",
        type=str,
        default=None,
        metavar="PATH",
        help="JSON with lat0, lon0 (shared origin for all CSVs in the dataset).",
    )
    pd_cli.add_argument(
        "--pattern",
        type=str,
        default="*.csv",
        metavar="GLOB",
        help="Glob pattern for trajectory files (default: '*.csv').",
    )
    pd_cli.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel worker processes (default: 1 = sequential).",
    )
    pd_cli.add_argument(
        "--continue-on-error",
        action="store_true",
        default=True,
        help="Continue processing other files if one fails (default: true).",
    )
    pd_cli.add_argument(
        "--no-continue-on-error",
        action="store_false",
        dest="continue_on_error",
        help="Abort on the first file error.",
    )
    pd_cli.add_argument(
        "--lane-width-m",
        type=float,
        default=3.5,
        metavar="M",
        help="HD-lite lane width for each bundle (meters, default 3.5).",
    )
    pd_cli.add_argument(
        "--dataset-name",
        type=str,
        default=None,
        metavar="NAME",
        help="Label prefix embedded in per-file GeoJSON/metadata (default: CSV stem).",
    )
    pd_cli.add_argument(
        "--trajectory-dtype",
        choices=_TRAJECTORY_DTYPE_CHOICES,
        default="float64",
        help=(
            "XY array dtype for trajectory loading (default float64). "
            "float32 is opt-in and may change exported coordinates slightly."
        ),
    )

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "doctor":
        return run_doctor()
    if args.command == "build":
        params = _build_params_from_args(args)
        try:
            if args.extra_csv:
                traj = load_multi_trajectory_csvs(
                    [args.input_csv, *args.extra_csv],
                    load_z=params.use_3d,
                    xy_dtype=params.trajectory_xy_dtype,
                )
                graph = build_graph_from_trajectory(traj, params)
            else:
                graph = build_graph_from_csv(args.input_csv, params)
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        export_graph_json(graph, args.output_json)
        return 0
    if args.command == "visualize":
        params = _build_params_from_args(args)
        try:
            traj = load_trajectory_csv(args.input_csv, xy_dtype=params.trajectory_xy_dtype)
            graph = build_graph_from_trajectory(traj, params)
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        write_trajectory_graph_svg(
            traj,
            graph,
            args.output_svg,
            width=args.width,
            height=args.height,
        )
        return 0
    if args.command == "validate":
        data = _load_json_for_cli(args.input_json)
        if not isinstance(data, dict):
            print("JSON root must be an object", file=sys.stderr)
            return 1
        try:
            validate_road_graph_document(data)
        except ValidationError as e:
            _validation_error(args.input_json, e)
            return 1
        return 0
    if args.command == "validate-detections":
        data = _load_json_for_cli(args.input_json)
        if not isinstance(data, dict):
            print("JSON root must be an object", file=sys.stderr)
            return 1
        try:
            validate_camera_detections_document(data)
        except ValidationError as e:
            _validation_error(args.input_json, e)
            return 1
        return 0
    if args.command == "validate-sd-nav":
        data = _load_json_for_cli(args.input_json)
        if not isinstance(data, dict):
            print("JSON root must be an object", file=sys.stderr)
            return 1
        try:
            validate_sd_nav_document(data)
        except ValidationError as e:
            _validation_error(args.input_json, e)
            return 1
        return 0
    if args.command == "validate-manifest":
        data = _load_json_for_cli(args.input_json)
        if not isinstance(data, dict):
            print("JSON root must be an object", file=sys.stderr)
            return 1
        try:
            validate_manifest_document(data)
        except ValidationError as e:
            _validation_error(args.input_json, e)
            return 1
        return 0
    if args.command == "validate-turn-restrictions":
        data = _load_json_for_cli(args.input_json)
        if not isinstance(data, dict):
            print("JSON root must be an object", file=sys.stderr)
            return 1
        try:
            validate_turn_restrictions_document(data)
        except ValidationError as e:
            _validation_error(args.input_json, e)
            return 1
        return 0
    if args.command == "enrich":
        graph = _cli_load_graph(args.input_json)
        refinements = None
        if args.lane_markings_json or args.camera_detections_json:
            from roadgraph_builder.hd.refinement import refine_hd_edges as _refine_hd_edges
            lm_data = _load_json_for_cli(args.lane_markings_json) if args.lane_markings_json else None
            cam_data = _load_json_for_cli(args.camera_detections_json) if args.camera_detections_json else None
            if not isinstance(lm_data, dict) and lm_data is not None:
                print("enrich: --lane-markings-json must be a JSON object.", file=sys.stderr)
                return 1
            if not isinstance(cam_data, dict) and cam_data is not None:
                print("enrich: --camera-detections-json must be a JSON object.", file=sys.stderr)
                return 1
            _graph_json = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
            refinements = _refine_hd_edges(
                _graph_json,
                lane_markings=lm_data,
                camera_detections=cam_data,
                base_lane_width_m=args.lane_width_m or 3.5,
            )
        enrich_sd_to_hd(
            graph,
            SDToHDConfig(lane_width_m=args.lane_width_m),
            refinements=refinements,
        )
        export_graph_json(graph, args.output_json)
        return 0
    if args.command == "nearest-node":
        return run_nearest_node(args, load_graph=_cli_load_graph)
    if args.command == "reconstruct-trips":
        graph = _cli_load_graph(args.input_json)
        try:
            traj = load_trajectory_csv(args.input_csv)
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        trips = reconstruct_trips(
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
        summary = trip_stats_summary(trips)
        doc = {
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
        if args.output:
            Path(args.output).write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.command == "fuse-traces":
        graph = _cli_load_graph(args.input_json)
        trajectories = []
        for p in args.trajectory_csvs:
            try:
                trajectories.append(load_trajectory_csv(p))
            except FileNotFoundError as e:
                print(f"File not found: {e.filename}", file=sys.stderr)
                return 1
        stats = fuse_traces_into_graph(
            graph,
            trajectories,
            snap_max_distance_m=args.snap_max_distance_m,
        )
        export_graph_json(graph, args.output_json)
        buckets = coverage_buckets(stats)
        total_matched = sum(s.matched_samples for s in stats.values())
        total_traces_seen = sum(s.trace_observation_count for s in stats.values())
        print(
            json.dumps(
                {
                    "trajectories": len(trajectories),
                    "edges_with_observations": sum(1 for s in stats.values() if s.trace_observation_count > 0),
                    "total_matched_samples": total_matched,
                    "total_trace_edge_hits": total_traces_seen,
                    "coverage_buckets": buckets,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "infer-signalized-junctions":
        graph = _cli_load_graph(args.input_json)
        try:
            traj = load_trajectory_csv(args.input_csv)
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        labelled = infer_signalized_junctions(
            graph,
            traj,
            stop_speed_mps=args.stop_speed_mps,
            stop_min_duration_s=args.stop_min_duration_s,
            max_distance_m=args.max_distance_m,
            min_stops=args.min_stops,
        )
        export_graph_json(graph, args.output_json)
        print(
            json.dumps(
                {"signalized_candidates": len(labelled), "details": labelled},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "infer-road-class":
        graph = _cli_load_graph(args.input_json)
        try:
            traj = load_trajectory_csv(args.input_csv)
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        counts = infer_road_class(
            graph,
            traj,
            max_distance_m=args.max_distance_m,
            min_samples=args.min_samples,
            thresholds=RoadClassThresholds(
                highway_mps=args.highway_mps,
                arterial_mps=args.arterial_mps,
            ),
        )
        export_graph_json(graph, args.output_json)
        print(json.dumps({"road_class_counts": counts, "total_edges": len(graph.edges)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "match-trajectory":
        graph = _cli_load_graph(args.input_json)
        try:
            traj = load_trajectory_csv(args.input_csv)
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        if args.hmm:
            hmm_result = hmm_match_trajectory(
                graph,
                traj.xy,
                candidate_radius_m=args.max_distance_m,
                gps_sigma_m=args.gps_sigma_m,
                transition_limit_m=args.transition_limit_m,
            )
            total = len(hmm_result)
            matched = [h for h in hmm_result if h is not None]
            edges_touched = {h.edge_id for h in matched}
            dists = [h.distance_m for h in matched]
            stats = {
                "samples": total,
                "matched": len(matched),
                "matched_ratio": (len(matched) / total) if total else 0.0,
                "edges_touched": len(edges_touched),
                "mean_distance_m": float(sum(dists) / len(dists)) if dists else 0.0,
                "max_distance_m": float(max(dists)) if dists else 0.0,
                "algorithm": "hmm_viterbi",
            }
            samples_doc = [
                {
                    "index": h.index,
                    "edge_id": h.edge_id,
                    "distance_m": h.distance_m,
                    "projection_xy_m": list(h.projection_xy_m),
                }
                if h is not None
                else {"index": i, "unmatched": True}
                for i, h in enumerate(hmm_result)
            ]
        else:
            snapped = snap_trajectory_to_graph(graph, traj.xy, max_distance_m=args.max_distance_m)
            stats = {**coverage_stats(snapped), "algorithm": "nearest_edge"}
            samples_doc = [
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
            ]
        doc = {"stats": stats, "samples": samples_doc}
        if args.output:
            Path(args.output).write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        # Always print the stats block so single-run operators see the summary.
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    if args.command == "stats":
        graph = _cli_load_graph(args.input_json)
        doc = {
            "graph_stats": graph_stats(
                graph, origin_lat=args.origin_lat, origin_lon=args.origin_lon
            ),
            "junctions": junction_stats(graph),
        }
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    if args.command == "route":
        return run_route(args, load_graph=_cli_load_graph, load_json=_load_json_for_cli)
    if args.command == "inspect-lidar":
        return run_inspect_lidar(args)
    if args.command == "fuse-lidar":
        return run_fuse_lidar(
            args,
            load_graph=_cli_load_graph,
            export_graph_json_func=export_graph_json,
        )
    if args.command == "infer-lane-count":
        from roadgraph_builder.hd.lane_inference import infer_lane_counts as _infer_lane_counts
        graph = _cli_load_graph(args.input_json)
        graph_json = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
        lm_data = None
        if args.lane_markings_json:
            raw_lm = _load_json_for_cli(args.lane_markings_json)
            if not isinstance(raw_lm, dict):
                print("infer-lane-count: --lane-markings-json must be a JSON object.", file=sys.stderr)
                return 1
            lm_data = raw_lm
        inferences = _infer_lane_counts(
            graph_json,
            lane_markings=lm_data,
            base_lane_width_m=args.base_lane_width_m,
            split_gap_m=args.split_gap_m,
            min_lanes=args.min_lanes,
            max_lanes=args.max_lanes,
        )
        # Write lane_count + lanes[] into each edge's attributes.hd.
        inf_by_id = {inf.edge_id: inf for inf in inferences}
        for edge in graph.edges:
            inf = inf_by_id.get(edge.id)
            if inf is None:
                continue
            attrs = dict(edge.attributes)
            hd = dict(attrs.get("hd", {}))
            hd["lane_count"] = inf.lane_count
            hd["lanes"] = [
                {
                    "lane_index": lg.lane_index,
                    "offset_m": lg.offset_m,
                    "centerline_m": [list(pt) for pt in lg.centerline_m],
                    "confidence": lg.confidence,
                }
                for lg in inf.lanes
            ]
            hd["lane_inference_sources"] = inf.sources_used
            attrs["hd"] = hd
            edge.attributes = attrs
        export_graph_json(graph, args.output_json)
        total_lanes = sum(inf.lane_count for inf in inferences)
        print(
            json.dumps(
                {
                    "edges_processed": len(inferences),
                    "total_lanes_inferred": total_lanes,
                    "sources_summary": {
                        src: sum(1 for inf in inferences if src in inf.sources_used)
                        for src in ("lane_markings", "trace_stats", "default")
                    },
                },
                indent=2,
            )
        )
        return 0
    if args.command == "export-lanelet2":
        return run_export_lanelet2(args, load_graph=_cli_load_graph, load_json=_load_json_for_cli)
    if args.command == "validate-lanelet2":
        return run_validate_lanelet2(args)
    if args.command == "validate-lanelet2-tags":
        return run_validate_lanelet2_tags(args)
    if args.command == "apply-camera":
        return run_apply_camera(
            args,
            load_graph=_cli_load_graph,
            export_graph_json_func=export_graph_json,
        )
    if args.command == "export-bundle":
        return run_export_bundle(
            args,
            build_params_from_args=_build_params_from_args,
            load_origin=load_wgs84_origin_json,
        )
    if args.command == "build-osm-graph":
        return run_build_osm_graph(
            args,
            build_params_from_args=_build_params_from_args,
            load_origin=load_wgs84_origin_json,
            export_graph_json_func=export_graph_json,
        )
    if args.command == "convert-osm-restrictions":
        return run_convert_osm_restrictions(args, load_graph=_cli_load_graph)
    if args.command == "project-camera":
        return run_project_camera(args, load_graph=_cli_load_graph)
    if args.command == "detect-lane-markings":
        return run_detect_lane_markings(args, load_json=_load_json_for_cli)
    if args.command == "detect-lane-markings-camera":
        return run_detect_lane_markings_camera(
            args,
            load_graph=_cli_load_graph,
            load_json=_load_json_for_cli,
        )
    if args.command == "validate-lane-markings":
        data = _load_json_for_cli(args.input_json)
        if not isinstance(data, dict):
            print("JSON root must be an object", file=sys.stderr)
            return 1
        try:
            validate_lane_markings_document(data)
        except ValidationError as e:
            _validation_error(args.input_json, e)
            return 1
        return 0
    if args.command == "guidance":
        return run_guidance(args, load_json=_load_json_for_cli)
    if args.command == "validate-guidance":
        return run_validate_guidance(
            args,
            load_json=_load_json_for_cli,
            validation_error_func=_validation_error,
        )
    if args.command == "update-graph":
        from roadgraph_builder.pipeline.incremental import update_graph_from_trajectory as _update_graph
        existing_path = Path(args.existing_json)
        if not existing_path.is_file():
            print(f"File not found: {existing_path}", file=sys.stderr)
            return 1
        new_csv_path = Path(args.new_csv)
        if not new_csv_path.is_file():
            print(f"File not found: {new_csv_path}", file=sys.stderr)
            return 1
        try:
            graph = load_graph_json(existing_path)
        except (TypeError, ValueError) as e:
            print(f"{existing_path}: {e}", file=sys.stderr)
            return 1
        try:
            new_traj = load_trajectory_csv(new_csv_path, xy_dtype=args.trajectory_dtype)
        except (FileNotFoundError, ValueError) as e:
            print(f"{new_csv_path}: {e}", file=sys.stderr)
            return 1
        merged = _update_graph(
            graph,
            new_traj,
            max_step_m=args.max_step_m,
            merge_endpoint_m=args.merge_endpoint_m,
            absorb_tolerance_m=args.absorb_tolerance_m,
        )
        export_graph_json(merged, args.output)
        print(
            json.dumps(
                {
                    "output": args.output,
                    "nodes": len(merged.nodes),
                    "edges": len(merged.edges),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "process-dataset":
        from roadgraph_builder.cli.dataset import process_dataset as _process_dataset
        input_dir = Path(args.input_dir)
        output_dir = Path(args.output_dir)
        if not input_dir.is_dir():
            print(f"Input directory not found: {input_dir}", file=sys.stderr)
            return 1
        origin_json = Path(args.origin_json) if args.origin_json else None
        if origin_json is not None and not origin_json.is_file():
            print(f"Origin JSON not found: {origin_json}", file=sys.stderr)
            return 1
        manifest = _process_dataset(
            input_dir=input_dir,
            output_dir=output_dir,
            origin_json=origin_json,
            pattern=args.pattern,
            parallel=args.parallel,
            continue_on_error=args.continue_on_error,
            lane_width_m=args.lane_width_m,
            dataset_name_prefix=args.dataset_name,
            trajectory_xy_dtype=args.trajectory_dtype,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0 if manifest.get("failed_count", 0) == 0 else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
