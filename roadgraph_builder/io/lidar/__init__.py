"""LiDAR inputs (point clouds, boundaries) — separate from trajectory geometry.

TODO: boundary extraction from point clouds; elevation; fusion with trajectory graph.
"""

from roadgraph_builder.io.lidar.loader import load_lidar_placeholder

__all__ = ["load_lidar_placeholder"]
