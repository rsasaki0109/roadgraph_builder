"""CLI parser and command handlers for graph build commands."""

from __future__ import annotations

import argparse
import sys
from typing import Callable, TextIO, TYPE_CHECKING

from roadgraph_builder.pipeline.build_graph import BuildParams

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.io.trajectory.loader import Trajectory


BuildParamsFromArgs = Callable[[argparse.Namespace], BuildParams]

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
        help="Douglas-Peucker tolerance (meters) for edge polylines; omit to skip.",
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


def add_build_parser(sub) -> None:  # type: ignore[no-untyped-def]
    """Register the ``build`` subcommand."""

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


def add_visualize_parser(sub) -> None:  # type: ignore[no-untyped-def]
    """Register the ``visualize`` subcommand."""

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


def run_build(
    args: argparse.Namespace,
    *,
    build_params_from_args: BuildParamsFromArgs = _build_params_from_args,
    load_multi_trajectory_csvs_func: Callable[..., "Trajectory"] | None = None,
    build_graph_from_trajectory_func: Callable[["Trajectory", BuildParams], "Graph"] | None = None,
    build_graph_from_csv_func: Callable[[str, BuildParams], "Graph"] | None = None,
    export_graph_json_func: Callable[..., object] | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``build`` from parsed args."""

    if load_multi_trajectory_csvs_func is None:
        from roadgraph_builder.io.trajectory.loader import (
            load_multi_trajectory_csvs as load_multi_trajectory_csvs_func,
        )
    if build_graph_from_trajectory_func is None:
        from roadgraph_builder.pipeline.build_graph import (
            build_graph_from_trajectory as build_graph_from_trajectory_func,
        )
    if build_graph_from_csv_func is None:
        from roadgraph_builder.pipeline.build_graph import build_graph_from_csv as build_graph_from_csv_func
    if export_graph_json_func is None:
        from roadgraph_builder.io.export.json_exporter import export_graph_json as export_graph_json_func

    err = stderr if stderr is not None else sys.stderr
    params = build_params_from_args(args)
    try:
        if args.extra_csv:
            traj = load_multi_trajectory_csvs_func(
                [args.input_csv, *args.extra_csv],
                load_z=params.use_3d,
                xy_dtype=params.trajectory_xy_dtype,
            )
            graph = build_graph_from_trajectory_func(traj, params)
        else:
            graph = build_graph_from_csv_func(args.input_csv, params)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    except ValueError as exc:
        print(str(exc), file=err)
        return 1
    export_graph_json_func(graph, args.output_json)
    return 0


def run_visualize(
    args: argparse.Namespace,
    *,
    build_params_from_args: BuildParamsFromArgs = _build_params_from_args,
    load_trajectory_csv_func: Callable[..., "Trajectory"] | None = None,
    build_graph_from_trajectory_func: Callable[["Trajectory", BuildParams], "Graph"] | None = None,
    write_trajectory_graph_svg_func: Callable[..., object] | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``visualize`` from parsed args."""

    if load_trajectory_csv_func is None:
        from roadgraph_builder.io.trajectory.loader import load_trajectory_csv as load_trajectory_csv_func
    if build_graph_from_trajectory_func is None:
        from roadgraph_builder.pipeline.build_graph import (
            build_graph_from_trajectory as build_graph_from_trajectory_func,
        )
    if write_trajectory_graph_svg_func is None:
        from roadgraph_builder.viz.svg_export import write_trajectory_graph_svg as write_trajectory_graph_svg_func

    err = stderr if stderr is not None else sys.stderr
    params = build_params_from_args(args)
    try:
        traj = load_trajectory_csv_func(args.input_csv, xy_dtype=params.trajectory_xy_dtype)
        graph = build_graph_from_trajectory_func(traj, params)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    except ValueError as exc:
        print(str(exc), file=err)
        return 1
    write_trajectory_graph_svg_func(
        traj,
        graph,
        args.output_svg,
        width=args.width,
        height=args.height,
    )
    return 0
