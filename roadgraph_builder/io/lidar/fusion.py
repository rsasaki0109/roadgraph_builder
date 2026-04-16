"""Attach LiDAR-related metadata to a graph; re-export boundary fusion."""

from __future__ import annotations

import numpy as np

from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.hd.lidar_fusion import fuse_lane_boundaries_from_points


def attach_lidar_points_metadata(graph: Graph, points_xy: np.ndarray) -> Graph:
    """Record that point cloud data is available (same meter frame as the graph).

    Does **not** update ``attributes.hd.lane_boundaries`` — use
    :func:`fuse_lane_boundaries_from_points` to fit boundaries from XY points.
    """
    if points_xy.ndim != 2 or points_xy.shape[1] != 2:
        raise ValueError("points_xy must be an (N, 2) array")
    n = int(points_xy.shape[0])
    lidar_block: dict[str, object] = {
        "point_count": n,
        "status": "loaded_not_fused",
        "notes": "Boundaries unchanged; call fuse_lane_boundaries_from_points() or fuse-lidar CLI.",
    }
    prev = graph.metadata.get("lidar")
    if isinstance(prev, dict):
        lidar_block = {**prev, **lidar_block}
    graph.metadata = {**graph.metadata, "lidar": lidar_block}
    return graph


__all__ = ["attach_lidar_points_metadata", "fuse_lane_boundaries_from_points"]
