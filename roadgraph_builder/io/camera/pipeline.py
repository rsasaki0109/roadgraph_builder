"""Image-space → graph-edge-keyed camera detections.

Orchestrates: image-detections JSON (per-image pose + pixel annotations) →
world-ground projection via :mod:`roadgraph_builder.io.camera.projection` →
nearest-edge snap via :func:`snap_trajectory_to_graph` → a dict shaped like
``camera_detections.schema.json`` so ``apply-camera`` / ``export-bundle`` can
consume it directly.

Detections whose ray points above the horizon, or whose ground projection is
farther than ``max_edge_distance_m`` from any edge, are dropped from the
output and counted separately so callers can surface miss rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, cast

import numpy as np

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.io.camera.calibration import CameraCalibration
from roadgraph_builder.io.camera.projection import (
    GroundProjection,
    project_image_detections,
)
from roadgraph_builder.routing.map_match import snap_trajectory_to_graph


@dataclass
class CameraProjectionResult:
    """Output of :func:`project_image_detections_to_graph_edges`."""

    observations: list[dict[str, Any]] = field(default_factory=list)
    projected_count: int = 0
    dropped_above_horizon: int = 0
    dropped_no_edge: int = 0


def project_image_detections_to_graph_edges(
    image_detections: Iterable[dict[str, Any]],
    calibration: CameraCalibration,
    graph: Graph,
    *,
    ground_z_m: float = 0.0,
    max_edge_distance_m: float = 5.0,
) -> CameraProjectionResult:
    """Full image → graph-edge pipeline. See module docstring.

    ``graph`` must be in the same world meter frame as the vehicle poses
    embedded in ``image_detections``. Edges are matched by nearest-edge
    projection; detections farther than ``max_edge_distance_m`` from every
    edge are dropped (``dropped_no_edge`` counts them).
    """
    items = list(image_detections)
    # Projection drops rays above the horizon already; count those by comparing
    # the raw detection count to the projection count.
    total_pixel_dets = 0
    for it in items:
        dets = it.get("detections") or []
        if isinstance(dets, list):
            total_pixel_dets += sum(
                1
                for d in dets
                if isinstance(d, dict)
                and isinstance(d.get("pixel"), dict)
                and isinstance(d["pixel"].get("u"), (int, float))
                and isinstance(d["pixel"].get("v"), (int, float))
                and isinstance(d.get("kind"), str)
                and d["kind"]
            )

    projections: list[GroundProjection] = project_image_detections(
        items, calibration, ground_z_m=ground_z_m
    )

    if not projections:
        return CameraProjectionResult(
            observations=[],
            projected_count=0,
            dropped_above_horizon=total_pixel_dets,
            dropped_no_edge=0,
        )

    xy = np.array([p.world_xy_m for p in projections], dtype=np.float64)
    snapped = snap_trajectory_to_graph(graph, xy, max_distance_m=max_edge_distance_m)

    observations: list[dict[str, Any]] = []
    dropped_no_edge = 0
    for p, s in zip(projections, snapped):
        if s is None:
            dropped_no_edge += 1
            continue
        obs: dict[str, Any] = {
            "edge_id": s.edge_id,
            "kind": p.kind,
            "projection": {
                "x_m": p.world_xy_m[0],
                "y_m": p.world_xy_m[1],
                "distance_to_edge_m": s.distance_m,
            },
            "pixel": {"u": p.pixel[0], "v": p.pixel[1]},
        }
        if p.image_id:
            obs["image_id"] = p.image_id
        if p.confidence is not None:
            obs["confidence"] = p.confidence
        if p.extras:
            # ``value`` / ``value_kmh`` / custom fields flow through unchanged.
            for k, v in p.extras.items():
                if k not in obs:
                    obs[k] = v
        observations.append(obs)

    return CameraProjectionResult(
        observations=observations,
        projected_count=len(projections),
        dropped_above_horizon=total_pixel_dets - len(projections),
        dropped_no_edge=dropped_no_edge,
    )


__all__ = [
    "CameraProjectionResult",
    "project_image_detections_to_graph_edges",
]
