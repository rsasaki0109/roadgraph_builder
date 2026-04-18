"""2D geometry helpers for trajectory clustering and centerline construction.

TODO: LiDAR — boundary extraction helpers can live alongside, but keep separate modules.
TODO: camera — projection/calibration is out of scope for MVP geometry.
"""

from __future__ import annotations

import numpy as np

# Future extension notes (repository-wide):
# - graph fusion: align multiple graphs before merging nodes/edges.
# - routing graph: derive a simplified graph for path search.


def _point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Minimum distance from P to segment AB."""
    abx = bx - ax
    aby = by - ay
    ab2 = abx * abx + aby * aby
    if ab2 < 1e-18:
        return float(np.hypot(px - ax, py - ay))
    t = max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / ab2))
    qx = ax + t * abx
    qy = ay + t * aby
    return float(np.hypot(px - qx, py - qy))


def _closest_point_on_polyline(
    px: float, py: float, poly: list[tuple[float, float]]
) -> tuple[float, tuple[float, float], int, float]:
    """Return ``(distance, point, segment_index, arc_length_along_poly)`` to the polyline.

    ``segment_index`` is the starting vertex of the segment that owns the closest
    point. ``arc_length_along_poly`` is measured from ``poly[0]`` to the projection.
    """
    best_d = float("inf")
    best_pt = (poly[0][0], poly[0][1])
    best_idx = 0
    best_arc = 0.0
    cum = 0.0
    for i in range(len(poly) - 1):
        ax, ay = poly[i]
        bx, by = poly[i + 1]
        abx, aby = bx - ax, by - ay
        ab2 = abx * abx + aby * aby
        if ab2 < 1e-18:
            t_clamped = 0.0
            qx, qy = ax, ay
        else:
            t = ((px - ax) * abx + (py - ay) * aby) / ab2
            t_clamped = max(0.0, min(1.0, t))
            qx = ax + t_clamped * abx
            qy = ay + t_clamped * aby
        d = float(np.hypot(px - qx, py - qy))
        if d < best_d:
            best_d = d
            best_pt = (qx, qy)
            best_idx = i
            seg_len = float(np.hypot(abx, aby))
            best_arc = cum + t_clamped * seg_len
        cum += float(np.hypot(abx, aby))
    return best_d, best_pt, best_idx, best_arc


def split_polylines_at_t_junctions(
    polylines: list[list[tuple[float, float]]],
    merge_threshold_m: float,
    *,
    min_interior_m: float = 1.0,
) -> list[list[tuple[float, float]]]:
    """Split every polyline where another polyline's endpoint falls near its interior.

    Treats the endpoint-proximity graph as a junction hint: if endpoint ``E`` of
    polyline ``A`` is within ``merge_threshold_m`` of a non-endpoint point on
    polyline ``B``, inject the projected point into ``B`` and split ``B`` into
    two polylines that share that junction vertex. The subsequent endpoint-merge
    union-find then fuses ``E`` and the new junction into a single graph node,
    turning what used to be two disjoint edges into a real T-junction.

    ``min_interior_m`` keeps us from splitting right next to ``B``'s own endpoints
    (those cases are already handled by the endpoint-merge pass).
    """
    if merge_threshold_m <= 0:
        return [list(pl) for pl in polylines]

    # Working list; we may subdivide entries, so iterate indices + re-scan.
    work: list[list[tuple[float, float]]] = [list(pl) for pl in polylines]

    def polyline_arc_length(pl: list[tuple[float, float]]) -> float:
        total = 0.0
        for i in range(len(pl) - 1):
            dx = pl[i + 1][0] - pl[i][0]
            dy = pl[i + 1][1] - pl[i][1]
            total += float(np.hypot(dx, dy))
        return total

    # Collect every endpoint that could act as a "junction seed": the first and
    # last vertex of each polyline. For very short polylines we skip splitting.
    changed = True
    # One pass is usually enough, but allow a couple of iterations because a
    # split can expose new T-junctions on the freshly-created halves.
    max_passes = 3
    for _pass in range(max_passes):
        if not changed:
            break
        changed = False
        endpoints: list[tuple[float, float]] = []
        for pl in work:
            if len(pl) >= 2:
                endpoints.append(pl[0])
                endpoints.append(pl[-1])

        new_work: list[list[tuple[float, float]]] = []
        for idx, pl in enumerate(work):
            if len(pl) < 3:
                new_work.append(pl)
                continue
            # Find the best (single) T-projection for this polyline this pass.
            best = None  # (endpoint_xy, projection, segment_idx, arc_along)
            for (ex, ey) in endpoints:
                # Skip this polyline's own endpoints.
                if (ex, ey) == pl[0] or (ex, ey) == pl[-1]:
                    continue
                d, pt, seg_i, arc_along = _closest_point_on_polyline(ex, ey, pl)
                if d > merge_threshold_m:
                    continue
                # Reject projections too close to this polyline's own ends.
                total_len = polyline_arc_length(pl)
                if arc_along < min_interior_m or (total_len - arc_along) < min_interior_m:
                    continue
                if best is None or d < best[0]:
                    best = (d, pt, seg_i, arc_along)
            if best is None:
                new_work.append(pl)
                continue
            _d, proj_pt, seg_i, _arc = best
            # Split pl at seg_i into [pl[:seg_i+1] + proj_pt] and [proj_pt + pl[seg_i+1:]].
            left = list(pl[: seg_i + 1]) + [proj_pt]
            right = [proj_pt] + list(pl[seg_i + 1:])
            if len(left) >= 2 and len(right) >= 2:
                new_work.append(left)
                new_work.append(right)
                changed = True
            else:
                new_work.append(pl)
        work = new_work

    return work


def simplify_polyline_rdp(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    """Douglas–Peucker simplification (2D). Keeps endpoints; epsilon in same units as coordinates."""
    if epsilon <= 0 or len(points) < 3:
        return list(points)

    def rdp(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(pts) < 3:
            return pts
        ax, ay = pts[0]
        bx, by = pts[-1]
        dmax = 0.0
        idx = 0
        for i in range(1, len(pts) - 1):
            px, py = pts[i]
            d = _point_segment_distance(px, py, ax, ay, bx, by)
            if d > dmax:
                dmax = d
                idx = i
        if dmax > epsilon:
            left = rdp(pts[: idx + 1])
            right = rdp(pts[idx:])
            return left[:-1] + right
        return [pts[0], pts[-1]]

    return rdp(list(points))


def split_indices_by_step(xy: np.ndarray, max_step: float) -> list[tuple[int, int]]:
    """Split point sequence into contiguous ranges where each step <= max_step."""
    if xy.shape[0] == 0:
        return []
    if xy.shape[0] == 1:
        return [(0, 1)]

    idx_start = 0
    ranges: list[tuple[int, int]] = []
    for i in range(1, xy.shape[0]):
        step = float(np.linalg.norm(xy[i] - xy[i - 1]))
        if step > max_step:
            ranges.append((idx_start, i))
            idx_start = i
    ranges.append((idx_start, xy.shape[0]))
    return ranges


def centerline_from_points(
    xy: np.ndarray,
    num_bins: int = 32,
    *,
    smoothing_m: float | None = None,
) -> list[tuple[float, float]]:
    """Arc-length parametrised + Gaussian-smoothed centerline.

    Input ``xy`` is expected to be a **single time-ordered pass** through the
    road segment (the caller — ``trajectory_to_polylines`` — splits trajectory
    gaps before calling). The function walks the points in their given order,
    computes cumulative arc length along that path, and resamples at
    ``num_bins`` uniformly-spaced arc-length positions. At each target, the
    output is a Gaussian-weighted average of the nearby input points in
    arc-length space (not in XY distance), so wobbles along the road get
    smoothed while preserving curvature.

    Args:
        xy: ``(N, 2)`` float array of 2D positions in the same meter frame
            as the surrounding pipeline. Any order; time order preferred.
        num_bins: Number of output samples (polyline vertices). Keeps the
            old parameter name for backward compatibility with the CLI.
        smoothing_m: Gaussian sigma in **arc-length meters**. ``None`` picks a
            sensible default (``total_length / num_bins``), which gives one
            bin-width of smoothing — comparable in detail to the old
            bin-median approach but without the straight-axis assumption.

    Returns:
        Polyline as a list of ``(x, y)`` tuples. At least two vertices when
        the input has any usable spread; empty when ``xy`` is empty.
    """
    if xy.shape[0] == 0:
        return []
    if xy.shape[0] == 1:
        return [(float(xy[0, 0]), float(xy[0, 1]))]

    # Cumulative arc length along the given point order.
    diffs = np.diff(xy, axis=0)
    seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
    s = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total_length = float(s[-1])

    if total_length < 1e-9:
        # All points coincide — return a single vertex.
        return [(float(xy[0, 0]), float(xy[0, 1]))]

    n_samples = max(2, int(num_bins))
    s_targets = np.linspace(0.0, total_length, n_samples)
    sigma = float(smoothing_m) if smoothing_m is not None else total_length / max(n_samples, 1)
    sigma = max(sigma, 1e-6)

    # Gaussian-weighted average in arc-length space. For the bounded-support
    # path we have, a dense (N × n_samples) weight matrix is fine.
    ds = s[:, None] - s_targets[None, :]
    weights = np.exp(-0.5 * (ds / sigma) ** 2)
    weights_sum = weights.sum(axis=0)
    weights_sum = np.where(weights_sum > 0, weights_sum, 1.0)
    smoothed_x = (weights * xy[:, 0:1]).sum(axis=0) / weights_sum
    smoothed_y = (weights * xy[:, 1:2]).sum(axis=0) / weights_sum

    # Anchor the first and last samples to the raw endpoints: Gaussian smoothing
    # at the boundary is one-sided and pulls the endpoint inward, which
    # fragments the graph when the endpoint-merge union-find no longer sees
    # adjacent-segment endpoints as coincident.
    smoothed_x[0] = float(xy[0, 0])
    smoothed_y[0] = float(xy[0, 1])
    smoothed_x[-1] = float(xy[-1, 0])
    smoothed_y[-1] = float(xy[-1, 1])

    polyline: list[tuple[float, float]] = [
        (float(smoothed_x[i]), float(smoothed_y[i])) for i in range(n_samples)
    ]
    return polyline


def polyline_mean_abs_curvature(poly: list[tuple[float, float]] | np.ndarray) -> float:
    """Mean absolute turning angle between consecutive edges of a polyline (radians).

    Lower is smoother. A perfectly straight polyline returns 0.
    Skips degenerate zero-length edges.
    """
    pts = np.asarray(poly, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 3:
        return 0.0
    angles: list[float] = []
    for i in range(1, pts.shape[0] - 1):
        v1 = pts[i] - pts[i - 1]
        v2 = pts[i + 1] - pts[i]
        l1 = float(np.hypot(v1[0], v1[1]))
        l2 = float(np.hypot(v2[0], v2[1]))
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        cosang = float(np.dot(v1, v2) / (l1 * l2))
        cosang = max(-1.0, min(1.0, cosang))
        angles.append(float(np.arccos(cosang)))
    if not angles:
        return 0.0
    return float(np.mean(angles))


def polyline_rms_residual(poly: list[tuple[float, float]] | np.ndarray, xy: np.ndarray) -> float:
    """Root-mean-square perpendicular distance from ``xy`` to ``poly``.

    Measures how well the polyline fits the source points; lower is tighter.
    Uses point-to-segment distance against every polyline segment, taking the
    minimum per input point. Returns 0 for empty inputs.
    """
    pts = np.asarray(poly, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 2 or xy.shape[0] == 0:
        return 0.0
    total = 0.0
    n = 0
    for px, py in xy:
        best = float("inf")
        for i in range(pts.shape[0] - 1):
            d = _point_segment_distance(
                float(px),
                float(py),
                float(pts[i, 0]),
                float(pts[i, 1]),
                float(pts[i + 1, 0]),
                float(pts[i + 1, 1]),
            )
            if d < best:
                best = d
        if best == float("inf"):
            continue
        total += best * best
        n += 1
    if n == 0:
        return 0.0
    return float(np.sqrt(total / n))


def merge_endpoints_union_find(
    points: list[tuple[float, float]],
    merge_dist: float,
) -> tuple[dict[str, tuple[float, float]], dict[int, str]]:
    """Merge endpoints within `merge_dist`; return node positions and index->node_id."""
    n = len(points)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    md2 = merge_dist * merge_dist
    for i in range(n):
        for j in range(i + 1, n):
            dx = points[i][0] - points[j][0]
            dy = points[i][1] - points[j][1]
            if dx * dx + dy * dy <= md2:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        r = find(i)
        groups.setdefault(r, []).append(i)

    node_positions: dict[str, tuple[float, float]] = {}
    idx_to_node: dict[int, str] = {}
    for gid, member_indices in enumerate(sorted(groups.values(), key=lambda ms: min(ms))):
        xs = [points[k][0] for k in member_indices]
        ys = [points[k][1] for k in member_indices]
        cx = float(sum(xs) / len(xs))
        cy = float(sum(ys) / len(ys))
        node_id = f"n{gid}"
        node_positions[node_id] = (cx, cy)
        for k in member_indices:
            idx_to_node[k] = node_id

    return node_positions, idx_to_node
