"""Multi-source HD lane width / centerline offset refinement.

Combines three optional observation sources to produce per-edge width and
centerline-offset corrections that replace the global uniform estimate:

  1. ``attributes.trace_stats`` — lateral jitter from repeated GPS traces.
  2. Lane markings (from detect-lane-markings output) — direct paint position.
  3. Camera detections — curb/lane observations snapped to edges.

Each source contributes evidence. Confidence grows monotonically with the
number of sources used and the number of observation bins available.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class EdgeHDRefinement:
    """Per-edge HD refinement result.

    Attributes:
        edge_id: Graph edge identifier.
        base_half_width_m: Half of the input lane width (unrefined).
        refined_half_width_m: Updated half-width after applying all sources.
        centerline_offset_m: Signed lateral shift of the centerline (positive =
            left in the edge's forward direction).
        sources_used: Names of sources that contributed (subset of
            {"traces", "lane_markings", "camera"}).
        confidence: 0.0–1.0, monotonically increasing with source count and
            observation count.
    """

    edge_id: str
    base_half_width_m: float
    refined_half_width_m: float
    centerline_offset_m: float
    sources_used: list[str]
    confidence: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _confidence(n_sources: int, n_bins: int) -> float:
    """Confidence in [0, 1) that increases with source count and observation count.

    Formula (monotonically increasing in both arguments):
      c = (n_sources / 3) * (1 - exp(-n_bins / 10))

    This ensures:
    - 0 sources → 0.0 regardless of bins.
    - More sources → higher ceiling.
    - More bins → higher value for a given source count.
    """
    if n_sources <= 0:
        return 0.0
    source_factor = min(n_sources, 3) / 3.0
    bin_factor = 1.0 - math.exp(-n_bins / 10.0)
    return round(source_factor * bin_factor, 4)


def _half_width_from_lane_markings(
    edge_id: str,
    lane_markings: dict,
) -> tuple[float | None, float | None, int]:
    """Estimate (half_width, centerline_offset, n_obs) from lane markings.

    Returns (None, None, 0) if no relevant candidates are found.
    The estimate uses the median lateral position of left and right candidates
    for the edge. Half-width = (|t_left| + |t_right|) / 2.
    Centerline offset = (t_left + t_right) / 2.
    """
    candidates = lane_markings.get("candidates", [])
    lefts: list[float] = []
    rights: list[float] = []
    n_obs = 0
    for c in candidates:
        if c.get("edge_id") != edge_id:
            continue
        polyline = c.get("polyline_m", [])
        n_obs += c.get("point_count", len(polyline))
        # Use the y-coordinates of polyline points as a proxy for lateral offset.
        # The polyline is in world XY, but for a straight-ish edge these
        # correspond closely to the t-coordinate.
        ts = [pt[1] if isinstance(pt, (list, tuple)) else pt.get("y", 0.0) for pt in polyline]
        if not ts:
            continue
        t_med = sum(ts) / len(ts)
        if c.get("side") == "left":
            lefts.append(t_med)
        elif c.get("side") == "right":
            rights.append(t_med)

    if not lefts and not rights:
        return None, None, 0

    t_left = sum(lefts) / len(lefts) if lefts else None
    t_right = sum(rights) / len(rights) if rights else None

    if t_left is not None and t_right is not None:
        half_width = (abs(t_left) + abs(t_right)) / 2.0
        offset = (t_left + t_right) / 2.0
    elif t_left is not None:
        half_width = abs(t_left)
        offset = 0.0
    else:
        assert t_right is not None
        half_width = abs(t_right)
        offset = 0.0

    return half_width, offset, n_obs


def _half_width_from_traces(edge: dict) -> tuple[float | None, int]:
    """Estimate half_width from trace_stats lateral jitter (2-sigma = full width)."""
    attrs = edge.get("attributes", {})
    trace_stats = attrs.get("trace_stats")
    if not isinstance(trace_stats, dict):
        return None, 0
    n_obs = trace_stats.get("matched_samples", 0)
    if not isinstance(n_obs, int) or n_obs < 3:
        return None, 0
    # Use matched_samples as a proxy for observation bins.
    # If the trace_stats don't have lateral jitter info, return None.
    return None, n_obs


def _half_width_from_camera(
    edge_id: str,
    camera_detections: dict,
) -> tuple[float | None, int]:
    """Estimate half-width from camera lane detections for this edge."""
    observations = camera_detections.get("observations", [])
    lateral_offsets: list[float] = []
    for obs in observations:
        if obs.get("edge_id") != edge_id:
            continue
        kind = obs.get("kind", "")
        if "lane" not in kind.lower() and "curb" not in kind.lower():
            continue
        # Try to extract lateral position hint.
        xy = obs.get("world_xy_m")
        if isinstance(xy, dict):
            lateral_offsets.append(abs(float(xy.get("y", 0.0))))
        elif isinstance(xy, (list, tuple)) and len(xy) >= 2:
            lateral_offsets.append(abs(float(xy[1])))

    if not lateral_offsets:
        return None, 0
    return sum(lateral_offsets) / len(lateral_offsets), len(lateral_offsets)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def refine_hd_edges(
    graph_json: dict,
    *,
    lane_markings: dict | None = None,
    camera_detections: dict | None = None,
    base_lane_width_m: float = 3.5,
) -> list[EdgeHDRefinement]:
    """Compute per-edge HD refinement from multiple observation sources.

    For each edge in graph_json, collects evidence from available sources
    and returns an EdgeHDRefinement. Edges with no observations keep the
    base_lane_width_m and a confidence of 0.0.

    Sources:
    - ``traces``: uses ``attributes.trace_stats.matched_samples`` as a
      proxy for observation count (no direct width estimate without raw points).
    - ``lane_markings``: uses candidate lateral positions per edge.
    - ``camera``: uses lane/curb detection lateral offsets per edge.

    When multiple sources provide width estimates, they are averaged. The
    base width is used as a fallback when no source provides a width estimate
    but an observation count is known.
    """
    base_half = base_lane_width_m / 2.0
    results: list[EdgeHDRefinement] = []

    for edge in graph_json.get("edges", []):
        edge_id = edge.get("id", "")

        sources_used: list[str] = []
        width_estimates: list[float] = []
        offset_estimates: list[float] = []
        total_bins = 0

        # Source 1: trace_stats.
        trace_hw, trace_bins = _half_width_from_traces(edge)
        if trace_bins > 0:
            sources_used.append("traces")
            total_bins += trace_bins
            if trace_hw is not None:
                width_estimates.append(trace_hw)

        # Source 2: lane markings.
        if lane_markings is not None:
            lm_hw, lm_offset, lm_bins = _half_width_from_lane_markings(edge_id, lane_markings)
            if lm_bins > 0:
                sources_used.append("lane_markings")
                total_bins += lm_bins
                if lm_hw is not None:
                    width_estimates.append(lm_hw)
                if lm_offset is not None:
                    offset_estimates.append(lm_offset)

        # Source 3: camera detections.
        if camera_detections is not None:
            cam_hw, cam_bins = _half_width_from_camera(edge_id, camera_detections)
            if cam_bins > 0:
                sources_used.append("camera")
                total_bins += cam_bins
                if cam_hw is not None:
                    width_estimates.append(cam_hw)

        # Compute refined values.
        refined_hw = (
            sum(width_estimates) / len(width_estimates)
            if width_estimates
            else base_half
        )
        centerline_offset = (
            sum(offset_estimates) / len(offset_estimates)
            if offset_estimates
            else 0.0
        )
        conf = _confidence(len(sources_used), total_bins)

        results.append(
            EdgeHDRefinement(
                edge_id=edge_id,
                base_half_width_m=base_half,
                refined_half_width_m=refined_hw,
                centerline_offset_m=centerline_offset,
                sources_used=sources_used,
                confidence=conf,
            )
        )

    return results


def apply_refinements_to_graph(
    graph: object,
    refinements: list[EdgeHDRefinement],
    *,
    base_lane_width_m: float = 3.5,
) -> None:
    """Apply EdgeHDRefinement list to a Graph object in-place.

    Updates each edge's ``attributes.hd.lane_boundaries`` using the refined
    half-width, and records the refinement metadata in
    ``attributes.hd.hd_refinement``.
    """
    from roadgraph_builder.hd.boundaries import centerline_lane_boundaries, polyline_to_json_points

    ref_by_id = {r.edge_id: r for r in refinements}

    for edge in graph.edges:  # type: ignore[union-attr]
        ref = ref_by_id.get(edge.id)
        if ref is None:
            continue
        attrs = dict(edge.attributes)
        hd = dict(attrs.get("hd", {}))

        # Update lane boundaries with refined half-width.
        lane_width = ref.refined_half_width_m * 2.0
        if lane_width > 0 and len(edge.polyline) >= 2:
            # Apply centerline offset: shift polyline laterally by offset.
            shifted_poly = _shift_polyline(edge.polyline, ref.centerline_offset_m)
            left, right = centerline_lane_boundaries(shifted_poly, lane_width)
            if left and right:
                hd["lane_boundaries"] = {
                    "left": polyline_to_json_points(left),
                    "right": polyline_to_json_points(right),
                }
                hd["quality"] = "multi_source_hd_lite"

        hd["hd_refinement"] = {
            "base_half_width_m": ref.base_half_width_m,
            "refined_half_width_m": ref.refined_half_width_m,
            "centerline_offset_m": ref.centerline_offset_m,
            "sources_used": ref.sources_used,
            "confidence": ref.confidence,
        }
        attrs["hd"] = hd
        edge.attributes = attrs


def _shift_polyline(
    polyline: list[tuple[float, float]],
    offset_m: float,
) -> list[tuple[float, float]]:
    """Shift polyline laterally by ``offset_m`` (positive = left)."""
    if abs(offset_m) < 1e-9 or len(polyline) < 2:
        return polyline
    import math
    result: list[tuple[float, float]] = []
    for i, (x, y) in enumerate(polyline):
        # Compute local normal.
        if i == 0:
            dx = polyline[1][0] - polyline[0][0]
            dy = polyline[1][1] - polyline[0][1]
        elif i == len(polyline) - 1:
            dx = polyline[-1][0] - polyline[-2][0]
            dy = polyline[-1][1] - polyline[-2][1]
        else:
            dx = polyline[i + 1][0] - polyline[i - 1][0]
            dy = polyline[i + 1][1] - polyline[i - 1][1]
        ln = math.hypot(dx, dy)
        if ln < 1e-9:
            result.append((x, y))
        else:
            # Left normal: (-dy/ln, dx/ln).
            nx, ny = -dy / ln, dx / ln
            result.append((x + offset_m * nx, y + offset_m * ny))
    return result


__all__ = ["EdgeHDRefinement", "refine_hd_edges", "apply_refinements_to_graph"]
