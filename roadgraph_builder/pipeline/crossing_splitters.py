"""Fast X/T-junction splitters using uniform grid hashing.

Replaces the O(N²) brute-force pair scans in
``utils.geometry.split_polylines_at_crossings`` and
``split_polylines_at_t_junctions`` with a uniform grid hash that reduces the
effective comparison set from all pairs to only those whose bounding boxes
share at least one grid cell.

Complexity (assuming segment length is O(grid_cell_m)):
  - Index phase: O(S · k)  where S = total segments, k = cells per segment
  - Query phase: O(S · B)  where B = mean bucket size (≪ S under bounded length)
  Overall: O(S log S) in typical road-network inputs.

Invariants preserved:
  - Output polyline geometry is numerically identical to the O(N²) functions
    when the same crossings/projections are detected.
  - Only strict interior crossings (0 < t < 1, 0 < u < 1) are injected.
  - T-junction projection is the exact perpendicular foot, same formula.
  - Endpoint-touch and very-short-interior cases are guarded exactly as before.
"""

from __future__ import annotations

import math
from collections import defaultdict

from roadgraph_builder.utils.geometry import (
    _segment_segment_intersection,
)


# ---------------------------------------------------------------------------
# Internal grid-hash helpers
# ---------------------------------------------------------------------------


def _cells_for_segment(
    ax: float, ay: float, bx: float, by: float, inv_cell: float
) -> list[tuple[int, int]]:
    """Return all grid cells (col, row) touched by segment AB.

    Uses a DDA-like walk along the segment so that every cell the segment
    passes through is included.  The number of cells per segment is
    O(max(|Δcol|, |Δrow|) + 1), which is bounded when segment length is
    bounded relative to the cell size.
    """
    c0 = int(math.floor(min(ax, bx) * inv_cell))
    c1 = int(math.floor(max(ax, bx) * inv_cell))
    r0 = int(math.floor(min(ay, by) * inv_cell))
    r1 = int(math.floor(max(ay, by) * inv_cell))
    cells: list[tuple[int, int]] = []
    for c in range(c0, c1 + 1):
        for r in range(r0, r1 + 1):
            cells.append((c, r))
    return cells


def _build_segment_grid(
    polylines: list[list[tuple[float, float]]],
    inv_cell: float,
) -> tuple[
    dict[tuple[int, int], list[tuple[int, int]]],  # cell → [(poly_idx, seg_idx)]
    list[tuple[float, float, float, float]],         # flat bbox list per segment
]:
    """Index every segment into a grid.  Returns grid dict and per-(poly,seg) bbox list."""
    grid: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for pi, pl in enumerate(polylines):
        for si in range(len(pl) - 1):
            ax, ay = pl[si]
            bx, by = pl[si + 1]
            for cell in _cells_for_segment(ax, ay, bx, by, inv_cell):
                grid[cell].append((pi, si))
    return grid, []  # bbox list not separately needed; kept for API symmetry


def _project_point_to_segment(
    px: float,
    py: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
) -> tuple[float, tuple[float, float], float, float]:
    """Return distance, projected point, segment fraction, and segment length."""
    abx = bx - ax
    aby = by - ay
    ab2 = abx * abx + aby * aby
    if ab2 < 1e-18:
        t_clamped = 0.0
        qx, qy = ax, ay
    else:
        t = ((px - ax) * abx + (py - ay) * aby) / ab2
        t_clamped = max(0.0, min(1.0, t))
        qx = ax + t_clamped * abx
        qy = ay + t_clamped * aby
    seg_len = math.hypot(abx, aby)
    return math.hypot(px - qx, py - qy), (qx, qy), t_clamped, seg_len


# ---------------------------------------------------------------------------
# Fast X-junction splitter
# ---------------------------------------------------------------------------


def split_polylines_at_crossings_fast(
    polylines: list[list[tuple[float, float]]],
    *,
    grid_cell_m: float = 10.0,
) -> list[list[tuple[float, float]]]:
    """Uniform grid hashing + neighbor-bucket pair scan for X-junctions.

    Detects interior X-shaped crossings (both parameters strictly between 0
    and 1) and injects the intersection point into both polylines. Endpoint-
    touch and T-style cases are intentionally ignored — the T-junction pass
    handles those.

    Complexity target: O(N log N) in the number of polyline segments,
    assuming bounded segment length relative to ``grid_cell_m``. Each
    segment hashes its bbox into grid cells; pair scan only compares
    segments sharing at least one cell.

    Args:
        polylines: List of polylines to split at interior crossings.
        grid_cell_m: Grid cell size in the same unit as the coordinates
            (meters in the standard pipeline). Smaller → fewer false
            candidates but more cells per long segment.  10 m is a safe
            default for road networks sampled at 5–25 m spacing.

    Returns:
        New list of polylines with crossing points injected and split.
        The result is geometrically identical to the O(N²) version.
    """
    n = len(polylines)
    if n < 2:
        return [list(pl) for pl in polylines]

    inv_cell = 1.0 / grid_cell_m

    # Per-polyline list of (segment_index, point) injection requests.
    splits: list[list[tuple[int, tuple[float, float]]]] = [[] for _ in range(n)]

    # Build segment grid.
    grid: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for pi, pl in enumerate(polylines):
        if len(pl) < 2:
            continue
        for si in range(len(pl) - 1):
            ax, ay = pl[si]
            bx, by = pl[si + 1]
            for cell in _cells_for_segment(ax, ay, bx, by, inv_cell):
                grid[cell].append((pi, si))

    # For each cell, test every pair of segments from *different* polylines.
    seen: set[tuple[int, int, int, int]] = set()
    for segs in grid.values():
        if len(segs) < 2:
            continue
        for a in range(len(segs)):
            pi, si = segs[a]
            for b in range(a + 1, len(segs)):
                pj, sj = segs[b]
                if pi == pj:
                    continue
                # Canonical key to avoid testing the same pair twice.
                key = (pi, si, pj, sj) if (pi, si) < (pj, sj) else (pj, sj, pi, si)
                if key in seen:
                    continue
                seen.add(key)
                pli = polylines[pi]
                plj = polylines[pj]
                a0, a1 = pli[si], pli[si + 1]
                b0, b1 = plj[sj], plj[sj + 1]
                cross = _segment_segment_intersection(a0, a1, b0, b1)
                if cross is None:
                    continue
                splits[pi].append((si, cross))
                splits[pj].append((sj, cross))

    # Apply injections (same logic as the O(N²) version).
    out: list[list[tuple[float, float]]] = []
    for idx, pl in enumerate(polylines):
        injections = splits[idx]
        if not injections:
            out.append(list(pl))
            continue
        injections.sort(key=lambda s: s[0])
        new_pl: list[tuple[float, float]] = [pl[0]]
        for si in range(len(pl) - 1):
            for inj_si, inj_pt in injections:
                if inj_si == si and inj_pt != new_pl[-1] and inj_pt != pl[si + 1]:
                    new_pl.append(inj_pt)
            new_pl.append(pl[si + 1])

        cross_pts = {pt for _si, pt in injections}
        last_cut = 0
        emitted = False
        for k in range(1, len(new_pl) - 1):
            if new_pl[k] in cross_pts:
                sub = new_pl[last_cut : k + 1]
                if len(sub) >= 2:
                    out.append(list(sub))
                    emitted = True
                last_cut = k
        tail = new_pl[last_cut:]
        if len(tail) >= 2:
            out.append(list(tail))
            emitted = True
        if not emitted:
            out.append(list(pl))

    return out


# ---------------------------------------------------------------------------
# Fast T-junction splitter
# ---------------------------------------------------------------------------


def split_polylines_at_t_junctions_fast(
    polylines: list[list[tuple[float, float]]],
    merge_threshold_m: float,
    *,
    min_interior_m: float = 1.0,
    grid_cell_m: float | None = None,
) -> list[list[tuple[float, float]]]:
    """Uniform grid hashing for T-junction detection.

    Same semantics as the O(N²) ``split_polylines_at_t_junctions`` but uses
    a grid to reduce the candidate segment set for each endpoint query from
    every segment on every polyline to only segments whose expanded bounding
    boxes overlap the endpoint cell.

    Strategy:
      1. Collect all endpoints from the current working list.
      2. Precompute per-segment arc starts and total lengths.
      3. Build a segment grid: hash each segment's bbox expanded by
         ``merge_threshold_m`` into cells using cell size ``grid_cell_m``
         (defaults to ``merge_threshold_m``).
      4. For each endpoint ``E``, query its cell to find candidate segments,
         then run the exact point-to-segment projection on only those segments.
      5. Accept the best per-polyline projection only if it is interior
         (arc guards satisfied).
      6. Split the polyline and repeat up to ``max_passes`` times.

    Complexity target: O(N log N) assuming bounded polyline length relative to
    the grid cell, which limits the number of candidate polylines per query.

    Args:
        polylines: Polylines to split at T-junctions.
        merge_threshold_m: Endpoint-proximity radius for junction detection.
        min_interior_m: Guard against splitting very close to a polyline's
            own endpoints (handled by the endpoint-merge union-find).
        grid_cell_m: Grid cell size; defaults to ``merge_threshold_m``.

    Returns:
        New list of polylines with T-junction injection points inserted and
        polylines split at those points.
    """
    if merge_threshold_m <= 0:
        return [list(pl) for pl in polylines]

    cell = grid_cell_m if grid_cell_m is not None else merge_threshold_m
    if cell <= 0:
        cell = merge_threshold_m
    inv_cell = 1.0 / cell

    def cell_for_point(x: float, y: float) -> tuple[int, int]:
        return (int(math.floor(x * inv_cell)), int(math.floor(y * inv_cell)))

    work: list[list[tuple[float, float]]] = [list(pl) for pl in polylines]
    max_passes = 3

    for _pass in range(max_passes):
        # Collect endpoints.
        endpoints: list[tuple[float, float]] = []
        for pl in work:
            if len(pl) >= 2:
                endpoints.append(pl[0])
                endpoints.append(pl[-1])

        # Build per-polyline arc starts once for this pass.  The segment grid
        # stores segment indices, so we can compute the same arc guards without
        # scanning the entire polyline for every endpoint candidate.
        arc_starts: list[list[float]] = []
        total_lengths: list[float] = []
        for pi, pl in enumerate(work):
            starts = [0.0]
            total = 0.0
            for si in range(len(pl) - 1):
                ax, ay = pl[si]
                bx, by = pl[si + 1]
                total += math.hypot(bx - ax, by - ay)
                starts.append(total)
            arc_starts.append(starts)
            total_lengths.append(total)

        # Index every segment by its bbox expanded by merge_threshold_m. A
        # point query in one cell then sees every segment that could be within
        # the threshold, plus limited bbox false positives that are rejected by
        # the exact projection below.
        segment_grid: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for pi, pl in enumerate(work):
            if len(pl) < 3:
                continue
            for si in range(len(pl) - 1):
                ax, ay = pl[si]
                bx, by = pl[si + 1]
                mn_x = min(ax, bx) - merge_threshold_m
                mx_x = max(ax, bx) + merge_threshold_m
                mn_y = min(ay, by) - merge_threshold_m
                mx_y = max(ay, by) + merge_threshold_m
                c0 = int(math.floor(mn_x * inv_cell))
                c1 = int(math.floor(mx_x * inv_cell))
                r0 = int(math.floor(mn_y * inv_cell))
                r1 = int(math.floor(mx_y * inv_cell))
                for c in range(c0, c1 + 1):
                    for r in range(r0, r1 + 1):
                        segment_grid[(c, r)].append((pi, si))

        # Build a set of endpoints per polyline so we can skip own endpoints
        # efficiently.
        own_endpoints: list[set[tuple[float, float]]] = [
            {pl[0], pl[-1]} if len(pl) >= 2 else set() for pl in work
        ]

        # For each endpoint ``E``, find candidate polylines via the grid and
        # record, per polyline, the best (closest interior) projection from any
        # endpoint.  This is the "inverted" loop: O(E × B) where B is the mean
        # bucket size, not O(P × E).
        # best_per_poly[idx] = (d, pt, seg_i, arc_along) or None
        best_per_poly: list[tuple | None] = [None] * len(work)
        for ex, ey in endpoints:
            ec = cell_for_point(ex, ey)
            candidates = segment_grid.get(ec, [])
            if not candidates:
                continue
            best_for_endpoint: dict[int, tuple[float, tuple[float, float], int, float]] = {}
            for idx, seg_i in candidates:
                pl = work[idx]
                # Skip if this endpoint belongs to this polyline.
                if (ex, ey) in own_endpoints[idx]:
                    continue
                ax, ay = pl[seg_i]
                bx, by = pl[seg_i + 1]
                d, pt, t_clamped, seg_len = _project_point_to_segment(
                    ex, ey, ax, ay, bx, by
                )
                arc_along = arc_starts[idx][seg_i] + t_clamped * seg_len
                cur_endpoint = best_for_endpoint.get(idx)
                if cur_endpoint is None or d < cur_endpoint[0]:
                    best_for_endpoint[idx] = (d, pt, seg_i, arc_along)

            for idx, (d, pt, seg_i, arc_along) in best_for_endpoint.items():
                if d > merge_threshold_m:
                    continue
                total_len = total_lengths[idx]
                if arc_along < min_interior_m or (total_len - arc_along) < min_interior_m:
                    continue
                cur = best_per_poly[idx]
                if cur is None or d < cur[0]:
                    best_per_poly[idx] = (d, pt, seg_i, arc_along)

        changed = False
        new_work: list[list[tuple[float, float]]] = []
        for idx, pl in enumerate(work):
            best = best_per_poly[idx]
            if best is None:
                new_work.append(pl)
                continue

            _d, proj_pt, seg_i, _arc = best
            left = list(pl[: seg_i + 1]) + [proj_pt]
            right = [proj_pt] + list(pl[seg_i + 1:])
            if len(left) >= 2 and len(right) >= 2:
                new_work.append(left)
                new_work.append(right)
                changed = True
            else:
                new_work.append(pl)
        work = new_work
        if not changed:
            break

    return work
