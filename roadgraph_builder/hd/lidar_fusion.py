"""Fit ``attributes.hd.lane_boundaries`` from XY points near each edge centerline.

3D3 additions: ``fit_ground_plane_ransac`` fits a plane to a point cloud using
RANSAC, and ``fuse_lane_boundaries_3d`` filters the cloud to a height band
above the fitted ground plane before running the standard 2D lane-boundary
fusion.  The ``fuse-lidar --ground-plane`` CLI flag activates this path;
omitting it falls back to the existing ``fuse_lane_boundaries_from_points``
which is byte-identical to v0.6.0.
"""

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


# ---------------------------------------------------------------------------
# 3D3: ground-plane RANSAC + 3D-aware fuse
# ---------------------------------------------------------------------------


def fit_ground_plane_ransac(
    points_xyz: np.ndarray,
    *,
    max_iter: int = 200,
    distance_tolerance_m: float = 0.1,
    seed: int = 0,
) -> tuple[np.ndarray, float]:
    """Fit a plane to a point cloud using RANSAC.

    Samples 3 random points per iteration, fits the plane through them, counts
    inliers (points within ``distance_tolerance_m`` of the plane), and keeps
    the hypothesis with the most inliers.  Returns ``(normal_xyz, d)`` such
    that ``normal · p + d ≈ 0`` for inlier points, with ``normal`` normalised.

    Algorithm is seeded for reproducibility via ``seed``.  For ground-plane
    extraction the normal is expected to point roughly upward (positive z).
    The returned normal is flipped to ensure ``normal[2] ≥ 0`` so the caller
    can rely on this convention.

    Args:
        points_xyz: (N, 3) float array of x, y, z coordinates.
        max_iter: Number of RANSAC iterations.
        distance_tolerance_m: Inlier threshold in metres.
        seed: Random seed for reproducibility.

    Returns:
        (normal_xyz, d) — normalised plane normal and offset.

    Raises:
        ValueError: If the array is not (N, 3) with N ≥ 3.
    """
    if points_xyz.ndim != 2 or points_xyz.shape[1] != 3:
        raise ValueError("points_xyz must be an (N, 3) array")
    n = points_xyz.shape[0]
    if n < 3:
        raise ValueError("Need at least 3 points to fit a plane")

    pts = np.asarray(points_xyz, dtype=np.float64)
    rng = np.random.default_rng(seed)

    best_normal = np.array([0.0, 0.0, 1.0])
    best_d = 0.0
    best_inliers = 0

    for _ in range(max_iter):
        # Sample 3 distinct points.
        idx = rng.choice(n, 3, replace=False)
        p0, p1, p2 = pts[idx[0]], pts[idx[1]], pts[idx[2]]
        v1 = p1 - p0
        v2 = p2 - p0
        normal = np.cross(v1, v2)
        norm_len = float(np.linalg.norm(normal))
        if norm_len < 1e-12:
            continue  # degenerate / collinear triple
        normal = normal / norm_len
        d = -float(normal @ p0)

        # Count inliers.
        dist = np.abs(pts @ normal + d)
        n_inliers = int(np.sum(dist <= distance_tolerance_m))
        if n_inliers > best_inliers:
            best_inliers = n_inliers
            best_normal = normal.copy()
            best_d = d

    # Ensure normal points upward (positive z component).
    if best_normal[2] < 0:
        best_normal = -best_normal
        best_d = -best_d

    return best_normal, best_d


def fuse_lane_boundaries_3d(
    graph: Graph,
    points_xyz_i: np.ndarray,
    *,
    height_band_m: tuple[float, float] = (0.0, 0.3),
    max_dist_m: float = 5.0,
    bins: int = 32,
    max_iter: int = 200,
    distance_tolerance_m: float = 0.1,
    seed: int = 0,
) -> Graph:
    """Ground-plane RANSAC filter followed by standard 2D lane-boundary fusion.

    1. Fits a ground plane to ``points_xyz_i[:, :3]`` using RANSAC.
    2. Keeps only points whose signed height above the ground plane falls
       within ``height_band_m`` (default 0.0–0.3 m), discarding vegetation,
       walls, and overhead structures.
    3. Passes the filtered XY projection to ``fuse_lane_boundaries_from_points``
       (unchanged 2D fusion path).

    The ``metadata.lidar`` block is augmented with ground-plane parameters and
    the number of points filtered.

    Args:
        graph: Road graph to update.
        points_xyz_i: (N, 3) or (N, 4) array — columns are x, y, z[, intensity].
            Intensity (column 3) is ignored during ground-plane fitting and
            filtering but the caller may supply it for parity with the existing
            ``load_points_xy_from_las`` output shape.
        height_band_m: (lo, hi) height range above the ground plane to keep.
        max_dist_m: Lateral distance threshold for lane-boundary snap.
        bins: Bin count for the boundary polyline.
        max_iter: RANSAC iterations.
        distance_tolerance_m: RANSAC inlier threshold.
        seed: RANSAC random seed.

    Returns:
        The mutated graph.
    """
    if points_xyz_i.ndim != 2 or points_xyz_i.shape[1] < 3:
        raise ValueError("points_xyz_i must be an (N, 3) or (N, 4) array")

    pts = np.asarray(points_xyz_i, dtype=np.float64)
    xyz = pts[:, :3]  # drop intensity if present

    # Step 1: fit ground plane.
    normal, d = fit_ground_plane_ransac(
        xyz,
        max_iter=max_iter,
        distance_tolerance_m=distance_tolerance_m,
        seed=seed,
    )

    # Step 2: compute height above plane for each point.
    heights = xyz @ normal + d  # signed: positive = above the plane

    lo, hi = float(height_band_m[0]), float(height_band_m[1])
    mask = (heights >= lo) & (heights <= hi)
    filtered_xyz = xyz[mask]
    n_filtered_out = int((~mask).sum())

    # Step 3: project filtered points to XY and run standard 2D fusion.
    points_xy = filtered_xyz[:, :2]
    graph = fuse_lane_boundaries_from_points(
        graph,
        points_xy,
        max_dist_m=max_dist_m,
        bins=bins,
    )

    # Augment lidar metadata with ground-plane info.
    lidar_block: dict[str, object] = {
        "ground_plane_normal": normal.tolist(),
        "ground_plane_d": float(d),
        "ground_plane_height_band_m": list(height_band_m),
        "ground_plane_filtered_out": n_filtered_out,
        "ground_plane_kept": int(mask.sum()),
    }
    prev = graph.metadata.get("lidar")
    if isinstance(prev, dict):
        lidar_block = {**prev, **lidar_block}
    graph.metadata = {**graph.metadata, "lidar": lidar_block}
    return graph
