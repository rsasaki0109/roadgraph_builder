"""LiDAR loaders (MVP: XY CSV; LAS/LAZ later)."""

from __future__ import annotations

from pathlib import Path

from roadgraph_builder.io.lidar.points import load_points_xy_csv


def load_lidar_placeholder(path: str | Path) -> None:
    """Reserved for LAS/LAZ / proprietary dumps — not implemented."""
    raise NotImplementedError(
        "LAS/LAZ loading is not implemented yet. Use load_points_xy_csv() for x,y text exports."
    )


__all__ = ["load_lidar_placeholder", "load_points_xy_csv"]
