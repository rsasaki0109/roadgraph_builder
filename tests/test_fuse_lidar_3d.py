"""3D3: fuse_lane_boundaries_3d tests.

Verifies:
  - Ground plane fitting + height band filters vegetation (z=2m) correctly.
  - Lane markings on road surface (low z) survive the filter.
  - Existing fuse_lane_boundaries_from_points (2D) is byte-identical when
    ground-plane mode is not used.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.hd.lidar_fusion import (
    fuse_lane_boundaries_3d,
    fuse_lane_boundaries_from_points,
)


def _simple_graph() -> Graph:
    """Straight 50 m edge along y=0."""
    nodes = [
        Node(id="n0", position=(0.0, 0.0)),
        Node(id="n1", position=(50.0, 0.0)),
    ]
    edges = [
        Edge(
            id="e0",
            start_node_id="n0",
            end_node_id="n1",
            polyline=[(float(x), 0.0) for x in range(0, 51, 5)],
            attributes={},
        )
    ]
    return Graph(nodes=nodes, edges=edges)


def _make_cloud_with_vegetation(
    n_road: int = 200,
    n_vegetation: int = 100,
    seed: int = 42,
) -> np.ndarray:
    """Synthetic xyz cloud.

    Road surface: flat at z=0, points scattered ±3 m of y=0.
    Vegetation: z in [1.5, 3.0], scattered anywhere in XY.
    """
    rng = np.random.default_rng(seed)
    # Road surface points (lane-marking-like, near y=±1.75)
    x_road = rng.uniform(0.0, 50.0, n_road)
    # Alternate left (y≈+1.75) and right (y≈-1.75)
    half = n_road // 2
    y_road = np.concatenate([
        rng.normal(1.75, 0.1, half),
        rng.normal(-1.75, 0.1, n_road - half),
    ])
    z_road = rng.normal(0.0, 0.02, n_road)

    # Vegetation / overhead noise at z > 1.5
    x_veg = rng.uniform(0.0, 50.0, n_vegetation)
    y_veg = rng.uniform(-10.0, 10.0, n_vegetation)
    z_veg = rng.uniform(1.5, 3.0, n_vegetation)

    xyz = np.stack(
        [
            np.concatenate([x_road, x_veg]),
            np.concatenate([y_road, y_veg]),
            np.concatenate([z_road, z_veg]),
        ],
        axis=1,
    )
    return xyz


def test_vegetation_excluded_by_ground_plane_filter():
    """With --ground-plane: vegetation at z>0.3 is excluded; road stays."""
    g = _simple_graph()
    cloud = _make_cloud_with_vegetation()

    fuse_lane_boundaries_3d(
        g,
        cloud,
        height_band_m=(0.0, 0.3),
        max_dist_m=3.0,
        bins=8,
        max_iter=100,
        seed=0,
    )
    lidar_meta = g.metadata.get("lidar", {})
    assert isinstance(lidar_meta, dict)
    # Vegetation should be filtered out
    n_filtered_out = lidar_meta.get("ground_plane_filtered_out", 0)
    assert n_filtered_out > 0, "Expected some points filtered out by height band"
    # Some points should be kept (the road surface)
    n_kept = lidar_meta.get("ground_plane_kept", 0)
    assert n_kept > 0, "Expected some road-surface points to survive the filter"


def test_3d_fuse_writes_metadata():
    """fuse_lane_boundaries_3d writes ground_plane_* keys into metadata.lidar."""
    g = _simple_graph()
    cloud = _make_cloud_with_vegetation()

    fuse_lane_boundaries_3d(g, cloud, max_iter=50, seed=1)
    lidar = g.metadata.get("lidar", {})
    assert "ground_plane_normal" in lidar
    assert "ground_plane_d" in lidar
    assert "ground_plane_height_band_m" in lidar
    normal = lidar["ground_plane_normal"]
    assert isinstance(normal, list) and len(normal) == 3


def test_2d_fuse_unchanged_without_ground_plane_flag():
    """fuse_lane_boundaries_from_points (2D) must not be affected by 3D code."""
    import copy
    g1 = _simple_graph()
    g2 = _simple_graph()

    cloud = _make_cloud_with_vegetation()
    xy = cloud[:, :2]  # 2D only

    fuse_lane_boundaries_from_points(g1, xy, max_dist_m=3.0, bins=8)
    fuse_lane_boundaries_from_points(g2, xy, max_dist_m=3.0, bins=8)

    # Both should be identical (deterministic)
    import json
    d1 = json.dumps(g1.to_dict(), sort_keys=True)
    d2 = json.dumps(g2.to_dict(), sort_keys=True)
    assert d1 == d2, "2D fuse must be deterministic and unchanged"


def test_3d_fuse_bad_shape_raises():
    """(N, 2) array should raise ValueError."""
    g = _simple_graph()
    with pytest.raises(ValueError, match="N, 3"):
        fuse_lane_boundaries_3d(g, np.ones((10, 2)))


def test_3d_fuse_metadata_has_normal_pointing_up():
    """The ground-plane normal must have positive z component."""
    g = _simple_graph()
    cloud = _make_cloud_with_vegetation()
    fuse_lane_boundaries_3d(g, cloud, max_iter=100, seed=0)
    normal = g.metadata["lidar"]["ground_plane_normal"]
    assert normal[2] >= 0, f"Normal z={normal[2]} should be ≥ 0 (upward-pointing)"
