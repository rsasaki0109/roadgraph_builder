"""2D geometry helpers for trajectory clustering and centerline construction.

TODO: LiDAR — boundary extraction helpers can live alongside, but keep separate modules.
TODO: camera — projection/calibration is out of scope for MVP geometry.
"""

from __future__ import annotations

import numpy as np

# Future extension notes (repository-wide):
# - graph fusion: align multiple graphs before merging nodes/edges.
# - intersection topology: detect degree-3+ junctions from edge connectivity.
# - routing graph: derive a simplified graph for path search.


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


def centerline_from_points(xy: np.ndarray, num_bins: int = 32) -> list[tuple[float, float]]:
    """Order points along primary axis (PCA), bin-average, return sparse polyline.

    `num_bins` trades smoothing vs. detail; tune for your trajectory density.
    """
    if xy.shape[0] == 0:
        return []
    if xy.shape[0] == 1:
        return [(float(xy[0, 0]), float(xy[0, 1]))]

    centered = xy - np.mean(xy, axis=0, keepdims=True)
    # 2x2 covariance PCA
    cov = centered.T @ centered / max(xy.shape[0] - 1, 1)
    eigvals, eigvecs = np.linalg.eigh(cov)
    axis = eigvecs[:, int(np.argmax(eigvals))]

    t = centered @ axis  # projection along main direction
    order = np.argsort(t)

    t_sorted = t[order]
    xmin, xmax = float(t_sorted[0]), float(t_sorted[-1])
    if xmax - xmin < 1e-9:
        # Degenerate spread: return endpoints of original order
        return [(float(xy[0, 0]), float(xy[0, 1])), (float(xy[-1, 0]), float(xy[-1, 1]))]

    bins = np.linspace(xmin, xmax, num_bins + 1)
    bin_idx = np.digitize(t_sorted, bins) - 1
    bin_idx = np.clip(bin_idx, 0, num_bins - 1)

    polyline: list[tuple[float, float]] = []
    xy_sorted = xy[order]
    for b in range(num_bins):
        mask = bin_idx == b
        if not np.any(mask):
            continue
        chunk = xy_sorted[mask]
        mx = float(np.mean(chunk[:, 0]))
        my = float(np.mean(chunk[:, 1]))
        polyline.append((mx, my))

    if len(polyline) < 2:
        return [
            (float(xy[order[0], 0]), float(xy[order[0], 1])),
            (float(xy[order[-1], 0]), float(xy[order[-1], 1])),
        ]
    return polyline


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
