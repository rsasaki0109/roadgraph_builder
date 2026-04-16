"""Attach HD-oriented attribute slots to an SD-seed graph (trajectory-derived)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.hd.boundaries import centerline_lane_boundaries, polyline_to_json_points

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


@dataclass(frozen=True)
class SDToHDConfig:
    """Controls SD→HD enrichment."""

    strategy: EnrichStrategy = "envelope"
    # If set and positive, fill lane_boundaries by offsetting the edge centerline (meters).
    lane_width_m: float | None = None


def enrich_sd_to_hd(graph: Graph, config: SDToHDConfig | None = None) -> Graph:
    """Add HD-oriented metadata and per-feature ``attributes.hd`` slots.

    With ``lane_width_m``, writes **centerline-offset** left/right polylines (HD-lite),
    not survey-grade boundaries. LiDAR/camera fusion can replace these later.
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
            merged = {**base, **prev_hd}
        else:
            merged = base
        attrs["hd"] = merged
        n.attributes = attrs

    return graph
