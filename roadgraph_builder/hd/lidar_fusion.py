"""Fit ``attributes.hd.lane_boundaries`` from XY points near each edge centerline."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.hd.boundaries import polyline_to_json_points


def _cross2(tx: float, ty: float, vx: float, vy: float) -> float:
    return tx * vy - ty * vx


def _polyline_length(polyline: list[tuple[float, float]]) -> float:
    s = 0.0
    for i in range(len(polyline) - 1):
        ax, ay = polyline[i]
        bx, by = polyline[i + 1]
        s += math.hypot(bx - ax, by - ay)
    return s


def closest_point_on_polyline(
    px: float,
    py: float,
    polyline: list[tuple[float, float]],
) -> tuple[float, float, tuple[float, float], tuple[float, float]]:
    """Return ``(distance, arc_length, closest_xy, tangent_unit)`` to the polyline."""
    best_d = float("inf")
    best_arc = 0.0
    best_c = (0.0, 0.0)
    best_tan = (1.0, 0.0)
    arc_base = 0.0
    for i in range(len(polyline) - 1):
        ax, ay = polyline[i]
        bx, by = polyline[i + 1]
        abx, aby = bx - ax, by - ay
        apx, apy = px - ax, py - ay
        denom = abx * abx + aby * aby
        seg_len = math.hypot(abx, aby)
        if denom < 1e-18:
            t = 0.0
            cx, cy = ax, ay
        else:
            t = max(0.0, min(1.0, (apx * abx + apy * aby) / denom))
            cx = ax + t * abx
            cy = ay + t * aby
        d = math.hypot(px - cx, py - cy)
        tx, ty = (abx / seg_len, aby / seg_len) if seg_len > 1e-12 else (1.0, 0.0)
        arc_len = arc_base + t * seg_len
        if d < best_d:
            best_d = d
            best_arc = arc_len
            best_c = (cx, cy)
            best_tan = (tx, ty)
        arc_base += seg_len
    return best_d, best_arc, best_c, best_tan


def _bin_median_polyline(
    samples: list[tuple[float, float, float]],
    total_arc: float,
    bins: int,
) -> list[tuple[float, float]]:
    """``samples`` are ``(arc, x, y)``. Return median (x,y) per bin along arc length."""
    if not samples or total_arc < 1e-9:
        return []
    buckets: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for arc, x, y in samples:
        if arc < 0.0:
            arc = 0.0
        if arc > total_arc:
            arc = total_arc
        bi = int(arc / total_arc * bins)
        bi = min(bins - 1, max(0, bi))
        buckets[bi].append((x, y))
    pts_out: list[tuple[float, float]] = []
    for bi in sorted(buckets.keys()):
        xs = [p[0] for p in buckets[bi]]
        ys = [p[1] for p in buckets[bi]]
        pts_out.append((float(np.median(xs)), float(np.median(ys))))
    if len(pts_out) >= 2:
        return pts_out
    samples.sort(key=lambda t: t[0])
    raw = [(p[1], p[2]) for p in samples]
    if len(raw) >= 2:
        if len(raw) > 48:
            step = max(1, len(raw) // 48)
            raw = raw[::step]
        return raw
    return pts_out


def fuse_lane_boundaries_from_points(
    graph: Graph,
    points_xy: np.ndarray,
    *,
    max_dist_m: float = 5.0,
    bins: int = 32,
) -> Graph:
    """Assign XY points to edges by proximity, split left/right of centerline, bin + median.

    Mutates edges that have at least two nearby points (combined sides). Edges with
    no points are left unchanged. Updates ``metadata`` with fusion summary.
    """
    if points_xy.ndim != 2 or points_xy.shape[1] != 2:
        raise ValueError("points_xy must be an (N, 2) array")
    if max_dist_m <= 0:
        raise ValueError("max_dist_m must be positive")
    if bins < 2:
        raise ValueError("bins must be >= 2")

    pts = np.asarray(points_xy, dtype=np.float64)
    n_edges_updated = 0

    for e in graph.edges:
        pl = e.polyline
        if len(pl) < 2:
            continue
        total_arc = _polyline_length(pl)
        if total_arc < 1e-9:
            continue

        left_samples: list[tuple[float, float, float]] = []
        right_samples: list[tuple[float, float, float]] = []
        for j in range(pts.shape[0]):
            px, py = float(pts[j, 0]), float(pts[j, 1])
            d, arc, c, tan = closest_point_on_polyline(px, py, pl)
            if d > max_dist_m:
                continue
            vx, vy = px - c[0], py - c[1]
            if abs(vx) < 1e-12 and abs(vy) < 1e-12:
                continue
            cr = _cross2(tan[0], tan[1], vx, vy)
            if cr > 0:
                left_samples.append((arc, px, py))
            elif cr < 0:
                right_samples.append((arc, px, py))

        if len(left_samples) + len(right_samples) < 2:
            continue

        left_pl = _bin_median_polyline(left_samples, total_arc, bins)
        right_pl = _bin_median_polyline(right_samples, total_arc, bins)

        attrs = dict(e.attributes)
        prev_hd = attrs.get("hd")
        hd: dict[str, object] = dict(prev_hd) if isinstance(prev_hd, dict) else {}
        hd["lane_boundaries"] = {
            "left": polyline_to_json_points(left_pl),
            "right": polyline_to_json_points(right_pl),
        }
        hd["quality"] = "lidar_binned_median"
        hd["note"] = "Boundaries from XY points near centerline (binned median); not survey-grade."
        attrs["hd"] = hd
        e.attributes = attrs
        n_edges_updated += 1

    lidar_block: dict[str, object] = {
        "point_count": int(pts.shape[0]),
        "status": "boundaries_fitted",
        "max_dist_m": max_dist_m,
        "bins": bins,
        "edges_updated": n_edges_updated,
    }
    prev = graph.metadata.get("lidar")
    if isinstance(prev, dict):
        lidar_block = {**prev, **lidar_block}
    graph.metadata = {**graph.metadata, "lidar": lidar_block}
    return graph
