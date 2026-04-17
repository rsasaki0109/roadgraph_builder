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
from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
from roadgraph_builder.cli.doctor import run_doctor
from roadgraph_builder.utils.geo import load_wgs84_origin_json
from roadgraph_builder.validation import (
    validate_camera_detections_document,
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
from roadgraph_builder.routing.shortest_path import shortest_path
from roadgraph_builder.viz.svg_export import write_trajectory_graph_svg


def _add_build_params(p: argparse.ArgumentParser) -> None:
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


def _build_params_from_args(args: argparse.Namespace) -> BuildParams:
    return BuildParams(
        max_step_m=args.max_step_m,
        merge_endpoint_m=args.merge_endpoint_m,
        centerline_bins=args.centerline_bins,
        simplify_tolerance_m=args.simplify_tolerance,
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
    p = argparse.ArgumentParser(prog="roadgraph_builder", description="Build a road graph from sensor exports.")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="Print version, Python, and whether example files exist (cwd = repo root).")

    b = sub.add_parser("build", help="Build graph from trajectory CSV and write JSON.")
    b.add_argument("input_csv", help="Input CSV with columns timestamp, x, y")
    b.add_argument("output_json", help="Output JSON path")
    _add_build_params(b)

    v = sub.add_parser("visualize", help="Build graph from CSV and write trajectory+graph SVG.")
    v.add_argument("input_csv", help="Input CSV with columns timestamp, x, y")
    v.add_argument("output_svg", help="Output SVG path")
    _add_build_params(v)
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

    ilas = sub.add_parser(
        "inspect-lidar",
        help="Print LAS public-header summary (version, point count, bbox, scale) as JSON.",
    )
    ilas.add_argument("input_las", help="Path to a .las file (public header is read; point records untouched).")

    rt = sub.add_parser(
        "route",
        help="Undirected Dijkstra shortest path between two node ids in a road graph JSON.",
    )
    rt.add_argument("input_json", help="Road graph JSON (e.g. sim/road_graph.json from export-bundle).")
    rt.add_argument("from_node", help="Source node id (e.g. n0).")
    rt.add_argument("to_node", help="Destination node id (e.g. n3).")

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
    _add_build_params(bun)

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "doctor":
        return run_doctor()
    if args.command == "build":
        params = _build_params_from_args(args)
        try:
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
            traj = load_trajectory_csv(args.input_csv)
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
        enrich_sd_to_hd(
            graph,
            SDToHDConfig(lane_width_m=args.lane_width_m),
        )
        export_graph_json(graph, args.output_json)
        return 0
    if args.command == "route":
        graph = _cli_load_graph(args.input_json)
        try:
            route = shortest_path(graph, args.from_node, args.to_node)
        except KeyError as e:
            print(f"{args.input_json}: {e.args[0]}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"{args.input_json}: {e}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "from_node": route.from_node,
                    "to_node": route.to_node,
                    "total_length_m": route.total_length_m,
                    "edge_sequence": route.edge_sequence,
                    "node_sequence": route.node_sequence,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
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
        graph = _cli_load_graph(args.input_json)
        pts_path = Path(args.points_path)
        if not pts_path.is_file():
            print(f"File not found: {pts_path}", file=sys.stderr)
            return 1
        try:
            if pts_path.suffix.lower() in {".las", ".laz"}:
                pts = load_points_xy_from_las(pts_path)
            else:
                pts = load_points_xy_csv(pts_path)
        except ValueError as e:
            print(f"{pts_path}: {e}", file=sys.stderr)
            return 1
        except ImportError as e:
            print(f"{pts_path}: {e}", file=sys.stderr)
            return 1
        fuse_lane_boundaries_from_points(
            graph,
            pts,
            max_dist_m=args.max_dist_m,
            bins=args.bins,
        )
        export_graph_json(graph, args.output_json)
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
        export_lanelet2(graph, args.output_osm, origin_lat=lat0, origin_lon=lon0)
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
            traj = load_trajectory_csv(args.input_csv)
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
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
