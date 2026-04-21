"""CLI entrypoint."""

from __future__ import annotations

import argparse
import sys

from jsonschema import ValidationError

import json
from pathlib import Path

from roadgraph_builder.hd.lidar_fusion import fuse_lane_boundaries_from_points
from roadgraph_builder.hd.pipeline import SDToHDConfig, enrich_sd_to_hd
from roadgraph_builder.io.export.json_exporter import export_graph_json
from roadgraph_builder.io.export.json_loader import load_graph_json
from roadgraph_builder.io.camera.detections import apply_camera_detections_to_graph, load_camera_detections_json
from roadgraph_builder.io.export.bundle import export_map_bundle
from roadgraph_builder.io.export.lanelet2 import export_lanelet2
from roadgraph_builder.io.lidar.las import load_points_xy_from_las, read_las_header
from roadgraph_builder.io.lidar.points import load_points_xy_csv
from roadgraph_builder.io.trajectory.loader import load_multi_trajectory_csvs, load_trajectory_csv
from roadgraph_builder.cli.doctor import run_doctor
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
from roadgraph_builder.routing.geojson_export import write_route_geojson
from roadgraph_builder.routing.hmm_match import hmm_match_trajectory
from roadgraph_builder.routing.map_match import coverage_stats, snap_trajectory_to_graph
from roadgraph_builder.routing.trip_reconstruction import reconstruct_trips, trip_stats_summary
from roadgraph_builder.routing.nearest import nearest_node
from roadgraph_builder.routing.shortest_path import shortest_path
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

    ilas = sub.add_parser(
        "inspect-lidar",
        help="Print LAS public-header summary (version, point count, bbox, scale) as JSON.",
    )
    ilas.add_argument("input_las", help="Path to a .las file (public header is read; point records untouched).")

    nn = sub.add_parser(
        "nearest-node",
        help="Find the graph node nearest to a query point (lat/lon or meter-frame x/y).",
    )
    nn.add_argument("input_json", help="Road graph JSON.")
    nn_group = nn.add_mutually_exclusive_group(required=True)
    nn_group.add_argument(
        "--latlon",
        nargs=2,
        type=float,
        metavar=("LAT", "LON"),
        help="WGS84 query; needs --origin-lat/--origin-lon or metadata.map_origin.",
    )
    nn_group.add_argument(
        "--xy",
        nargs=2,
        type=float,
        metavar=("X_M", "Y_M"),
        help="Meter-frame query (same frame as the graph).",
    )
    nn.add_argument("--origin-lat", type=float, default=None, metavar="DEG")
    nn.add_argument("--origin-lon", type=float, default=None, metavar="DEG")

    rt = sub.add_parser(
        "route",
        help="Dijkstra shortest path between two nodes (by id or by lat/lon; optional turn_restrictions).",
    )
    rt.add_argument("input_json", help="Road graph JSON (e.g. sim/road_graph.json from export-bundle).")
    rt.add_argument(
        "from_node",
        nargs="?",
        help="Source node id (e.g. n0). Omit when using --from-latlon.",
    )
    rt.add_argument(
        "to_node",
        nargs="?",
        help="Destination node id (e.g. n3). Omit when using --to-latlon.",
    )
    rt.add_argument(
        "--from-latlon",
        nargs=2,
        type=float,
        default=None,
        metavar=("LAT", "LON"),
        help="Snap the source to the node nearest this WGS84 coordinate.",
    )
    rt.add_argument(
        "--to-latlon",
        nargs=2,
        type=float,
        default=None,
        metavar=("LAT", "LON"),
        help="Snap the destination to the node nearest this WGS84 coordinate.",
    )
    rt.add_argument(
        "--turn-restrictions-json",
        type=str,
        default=None,
        metavar="PATH",
        help="JSON with a 'turn_restrictions' array (nav/sd_nav.json or a standalone turn_restrictions.json).",
    )
    rt.add_argument(
        "--output",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional GeoJSON path. Writes a FeatureCollection (route LineString + per-edge features + start/end points).",
    )
    rt.add_argument(
        "--origin-lat",
        type=float,
        default=None,
        metavar="DEG",
        help="WGS84 origin latitude for --output. Falls back to graph metadata.map_origin when omitted.",
    )
    rt.add_argument(
        "--origin-lon",
        type=float,
        default=None,
        metavar="DEG",
        help="WGS84 origin longitude for --output.",
    )
    rt.add_argument(
        "--prefer-observed",
        action="store_true",
        default=False,
        help=(
            "Prefer edges with trace observations over unobserved edges. "
            "Multiplies cost of observed edges by --observed-bonus and unobserved "
            "edges by --unobserved-penalty."
        ),
    )
    rt.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "Exclude edges whose hd_refinement.confidence < FLOAT from the search. "
            "Exits 1 with an error message when no path is reachable."
        ),
    )
    rt.add_argument(
        "--observed-bonus",
        type=float,
        default=0.5,
        metavar="FLOAT",
        help="Cost multiplier for observed edges when --prefer-observed is set (default 0.5).",
    )
    rt.add_argument(
        "--unobserved-penalty",
        type=float,
        default=2.0,
        metavar="FLOAT",
        help="Cost multiplier for unobserved edges when --prefer-observed is set (default 2.0).",
    )
    rt.add_argument(
        "--uphill-penalty",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "3D cost multiplier for uphill edges (slope_deg > 0). "
            "Values >1.0 discourage ascents. Only active when the graph has elevation data."
        ),
    )
    rt.add_argument(
        "--downhill-bonus",
        type=float,
        default=None,
        metavar="FLOAT",
        help=(
            "3D cost multiplier for downhill edges (slope_deg < 0). "
            "Values <1.0 favour descents. Only active when the graph has elevation data."
        ),
    )
    rt.add_argument(
        "--allow-lane-change",
        action="store_true",
        default=False,
        help=(
            "A3: enable lane-level routing over (node, edge, direction, lane_index) state. "
            "Lane swaps within the same edge cost --lane-change-cost-m. "
            "Without this flag, routing is edge-level (byte-identical to v0.6.0)."
        ),
    )
    rt.add_argument(
        "--lane-change-cost-m",
        type=float,
        default=50.0,
        metavar="M",
        help="Cost in meters for a within-edge lane swap when --allow-lane-change is set (default 50).",
    )

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

    fuse = sub.add_parser(
        "fuse-lidar",
        help="Fit lane boundaries from a meter-frame point set (CSV or LAS) via per-edge proximity + binned median.",
    )
    fuse.add_argument("input_json", help="Road graph JSON")
    fuse.add_argument(
        "points_path",
        help="Point set in graph meters: CSV with x,y columns, LAS 1.0–1.4 (.las), or LAZ (.laz, requires 'laz' extra).",
    )
    fuse.add_argument("output_json", help="Output JSON path")
    fuse.add_argument(
        "--max-dist-m",
        type=float,
        default=5.0,
        metavar="M",
        help="Max perpendicular distance from a point to an edge centerline (meters).",
    )
    fuse.add_argument(
        "--bins",
        type=int,
        default=32,
        help="Number of bins along each edge for median aggregation.",
    )
    fuse.add_argument(
        "--ground-plane",
        action="store_true",
        default=False,
        help=(
            "3D mode: fit a ground plane via RANSAC to z-coordinate data and keep only "
            "points within --height-band-lo..--height-band-hi metres above the plane "
            "before lane-boundary fusion. Requires the point file to have x, y, z columns. "
            "Without this flag the behaviour is byte-identical to v0.6.0 (2D XY only)."
        ),
    )
    fuse.add_argument(
        "--height-band-lo",
        type=float,
        default=0.0,
        metavar="M",
        help="Lower bound of height band above ground plane (meters, default 0.0).",
    )
    fuse.add_argument(
        "--height-band-hi",
        type=float,
        default=0.3,
        metavar="M",
        help="Upper bound of height band above ground plane (meters, default 0.3).",
    )

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

    exo = sub.add_parser(
        "export-lanelet2",
        help="Write OSM XML 0.6 (WGS84) with centerlines and hd lane boundaries for JOSM / Lanelet2 tooling.",
    )
    exo.add_argument("input_json", help="Road graph JSON")
    exo.add_argument("output_osm", help="Output .osm path")
    exo.add_argument(
        "--origin-lat",
        type=float,
        default=None,
        metavar="DEG",
        help="WGS84 origin latitude (degrees), same as map GeoJSON. Omit if metadata.map_origin has lat0/lon0.",
    )
    exo.add_argument(
        "--origin-lon",
        type=float,
        default=None,
        metavar="DEG",
        help="WGS84 origin longitude (degrees).",
    )
    exo.add_argument(
        "--per-lane",
        action="store_true",
        default=False,
        help=(
            "Expand each edge into one lanelet per lane using attributes.hd.lanes[] "
            "(populated by infer-lane-count). Edges without hd.lanes fall back to "
            "single-lanelet output. Without this flag, behavior is identical to 0.5.0."
        ),
    )
    exo.add_argument(
        "--speed-limit-tagging",
        choices=["lanelet-attr", "regulatory-element"],
        default="lanelet-attr",
        metavar="{lanelet-attr,regulatory-element}",
        help=(
            "Speed limit tagging style (default: lanelet-attr = inline tag on lanelet, "
            "matching 0.5.0 behavior). Use regulatory-element for strict Lanelet2 spec compliance."
        ),
    )
    exo.add_argument(
        "--lane-markings-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional lane_markings.json for solid/dashed boundary subtype classification.",
    )
    exo.add_argument(
        "--camera-detections-json",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Optional camera_detections.json (observations[]) to wire traffic_light and "
            "stop_line detections into regulatory_element relations (A1). "
            "Without this flag, output is byte-identical to v0.6.0 δ."
        ),
    )

    vl2 = sub.add_parser(
        "validate-lanelet2",
        help=(
            "Run the upstream Autoware lanelet2_validation tool on an OSM file (A2). "
            "Exits 0 when the tool is not installed (skip) or when errors=0. "
            "Exits 1 when the tool reports ≥1 error. "
            "Distinct from validate-lanelet2-tags (which only checks tag completeness)."
        ),
    )
    vl2.add_argument("input_osm", help="OSM XML file produced by export-lanelet2 or export-bundle.")
    vl2.add_argument(
        "--timeout",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Hard timeout for the lanelet2_validation subprocess (default 30 s).",
    )

    vlt = sub.add_parser(
        "validate-lanelet2-tags",
        help="Check required Lanelet2 tags (subtype, location) on all lanelet relations in an OSM file.",
    )
    vlt.add_argument("input_osm", help="OSM XML file produced by export-lanelet2.")

    cam = sub.add_parser(
        "apply-camera",
        help="Merge camera/perception JSON observations into attributes.hd.semantic_rules.",
    )
    cam.add_argument("input_json", help="Road graph JSON")
    cam.add_argument("detections_json", help="JSON with observations[] (edge_id, kind, …)")
    cam.add_argument("output_json", help="Output JSON path")

    bun = sub.add_parser(
        "export-bundle",
        help="Write nav/sd_nav.json, sim/{road_graph,map,trajectory}, lanelet/map.osm in one directory.",
    )
    bun.add_argument("input_csv", help="Trajectory CSV (timestamp, x, y)")
    bun.add_argument("output_dir", help="Output directory (created)")
    bun.add_argument(
        "--origin-json",
        type=str,
        default=None,
        metavar="PATH",
        help="JSON with lat0, lon0 (e.g. examples/toy_map_origin.json). Alternative to --origin-lat/--origin-lon.",
    )
    bun.add_argument(
        "--origin-lat",
        type=float,
        default=None,
        metavar="DEG",
        help="WGS84 origin latitude (omit if --origin-json is set).",
    )
    bun.add_argument(
        "--origin-lon",
        type=float,
        default=None,
        metavar="DEG",
        help="WGS84 origin longitude (omit if --origin-json is set).",
    )
    bun.add_argument(
        "--dataset-name",
        type=str,
        default="bundle",
        help="Label embedded in GeoJSON and metadata.",
    )
    bun.add_argument(
        "--lane-width-m",
        type=float,
        default=3.5,
        metavar="M",
        help="HD-lite lane width for enrich; use 0 to skip centerline-offset boundaries.",
    )
    bun.add_argument(
        "--detections-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional camera detections JSON (same as apply-camera).",
    )
    bun.add_argument(
        "--turn-restrictions-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional manual turn-restrictions JSON merged into nav/sd_nav.json.",
    )
    bun.add_argument(
        "--lidar-points",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional LiDAR point set (CSV or .las) fused into per-edge boundaries.",
    )
    bun.add_argument(
        "--fuse-max-dist-m",
        type=float,
        default=5.0,
        metavar="M",
        help="Max perpendicular distance from a point to an edge centerline for LiDAR fusion.",
    )
    bun.add_argument(
        "--fuse-bins",
        type=int,
        default=32,
        metavar="N",
        help="Number of along-edge bins for LiDAR median aggregation.",
    )
    bun.add_argument(
        "--extra-csv",
        action="append",
        default=[],
        metavar="PATH",
        help="Additional trajectory CSV to concatenate with the primary input (same meter origin). Repeatable.",
    )
    bun.add_argument(
        "--lane-markings-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional lane_markings.json for per-edge HD width refinement.",
    )
    bun.add_argument(
        "--camera-detections-refine-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional camera_detections.json for per-edge HD width refinement (separate from --detections-json).",
    )
    _add_build_params(bun, include_trajectory_dtype=True)

    bog = sub.add_parser(
        "build-osm-graph",
        help="Build road graph JSON from an Overpass highway-ways dump (e.g. scripts/fetch_osm_highways.py output).",
    )
    bog.add_argument("input_json", help="Raw Overpass JSON (ways + nodes).")
    bog.add_argument("output_json", help="Output road graph JSON path.")
    bog.add_argument(
        "--origin-json",
        type=str,
        default=None,
        metavar="PATH",
        help="JSON with lat0, lon0. Alternative to --origin-lat/--origin-lon.",
    )
    bog.add_argument("--origin-lat", type=float, default=None, metavar="DEG")
    bog.add_argument("--origin-lon", type=float, default=None, metavar="DEG")
    bog.add_argument(
        "--highway-classes",
        type=str,
        default=None,
        metavar="LIST",
        help="Comma-separated highway= values to include (default: drivable set).",
    )
    _add_build_params(bog)

    cor = sub.add_parser(
        "convert-osm-restrictions",
        help=(
            "Map OSM type=restriction relations onto an existing road graph. "
            "Writes a turn_restrictions JSON that export-bundle --turn-restrictions-json consumes."
        ),
    )
    cor.add_argument("graph_json", help="Road graph JSON (with metadata.map_origin).")
    cor.add_argument("restrictions_json", help="Raw Overpass JSON with restriction relations.")
    cor.add_argument("output_json", help="Output turn_restrictions JSON path.")
    cor.add_argument(
        "--max-snap-m",
        type=float,
        default=15.0,
        metavar="M",
        help="Max distance from projected OSM via node to nearest graph node.",
    )
    cor.add_argument(
        "--min-alignment",
        type=float,
        default=0.3,
        metavar="COS",
        help="Min cos(angle) between incident edge tangent and OSM way direction.",
    )
    cor.add_argument(
        "--id-prefix",
        type=str,
        default="tr_osm_",
        help="Prefix for generated turn_restrictions.id entries.",
    )
    cor.add_argument(
        "--skipped-json",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional path to write per-relation skip reasons.",
    )

    pc = sub.add_parser(
        "project-camera",
        help=(
            "Project per-image pixel detections onto the ground plane using a "
            "pinhole camera + per-image vehicle pose, snap to the nearest graph "
            "edge, and write an edge-keyed camera_detections.json."
        ),
    )
    pc.add_argument("calibration_json", help="Camera calibration JSON (intrinsic + camera_to_vehicle).")
    pc.add_argument("image_detections_json", help="Per-image pixel detections JSON.")
    pc.add_argument("graph_json", help="Road graph JSON (same world meter frame as vehicle poses).")
    pc.add_argument("output_json", help="Output camera_detections.json path.")
    pc.add_argument(
        "--ground-z-m",
        type=float,
        default=0.0,
        metavar="M",
        help="Height of the assumed-flat ground plane in the world frame.",
    )
    pc.add_argument(
        "--max-edge-distance-m",
        type=float,
        default=5.0,
        metavar="M",
        help="Max perpendicular distance from a projected detection to a graph edge.",
    )

    dlm = sub.add_parser(
        "detect-lane-markings",
        help="Detect lane markings from LiDAR intensity peaks; write lane_markings.json.",
    )
    dlm.add_argument("graph_json", help="Road graph JSON.")
    dlm.add_argument("points_las", help="LAS/LAZ point cloud with intensity column (meter frame).")
    dlm.add_argument("--output", type=str, default="lane_markings.json", metavar="PATH", help="Output JSON path (default: lane_markings.json).")
    dlm.add_argument("--max-lateral-m", type=float, default=2.5, metavar="M", help="Max lateral distance from edge centerline to consider (m).")
    dlm.add_argument("--intensity-percentile", type=float, default=85.0, metavar="PCT", help="Percentile threshold for intensity peaks.")
    dlm.add_argument("--bin-m", type=float, default=1.0, metavar="M", help="Along-edge bin size (m).")
    dlm.add_argument("--min-points-per-bin", type=int, default=3, metavar="N", help="Min points per bin to form a cluster.")

    dlmc = sub.add_parser(
        "detect-lane-markings-camera",
        help=(
            "Detect lane markings from camera images using pure-NumPy HSV thresholds "
            "and project onto graph edges (3D2). Writes a camera_lanes.json."
        ),
    )
    dlmc.add_argument("graph_json", help="Road graph JSON (meter frame).")
    dlmc.add_argument("calibration_json", help="Camera calibration JSON (CameraCalibration format).")
    dlmc.add_argument("images_dir", help="Directory containing image files (.jpg/.png) named image_<id>.*")
    dlmc.add_argument("poses_json", help="JSON file with per-image poses: [{image_id, pose_x_m, pose_y_m, heading_rad}, ...]")
    dlmc.add_argument("--output", type=str, default="camera_lanes.json", metavar="PATH", help="Output JSON path (default: camera_lanes.json).")
    dlmc.add_argument("--white-threshold", type=int, default=200, metavar="V", help="Minimum value (0-255) for white lane detection.")
    dlmc.add_argument("--yellow-hue-lo", type=int, default=20, metavar="H", help="Lower bound of yellow hue range (0-360).")
    dlmc.add_argument("--yellow-hue-hi", type=int, default=40, metavar="H", help="Upper bound of yellow hue range (0-360).")
    dlmc.add_argument("--saturation-min", type=int, default=100, metavar="S", help="Minimum saturation (0-255) for yellow detection.")
    dlmc.add_argument("--min-line-length-px", type=int, default=30, metavar="PX", help="Minimum major-axis length (pixels) for lane candidates.")
    dlmc.add_argument("--max-edge-distance-m", type=float, default=3.5, metavar="M", help="Max lateral distance for edge snap.")

    vlm = sub.add_parser(
        "validate-lane-markings",
        help="Validate a lane_markings.json against lane_markings.schema.json.",
    )
    vlm.add_argument("input_json", help="lane_markings.json produced by detect-lane-markings.")

    guid = sub.add_parser(
        "guidance",
        help="Build turn-by-turn navigation steps from a route GeoJSON + sd_nav.json.",
    )
    guid.add_argument("route_geojson", help="Route GeoJSON (from the route CLI --output).")
    guid.add_argument("sd_nav_json", help="SD nav JSON (nav/sd_nav.json from export-bundle).")
    guid.add_argument("--output", type=str, default="guidance.json", metavar="PATH", help="Output JSON path (default: guidance.json).")
    guid.add_argument("--slight-deg", type=float, default=20.0, metavar="DEG", help="Angle threshold for slight turns (degrees).")
    guid.add_argument("--sharp-deg", type=float, default=120.0, metavar="DEG", help="Angle threshold for sharp turns (degrees).")
    guid.add_argument("--u-turn-deg", type=float, default=165.0, metavar="DEG", help="Angle threshold for U-turns (degrees).")

    vguid = sub.add_parser(
        "validate-guidance",
        help="Validate a guidance.json against guidance.schema.json.",
    )
    vguid.add_argument("input_json", help="guidance.json produced by the guidance CLI.")

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
        graph = _cli_load_graph(args.input_json)
        try:
            if args.latlon is not None:
                result = nearest_node(
                    graph,
                    lat=args.latlon[0],
                    lon=args.latlon[1],
                    origin_lat=args.origin_lat,
                    origin_lon=args.origin_lon,
                )
            else:
                result = nearest_node(graph, x_m=args.xy[0], y_m=args.xy[1])
        except ValueError as e:
            print(f"{args.input_json}: {e}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "node_id": result.node_id,
                    "distance_m": result.distance_m,
                    "query_xy_m": list(result.query_xy_m),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
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
        graph = _cli_load_graph(args.input_json)

        def _snap(latlon, positional):
            if latlon is not None and positional is not None:
                print("route: pass either a node id or --*-latlon, not both.", file=sys.stderr)
                return None, None
            if latlon is not None:
                try:
                    result = nearest_node(
                        graph,
                        lat=latlon[0],
                        lon=latlon[1],
                        origin_lat=args.origin_lat,
                        origin_lon=args.origin_lon,
                    )
                except ValueError as e:
                    print(f"{args.input_json}: {e}", file=sys.stderr)
                    return None, None
                return result.node_id, {
                    "requested_lat": latlon[0],
                    "requested_lon": latlon[1],
                    "distance_m": result.distance_m,
                }
            return positional, None

        from_id, from_snap = _snap(args.from_latlon, args.from_node)
        to_id, to_snap = _snap(args.to_latlon, args.to_node)
        if from_id is None or to_id is None:
            if args.from_latlon is None and args.from_node is None:
                print("route: provide either from_node positional or --from-latlon.", file=sys.stderr)
            if args.to_latlon is None and args.to_node is None:
                print("route: provide either to_node positional or --to-latlon.", file=sys.stderr)
            return 1

        restrictions: list[dict] = []
        if args.turn_restrictions_json:
            tr_doc = _load_json_for_cli(args.turn_restrictions_json)
            if isinstance(tr_doc, dict):
                maybe = tr_doc.get("turn_restrictions", [])
                if isinstance(maybe, list):
                    restrictions = [r for r in maybe if isinstance(r, dict)]
            elif isinstance(tr_doc, list):
                restrictions = [r for r in tr_doc if isinstance(r, dict)]
        try:
            route = shortest_path(
                graph,
                from_id,
                to_id,
                turn_restrictions=restrictions or None,
                prefer_observed=getattr(args, "prefer_observed", False),
                min_confidence=getattr(args, "min_confidence", None),
                observed_bonus=getattr(args, "observed_bonus", 0.5),
                unobserved_penalty=getattr(args, "unobserved_penalty", 2.0),
                uphill_penalty=getattr(args, "uphill_penalty", None),
                downhill_bonus=getattr(args, "downhill_bonus", None),
                allow_lane_change=getattr(args, "allow_lane_change", False),
                lane_change_cost_m=getattr(args, "lane_change_cost_m", 50.0),
            )
        except KeyError as e:
            print(f"{args.input_json}: {e.args[0]}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"{args.input_json}: {e}", file=sys.stderr)
            return 1

        if args.output:
            lat0, lon0 = args.origin_lat, args.origin_lon
            if (lat0 is None) ^ (lon0 is None):
                print("route --output: pass both --origin-lat and --origin-lon, or neither.", file=sys.stderr)
                return 1
            if lat0 is None:
                mo = graph.metadata.get("map_origin") if isinstance(graph.metadata, dict) else None
                if isinstance(mo, dict) and "lat0" in mo and "lon0" in mo:
                    lat0 = float(mo["lat0"])
                    lon0 = float(mo["lon0"])
                else:
                    print(
                        "route --output: set --origin-lat/--origin-lon or metadata.map_origin {lat0, lon0}.",
                        file=sys.stderr,
                    )
                    return 1
            write_route_geojson(args.output, graph, route, origin_lat=lat0, origin_lon=lon0)

        route_doc: dict = {
            "from_node": route.from_node,
            "to_node": route.to_node,
            "snapped_from": from_snap,
            "snapped_to": to_snap,
            "total_length_m": route.total_length_m,
            "edge_sequence": route.edge_sequence,
            "edge_directions": route.edge_directions,
            "node_sequence": route.node_sequence,
            "applied_restrictions": len(restrictions),
            "output": args.output if args.output else None,
        }
        if route.lane_sequence is not None:
            route_doc["lane_sequence"] = route.lane_sequence
        print(json.dumps(route_doc, ensure_ascii=False, indent=2))
        return 0
    if args.command == "inspect-lidar":
        p = Path(args.input_las)
        if not p.is_file():
            print(f"File not found: {p}", file=sys.stderr)
            return 1
        try:
            header = read_las_header(p)
        except ValueError as e:
            print(f"{p}: {e}", file=sys.stderr)
            return 1
        print(json.dumps(header.to_summary(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "fuse-lidar":
        from roadgraph_builder.hd.lidar_fusion import fuse_lane_boundaries_3d
        from roadgraph_builder.io.lidar.points import load_points_xyz_csv

        graph = _cli_load_graph(args.input_json)
        pts_path = Path(args.points_path)
        if not pts_path.is_file():
            print(f"File not found: {pts_path}", file=sys.stderr)
            return 1
        use_ground_plane = getattr(args, "ground_plane", False)
        try:
            if pts_path.suffix.lower() in {".las", ".laz"}:
                if use_ground_plane:
                    # Load xyz (intensity optional) for ground-plane mode.
                    from roadgraph_builder.io.lidar.las import load_points_xyz_from_las
                    pts = load_points_xyz_from_las(pts_path)
                else:
                    pts = load_points_xy_from_las(pts_path)
            else:
                if use_ground_plane:
                    pts = load_points_xyz_csv(pts_path)
                else:
                    pts = load_points_xy_csv(pts_path)
        except ValueError as e:
            print(f"{pts_path}: {e}", file=sys.stderr)
            return 1
        except ImportError as e:
            print(f"{pts_path}: {e}", file=sys.stderr)
            return 1
        if use_ground_plane:
            if pts.ndim != 2 or pts.shape[1] < 3:
                print(
                    f"{pts_path}: --ground-plane requires x,y,z columns; "
                    f"got shape {pts.shape}",
                    file=sys.stderr,
                )
                return 1
            fuse_lane_boundaries_3d(
                graph,
                pts,
                height_band_m=(args.height_band_lo, args.height_band_hi),
                max_dist_m=args.max_dist_m,
                bins=args.bins,
            )
        else:
            fuse_lane_boundaries_from_points(
                graph,
                pts,
                max_dist_m=args.max_dist_m,
                bins=args.bins,
            )
        export_graph_json(graph, args.output_json)
        return 0
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
        graph = _cli_load_graph(args.input_json)
        lat0, lon0 = args.origin_lat, args.origin_lon
        if (lat0 is None) ^ (lon0 is None):
            print("export-lanelet2: pass both --origin-lat and --origin-lon, or neither to use metadata.", file=sys.stderr)
            return 1
        if lat0 is None:
            mo = graph.metadata.get("map_origin")
            if isinstance(mo, dict) and "lat0" in mo and "lon0" in mo:
                lat0 = float(mo["lat0"])
                lon0 = float(mo["lon0"])
            else:
                print(
                    "export-lanelet2: set --origin-lat/--origin-lon or metadata.map_origin {lat0, lon0}.",
                    file=sys.stderr,
                )
                return 1
        lm_data = None
        if getattr(args, "lane_markings_json", None):
            raw_lm = _load_json_for_cli(args.lane_markings_json)
            if not isinstance(raw_lm, dict):
                print("export-lanelet2: --lane-markings-json must be a JSON object.", file=sys.stderr)
                return 1
            lm_data = raw_lm
        cam_det_data = None
        if getattr(args, "camera_detections_json", None):
            raw_cam = _load_json_for_cli(args.camera_detections_json)
            if not isinstance(raw_cam, dict):
                print("export-lanelet2: --camera-detections-json must be a JSON object.", file=sys.stderr)
                return 1
            cam_det_data = raw_cam
        if getattr(args, "per_lane", False):
            from roadgraph_builder.io.export.lanelet2 import export_lanelet2_per_lane
            export_lanelet2_per_lane(graph, args.output_osm, origin_lat=lat0, origin_lon=lon0)
        else:
            export_lanelet2(
                graph,
                args.output_osm,
                origin_lat=lat0,
                origin_lon=lon0,
                speed_limit_tagging=getattr(args, "speed_limit_tagging", "lanelet-attr"),
                lane_markings=lm_data,
                camera_detections=cam_det_data,
            )
        return 0
    if args.command == "validate-lanelet2":
        from roadgraph_builder.io.export.lanelet2_validator_bridge import run_autoware_validator
        osm_path = Path(args.input_osm)
        if not osm_path.is_file():
            print(f"File not found: {osm_path}", file=sys.stderr)
            return 1
        result = run_autoware_validator(osm_path, timeout_s=getattr(args, "timeout", 30))
        # Always print the structured result as JSON on stdout.
        import json as _json
        print(_json.dumps(result, indent=2))
        if result["status"] == "skipped":
            # Graceful skip: exit 0 with a warning on stderr.
            print(
                f"validate-lanelet2: SKIPPED — {result['reason']}",
                file=sys.stderr,
            )
            return 0
        if result["status"] == "failed":
            for err in result.get("error_lines", []):
                print(f"ERROR: {err}", file=sys.stderr)
            print(
                f"validate-lanelet2: {result['errors']} error(s) found.",
                file=sys.stderr,
            )
            return 1
        return 0
    if args.command == "validate-lanelet2-tags":
        from roadgraph_builder.io.export.lanelet2 import validate_lanelet2_tags
        osm_path = Path(args.input_osm)
        if not osm_path.is_file():
            print(f"File not found: {osm_path}", file=sys.stderr)
            return 1
        try:
            errors, warnings = validate_lanelet2_tags(osm_path)
        except Exception as exc:
            print(f"validate-lanelet2-tags: failed to parse {osm_path}: {exc}", file=sys.stderr)
            return 1
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            print(f"validate-lanelet2-tags: {len(errors)} error(s) found.", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "result": "ok",
                    "warnings": len(warnings),
                    "errors": 0,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "apply-camera":
        graph = _cli_load_graph(args.input_json)
        try:
            obs = load_camera_detections_json(args.detections_json)
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        apply_camera_detections_to_graph(graph, obs)
        export_graph_json(graph, args.output_json)
        return 0
    if args.command == "export-bundle":
        params = _build_params_from_args(args)
        try:
            if args.extra_csv:
                traj = load_multi_trajectory_csvs(
                    [args.input_csv, *args.extra_csv],
                    load_z=params.use_3d,
                    xy_dtype=params.trajectory_xy_dtype,
                )
            else:
                traj = load_trajectory_csv(
                    args.input_csv,
                    load_z=params.use_3d,
                    xy_dtype=params.trajectory_xy_dtype,
                )
            graph = build_graph_from_trajectory(traj, params)
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        lw = None if args.lane_width_m <= 0 else args.lane_width_m
        oj = args.origin_json
        if oj:
            try:
                lat0, lon0 = load_wgs84_origin_json(oj)
            except FileNotFoundError as e:
                print(f"File not found: {e.filename}", file=sys.stderr)
                return 1
        elif args.origin_lat is not None and args.origin_lon is not None:
            lat0, lon0 = args.origin_lat, args.origin_lon
        else:
            print(
                "export-bundle: pass --origin-json PATH or both --origin-lat and --origin-lon.",
                file=sys.stderr,
            )
            return 1
        export_map_bundle(
            graph,
            traj.xy,
            args.input_csv,
            args.output_dir,
            origin_lat=lat0,
            origin_lon=lon0,
            dataset_name=args.dataset_name,
            lane_width_m=lw,
            detections_json=args.detections_json,
            turn_restrictions_json=args.turn_restrictions_json,
            lidar_points=args.lidar_points,
            fuse_max_dist_m=args.fuse_max_dist_m,
            fuse_bins=args.fuse_bins,
            origin_json_path=oj,
            lane_markings_json=args.lane_markings_json,
            camera_detections_refine_json=args.camera_detections_refine_json,
        )
        return 0
    if args.command == "build-osm-graph":
        from roadgraph_builder.io.osm import build_graph_from_overpass_highways
        params = _build_params_from_args(args)
        try:
            raw = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        if not isinstance(raw, dict):
            print("build-osm-graph: input JSON root must be an object.", file=sys.stderr)
            return 1
        oj = args.origin_json
        if oj:
            try:
                lat0, lon0 = load_wgs84_origin_json(oj)
            except FileNotFoundError as e:
                print(f"File not found: {e.filename}", file=sys.stderr)
                return 1
        elif args.origin_lat is not None and args.origin_lon is not None:
            lat0, lon0 = args.origin_lat, args.origin_lon
        else:
            print(
                "build-osm-graph: pass --origin-json PATH or both --origin-lat and --origin-lon.",
                file=sys.stderr,
            )
            return 1
        hw_filter = None
        if args.highway_classes:
            hw_filter = {c.strip() for c in args.highway_classes.split(",") if c.strip()}
        graph = build_graph_from_overpass_highways(
            raw, origin_lat=lat0, origin_lon=lon0, params=params, highway_filter=hw_filter
        )
        export_graph_json(graph, args.output_json)
        print(
            f"Wrote {args.output_json}: {len(graph.nodes)} nodes, {len(graph.edges)} edges.",
            file=sys.stderr,
        )
        return 0
    if args.command == "convert-osm-restrictions":
        from roadgraph_builder.io.osm import (
            convert_osm_restrictions_to_graph,
            load_overpass_json,
        )
        from roadgraph_builder.io.osm.turn_restrictions import strip_private_fields
        try:
            graph = _cli_load_graph(args.graph_json)
            overpass = load_overpass_json(args.restrictions_json)
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        except KeyError as e:
            print(f"{e}", file=sys.stderr)
            return 1
        try:
            result = convert_osm_restrictions_to_graph(
                graph,
                overpass,
                max_snap_distance_m=args.max_snap_m,
                min_edge_tangent_alignment=args.min_alignment,
                id_prefix=args.id_prefix,
            )
        except KeyError as e:
            print(f"{e}", file=sys.stderr)
            return 1
        cleaned = strip_private_fields(result.restrictions)
        doc: dict[str, object] = {
            "format_version": 1,
            "attribution": "© OpenStreetMap contributors",
            "license": "ODbL-1.0",
            "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
            "turn_restrictions": cleaned,
        }
        Path(args.output_json).write_text(
            json.dumps(doc, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"Wrote {args.output_json}: {len(cleaned)} restrictions "
            f"({len(result.skipped)} skipped).",
            file=sys.stderr,
        )
        if args.skipped_json:
            Path(args.skipped_json).write_text(
                json.dumps(result.skipped, indent=2) + "\n", encoding="utf-8"
            )
        return 0
    if args.command == "project-camera":
        from roadgraph_builder.io.camera import (
            load_camera_calibration,
            load_image_detections_json,
            project_image_detections_to_graph_edges,
        )
        try:
            calib = load_camera_calibration(args.calibration_json)
            items = load_image_detections_json(args.image_detections_json)
            graph = _cli_load_graph(args.graph_json)
        except FileNotFoundError as e:
            print(f"File not found: {e.filename}", file=sys.stderr)
            return 1
        except (KeyError, ValueError, TypeError) as e:
            print(f"{e}", file=sys.stderr)
            return 1
        result = project_image_detections_to_graph_edges(
            items,
            calib,
            graph,
            ground_z_m=args.ground_z_m,
            max_edge_distance_m=args.max_edge_distance_m,
        )
        doc = {"format_version": 1, "observations": result.observations}
        Path(args.output_json).write_text(
            json.dumps(doc, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"Wrote {args.output_json}: {len(result.observations)} observations "
            f"(projected {result.projected_count}, "
            f"dropped_above_horizon {result.dropped_above_horizon}, "
            f"dropped_no_edge {result.dropped_no_edge}).",
            file=sys.stderr,
        )
        return 0
    if args.command == "detect-lane-markings":
        import numpy as _dlm_np
        from roadgraph_builder.io.lidar.lane_marking import detect_lane_markings as _detect_lane_markings
        from roadgraph_builder.io.lidar.las import read_las_header as _read_las_header_dlm
        graph_data = _load_json_for_cli(args.graph_json)
        if not isinstance(graph_data, dict):
            print("detect-lane-markings: graph JSON root must be an object.", file=sys.stderr)
            return 1
        pts_path = Path(args.points_las)
        if not pts_path.is_file():
            print(f"File not found: {pts_path}", file=sys.stderr)
            return 1
        try:
            if pts_path.suffix.lower() in {".las", ".laz"}:
                _hdr = _read_las_header_dlm(pts_path)
                record_length = _hdr.point_data_record_length
                point_count = _hdr.point_count
                with pts_path.open("rb") as _fh:
                    _fh.seek(_hdr.offset_to_point_data)
                    blob = _fh.read(record_length * point_count)
                _buf = _dlm_np.frombuffer(blob, dtype=_dlm_np.uint8).reshape(point_count, record_length)
                _xi = _buf[:, 0:4].copy().view(_dlm_np.int32).reshape(point_count)
                _yi = _buf[:, 4:8].copy().view(_dlm_np.int32).reshape(point_count)
                _zi = _buf[:, 8:12].copy().view(_dlm_np.int32).reshape(point_count)
                _ii = _buf[:, 12:14].copy().view(_dlm_np.uint16).reshape(point_count)
                _sx, _sy, _sz = _hdr.scale
                _ox, _oy, _oz = _hdr.offset
                pts_xyzi = _dlm_np.empty((point_count, 4), dtype=_dlm_np.float64)
                pts_xyzi[:, 0] = _xi.astype(_dlm_np.float64) * _sx + _ox
                pts_xyzi[:, 1] = _yi.astype(_dlm_np.float64) * _sy + _oy
                pts_xyzi[:, 2] = _zi.astype(_dlm_np.float64) * _sz + _oz
                pts_xyzi[:, 3] = _ii.astype(_dlm_np.float64)
            else:
                print(f"detect-lane-markings: only LAS/LAZ files are supported, got {pts_path.suffix}", file=sys.stderr)
                return 1
        except ValueError as e:
            print(f"{pts_path}: {e}", file=sys.stderr)
            return 1
        candidates = _detect_lane_markings(
            graph_data,
            pts_xyzi,
            max_lateral_m=args.max_lateral_m,
            intensity_percentile=args.intensity_percentile,
            along_edge_bin_m=args.bin_m,
            min_points_per_bin=args.min_points_per_bin,
        )
        doc = {
            "candidates": [
                {
                    "edge_id": c.edge_id,
                    "side": c.side,
                    "polyline_m": [list(pt) for pt in c.polyline_m],
                    "intensity_median": c.intensity_median,
                    "point_count": c.point_count,
                }
                for c in candidates
            ]
        }
        out_path = Path(args.output)
        out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(
            f"Wrote {out_path}: {len(candidates)} candidates.",
            file=sys.stderr,
        )
        return 0
    if args.command == "detect-lane-markings-camera":
        from roadgraph_builder.io.camera.calibration import CameraCalibration
        from roadgraph_builder.io.camera.lane_detection import (
            detect_lanes_from_image_rgb,
            project_camera_lanes_to_graph_edges,
        )

        graph = _cli_load_graph(args.graph_json)
        cal_raw = _load_json_for_cli(args.calibration_json)
        if not isinstance(cal_raw, dict):
            print("detect-lane-markings-camera: calibration JSON must be an object.", file=sys.stderr)
            return 1
        try:
            calibration = CameraCalibration.from_dict(cal_raw)
        except (KeyError, TypeError, ValueError) as e:
            print(f"detect-lane-markings-camera: bad calibration: {e}", file=sys.stderr)
            return 1
        poses_raw = _load_json_for_cli(args.poses_json)
        if not isinstance(poses_raw, list):
            print("detect-lane-markings-camera: poses JSON must be a list.", file=sys.stderr)
            return 1

        images_dir = Path(args.images_dir)
        if not images_dir.is_dir():
            print(f"Directory not found: {images_dir}", file=sys.stderr)
            return 1

        all_candidates = []
        import_error_msg: str | None = None
        for pose_entry in poses_raw:
            if not isinstance(pose_entry, dict):
                continue
            image_id = str(pose_entry.get("image_id", ""))
            pose_x = float(pose_entry.get("pose_x_m", 0.0))
            pose_y = float(pose_entry.get("pose_y_m", 0.0))
            heading = float(pose_entry.get("heading_rad", 0.0))

            # Locate image file (try png and jpg).
            img_file: Path | None = None
            for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG", ".JPEG"):
                candidate = images_dir / f"{image_id}{ext}"
                if candidate.is_file():
                    img_file = candidate
                    break
            if img_file is None:
                continue

            # Load image — prefer cv2 if available, otherwise try numpy-based fallback.
            try:
                try:
                    import cv2  # type: ignore[import-not-found]
                    bgr = cv2.imread(str(img_file))
                    if bgr is None:
                        continue
                    rgb_arr = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                except ImportError:
                    # No cv2: attempt to read PNG without external deps.
                    try:
                        import struct, zlib
                        _png = img_file.read_bytes()
                        if _png[:8] != b"\x89PNG\r\n\x1a\n":
                            print(
                                f"detect-lane-markings-camera: cv2 not available; "
                                f"only PNG supported without it. Skipping {img_file.name}.",
                                file=sys.stderr,
                            )
                            continue
                        # Parse IHDR
                        w_png = struct.unpack(">I", _png[16:20])[0]
                        h_png = struct.unpack(">I", _png[20:24])[0]
                        bit_depth = _png[24]
                        color_type = _png[25]
                        if bit_depth != 8 or color_type != 2:
                            print(f"detect-lane-markings-camera: only 8-bit RGB PNG supported. Skipping.", file=sys.stderr)
                            continue
                        # Collect IDAT chunks and decompress.
                        offset_p = 8
                        idat_data = b""
                        while offset_p < len(_png):
                            length = struct.unpack(">I", _png[offset_p:offset_p+4])[0]
                            chunk_type = _png[offset_p+4:offset_p+8]
                            if chunk_type == b"IDAT":
                                idat_data += _png[offset_p+8:offset_p+8+length]
                            elif chunk_type == b"IEND":
                                break
                            offset_p += 12 + length
                        raw = zlib.decompress(idat_data)
                        row_stride = 1 + w_png * 3
                        import numpy as _np
                        pixels_flat = []
                        for ri in range(h_png):
                            row_data = raw[ri * row_stride + 1: (ri + 1) * row_stride]
                            pixels_flat.append(list(row_data))
                        rgb_arr = _np.array(pixels_flat, dtype=_np.uint8).reshape(h_png, w_png, 3)
                    except Exception as inner:
                        print(f"detect-lane-markings-camera: failed to read {img_file.name}: {inner}", file=sys.stderr)
                        continue
            except Exception as e:
                print(f"detect-lane-markings-camera: error loading {img_file}: {e}", file=sys.stderr)
                continue

            lanes = detect_lanes_from_image_rgb(
                rgb_arr,
                white_threshold=args.white_threshold,
                yellow_hue_range=(args.yellow_hue_lo, args.yellow_hue_hi),
                saturation_min=args.saturation_min,
                min_line_length_px=args.min_line_length_px,
            )
            projected = project_camera_lanes_to_graph_edges(
                lanes,
                calibration,
                graph,
                pose_xy_m=(pose_x, pose_y),
                heading_rad=heading,
                max_edge_distance_m=args.max_edge_distance_m,
            )
            all_candidates.extend(projected)

        doc = {
            "camera_lanes": [
                {
                    "edge_id": c.edge_id,
                    "world_xy_m": list(c.world_xy_m),
                    "kind": c.kind,
                    "side": c.side,
                    "confidence": c.confidence,
                }
                for c in all_candidates
            ]
        }
        out_path = Path(args.output)
        out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(
            f"Wrote {out_path}: {len(all_candidates)} camera lane candidates.",
            file=sys.stderr,
        )
        return 0
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
        from roadgraph_builder.navigation.guidance import build_guidance as _build_guidance
        route_data = _load_json_for_cli(args.route_geojson)
        sd_nav_data = _load_json_for_cli(args.sd_nav_json)
        if not isinstance(route_data, dict):
            print("guidance: route GeoJSON root must be an object.", file=sys.stderr)
            return 1
        if not isinstance(sd_nav_data, dict):
            print("guidance: sd_nav JSON root must be an object.", file=sys.stderr)
            return 1
        steps = _build_guidance(
            route_data,
            sd_nav_data,
            slight_deg=args.slight_deg,
            sharp_deg=args.sharp_deg,
            u_turn_deg=args.u_turn_deg,
        )
        doc = {
            "steps": [
                {
                    "step_index": s.step_index,
                    "edge_id": s.edge_id,
                    "start_distance_m": s.start_distance_m,
                    "length_m": s.length_m,
                    "maneuver_at_end": s.maneuver_at_end,
                    "heading_change_deg": s.heading_change_deg,
                    "junction_type_at_end": s.junction_type_at_end,
                    "description": s.description,
                    "sd_nav_edge_maneuvers": s.sd_nav_edge_maneuvers,
                }
                for s in steps
            ]
        }
        out_path = Path(args.output)
        out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out_path}: {len(steps)} steps.", file=sys.stderr)
        return 0
    if args.command == "validate-guidance":
        from roadgraph_builder.validation import validate_guidance_document
        data = _load_json_for_cli(args.input_json)
        if not isinstance(data, dict):
            print("JSON root must be an object", file=sys.stderr)
            return 1
        try:
            validate_guidance_document(data)
        except ValidationError as e:
            _validation_error(args.input_json, e)
            return 1
        return 0
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
