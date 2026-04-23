"""Snap a trajectory onto the graph's edge polylines (map matching, MVP).

Nearest-edge projection per sample: for each input ``(x, y)`` find the edge
whose polyline lies closest, record the parametric position along that edge
and the perpendicular distance. Samples farther than ``max_distance_m`` from
any edge are returned as ``None`` so callers can detect gaps. A graph-local
spatial index keeps repeated samples from scanning every edge. No HMM yet —
samples are independent, which is fine for a graph with short straight-ish
edges but will snap between parallel streets when lanes run side-by-side.

For trajectories in the same meter frame as the graph; use the graph's
``metadata.map_origin`` when converting from lat/lon upstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from roadgraph_builder.routing.edge_index import (
    get_edge_projection_index,
    project_point_on_polyline,
)

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.graph import Graph


@dataclass(frozen=True)
class SnappedPoint:
    """One trajectory sample projected onto the nearest edge's polyline.

    Attributes:
        index: Position of the sample in the input trajectory.
        edge_id: Id of the matched :class:`Edge`.
        projection_xy_m: Closest point on the edge's polyline in the graph frame.
        distance_m: Perpendicular distance from the sample to the projection.
        arc_length_m: Arc length from the edge's start node to the projection.
        edge_length_m: Total arc length of the matched edge's polyline.
        t: Normalised position along the edge (``arc_length / edge_length``).
    """

    index: int
    edge_id: str
    projection_xy_m: tuple[float, float]
    distance_m: float
    arc_length_m: float
    edge_length_m: float
    t: float


def _project_point_on_polyline(
    px: float, py: float, poly
) -> tuple[float, tuple[float, float], float, float]:
    """Backward-compatible wrapper around the shared projection helper."""

    return project_point_on_polyline(px, py, poly)


def snap_trajectory_to_graph(
    graph: "Graph",
    traj_xy,
    *,
    max_distance_m: float = 15.0,
) -> list[SnappedPoint | None]:
    """Project every trajectory sample onto the closest edge within ``max_distance_m``.

    Samples that never find an edge inside the threshold return ``None`` in the
    output list at the same index. The first call per graph builds a spatial
    segment index; later trajectory samples search only nearby cells while
    preserving graph-order tie-breaking.
    """
    xy = list(traj_xy) if not hasattr(traj_xy, "shape") else [tuple(row) for row in traj_xy]
    edge_index = get_edge_projection_index(graph)
    results: list[SnappedPoint | None] = []
    for idx, pt in enumerate(xy):
        px = float(pt[0])
        py = float(pt[1])
        projection = edge_index.nearest_projection(px, py, max_distance_m)
        if projection is None:
            results.append(None)
            continue
        edge_len = projection.edge_length_m
        t = (projection.arc_length_m / edge_len) if edge_len > 1e-9 else 0.0
        results.append(
            SnappedPoint(
                index=idx,
                edge_id=projection.edge_id,
                projection_xy_m=projection.projection_xy_m,
                distance_m=projection.distance_m,
                arc_length_m=projection.arc_length_m,
                edge_length_m=edge_len,
                t=t,
            )
        )
    return results


def coverage_stats(snapped: Iterable["SnappedPoint | None"]) -> dict:
    """Summary of how well a snapped trajectory covered the graph."""
    snapped = list(snapped)
    total = len(snapped)
    hits = [s for s in snapped if s is not None]
    edges_touched = {s.edge_id for s in hits}
    if hits:
        dists = [s.distance_m for s in hits]
        mean_d = float(sum(dists) / len(dists))
        max_d = float(max(dists))
    else:
        mean_d = 0.0
        max_d = 0.0
    return {
        "samples": total,
        "matched": len(hits),
        "matched_ratio": (len(hits) / total) if total else 0.0,
        "edges_touched": len(edges_touched),
        "mean_distance_m": mean_d,
        "max_distance_m": max_d,
    }


__all__ = ["SnappedPoint", "coverage_stats", "snap_trajectory_to_graph"]
