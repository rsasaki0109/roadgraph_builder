"""HD-lite lane ribbons from centerline polylines (no LiDAR required).

Offsets each vertex perpendicular to the local tangent by half the lane width
using a proper miter join: at interior vertices the left / right offset is
placed on the angle bisector of the two incident edge normals, scaled so the
resulting ribbon keeps **uniform perpendicular distance** from the centerline
on straight and curved sections alike. Sharp corners fall back to a bevel
(two separate offset points) once the miter length would exceed
``miter_limit`` times the offset distance.

The result is a geometric prior, not survey-grade HD boundaries.
"""

from __future__ import annotations

import math


_DEFAULT_MITER_LIMIT = 4.0


def polyline_to_json_points(points: list[tuple[float, float]]) -> list[dict[str, float]]:
    """Serialize points for ``attributes.hd.lane_boundaries`` (JSON-friendly)."""
    return [{"x": float(x), "y": float(y)} for x, y in points]


def centerline_lane_boundaries(
    polyline: list[tuple[float, float]],
    lane_width_m: float,
    *,
    miter_limit: float = _DEFAULT_MITER_LIMIT,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Build left/right offset polylines parallel to the centerline.

    Left/right use the path direction (increasing index): **left** is a +90°
    rotation of the tangent in the standard (x, y) plane. Interior vertices
    use the miter join described in the module docstring; degenerate cases
    (zero-length edges, near-180° reversals) fall back to the incoming
    edge normal so the ribbon stays defined.

    Returns empty lists if ``len(polyline) < 2`` or ``lane_width_m <= 0``.
    """
    if lane_width_m <= 0 or len(polyline) < 2:
        return ([], [])
    half = lane_width_m / 2.0
    left = _offset_polyline(polyline, +half, miter_limit=miter_limit)
    right = _offset_polyline(polyline, -half, miter_limit=miter_limit)
    return left, right


def _edge_left_normals(polyline: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Per-edge left unit normals (rotated +90° from tangent). Zero-length edges yield (0,0)."""
    normals: list[tuple[float, float]] = []
    for i in range(len(polyline) - 1):
        dx = polyline[i + 1][0] - polyline[i][0]
        dy = polyline[i + 1][1] - polyline[i][1]
        ln = math.hypot(dx, dy)
        if ln < 1e-12:
            normals.append((0.0, 0.0))
        else:
            normals.append((-dy / ln, dx / ln))
    return normals


def _offset_polyline(
    polyline: list[tuple[float, float]],
    signed_offset: float,
    *,
    miter_limit: float = _DEFAULT_MITER_LIMIT,
) -> list[tuple[float, float]]:
    """Offset ``polyline`` by ``signed_offset`` along each edge's left normal.

    Positive offset produces the left-side ribbon; negative produces the right.
    At interior vertices uses a miter join; bevels when the miter would exceed
    ``miter_limit * |signed_offset|``.
    """
    n = len(polyline)
    if n < 2:
        return list(polyline)
    edge_normals = _edge_left_normals(polyline)
    out: list[tuple[float, float]] = []

    # First vertex uses the first edge's normal.
    nx, ny = edge_normals[0]
    out.append((polyline[0][0] + signed_offset * nx, polyline[0][1] + signed_offset * ny))

    max_miter = miter_limit * abs(signed_offset) if miter_limit > 0 else float("inf")

    for i in range(1, n - 1):
        n1 = edge_normals[i - 1]
        n2 = edge_normals[i]
        # Fallback to whichever normal is non-zero if one edge is degenerate.
        if n1 == (0.0, 0.0) and n2 == (0.0, 0.0):
            out.append((polyline[i][0], polyline[i][1]))
            continue
        if n1 == (0.0, 0.0):
            bx, by = n2
        elif n2 == (0.0, 0.0):
            bx, by = n1
        else:
            bx, by = n1[0] + n2[0], n1[1] + n2[1]
            bl = math.hypot(bx, by)
            if bl < 1e-12:
                # 180° reversal — offset would flip sides. Use the incoming normal
                # as a best-effort continuation.
                bx, by = n1
            else:
                bx, by = bx / bl, by / bl
        # Miter length: we want the projection of (miter_len * bisector) onto n1 to equal signed_offset.
        dot = bx * n1[0] + by * n1[1]
        if dot < 1e-6:
            # Near-perpendicular bisector — treat as bevel.
            out.append((polyline[i][0] + signed_offset * n1[0], polyline[i][1] + signed_offset * n1[1]))
            out.append((polyline[i][0] + signed_offset * n2[0], polyline[i][1] + signed_offset * n2[1]))
            continue
        miter_len = signed_offset / dot
        if abs(miter_len) > max_miter:
            out.append((polyline[i][0] + signed_offset * n1[0], polyline[i][1] + signed_offset * n1[1]))
            out.append((polyline[i][0] + signed_offset * n2[0], polyline[i][1] + signed_offset * n2[1]))
            continue
        out.append((polyline[i][0] + miter_len * bx, polyline[i][1] + miter_len * by))

    # Last vertex uses the last edge's normal.
    nx, ny = edge_normals[-1]
    out.append((polyline[-1][0] + signed_offset * nx, polyline[-1][1] + signed_offset * ny))
    return out
