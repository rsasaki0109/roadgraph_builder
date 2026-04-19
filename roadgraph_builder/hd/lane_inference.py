"""Per-edge lane-count inference from lane markings and/or trace_stats.

Algorithm (deterministic, no ML):
  1. For each edge collect paint-marker lateral offsets from lane_markings.json
     (candidates keyed by edge_id and lateral_offset from the edge y-axis).
  2. Cluster those offsets with 1-D agglomerative clustering (gap > split_gap_m).
     Consecutive clusters define boundaries; the number of inter-boundary gaps is
     the lane count.
  3. If lane_markings are absent (or yield no clusters for an edge), fall back to
     ``attributes.trace_stats.perpendicular_offsets`` — the number of lateral
     modes there equals the lane count.
  4. If both sources are absent: return lane_count=1, confidence=0.0, source="default".

Lane geometries are computed by offsetting the edge's own polyline laterally by
symmetric / centred offsets derived from base_lane_width_m and the inferred count.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LaneGeometry:
    """Geometry for one inferred lane.

    Attributes:
        lane_index: 0 = leftmost in the edge's digitized direction.
        offset_m: Signed lateral offset from the edge centerline (positive = left).
        centerline_m: Sequence of (x, y) points in the graph meter frame.
        confidence: Per-lane confidence in [0, 1].
    """

    lane_index: int
    offset_m: float
    centerline_m: list[tuple[float, float]]
    confidence: float


@dataclass(frozen=True)
class EdgeLaneInference:
    """Lane-inference result for one edge.

    Attributes:
        edge_id: Graph edge identifier.
        lane_count: Number of inferred lanes (≥1, ≤max_lanes).
        lanes: Per-lane geometry list, length == lane_count.
        sources_used: Subset of {"lane_markings", "trace_stats", "default"}.
    """

    edge_id: str
    lane_count: int
    lanes: list[LaneGeometry]
    sources_used: list[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _offset_polyline(
    polyline: list[tuple[float, float]],
    offset_m: float,
) -> list[tuple[float, float]]:
    """Return a copy of *polyline* shifted laterally by *offset_m* (positive=left)."""
    if abs(offset_m) < 1e-9 or len(polyline) < 2:
        return list(polyline)
    result: list[tuple[float, float]] = []
    n = len(polyline)
    for i, (x, y) in enumerate(polyline):
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
        if ln < 1e-9:
            result.append((x, y))
        else:
            nx, ny = -dy / ln, dx / ln  # left-hand normal
            result.append((x + offset_m * nx, y + offset_m * ny))
    return result


def _cluster_1d(values: list[float], split_gap_m: float) -> list[list[float]]:
    """1-D agglomerative clustering: split whenever gap between sorted values > split_gap_m."""
    if not values:
        return []
    sv = sorted(values)
    clusters: list[list[float]] = [[sv[0]]]
    for v in sv[1:]:
        if v - clusters[-1][-1] > split_gap_m:
            clusters.append([v])
        else:
            clusters[-1].append(v)
    return clusters


def _count_from_marker_clusters(
    clusters: list[list[float]],
    edge_half_width: float,
) -> int:
    """Map boundary-cluster count to lane count.

    Boundaries are clusters of marker positions.  The number of lanes is
    (number_of_interior_gaps_between_clusters) + 1, which equals
    len(clusters) - 1 when both outer edges are present, or len(clusters)
    when only one side is detected.

    We add 1 to account for the road width containing at least 1 lane.
    """
    n = len(clusters)
    if n <= 1:
        return 1
    # Interior + outer boundaries → lanes = boundaries - 1
    return max(1, n - 1)


def _lane_offsets(lane_count: int, half_road_width: float) -> list[float]:
    """Compute symmetric lateral offsets for *lane_count* lanes.

    Returns a list of length *lane_count* with offsets in descending order
    (leftmost first, positive = left).

    For even lane_count: offsets are symmetric around 0 with lane spacing =
    2*half_road_width/lane_count.
    For odd lane_count: the centre lane is at 0, remainder symmetric.
    """
    if lane_count <= 1:
        return [0.0]
    spacing = (2.0 * half_road_width) / lane_count
    # Centre of lane i (0 = leftmost): offset from road centre
    # leftmost offset = half_road_width - spacing/2
    leftmost = half_road_width - spacing / 2.0
    return [leftmost - i * spacing for i in range(lane_count)]


def _lateral_offsets_from_lane_markings(
    edge_id: str,
    lane_markings: dict,
) -> list[float]:
    """Extract all lateral marker positions for *edge_id* from lane_markings."""
    candidates = lane_markings.get("candidates", [])
    offsets: list[float] = []
    for c in candidates:
        if c.get("edge_id") != edge_id:
            continue
        polyline = c.get("polyline_m", [])
        if not polyline:
            continue
        # Use y-coordinates as lateral proxy (same convention as refinement.py).
        ts = [
            pt[1] if isinstance(pt, (list, tuple)) else pt.get("y", 0.0)
            for pt in polyline
        ]
        if ts:
            offsets.append(sum(ts) / len(ts))
    return offsets


def _mode_count_from_perpendicular_offsets(
    perpendicular_offsets: list[float],
    split_gap_m: float,
) -> int:
    """Count lateral modes in a list of perpendicular offset samples.

    Uses the same 1-D agglomerative clustering so the result is consistent
    with the lane-markings path.  Returns at least 1.
    """
    if not perpendicular_offsets:
        return 1
    clusters = _cluster_1d(perpendicular_offsets, split_gap_m)
    return max(1, len(clusters))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def infer_lane_counts(
    graph_json: dict,
    *,
    lane_markings: dict | None = None,
    base_lane_width_m: float = 3.5,
    split_gap_m: float = 2.0,
    min_lanes: int = 1,
    max_lanes: int = 6,
) -> list[EdgeLaneInference]:
    """Infer per-edge lane count and individual lane geometries.

    For each edge in *graph_json* the function:

    1. Collects lateral-marker positions from *lane_markings* (if provided)
       and clusters them.  The cluster count minus one gives the lane count.
    2. Falls back to ``attributes.trace_stats.perpendicular_offsets`` when
       lane_markings are absent or yield no clusters.
    3. Uses ``source="default"`` (lane_count=1) when both sources are absent.

    Per-lane centerlines are computed by offsetting the edge polyline
    symmetrically around the road centreline at spacing = road_width / lane_count.

    Args:
        graph_json: Road graph dict (nodes/edges).
        lane_markings: Optional lane_markings.json dict (with "candidates" list).
        base_lane_width_m: Assumed width of a single lane (used to compute
            road half-width when refined_half_width_m is absent).
        split_gap_m: Gap threshold for 1-D agglomerative clustering (meters).
        min_lanes: Floor on inferred lane count (default 1).
        max_lanes: Ceiling on inferred lane count (default 6).

    Returns:
        List of :class:`EdgeLaneInference`, one per edge.
    """
    results: list[EdgeLaneInference] = []

    for edge in graph_json.get("edges", []):
        edge_id = str(edge.get("id", ""))
        attrs = edge.get("attributes", {})
        hd = attrs.get("hd", {}) if isinstance(attrs.get("hd"), dict) else {}

        # Determine road half-width from refinement or default.
        hd_ref = hd.get("hd_refinement", {}) if isinstance(hd.get("hd_refinement"), dict) else {}
        refined_hw: float | None = hd_ref.get("refined_half_width_m")
        if refined_hw and refined_hw > 0:
            road_half_width = refined_hw
        else:
            road_half_width = base_lane_width_m / 2.0

        polyline_raw = edge.get("polyline", [])
        polyline: list[tuple[float, float]] = []
        for pt in polyline_raw:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                polyline.append((float(pt[0]), float(pt[1])))
            elif isinstance(pt, dict):
                polyline.append((float(pt.get("x", 0.0)), float(pt.get("y", 0.0))))

        sources_used: list[str] = []
        lane_count = 1
        per_lane_confidence = 0.0

        # --- Source 1: lane_markings ---
        if lane_markings is not None:
            offsets = _lateral_offsets_from_lane_markings(edge_id, lane_markings)
            if offsets:
                clusters = _cluster_1d(offsets, split_gap_m)
                inferred = _count_from_marker_clusters(clusters, road_half_width)
                inferred = max(min_lanes, min(max_lanes, inferred))
                lane_count = inferred
                sources_used.append("lane_markings")
                # Confidence: scale with number of marker observations (up to 1.0)
                n_obs = len(offsets)
                per_lane_confidence = round(min(1.0, 1.0 - math.exp(-n_obs / 5.0)), 4)

        # --- Source 2: trace_stats fallback ---
        if not sources_used:
            trace_stats = attrs.get("trace_stats")
            if isinstance(trace_stats, dict):
                perp = trace_stats.get("perpendicular_offsets")
                if isinstance(perp, list) and perp:
                    inferred = _mode_count_from_perpendicular_offsets(
                        [float(v) for v in perp], split_gap_m
                    )
                    inferred = max(min_lanes, min(max_lanes, inferred))
                    lane_count = inferred
                    sources_used.append("trace_stats")
                    n_obs = len(perp)
                    per_lane_confidence = round(min(1.0, 1.0 - math.exp(-n_obs / 10.0)), 4)

        # --- Source 3: default ---
        if not sources_used:
            sources_used.append("default")
            per_lane_confidence = 0.0

        # Clamp
        lane_count = max(min_lanes, min(max_lanes, lane_count))

        # Compute per-lane offsets and centerlines.
        offsets_m = _lane_offsets(lane_count, road_half_width)
        lanes: list[LaneGeometry] = []
        for idx, off in enumerate(offsets_m):
            cl = _offset_polyline(polyline, off) if len(polyline) >= 2 else list(polyline)
            lanes.append(
                LaneGeometry(
                    lane_index=idx,
                    offset_m=round(off, 6),
                    centerline_m=cl,
                    confidence=per_lane_confidence,
                )
            )

        results.append(
            EdgeLaneInference(
                edge_id=edge_id,
                lane_count=lane_count,
                lanes=lanes,
                sources_used=sources_used,
            )
        )

    return results


__all__ = ["LaneGeometry", "EdgeLaneInference", "infer_lane_counts"]
