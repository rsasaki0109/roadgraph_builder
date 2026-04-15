"""CLI entrypoint."""

from __future__ import annotations

import argparse
import sys

from jsonschema import ValidationError

import json
from pathlib import Path

from roadgraph_builder.io.export.json_exporter import export_graph_json
from roadgraph_builder.io.trajectory.loader import load_trajectory_csv
from roadgraph_builder.validation import validate_road_graph_document
from roadgraph_builder.pipeline.build_graph import (
    BuildParams,
    build_graph_from_csv,
    build_graph_from_trajectory,
)
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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="roadgraph_builder", description="Build a road graph from sensor exports.")
    sub = p.add_subparsers(dest="command", required=True)

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

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "build":
        params = _build_params_from_args(args)
        graph = build_graph_from_csv(args.input_csv, params)
        export_graph_json(graph, args.output_json)
        return 0
    if args.command == "visualize":
        params = _build_params_from_args(args)
        traj = load_trajectory_csv(args.input_csv)
        graph = build_graph_from_trajectory(traj, params)
        write_trajectory_graph_svg(
            traj,
            graph,
            args.output_svg,
            width=args.width,
            height=args.height,
        )
        return 0
    if args.command == "validate":
        data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            print("JSON root must be an object", file=sys.stderr)
            return 1
        try:
            validate_road_graph_document(data)
        except ValidationError as e:
            print(e.message, file=sys.stderr)
            return 1
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
