"""Snap a trajectory onto the graph's edge polylines (map matching, MVP).

Nearest-edge projection per sample: for each input ``(x, y)`` find the edge
whose polyline lies closest, record the parametric position along that edge
and the perpendicular distance. Samples farther than ``max_distance_m`` from
any edge are returned as ``None`` so callers can detect gaps. No HMM yet —
samples are independent, which is fine for a graph with short straight-ish
edges but will snap between parallel streets when lanes run side-by-side.

For trajectories in the same meter frame as the graph; use the graph's
``metadata.map_origin`` when converting from lat/lon upstream.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from roadgraph_builder.core.graph.edge import Edge
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
    """Closest point on ``poly`` (list of (x, y)). Returns (distance, projection, arc_length_at_projection, total_length)."""
    if len(poly) < 2:
        return (float("inf"), (0.0, 0.0), 0.0, 0.0)
    best_d = float("inf")
    best_pt = (0.0, 0.0)
    best_arc = 0.0
    cum = 0.0
    for i in range(len(poly) - 1):
        ax, ay = poly[i]
        bx, by = poly[i + 1]
        abx = bx - ax
        aby = by - ay
        ab2 = abx * abx + aby * aby
        if ab2 < 1e-18:
            t = 0.0
            qx, qy = ax, ay
        else:
            t = ((px - ax) * abx + (py - ay) * aby) / ab2
            t = max(0.0, min(1.0, t))
            qx = ax + t * abx
            qy = ay + t * aby
        d = math.hypot(px - qx, py - qy)
        if d < best_d:
            best_d = d
            best_pt = (qx, qy)
            seg_len = math.hypot(abx, aby)
            best_arc = cum + t * seg_len
        cum += math.hypot(abx, aby)
    return best_d, best_pt, best_arc, cum


def snap_trajectory_to_graph(
    graph: "Graph",
    traj_xy,
    *,
    max_distance_m: float = 15.0,
) -> list[SnappedPoint | None]:
    """Project every trajectory sample onto the closest edge within ``max_distance_m``.

    Samples that never find an edge inside the threshold return ``None`` in the
    output list at the same index. Edges are iterated in graph order and scanned
    per sample — O(N * M) for N points and M edges. Fine for SD demos;
    medium-city traces will want a spatial index.
    """
    xy = list(traj_xy) if not hasattr(traj_xy, "shape") else [tuple(row) for row in traj_xy]
    edges = list(graph.edges)
    if not edges:
        return [None] * len(xy)

    results: list[SnappedPoint | None] = []
    for idx, pt in enumerate(xy):
        px = float(pt[0])
        py = float(pt[1])
        best: SnappedPoint | None = None
        for e in edges:
            d, proj, arc, edge_len = _project_point_on_polyline(px, py, e.polyline)
            if d >= max_distance_m:
                continue
            if best is None or d < best.distance_m:
                t = (arc / edge_len) if edge_len > 1e-9 else 0.0
                best = SnappedPoint(
                    index=idx,
                    edge_id=e.id,
                    projection_xy_m=proj,
                    distance_m=d,
                    arc_length_m=arc,
                    edge_length_m=edge_len,
                    t=t,
                )
        results.append(best)
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
