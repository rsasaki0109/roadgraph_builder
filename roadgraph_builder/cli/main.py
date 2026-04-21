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
from roadgraph_builder.cli.dataset import (
    add_process_dataset_parser,
    run_process_dataset,
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
from roadgraph_builder.cli.incremental import (
    add_update_graph_parser,
    run_update_graph,
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
    add_update_graph_parser(sub, trajectory_dtype_choices=_TRAJECTORY_DTYPE_CHOICES)
    add_process_dataset_parser(sub, trajectory_dtype_choices=_TRAJECTORY_DTYPE_CHOICES)

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
        return run_update_graph(args, export_graph_json_func=export_graph_json)
    if args.command == "process-dataset":
        return run_process_dataset(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
