"""CLI parser and command handlers for HD-lite enrichment commands."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


LoadGraph = Callable[[str], "Graph"]
LoadJson = Callable[[str], object]


class CliHDError(ValueError):
    """User-facing HD CLI error."""


def add_hd_parsers(sub) -> None:  # type: ignore[no-untyped-def]
    """Register HD-lite enrichment subcommands."""

    enr = sub.add_parser(
        "enrich",
        help="Attach SD->HD metadata; optional centerline-offset lane boundaries (--lane-width-m).",
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


def optional_json_object(
    *,
    path: str | None,
    load_json: LoadJson,
    command: str,
    option: str,
) -> dict[str, object] | None:
    """Load an optional JSON object argument."""

    if not path:
        return None
    data = load_json(path)
    if not isinstance(data, dict):
        raise CliHDError(f"{command}: {option} must be a JSON object.")
    return data


def build_hd_refinements(
    args: argparse.Namespace,
    *,
    load_json: LoadJson,
    refine_hd_edges_func: Callable[..., object],
) -> object | None:
    """Resolve optional lane/camera refinement inputs for ``enrich``."""

    if not (args.lane_markings_json or args.camera_detections_json):
        return None
    lane_markings = optional_json_object(
        path=args.lane_markings_json,
        load_json=load_json,
        command="enrich",
        option="--lane-markings-json",
    )
    camera_detections = optional_json_object(
        path=args.camera_detections_json,
        load_json=load_json,
        command="enrich",
        option="--camera-detections-json",
    )
    graph_json = load_json(args.input_json)
    if not isinstance(graph_json, dict):
        raise CliHDError("enrich: input graph JSON root must be an object.")
    return refine_hd_edges_func(
        graph_json,
        lane_markings=lane_markings,
        camera_detections=camera_detections,
        base_lane_width_m=args.lane_width_m or 3.5,
    )


def lane_inference_summary(inferences) -> dict[str, object]:  # type: ignore[no-untyped-def]
    """Build the printed summary for ``infer-lane-count``."""

    return {
        "edges_processed": len(inferences),
        "total_lanes_inferred": sum(inf.lane_count for inf in inferences),
        "sources_summary": {
            src: sum(1 for inf in inferences if src in inf.sources_used)
            for src in ("lane_markings", "trace_stats", "default")
        },
    }


def apply_lane_inferences(graph: "Graph", inferences) -> None:  # type: ignore[no-untyped-def]
    """Write lane-count inference results into graph edge HD attributes."""

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
                "lane_index": lane.lane_index,
                "offset_m": lane.offset_m,
                "centerline_m": [list(pt) for pt in lane.centerline_m],
                "confidence": lane.confidence,
            }
            for lane in inf.lanes
        ]
        hd["lane_inference_sources"] = inf.sources_used
        attrs["hd"] = hd
        edge.attributes = attrs


def run_enrich(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    load_json: LoadJson,
    export_graph_json_func: Callable[..., object],
    enrich_sd_to_hd_func: Callable[..., object] | None = None,
    sd_to_hd_config_factory: Callable[..., object] | None = None,
    refine_hd_edges_func: Callable[..., object] | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``enrich`` from parsed args."""

    if enrich_sd_to_hd_func is None:
        from roadgraph_builder.hd.pipeline import enrich_sd_to_hd as enrich_sd_to_hd_func
    if sd_to_hd_config_factory is None:
        from roadgraph_builder.hd.pipeline import SDToHDConfig as sd_to_hd_config_factory
    if refine_hd_edges_func is None:
        from roadgraph_builder.hd.refinement import refine_hd_edges as refine_hd_edges_func

    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)
    try:
        refinements = build_hd_refinements(
            args,
            load_json=load_json,
            refine_hd_edges_func=refine_hd_edges_func,
        )
    except CliHDError as exc:
        print(str(exc), file=err)
        return 1
    enrich_sd_to_hd_func(
        graph,
        sd_to_hd_config_factory(lane_width_m=args.lane_width_m),
        refinements=refinements,
    )
    export_graph_json_func(graph, args.output_json)
    return 0


def run_infer_lane_count(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    load_json: LoadJson,
    export_graph_json_func: Callable[..., object],
    infer_lane_counts_func: Callable[..., object] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``infer-lane-count`` from parsed args."""

    if infer_lane_counts_func is None:
        from roadgraph_builder.hd.lane_inference import infer_lane_counts as infer_lane_counts_func

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)
    graph_json = load_json(args.input_json)
    if not isinstance(graph_json, dict):
        print("infer-lane-count: input graph JSON root must be an object.", file=err)
        return 1
    try:
        lane_markings = optional_json_object(
            path=args.lane_markings_json,
            load_json=load_json,
            command="infer-lane-count",
            option="--lane-markings-json",
        )
    except CliHDError as exc:
        print(str(exc), file=err)
        return 1
    inferences = infer_lane_counts_func(
        graph_json,
        lane_markings=lane_markings,
        base_lane_width_m=args.base_lane_width_m,
        split_gap_m=args.split_gap_m,
        min_lanes=args.min_lanes,
        max_lanes=args.max_lanes,
    )
    apply_lane_inferences(graph, inferences)
    export_graph_json_func(graph, args.output_json)
    print(json.dumps(lane_inference_summary(inferences), indent=2), file=out)
    return 0
