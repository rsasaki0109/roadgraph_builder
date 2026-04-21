"""CLI parser and command handlers for export commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.pipeline.build_graph import BuildParams


AddBuildParams = Callable[[argparse.ArgumentParser], None]
BuildParamsFromArgs = Callable[[argparse.Namespace], "BuildParams"]
LoadGraph = Callable[[str], "Graph"]
LoadJson = Callable[[str], object]
LoadOrigin = Callable[[str], tuple[float, float]]


class CliExportError(ValueError):
    """User-facing export CLI error."""


def add_lanelet2_parsers(sub) -> None:  # type: ignore[no-untyped-def]
    """Register Lanelet2 export and validation subcommands."""

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
            "Without this flag, output is byte-identical to v0.6.0 delta."
        ),
    )

    vl2 = sub.add_parser(
        "validate-lanelet2",
        help=(
            "Run the upstream Autoware lanelet2_validation tool on an OSM file (A2). "
            "Exits 0 when the tool is not installed (skip) or when errors=0. "
            "Exits 1 when the tool reports >=1 error. "
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


def add_export_bundle_parser(
    sub,  # type: ignore[no-untyped-def]
    *,
    add_build_params: AddBuildParams,
) -> None:
    """Register the ``export-bundle`` subcommand."""

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
    bun.add_argument(
        "--compact-geojson",
        action="store_true",
        default=False,
        help="Write sim/map.geojson without pretty indentation for smaller, faster large bundle exports.",
    )
    add_build_params(bun)


def resolve_graph_origin(
    graph: "Graph",
    *,
    origin_lat: float | None,
    origin_lon: float | None,
    command: str,
) -> tuple[float, float]:
    """Resolve WGS84 origin from explicit args or ``graph.metadata.map_origin``."""

    if (origin_lat is None) ^ (origin_lon is None):
        raise CliExportError(f"{command}: pass both --origin-lat and --origin-lon, or neither to use metadata.")
    if origin_lat is not None and origin_lon is not None:
        return float(origin_lat), float(origin_lon)

    map_origin = graph.metadata.get("map_origin") if isinstance(graph.metadata, dict) else None
    if isinstance(map_origin, dict) and "lat0" in map_origin and "lon0" in map_origin:
        return float(map_origin["lat0"]), float(map_origin["lon0"])
    raise CliExportError(f"{command}: set --origin-lat/--origin-lon or metadata.map_origin {{lat0, lon0}}.")


def resolve_bundle_origin(
    *,
    origin_json: str | None,
    origin_lat: float | None,
    origin_lon: float | None,
    load_origin: LoadOrigin,
) -> tuple[float, float]:
    """Resolve ``export-bundle`` origin from JSON or explicit coordinates."""

    if origin_json:
        return load_origin(origin_json)
    if origin_lat is not None and origin_lon is not None:
        return float(origin_lat), float(origin_lon)
    raise CliExportError("export-bundle: pass --origin-json PATH or both --origin-lat and --origin-lon.")


def optional_json_object(
    *,
    path: str | None,
    load_json: LoadJson,
    command: str,
    option: str,
) -> dict | None:
    """Load an optional JSON option and require an object root."""

    if path is None:
        return None
    raw = load_json(path)
    if not isinstance(raw, dict):
        raise CliExportError(f"{command}: {option} must be a JSON object.")
    return raw


def run_export_lanelet2(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    load_json: LoadJson,
    export_lanelet2_func: Callable[..., object] | None = None,
    export_lanelet2_per_lane_func: Callable[..., object] | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``export-lanelet2`` from parsed args."""

    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)
    try:
        lat0, lon0 = resolve_graph_origin(
            graph,
            origin_lat=args.origin_lat,
            origin_lon=args.origin_lon,
            command="export-lanelet2",
        )
        lm_data = optional_json_object(
            path=getattr(args, "lane_markings_json", None),
            load_json=load_json,
            command="export-lanelet2",
            option="--lane-markings-json",
        )
        cam_det_data = optional_json_object(
            path=getattr(args, "camera_detections_json", None),
            load_json=load_json,
            command="export-lanelet2",
            option="--camera-detections-json",
        )
    except CliExportError as exc:
        print(str(exc), file=err)
        return 1

    if getattr(args, "per_lane", False):
        if export_lanelet2_per_lane_func is None:
            from roadgraph_builder.io.export.lanelet2 import export_lanelet2_per_lane

            export_lanelet2_per_lane_func = export_lanelet2_per_lane
        export_lanelet2_per_lane_func(graph, args.output_osm, origin_lat=lat0, origin_lon=lon0)
    else:
        if export_lanelet2_func is None:
            from roadgraph_builder.io.export.lanelet2 import export_lanelet2

            export_lanelet2_func = export_lanelet2
        export_lanelet2_func(
            graph,
            args.output_osm,
            origin_lat=lat0,
            origin_lon=lon0,
            speed_limit_tagging=getattr(args, "speed_limit_tagging", "lanelet-attr"),
            lane_markings=lm_data,
            camera_detections=cam_det_data,
        )
    return 0


def run_validate_lanelet2(
    args: argparse.Namespace,
    *,
    run_validator: Callable[..., dict] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``validate-lanelet2`` from parsed args."""

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    osm_path = Path(args.input_osm)
    if not osm_path.is_file():
        print(f"File not found: {osm_path}", file=err)
        return 1
    if run_validator is None:
        from roadgraph_builder.io.export.lanelet2_validator_bridge import run_autoware_validator

        run_validator = run_autoware_validator
    result = run_validator(osm_path, timeout_s=getattr(args, "timeout", 30))
    print(json.dumps(result, indent=2), file=out)
    if result["status"] == "skipped":
        print(f"validate-lanelet2: SKIPPED — {result['reason']}", file=err)
        return 0
    if result["status"] == "failed":
        for item in result.get("error_lines", []):
            print(f"ERROR: {item}", file=err)
        print(f"validate-lanelet2: {result['errors']} error(s) found.", file=err)
        return 1
    return 0


def run_validate_lanelet2_tags(
    args: argparse.Namespace,
    *,
    validate_tags: Callable[[Path], tuple[list[str], list[str]]] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``validate-lanelet2-tags`` from parsed args."""

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    osm_path = Path(args.input_osm)
    if not osm_path.is_file():
        print(f"File not found: {osm_path}", file=err)
        return 1
    if validate_tags is None:
        from roadgraph_builder.io.export.lanelet2 import validate_lanelet2_tags

        validate_tags = validate_lanelet2_tags
    try:
        errors, warnings = validate_tags(osm_path)
    except Exception as exc:
        print(f"validate-lanelet2-tags: failed to parse {osm_path}: {exc}", file=err)
        return 1
    for warning in warnings:
        print(f"WARNING: {warning}", file=err)
    if errors:
        for item in errors:
            print(f"ERROR: {item}", file=err)
        print(f"validate-lanelet2-tags: {len(errors)} error(s) found.", file=err)
        return 1
    print(json.dumps({"result": "ok", "warnings": len(warnings), "errors": 0}, indent=2), file=out)
    return 0


def run_export_bundle(
    args: argparse.Namespace,
    *,
    build_params_from_args: BuildParamsFromArgs,
    load_origin: LoadOrigin,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``export-bundle`` from parsed args."""

    from roadgraph_builder.io.export.bundle import export_map_bundle
    from roadgraph_builder.io.trajectory.loader import load_multi_trajectory_csvs, load_trajectory_csv
    from roadgraph_builder.pipeline.build_graph import build_graph_from_trajectory

    err = stderr if stderr is not None else sys.stderr
    params = build_params_from_args(args)
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
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    except ValueError as exc:
        print(str(exc), file=err)
        return 1

    lane_width_m = None if args.lane_width_m <= 0 else args.lane_width_m
    try:
        lat0, lon0 = resolve_bundle_origin(
            origin_json=args.origin_json,
            origin_lat=args.origin_lat,
            origin_lon=args.origin_lon,
            load_origin=load_origin,
        )
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    except CliExportError as exc:
        print(str(exc), file=err)
        return 1

    export_map_bundle(
        graph,
        traj.xy,
        args.input_csv,
        args.output_dir,
        origin_lat=lat0,
        origin_lon=lon0,
        dataset_name=args.dataset_name,
        lane_width_m=lane_width_m,
        detections_json=args.detections_json,
        turn_restrictions_json=args.turn_restrictions_json,
        lidar_points=args.lidar_points,
        fuse_max_dist_m=args.fuse_max_dist_m,
        fuse_bins=args.fuse_bins,
        origin_json_path=args.origin_json,
        lane_markings_json=args.lane_markings_json,
        camera_detections_refine_json=args.camera_detections_refine_json,
        compact_geojson=args.compact_geojson,
    )
    return 0
