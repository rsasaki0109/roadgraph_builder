from __future__ import annotations

import math

import numpy as np

from roadgraph_builder.utils.geometry import (
    centerline_from_points,
    polyline_mean_abs_curvature,
    polyline_rms_residual,
)


def _noisy_arc(n: int = 60, radius: float = 80.0, noise_m: float = 1.2, seed: int = 0):
    rng = np.random.default_rng(seed)
    thetas = np.linspace(0.0, math.pi / 2.0, n)
    clean = np.stack([radius * np.cos(thetas), radius * np.sin(thetas)], axis=1)
    return clean + rng.normal(scale=noise_m, size=clean.shape)


def test_centerline_anchors_raw_endpoints():
    xy = _noisy_arc()
    poly = centerline_from_points(xy, num_bins=32)
    assert poly[0] == (float(xy[0, 0]), float(xy[0, 1]))
    assert poly[-1] == (float(xy[-1, 0]), float(xy[-1, 1]))


def test_centerline_smoothing_reduces_curvature():
    xy = _noisy_arc(noise_m=2.0, seed=42)
    poly = centerline_from_points(xy, num_bins=32)
    # Interior of the polyline should have lower per-vertex turning angle
    # than the raw GPS-like samples (noise dominates the noisy input).
    raw_curv = polyline_mean_abs_curvature([(float(p[0]), float(p[1])) for p in xy])
    smoothed_curv = polyline_mean_abs_curvature(poly)
    assert smoothed_curv < raw_curv * 0.5, (smoothed_curv, raw_curv)


def test_centerline_rms_residual_stays_small():
    xy = _noisy_arc(noise_m=1.0, seed=7)
    poly = centerline_from_points(xy, num_bins=32)
    rms = polyline_rms_residual(poly, xy)
    # RMS fit should be O(noise) — well under 3 * sigma.
    assert rms < 3.0, rms


def test_centerline_degenerate_collapsed_points_returns_single_vertex():
    xy = np.array([[5.0, 5.0], [5.0, 5.0], [5.0, 5.0]])
    poly = centerline_from_points(xy, num_bins=32)
    assert poly == [(5.0, 5.0)]


def test_polyline_mean_abs_curvature_zero_on_straight_line():
    poly = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
    assert polyline_mean_abs_curvature(poly) == 0.0


def test_polyline_mean_abs_curvature_right_angle():
    poly = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    val = polyline_mean_abs_curvature(poly)
    assert math.isclose(val, math.pi / 2.0, abs_tol=1e-9)


def test_polyline_rms_residual_matches_expected_geometry():
    poly = [(0.0, 0.0), (10.0, 0.0)]
    xy = np.array([[5.0, 0.5], [5.0, -0.5]])
    assert math.isclose(polyline_rms_residual(poly, xy), 0.5, abs_tol=1e-9)
