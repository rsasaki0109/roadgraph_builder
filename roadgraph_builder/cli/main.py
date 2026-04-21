"""CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from roadgraph_builder.cli.build import (
    _TRAJECTORY_DTYPE_CHOICES,
    _add_build_params,
    _build_params_from_args,
    add_build_parser,
    add_visualize_parser,
    run_build,
    run_visualize,
)
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
from roadgraph_builder.cli.hd import (
    add_hd_parsers,
    run_enrich,
    run_infer_lane_count,
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
from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
from roadgraph_builder.cli.doctor import run_doctor
from roadgraph_builder.cli.routing import (
    add_nearest_node_parser,
    add_route_parser,
    run_nearest_node,
    run_route,
)
from roadgraph_builder.cli.validate import (
    VALIDATION_COMMANDS,
    add_validation_parsers,
    print_validation_error,
    run_validate_document,
)
from roadgraph_builder.cli.trajectory import (
    add_trajectory_parsers,
    run_fuse_traces,
    run_infer_road_class,
    run_infer_signalized_junctions,
    run_match_trajectory,
    run_reconstruct_trips,
    run_stats,
)
from roadgraph_builder.utils.geo import load_wgs84_origin_json


def _load_json_for_cli(path_str: str) -> object:
    """Read JSON from ``path_str``; exit with code 1 if the file is missing."""
    path = Path(path_str)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"File not found: {path}", file=sys.stderr)
        raise SystemExit(1) from None


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

    add_build_parser(sub)
    add_visualize_parser(sub)
    add_validation_parsers(sub)
    add_hd_parsers(sub)

    add_inspect_lidar_parser(sub)

    add_nearest_node_parser(sub)
    add_route_parser(sub)

    add_trajectory_parsers(sub)

    add_fuse_lidar_parser(sub)

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
        return run_build(
            args,
            build_params_from_args=_build_params_from_args,
            export_graph_json_func=export_graph_json,
        )
    if args.command == "visualize":
        return run_visualize(args, build_params_from_args=_build_params_from_args)
    if args.command in VALIDATION_COMMANDS:
        return run_validate_document(
            args,
            load_json=_load_json_for_cli,
            validation_error_func=print_validation_error,
        )
    if args.command == "enrich":
        return run_enrich(
            args,
            load_graph=_cli_load_graph,
            load_json=_load_json_for_cli,
            export_graph_json_func=export_graph_json,
        )
    if args.command == "nearest-node":
        return run_nearest_node(args, load_graph=_cli_load_graph)
    if args.command == "reconstruct-trips":
        return run_reconstruct_trips(args, load_graph=_cli_load_graph)
    if args.command == "fuse-traces":
        return run_fuse_traces(
            args,
            load_graph=_cli_load_graph,
            export_graph_json_func=export_graph_json,
        )
    if args.command == "infer-signalized-junctions":
        return run_infer_signalized_junctions(
            args,
            load_graph=_cli_load_graph,
            export_graph_json_func=export_graph_json,
        )
    if args.command == "infer-road-class":
        return run_infer_road_class(
            args,
            load_graph=_cli_load_graph,
            export_graph_json_func=export_graph_json,
        )
    if args.command == "match-trajectory":
        return run_match_trajectory(args, load_graph=_cli_load_graph)
    if args.command == "stats":
        return run_stats(args, load_graph=_cli_load_graph)
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
        return run_infer_lane_count(
            args,
            load_graph=_cli_load_graph,
            load_json=_load_json_for_cli,
            export_graph_json_func=export_graph_json,
        )
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
    if args.command == "guidance":
        return run_guidance(args, load_json=_load_json_for_cli)
    if args.command == "validate-guidance":
        return run_validate_guidance(
            args,
            load_json=_load_json_for_cli,
            validation_error_func=print_validation_error,
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
