"""Routing helpers on ``Graph`` (shortest path, reachability, etc)."""

from roadgraph_builder.routing.geojson_export import (
    build_reachability_geojson,
    build_route_geojson,
    write_reachability_geojson,
    write_route_geojson,
)
from roadgraph_builder.routing.edge_index import EdgeProjection, EdgeProjectionIndex
from roadgraph_builder.routing.hmm_match import HmmMatch, hmm_match_trajectory
from roadgraph_builder.routing.map_match import SnappedPoint, coverage_stats, snap_trajectory_to_graph
from roadgraph_builder.routing.nearest import NearestNode, nearest_node
from roadgraph_builder.routing.reachability import (
    ReachabilityAnalyzer,
    ReachabilityResult,
    ReachableEdge,
    ReachableNode,
    reachable_within,
)
from roadgraph_builder.routing.shortest_path import (
    Route,
    RouteDiagnostics,
    RoutePlanner,
    shortest_path,
)
from roadgraph_builder.routing.trip_reconstruction import Trip, reconstruct_trips, trip_stats_summary

__all__ = [
    "HmmMatch",
    "EdgeProjection",
    "EdgeProjectionIndex",
    "NearestNode",
    "ReachabilityAnalyzer",
    "ReachabilityResult",
    "ReachableEdge",
    "ReachableNode",
    "Route",
    "RouteDiagnostics",
    "RoutePlanner",
    "SnappedPoint",
    "Trip",
    "build_reachability_geojson",
    "build_route_geojson",
    "coverage_stats",
    "hmm_match_trajectory",
    "nearest_node",
    "reachable_within",
    "reconstruct_trips",
    "shortest_path",
    "snap_trajectory_to_graph",
    "trip_stats_summary",
    "write_reachability_geojson",
    "write_route_geojson",
]
