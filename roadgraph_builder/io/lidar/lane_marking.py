"""Per-edge intensity-peak extraction for lane marking detection.

Uses the physical property that road paint (white/yellow lines) reflects
LiDAR intensity significantly higher than the surrounding road surface.
Produces LaneMarkingCandidate objects (left/right/center) per graph edge
from a raw (N, 4) point array without any ML model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LaneMarkingCandidate:
    """A detected lane marking candidate on one graph edge.

    ``polyline_m`` is a list of (s, t_offset_from_centerline) in local
    edge coordinates, already converted back to world XY by the caller's
    coordinate transform. Actually stored as world-frame (x, y) tuples.
    """

    edge_id: str
    side: str  # "left" | "right" | "center"
    polyline_m: list[tuple[float, float]]
    intensity_median: float
    point_count: int


def _project_points_onto_edge(
    points_xyz_i: np.ndarray,
    polyline: list[tuple[float, float]],
    max_lateral_m: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Project points onto edge curvilinear coordinate frame (s, t).

    Returns (s, t, mask) where s is along-edge distance, t is signed
    lateral offset (left positive), and mask selects points within
    max_lateral_m of the centerline.
    """
    if len(polyline) < 2:
        empty = np.zeros(len(points_xyz_i), dtype=np.float64)
        return empty, empty, np.zeros(len(points_xyz_i), dtype=bool)

    px = points_xyz_i[:, 0]
    py = points_xyz_i[:, 1]

    # Build cumulative arc-length and per-segment data.
    seg_starts = np.array(polyline[:-1], dtype=np.float64)
    seg_ends = np.array(polyline[1:], dtype=np.float64)
    seg_dx = seg_ends[:, 0] - seg_starts[:, 0]
    seg_dy = seg_ends[:, 1] - seg_starts[:, 1]
    seg_len = np.hypot(seg_dx, seg_dy)
    cum_len = np.concatenate([[0.0], np.cumsum(seg_len)])

    n_pts = len(points_xyz_i)
    s_best = np.full(n_pts, -1.0, dtype=np.float64)
    t_best = np.full(n_pts, np.inf, dtype=np.float64)

    for i, (sdx, sdy, sl, s0, (sx, sy)) in enumerate(
        zip(seg_dx, seg_dy, seg_len, cum_len, seg_starts)
    ):
        if sl < 1e-9:
            continue
        # Scalar projection of (p - start) onto segment direction.
        rel_x = px - sx
        rel_y = py - sy
        ux, uy = sdx / sl, sdy / sl
        s_proj = rel_x * ux + rel_y * uy  # along segment
        s_proj_clipped = np.clip(s_proj, 0.0, sl)
        # Lateral offset (left = +).
        t_proj = -rel_x * uy + rel_y * ux

        # Perpendicular distance when clamped.
        foot_x = sx + s_proj_clipped * ux
        foot_y = sy + s_proj_clipped * uy
        dist = np.hypot(px - foot_x, py - foot_y)

        # Update best (closest segment).
        update = dist < np.abs(t_best)
        s_best[update] = s0 + s_proj_clipped[update]
        t_best[update] = t_proj[update]

    mask = np.abs(t_best) <= max_lateral_m
    return s_best, t_best, mask


def _world_xy_from_st(
    s: float,
    t: float,
    polyline: list[tuple[float, float]],
) -> tuple[float, float]:
    """Convert (s, t) back to world (x, y) using the edge polyline."""
    seg_starts = np.array(polyline[:-1], dtype=np.float64)
    seg_ends = np.array(polyline[1:], dtype=np.float64)
    seg_dx = seg_ends[:, 0] - seg_starts[:, 0]
    seg_dy = seg_ends[:, 1] - seg_starts[:, 1]
    seg_len = np.hypot(seg_dx, seg_dy)
    cum_len = np.concatenate([[0.0], np.cumsum(seg_len)])

    for i, (sdx, sdy, sl, s0, (sx, sy)) in enumerate(
        zip(seg_dx, seg_dy, seg_len, cum_len[:-1], seg_starts)
    ):
        s1 = cum_len[i + 1]
        if s <= s1 + 1e-9:
            ds = min(s - s0, sl)
            if sl < 1e-9:
                ux, uy = 1.0, 0.0
            else:
                ux, uy = sdx / sl, sdy / sl
            world_x = sx + ds * ux + t * (-uy)
            world_y = sy + ds * uy + t * ux
            return (float(world_x), float(world_y))

    # Past end — use last segment.
    if seg_len[-1] < 1e-9:
        return polyline[-1]
    ux = seg_dx[-1] / seg_len[-1]
    uy = seg_dy[-1] / seg_len[-1]
    return (
        float(polyline[-1][0] + t * (-uy)),
        float(polyline[-1][1] + t * ux),
    )


def detect_lane_markings(
    graph_json: dict,
    points_xyz_i: np.ndarray,  # (N, 4): x, y, z, intensity
    *,
    max_lateral_m: float = 2.5,
    intensity_percentile: float = 85.0,
    along_edge_bin_m: float = 1.0,
    min_points_per_bin: int = 3,
) -> list[LaneMarkingCandidate]:
    """Per-edge intensity-peak extraction for lane marking detection.

    Algorithm (deterministic, no ML):
    1. For each edge, snap all points within ``max_lateral_m`` of the
       centerline. Project each point to (s, t) along/across the edge.
    2. Compute global intensity threshold = ``intensity_percentile``-th
       percentile across snapped points for the edge.
    3. Bin along s at ``along_edge_bin_m``. In each bin, select points
       above threshold and cluster by t (1-D agglomerative: gaps > 0.5 m
       split). Each cluster whose median intensity is still above the
       threshold becomes a candidate row.
    4. For rows forming continuous sequences (>= 5 bins), emit a
       LaneMarkingCandidate with side tagged by sign of median t
       (left = t > 0.5 m, right = t < -0.5 m, center = |t| < 0.5 m).
    """
    if points_xyz_i.ndim != 2 or points_xyz_i.shape[1] < 4:
        raise ValueError("points_xyz_i must be shape (N, 4): x, y, z, intensity")

    candidates: list[LaneMarkingCandidate] = []
    edges = graph_json.get("edges", [])

    for edge in edges:
        edge_id = edge.get("id", "")
        raw_poly = edge.get("polyline", [])
        if len(raw_poly) < 2:
            continue

        # Parse polyline — supports list-of-dicts or list-of-lists.
        polyline: list[tuple[float, float]] = []
        for pt in raw_poly:
            if isinstance(pt, dict):
                polyline.append((float(pt["x"]), float(pt["y"])))
            elif hasattr(pt, "__iter__"):
                coords = list(pt)
                polyline.append((float(coords[0]), float(coords[1])))

        if len(polyline) < 2:
            continue

        s_all, t_all, mask = _project_points_onto_edge(
            points_xyz_i, polyline, max_lateral_m
        )
        if mask.sum() < min_points_per_bin:
            continue

        s_edge = s_all[mask]
        t_edge = t_all[mask]
        i_edge = points_xyz_i[mask, 3]

        # Edge total arc length.
        seg_starts = np.array(polyline[:-1], dtype=np.float64)
        seg_ends = np.array(polyline[1:], dtype=np.float64)
        total_len = float(np.sum(np.hypot(
            seg_ends[:, 0] - seg_starts[:, 0],
            seg_ends[:, 1] - seg_starts[:, 1],
        )))

        # Global intensity threshold for this edge.
        threshold = float(np.percentile(i_edge, intensity_percentile))

        # Bin along s.
        n_bins = max(1, int(math.ceil(total_len / along_edge_bin_m)))
        bin_edges = np.linspace(0.0, total_len, n_bins + 1)

        # Map: (bin_index, cluster_t_median) → list of t values and intensity.
        # We collect per-bin cluster hits, then look for continuous sequences.

        # Structure: bin_idx -> list of (cluster_t_center, cluster_i_median, pt_count)
        bin_clusters: dict[int, list[tuple[float, float, int]]] = {}

        for b in range(n_bins):
            s_lo, s_hi = bin_edges[b], bin_edges[b + 1]
            in_bin = (s_edge >= s_lo) & (s_edge < s_hi)
            if in_bin.sum() < min_points_per_bin:
                continue
            t_bin = t_edge[in_bin]
            i_bin = i_edge[in_bin]
            # Keep only above-threshold.
            above = i_bin >= threshold
            if above.sum() < min_points_per_bin:
                continue
            t_hi = t_bin[above]
            i_hi = i_bin[above]
            # 1-D agglomerative clustering by t (gap > 0.5 m splits).
            order = np.argsort(t_hi)
            t_sorted = t_hi[order]
            i_sorted = i_hi[order]
            clusters_in_bin: list[tuple[float, float, int]] = []
            cluster_t: list[float] = [float(t_sorted[0])]
            cluster_i: list[float] = [float(i_sorted[0])]
            for j in range(1, len(t_sorted)):
                if t_sorted[j] - t_sorted[j - 1] > 0.5:
                    if len(cluster_t) >= min_points_per_bin:
                        clusters_in_bin.append(
                            (float(np.median(cluster_t)), float(np.median(cluster_i)), len(cluster_t))
                        )
                    cluster_t = []
                    cluster_i = []
                cluster_t.append(float(t_sorted[j]))
                cluster_i.append(float(i_sorted[j]))
            if len(cluster_t) >= min_points_per_bin:
                clusters_in_bin.append(
                    (float(np.median(cluster_t)), float(np.median(cluster_i)), len(cluster_t))
                )
            if clusters_in_bin:
                bin_clusters[b] = clusters_in_bin

        if not bin_clusters:
            continue

        # Group clusters across bins by lateral proximity (< 0.5 m).
        # Each "track" is a dict mapping bin_idx -> (t_median, i_median, count).
        tracks: list[dict[int, tuple[float, float, int]]] = []

        for b in sorted(bin_clusters.keys()):
            for t_center, i_med, cnt in bin_clusters[b]:
                matched = False
                for track in tracks:
                    # Look at the last bin in track to see if this cluster is close.
                    last_b = max(track.keys())
                    if b - last_b > 2:
                        # Gap too large — don't extend.
                        continue
                    last_t = track[last_b][0]
                    if abs(t_center - last_t) < 0.5:
                        track[b] = (t_center, i_med, cnt)
                        matched = True
                        break
                if not matched:
                    tracks.append({b: (t_center, i_med, cnt)})

        # Emit candidates for tracks spanning >= 5 bins.
        for track in tracks:
            if len(track) < 5:
                continue
            t_vals = [v[0] for v in track.values()]
            i_vals = [v[1] for v in track.values()]
            counts = [v[2] for v in track.values()]
            t_med = float(np.median(t_vals))
            i_med = float(np.median(i_vals))
            total_pts = sum(counts)

            if t_med > 0.5:
                side = "left"
            elif t_med < -0.5:
                side = "right"
            else:
                side = "center"

            # Build polyline: one world point per bin.
            poly_pts: list[tuple[float, float]] = []
            for b in sorted(track.keys()):
                s_center = float(bin_edges[b] + bin_edges[b + 1]) / 2.0
                t_center_b = track[b][0]
                xy = _world_xy_from_st(s_center, t_center_b, polyline)
                poly_pts.append(xy)

            if len(poly_pts) < 2:
                continue

            candidates.append(
                LaneMarkingCandidate(
                    edge_id=edge_id,
                    side=side,
                    polyline_m=poly_pts,
                    intensity_median=i_med,
                    point_count=total_pts,
                )
            )

    return candidates


__all__ = ["LaneMarkingCandidate", "detect_lane_markings"]
