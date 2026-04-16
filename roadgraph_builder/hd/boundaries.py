"""HD-lite lane ribbons from centerline polylines (no LiDAR required).

Offsets each vertex perpendicular to the local tangent by half the lane width.
This is a geometric prior, not survey-grade HD boundaries.
"""

from __future__ import annotations

import math


def polyline_to_json_points(points: list[tuple[float, float]]) -> list[dict[str, float]]:
    """Serialize points for ``attributes.hd.lane_boundaries`` (JSON-friendly)."""
    return [{"x": float(x), "y": float(y)} for x, y in points]


def centerline_lane_boundaries(
    polyline: list[tuple[float, float]],
    lane_width_m: float,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Build left/right offset polylines parallel to the centerline.

    Left/right use the path direction (increasing index): **left** is a +90°
    rotation of the tangent in the standard (x, y) plane.

    Returns empty lists if ``len(polyline) < 2`` or ``lane_width_m <= 0``.
    """
    if lane_width_m <= 0:
        return ([], [])
    n = len(polyline)
    if n < 2:
        return ([], [])
    half = lane_width_m / 2.0
    normals = _left_unit_normals(polyline)
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for i in range(n):
        px, py = polyline[i]
        nx, ny = normals[i]
        left.append((px + half * nx, py + half * ny))
        right.append((px - half * nx, py - half * ny))
    return (left, right)


def _left_unit_normals(polyline: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """One inward-facing left normal per vertex (unit length where possible)."""
    n = len(polyline)
    out: list[tuple[float, float]] = []
    fallback = (0.0, 1.0)
    for i in range(n):
        if i == 0:
            dx = polyline[1][0] - polyline[0][0]
            dy = polyline[1][1] - polyline[0][1]
        elif i == n - 1:
            dx = polyline[-1][0] - polyline[-2][0]
            dy = polyline[-1][1] - polyline[-2][1]
        else:
            dx = polyline[i + 1][0] - polyline[i - 1][0]
            dy = polyline[i + 1][1] - polyline[i - 1][1]
        ln = math.hypot(dx, dy)
        if ln < 1e-12:
            out.append(out[-1] if out else fallback)
            continue
        tx = dx / ln
        ty = dy / ln
        # Left normal (CCW from tangent).
        out.append((-ty, tx))
    return out
