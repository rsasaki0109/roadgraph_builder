"""Attach HD-oriented attribute slots to an SD-seed graph (trajectory-derived)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.hd.boundaries import centerline_lane_boundaries, polyline_to_json_points

if TYPE_CHECKING:
    from roadgraph_builder.hd.refinement import EdgeHDRefinement

EnrichStrategy = Literal["envelope"]

_PIPELINE_VERSION = "0.2"


def _default_edge_hd() -> dict[str, object]:
    return {
        "tier": "sd_seed",
        "target_tier": "hd",
        "lane_boundaries": {"left": [], "right": []},
        "semantic_rules": [],
        "quality": "trajectory_derived",
        "note": "Lane boundaries empty until LiDAR/camera observations are fused.",
    }


def _default_node_hd() -> dict[str, object]:
    return {
        "vertical_model": "unknown",
        "elevation_m": None,
    }


def _compute_slope_deg_from_edge(edge) -> float | None:  # type: ignore[no-untyped-def]
    """Compute slope (degrees) from edge attributes if 3D data is available.

    Uses ``attributes.slope_deg`` when already annotated by the 3D build path,
    otherwise falls back to ``attributes.polyline_z`` if present.
    Returns ``None`` when no elevation data is available.
    """
    import math

    attrs = edge.attributes if isinstance(edge.attributes, dict) else {}
    # Already computed by 3D build path.
    sd = attrs.get("slope_deg")
    if sd is not None:
        try:
            return float(sd)
        except (TypeError, ValueError):
            pass
    # Fallback: compute from polyline_z.
    pz = attrs.get("polyline_z")
    if not isinstance(pz, list) or len(pz) < 2:
        return None
    pl = edge.polyline
    total_arc = 0.0
    for i in range(len(pl) - 1):
        dx = pl[i + 1][0] - pl[i][0]
        dy = pl[i + 1][1] - pl[i][1]
        total_arc += math.hypot(dx, dy)
    if total_arc < 1e-6:
        return 0.0
    dz = float(pz[-1]) - float(pz[0])
    return math.degrees(math.atan2(dz, total_arc))


@dataclass(frozen=True)
class SDToHDConfig:
    """Controls SD→HD enrichment."""

    strategy: EnrichStrategy = "envelope"
    # If set and positive, fill lane_boundaries by offsetting the edge centerline (meters).
    lane_width_m: float | None = None


def enrich_sd_to_hd(
    graph: Graph,
    config: SDToHDConfig | None = None,
    *,
    refinements: list[EdgeHDRefinement] | None = None,
) -> Graph:
    """Add HD-oriented metadata and per-feature ``attributes.hd`` slots.

    With ``lane_width_m``, writes **centerline-offset** left/right polylines (HD-lite),
    not survey-grade boundaries. LiDAR/camera fusion can replace these later.

    When ``refinements`` is provided (a list of ``EdgeHDRefinement``), the
    per-edge refined half-width and centerline offset are applied on top of
    the initial lane-boundary computation. Passing ``refinements=None``
    preserves backward-compatible behaviour.
    """
    cfg = config or SDToHDConfig()
    if cfg.strategy != "envelope":
        raise ValueError(f"Unsupported strategy: {cfg.strategy!r}")

    has_ribbon = cfg.lane_width_m is not None and cfg.lane_width_m > 0

    sd_to_hd_meta: dict[str, object] = {
        "pipeline_version": _PIPELINE_VERSION,
        "status": "centerline_boundaries_hd_lite" if has_ribbon else "envelope",
        "stages_completed": (
            ["attach_hd_attribute_slots", "centerline_offset_boundaries"]
            if has_ribbon
            else ["attach_hd_attribute_slots"]
        ),
        "stages_pending": [
            "lidar_boundary_refinement",
            "camera_semantics",
            "fusion_refine",
            "lanelet2_export",
        ],
        "navigation_hints": {
            "sd_nav_maneuvers": "topology_geometry_v1",
            "reference": "nav/sd_nav.json",
            "description": "Coarse allowed_maneuvers at digitized end nodes; pair with HD lane boundaries when present.",
        },
        "notes": (
            "Centerline offsets by half lane width; not survey-grade."
            if has_ribbon
            else "Trajectory-only seed; boundaries and rules are placeholders."
        ),
    }
    if has_ribbon:
        sd_to_hd_meta["lane_width_m"] = cfg.lane_width_m
    graph.metadata = {
        **graph.metadata,
        "sd_to_hd": sd_to_hd_meta,
    }

    for e in graph.edges:
        attrs = dict(e.attributes)
        prev_hd = attrs.get("hd")
        base = _default_edge_hd()
        if isinstance(prev_hd, dict):
            merged: dict[str, object] = {**base, **prev_hd}
        else:
            merged = dict(base)
        # 3D: propagate slope into hd block when elevation data is present.
        slope = _compute_slope_deg_from_edge(e)
        if slope is not None:
            merged["slope_deg"] = slope
        if has_ribbon:
            assert cfg.lane_width_m is not None
            left, right = centerline_lane_boundaries(e.polyline, cfg.lane_width_m)
            if left and right:
                merged["lane_boundaries"] = {
                    "left": polyline_to_json_points(left),
                    "right": polyline_to_json_points(right),
                }
                merged["quality"] = "centerline_offset_hd_lite"
                merged["note"] = "Offsets from centerline by half lane width; not survey-grade."
            else:
                merged["lane_boundaries"] = {"left": [], "right": []}
                merged["quality"] = "trajectory_derived_insufficient_polyline"
                merged["note"] = "Need at least two centerline points for offset boundaries."
        attrs["hd"] = merged
        e.attributes = attrs

    for n in graph.nodes:
        attrs = dict(n.attributes)
        prev_hd = attrs.get("hd")
        base = _default_node_hd()
        if isinstance(prev_hd, dict):
            merged_n: dict[str, object] = {**base, **prev_hd}
        else:
            merged_n = dict(base)
        # 3D: pick up elevation_m from node attributes when available.
        elev = attrs.get("elevation_m")
        if elev is not None:
            try:
                merged_n["elevation_m"] = float(elev)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass
        attrs["hd"] = merged_n
        n.attributes = attrs

    # Apply multi-source refinements when provided (backward-compatible: None = skip).
    if refinements is not None:
        from roadgraph_builder.hd.refinement import apply_refinements_to_graph
        apply_refinements_to_graph(
            graph,
            refinements,
            base_lane_width_m=cfg.lane_width_m or 3.5,
        )

    return graph
