"""Infer a coarse ``road_class`` per edge from observed GPS speed.

Snap the source trajectory to the built graph, compute per-edge speeds from
consecutive samples that land on the same edge, and classify each edge by
the median observed speed. Writes ``attributes.observed_speed_mps_median``,
``attributes.observed_speed_samples``, and ``attributes.road_class_inferred``
onto every edge that saw at least ``min_samples`` speed observations.

Classes (default thresholds, metres per second → km/h):
    ``highway``     ≥ 20 mps (~72 km/h)
    ``arterial``    ≥ 10 mps (~36 km/h)
    ``residential`` otherwise
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from roadgraph_builder.routing.map_match import snap_trajectory_to_graph

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.io.trajectory.loader import Trajectory


@dataclass(frozen=True)
class RoadClassThresholds:
    """Speed thresholds (meters/second) used to classify edges by median speed."""

    highway_mps: float = 20.0
    arterial_mps: float = 10.0


def classify_speed(
    median_mps: float, thresholds: RoadClassThresholds | None = None
) -> str:
    th = thresholds or RoadClassThresholds()
    if median_mps >= th.highway_mps:
        return "highway"
    if median_mps >= th.arterial_mps:
        return "arterial"
    return "residential"


def infer_road_class(
    graph: "Graph",
    traj: "Trajectory",
    *,
    max_distance_m: float = 15.0,
    min_samples: int = 3,
    thresholds: RoadClassThresholds | None = None,
) -> dict[str, int]:
    """Annotate every edge with the inferred road class; return class counts.

    For each pair of consecutive trajectory samples matched to the *same* edge
    (as in :func:`snap_trajectory_to_graph`), the along-edge speed is
    ``|arc_length_i+1 − arc_length_i| / (t_{i+1} − t_i)``. Per-edge median
    speed drives the classification.

    Edges with fewer than ``min_samples`` observations keep whatever road_class
    they had (or none at all); the returned count only reflects newly-labelled
    edges in this call.
    """
    snapped = snap_trajectory_to_graph(graph, traj.xy, max_distance_m=max_distance_m)
    ts = traj.timestamps
    per_edge: dict[str, list[float]] = defaultdict(list)
    for i in range(len(snapped) - 1):
        a = snapped[i]
        b = snapped[i + 1]
        if a is None or b is None:
            continue
        if a.edge_id != b.edge_id:
            continue
        dt = float(ts[i + 1] - ts[i])
        if dt <= 0:
            continue
        ds = abs(b.arc_length_m - a.arc_length_m)
        speed = ds / dt
        # Cap at 250 km/h to ignore GPS glitches.
        if speed > 70.0:
            continue
        per_edge[a.edge_id].append(speed)

    counts: dict[str, int] = {}
    for e in graph.edges:
        speeds = per_edge.get(e.id, [])
        if len(speeds) < min_samples:
            continue
        speeds.sort()
        median = speeds[len(speeds) // 2]
        cls = classify_speed(median, thresholds)
        if not isinstance(e.attributes, dict):
            e.attributes = {}
        e.attributes["observed_speed_mps_median"] = float(median)
        e.attributes["observed_speed_samples"] = len(speeds)
        e.attributes["road_class_inferred"] = cls
        counts[cls] = counts.get(cls, 0) + 1
    return counts


__all__ = ["RoadClassThresholds", "classify_speed", "infer_road_class"]
