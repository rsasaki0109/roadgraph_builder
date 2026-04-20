"""3D3: RANSAC ground-plane fitting tests.

Verifies:
  - Flat point cloud → normal ≈ (0, 0, 1).
  - Tilted 10% slope plane → normal within ±2° of expected.
  - Normal always points upward (z ≥ 0) regardless of point ordering.
  - Outlier-heavy input: RANSAC still recovers the dominant plane.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from roadgraph_builder.hd.lidar_fusion import fit_ground_plane_ransac


def _flat_cloud(n: int = 500, noise: float = 0.02, seed: int = 42) -> np.ndarray:
    """Flat ground plane at z=0 with Gaussian noise."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(-50.0, 50.0, n)
    y = rng.uniform(-50.0, 50.0, n)
    z = rng.normal(0.0, noise, n)
    return np.stack([x, y, z], axis=1)


def _tilted_cloud(
    slope_x: float = 0.1,
    slope_y: float = 0.0,
    n: int = 500,
    noise: float = 0.02,
    seed: int = 0,
) -> np.ndarray:
    """Plane tilted by slope_x in x-direction (z = slope_x * x + slope_y * y)."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(-50.0, 50.0, n)
    y = rng.uniform(-50.0, 50.0, n)
    z = slope_x * x + slope_y * y + rng.normal(0.0, noise, n)
    return np.stack([x, y, z], axis=1)


def _angle_between_normals(n1: np.ndarray, n2: np.ndarray) -> float:
    """Angle in degrees between two unit normals."""
    cos_theta = float(np.clip(np.dot(n1 / np.linalg.norm(n1), n2 / np.linalg.norm(n2)), -1.0, 1.0))
    return math.degrees(math.acos(cos_theta))


def test_flat_cloud_normal_is_upward():
    """Flat ground cloud: RANSAC should recover (0, 0, 1) ± 1°."""
    cloud = _flat_cloud(n=500)
    normal, d = fit_ground_plane_ransac(cloud, max_iter=200, seed=0)
    expected = np.array([0.0, 0.0, 1.0])
    angle = _angle_between_normals(normal, expected)
    assert angle < 1.0, f"Normal angle from (0,0,1) = {angle:.2f}° > 1°"
    assert normal[2] >= 0, "Normal z component must be non-negative"


def test_flat_cloud_d_near_zero():
    """For a cloud centred at z=0, the offset d should be near 0."""
    cloud = _flat_cloud(n=300)
    normal, d = fit_ground_plane_ransac(cloud, max_iter=200, seed=0)
    assert abs(d) < 0.5, f"|d| = {abs(d):.3f} expected < 0.5"


def test_tilted_10pct_slope_normal():
    """10% x-slope plane: RANSAC normal should be within ±2° of expected."""
    slope = 0.1
    cloud = _tilted_cloud(slope_x=slope, n=500, noise=0.02, seed=1)
    normal, d = fit_ground_plane_ransac(cloud, max_iter=200, seed=0)
    # Expected normal: cross product of (1,0,slope) and (0,1,0) → (-slope, 0, 1) normalised.
    expected_raw = np.array([-slope, 0.0, 1.0])
    expected = expected_raw / np.linalg.norm(expected_raw)
    # Flip if needed (normal must point up)
    if expected[2] < 0:
        expected = -expected
    angle = _angle_between_normals(normal, expected)
    assert angle < 2.0, f"Normal angle from expected = {angle:.2f}° (> 2° threshold)"
    assert normal[2] >= 0, "Normal z component must be non-negative"


def test_ransac_rejects_outliers():
    """Dominant flat plane + 40% outlier points at z=5: RANSAC still finds the flat plane."""
    rng = np.random.default_rng(7)
    n_inliers = 300
    n_outliers = 200
    # Inliers: flat ground
    xi = rng.uniform(-20.0, 20.0, n_inliers)
    yi = rng.uniform(-20.0, 20.0, n_inliers)
    zi = rng.normal(0.0, 0.05, n_inliers)
    # Outliers: vegetation at z≈5
    xo = rng.uniform(-20.0, 20.0, n_outliers)
    yo = rng.uniform(-20.0, 20.0, n_outliers)
    zo = rng.uniform(3.0, 7.0, n_outliers)
    cloud = np.stack(
        [np.concatenate([xi, xo]), np.concatenate([yi, yo]), np.concatenate([zi, zo])],
        axis=1,
    )
    rng2 = np.random.default_rng(0)
    cloud = cloud[rng2.permutation(len(cloud))]  # shuffle

    normal, d = fit_ground_plane_ransac(cloud, max_iter=300, distance_tolerance_m=0.2, seed=42)
    expected = np.array([0.0, 0.0, 1.0])
    angle = _angle_between_normals(normal, expected)
    assert angle < 5.0, f"Normal angle = {angle:.2f}° with 40% outliers (threshold 5°)"


def test_ransac_raises_on_bad_shape():
    """Non-(N,3) input must raise ValueError."""
    with pytest.raises(ValueError, match="N, 3"):
        fit_ground_plane_ransac(np.ones((10, 2)))


def test_ransac_raises_on_too_few_points():
    """Fewer than 3 points must raise ValueError."""
    with pytest.raises(ValueError, match="at least 3"):
        fit_ground_plane_ransac(np.ones((2, 3)))
