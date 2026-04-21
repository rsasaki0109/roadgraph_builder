"""CLI parser and command handlers for routing commands."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Callable, Sequence, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.routing.shortest_path import Route


LoadGraph = Callable[[str], "Graph"]
LoadJson = Callable[[str], object]


class CliRoutingError(ValueError):
    """User-facing routing CLI error."""


@dataclass(frozen=True)
class ResolvedRouteEndpoint:
    """A route endpoint after optional lat/lon snapping."""

    node_id: str
    snap: dict[str, float] | None


def add_nearest_node_parser(sub) -> None:  # type: ignore[no-untyped-def]
    """Register the ``nearest-node`` subcommand."""

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


def add_route_parser(sub) -> None:  # type: ignore[no-untyped-def]
    """Register the ``route`` subcommand."""

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


def turn_restrictions_from_document(doc: object) -> list[dict]:
    """Extract CLI-consumable turn restriction dicts from supported JSON roots."""

    if isinstance(doc, dict):
        maybe = doc.get("turn_restrictions", [])
        if isinstance(maybe, list):
            return [r for r in maybe if isinstance(r, dict)]
        return []
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    return []


def resolve_route_endpoint(
    graph: "Graph",
    *,
    label: str,
    latlon: Sequence[float] | None,
    positional: str | None,
    origin_lat: float | None,
    origin_lon: float | None,
    graph_label: str,
) -> ResolvedRouteEndpoint:
    """Resolve a route endpoint from either a node id or WGS84 coordinate."""

    if latlon is not None and positional is not None:
        raise CliRoutingError("route: pass either a node id or --*-latlon, not both.")
    if latlon is None:
        if positional is None:
            raise CliRoutingError(
                f"route: provide either {label}_node positional or --{label}-latlon."
            )
        return ResolvedRouteEndpoint(node_id=positional, snap=None)

    from roadgraph_builder.routing.nearest import nearest_node

    try:
        result = nearest_node(
            graph,
            lat=latlon[0],
            lon=latlon[1],
            origin_lat=origin_lat,
            origin_lon=origin_lon,
        )
    except ValueError as exc:
        raise CliRoutingError(f"{graph_label}: {exc}") from exc
    return ResolvedRouteEndpoint(
        node_id=result.node_id,
        snap={
            "requested_lat": float(latlon[0]),
            "requested_lon": float(latlon[1]),
            "distance_m": result.distance_m,
        },
    )


def resolve_route_origin(
    graph: "Graph",
    *,
    origin_lat: float | None,
    origin_lon: float | None,
) -> tuple[float, float]:
    """Resolve the WGS84 origin needed for route GeoJSON output."""

    if (origin_lat is None) ^ (origin_lon is None):
        raise CliRoutingError("route --output: pass both --origin-lat and --origin-lon, or neither.")
    if origin_lat is not None and origin_lon is not None:
        return float(origin_lat), float(origin_lon)

    map_origin = graph.metadata.get("map_origin") if isinstance(graph.metadata, dict) else None
    if isinstance(map_origin, dict) and "lat0" in map_origin and "lon0" in map_origin:
        return float(map_origin["lat0"]), float(map_origin["lon0"])
    raise CliRoutingError(
        "route --output: set --origin-lat/--origin-lon or metadata.map_origin {lat0, lon0}."
    )


def route_to_document(
    route: "Route",
    *,
    from_snap: dict[str, float] | None,
    to_snap: dict[str, float] | None,
    restrictions_count: int,
    output: str | None,
) -> dict[str, object]:
    """Serialize the route result to the CLI JSON shape."""

    doc: dict[str, object] = {
        "from_node": route.from_node,
        "to_node": route.to_node,
        "snapped_from": from_snap,
        "snapped_to": to_snap,
        "total_length_m": route.total_length_m,
        "edge_sequence": route.edge_sequence,
        "edge_directions": route.edge_directions,
        "node_sequence": route.node_sequence,
        "applied_restrictions": restrictions_count,
        "output": output,
    }
    if route.lane_sequence is not None:
        doc["lane_sequence"] = route.lane_sequence
    return doc


def run_nearest_node(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``nearest-node`` from parsed args."""

    from roadgraph_builder.routing.nearest import nearest_node

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)
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
    except ValueError as exc:
        print(f"{args.input_json}: {exc}", file=err)
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
        ),
        file=out,
    )
    return 0


def run_route(
    args: argparse.Namespace,
    *,
    load_graph: LoadGraph,
    load_json: LoadJson,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Execute ``route`` from parsed args."""

    from roadgraph_builder.routing.geojson_export import write_route_geojson
    from roadgraph_builder.routing.shortest_path import shortest_path

    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    graph = load_graph(args.input_json)

    missing_endpoint = False
    if args.from_latlon is None and args.from_node is None:
        print("route: provide either from_node positional or --from-latlon.", file=err)
        missing_endpoint = True
    if args.to_latlon is None and args.to_node is None:
        print("route: provide either to_node positional or --to-latlon.", file=err)
        missing_endpoint = True
    if missing_endpoint:
        return 1

    try:
        from_endpoint = resolve_route_endpoint(
            graph,
            label="from",
            latlon=args.from_latlon,
            positional=args.from_node,
            origin_lat=args.origin_lat,
            origin_lon=args.origin_lon,
            graph_label=args.input_json,
        )
        to_endpoint = resolve_route_endpoint(
            graph,
            label="to",
            latlon=args.to_latlon,
            positional=args.to_node,
            origin_lat=args.origin_lat,
            origin_lon=args.origin_lon,
            graph_label=args.input_json,
        )
    except CliRoutingError as exc:
        print(str(exc), file=err)
        return 1

    restrictions: list[dict] = []
    if args.turn_restrictions_json:
        restrictions = turn_restrictions_from_document(load_json(args.turn_restrictions_json))
    try:
        route = shortest_path(
            graph,
            from_endpoint.node_id,
            to_endpoint.node_id,
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
    except KeyError as exc:
        print(f"{args.input_json}: {exc.args[0]}", file=err)
        return 1
    except ValueError as exc:
        print(f"{args.input_json}: {exc}", file=err)
        return 1

    if args.output:
        try:
            lat0, lon0 = resolve_route_origin(
                graph,
                origin_lat=args.origin_lat,
                origin_lon=args.origin_lon,
            )
        except CliRoutingError as exc:
            print(str(exc), file=err)
            return 1
        write_route_geojson(args.output, graph, route, origin_lat=lat0, origin_lon=lon0)

    print(
        json.dumps(
            route_to_document(
                route,
                from_snap=from_endpoint.snap,
                to_snap=to_endpoint.snap,
                restrictions_count=len(restrictions),
                output=args.output if args.output else None,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        file=out,
    )
    return 0
