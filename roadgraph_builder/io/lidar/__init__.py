"""LiDAR inputs (point clouds, boundaries) — separate from trajectory geometry.

``load_points_xy_csv`` loads meter-frame XY samples. ``fuse_lane_boundaries_from_points``
fits per-edge boundaries (proximity + binned median). ``attach_lidar_points_metadata``
only records point counts without changing geometry.

For centerline-offset lane ribbons without point clouds, see
``roadgraph_builder.hd.boundaries`` (used by ``enrich --lane-width-m``).
"""

from roadgraph_builder.io.lidar.fusion import attach_lidar_points_metadata, fuse_lane_boundaries_from_points
from roadgraph_builder.io.lidar.las import LASHeader, read_las_header
from roadgraph_builder.io.lidar.loader import load_lidar_placeholder, load_points_xy_csv

__all__ = [
    "LASHeader",
    "attach_lidar_points_metadata",
    "fuse_lane_boundaries_from_points",
    "load_lidar_placeholder",
    "load_points_xy_csv",
    "read_las_header",
]
