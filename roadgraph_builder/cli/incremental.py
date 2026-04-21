"""CLI parser and command handler for incremental graph updates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.io.trajectory.loader import Trajectory


def add_update_graph_parser(
    sub,  # type: ignore[no-untyped-def]
    *,
    trajectory_dtype_choices: tuple[str, ...],
) -> None:
    """Register the ``update-graph`` subcommand."""

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
        choices=trajectory_dtype_choices,
        default="float64",
        help=(
            "XY array dtype for loading new_csv (default float64). "
            "float32 is opt-in and may change merged geometry slightly."
        ),
    )


def update_graph_summary(output: str, graph: "Graph") -> dict[str, object]:
    """Build the printed summary for ``update-graph``."""

    return {"output": output, "nodes": len(graph.nodes), "edges": len(graph.edges)}


def run_update_graph(
    args: argparse.Namespace,
    *,
    load_graph_json_func: Callable[[Path], "Graph"] | None = None,
    load_trajectory_csv_func: Callable[..., "Trajectory"] | None = None,
    update_graph_func: Callable[..., "Graph"] | None = None,
    export_graph_json_func: Callable[..., object] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``update-graph`` from parsed args."""

    if load_graph_json_func is None:
        from roadgraph_builder.io.export.json_loader import load_graph_json as load_graph_json_func
    if load_trajectory_csv_func is None:
        from roadgraph_builder.io.trajectory.loader import load_trajectory_csv as load_trajectory_csv_func
    if update_graph_func is None:
        from roadgraph_builder.pipeline.incremental import update_graph_from_trajectory as update_graph_func
    if export_graph_json_func is None:
        from roadgraph_builder.io.export.json_exporter import export_graph_json as export_graph_json_func

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    existing_path = Path(args.existing_json)
    if not existing_path.is_file():
        print(f"File not found: {existing_path}", file=err)
        return 1
    new_csv_path = Path(args.new_csv)
    if not new_csv_path.is_file():
        print(f"File not found: {new_csv_path}", file=err)
        return 1
    try:
        graph = load_graph_json_func(existing_path)
    except (TypeError, ValueError) as exc:
        print(f"{existing_path}: {exc}", file=err)
        return 1
    try:
        new_traj = load_trajectory_csv_func(new_csv_path, xy_dtype=args.trajectory_dtype)
    except (FileNotFoundError, ValueError) as exc:
        print(f"{new_csv_path}: {exc}", file=err)
        return 1
    merged = update_graph_func(
        graph,
        new_traj,
        max_step_m=args.max_step_m,
        merge_endpoint_m=args.merge_endpoint_m,
        absorb_tolerance_m=args.absorb_tolerance_m,
    )
    export_graph_json_func(merged, args.output)
    print(json.dumps(update_graph_summary(args.output, merged), ensure_ascii=False, indent=2), file=out)
    return 0
