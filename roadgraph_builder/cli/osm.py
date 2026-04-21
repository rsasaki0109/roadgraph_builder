"""CLI parser and command handlers for OSM graph/restriction commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.pipeline.build_graph import BuildParams


AddBuildParams = Callable[[argparse.ArgumentParser], None]
BuildParamsFromArgs = Callable[[argparse.Namespace], "BuildParams"]
LoadGraph = Callable[[str], object]
LoadOrigin = Callable[[str], tuple[float, float]]


class CliOsmError(ValueError):
    """User-facing OSM CLI error."""


def add_osm_parsers(
    sub,  # type: ignore[no-untyped-def]
    *,
    add_build_params: AddBuildParams,
) -> None:
    """Register OSM graph and turn-restriction subcommands."""

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
    add_build_params(bog)

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


def resolve_osm_origin(
    *,
    origin_json: str | None,
    origin_lat: float | None,
    origin_lon: float | None,
    load_origin: LoadOrigin,
    command: str,
) -> tuple[float, float]:
    """Resolve WGS84 origin from JSON or explicit coordinates."""

    if origin_json:
        return load_origin(origin_json)
    if origin_lat is not None and origin_lon is not None:
        return float(origin_lat), float(origin_lon)
    raise CliOsmError(f"{command}: pass --origin-json PATH or both --origin-lat and --origin-lon.")


def highway_filter_from_arg(highway_classes: str | None) -> set[str] | None:
    """Parse a comma-separated highway class filter."""

    if not highway_classes:
        return None
    return {item.strip() for item in highway_classes.split(",") if item.strip()}


def turn_restrictions_document(restrictions: list[dict]) -> dict[str, object]:
    """Build the public turn-restrictions JSON document."""

    return {
        "format_version": 1,
        "attribution": "© OpenStreetMap contributors",
        "license": "ODbL-1.0",
        "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
        "turn_restrictions": restrictions,
    }


def run_build_osm_graph(
    args: argparse.Namespace,
    *,
    build_params_from_args: BuildParamsFromArgs,
    load_origin: LoadOrigin,
    export_graph_json_func: Callable[..., object],
    stderr: TextIO | None = None,
) -> int:
    """Execute ``build-osm-graph`` from parsed args."""

    from roadgraph_builder.io.osm import build_graph_from_overpass_highways

    err = stderr if stderr is not None else sys.stderr
    params = build_params_from_args(args)
    try:
        raw = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    if not isinstance(raw, dict):
        print("build-osm-graph: input JSON root must be an object.", file=err)
        return 1
    try:
        lat0, lon0 = resolve_osm_origin(
            origin_json=args.origin_json,
            origin_lat=args.origin_lat,
            origin_lon=args.origin_lon,
            load_origin=load_origin,
            command="build-osm-graph",
        )
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    except CliOsmError as exc:
        print(str(exc), file=err)
        return 1

    graph = build_graph_from_overpass_highways(
        raw,
        origin_lat=lat0,
        origin_lon=lon0,
        params=params,
        highway_filter=highway_filter_from_arg(args.highway_classes),
    )
    export_graph_json_func(graph, args.output_json)
    print(f"Wrote {args.output_json}: {len(graph.nodes)} nodes, {len(graph.edges)} edges.", file=err)
    return 0


def run_convert_osm_restrictions(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``convert-osm-restrictions`` from parsed args."""

    from roadgraph_builder.io.osm import convert_osm_restrictions_to_graph, load_overpass_json
    from roadgraph_builder.io.osm.turn_restrictions import strip_private_fields

    err = stderr if stderr is not None else sys.stderr
    try:
        graph = load_graph(args.graph_json)
        overpass = load_overpass_json(args.restrictions_json)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename}", file=err)
        return 1
    except KeyError as exc:
        print(f"{exc}", file=err)
        return 1
    try:
        result = convert_osm_restrictions_to_graph(
            graph,
            overpass,
            max_snap_distance_m=args.max_snap_m,
            min_edge_tangent_alignment=args.min_alignment,
            id_prefix=args.id_prefix,
        )
    except KeyError as exc:
        print(f"{exc}", file=err)
        return 1

    cleaned = strip_private_fields(result.restrictions)
    Path(args.output_json).write_text(
        json.dumps(turn_restrictions_document(cleaned), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output_json}: {len(cleaned)} restrictions ({len(result.skipped)} skipped).", file=err)
    if args.skipped_json:
        Path(args.skipped_json).write_text(json.dumps(result.skipped, indent=2) + "\n", encoding="utf-8")
    return 0
