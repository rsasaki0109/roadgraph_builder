"""Regression tests for Brown-Conrady lens distortion support.

The reference implementation is ``cv2.undistortPoints``. These tests skip if
OpenCV isn't installed; the calibration module's undistortion runs as pure
numpy, so the shipped `roadgraph_builder` install has no cv2 dependency.
"""

from __future__ import annotations

import numpy as np
import pytest

from roadgraph_builder.io.camera.calibration import (
    CameraCalibration,
    CameraIntrinsic,
    RigidTransform,
)
from roadgraph_builder.io.camera.projection import pixel_to_ground


def test_no_distortion_passes_through():
    intr = CameraIntrinsic(fx=500, fy=500, cx=500, cy=500)
    x, y = intr.undistort_pixel_to_normalized(750.0, 600.0)
    # Raw K^-1: (750-500)/500 = 0.5, (600-500)/500 = 0.2
    assert x == pytest.approx(0.5, abs=1e-12)
    assert y == pytest.approx(0.2, abs=1e-12)


def test_zero_tuple_distortion_passes_through():
    intr = CameraIntrinsic(
        fx=500, fy=500, cx=500, cy=500, distortion=(0.0, 0.0, 0.0, 0.0, 0.0)
    )
    assert intr.undistort_pixel_to_normalized(750.0, 600.0) == pytest.approx((0.5, 0.2), abs=1e-12)


def test_undistortion_matches_cv2():
    cv2 = pytest.importorskip("cv2")
    # Moderate wide-angle distortion (inspired by automotive 120-deg FOV cameras).
    dist = (-0.28, 0.11, 0.0008, -0.0005, -0.02)
    intr = CameraIntrinsic(
        fx=800, fy=800, cx=640, cy=400,
        image_width=1280, image_height=800,
        distortion=dist,
    )
    pixels = np.array(
        [
            [640.0, 400.0],   # principal point
            [100.0, 100.0],   # corner
            [1180.0, 700.0],
            [900.0, 500.0],
            [200.0, 700.0],
        ],
        dtype=np.float64,
    )
    K = intr.matrix
    D = intr.distortion_array
    # OpenCV's default undistortPoints uses a hard-coded 5-iter termination.
    # Use its iterative variant with a tight tolerance so both implementations
    # compare at their converged fixed points rather than at different
    # truncation horizons.
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-12)
    cv_result = cv2.undistortPointsIter(
        pixels.reshape(-1, 1, 2), K, D, None, None, criteria
    ).reshape(-1, 2)
    for (u, v), (x_ref, y_ref) in zip(pixels, cv_result):
        x, y = intr.undistort_pixel_to_normalized(float(u), float(v))
        # OpenCV uses float32 internally in some build configs; ours is
        # float64, so ~1e-6 is a tight-enough cross-check at corner pixels
        # with strong distortion. Matches out-of-band results we observed.
        assert x == pytest.approx(x_ref, abs=1e-6)
        assert y == pytest.approx(y_ref, abs=1e-6)


def test_pixel_to_ground_applies_distortion():
    """A distorted pixel should project differently than the pinhole-only case."""
    dist = (-0.25, 0.08, 0.0, 0.0, 0.0)
    intr = CameraIntrinsic(fx=500, fy=500, cx=500, cy=500, distortion=dist)
    calib = CameraCalibration(
        intrinsic=intr,
        camera_to_vehicle=RigidTransform.from_rpy_xyz((0.0, 0.0, 0.0), (0.0, 0.0, 1.5)),
    )
    pose = RigidTransform.from_rpy_xyz((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    # Pixel 400 rows below principal point (a corner-ish sample).
    hit_with = pixel_to_ground(900.0, 900.0, calib, pose)

    intr_plain = CameraIntrinsic(fx=500, fy=500, cx=500, cy=500)
    calib_plain = CameraCalibration(
        intrinsic=intr_plain,
        camera_to_vehicle=RigidTransform.from_rpy_xyz((0.0, 0.0, 0.0), (0.0, 0.0, 1.5)),
    )
    hit_without = pixel_to_ground(900.0, 900.0, calib_plain, pose)
    assert hit_with is not None
    assert hit_without is not None
    # Distortion must shift the ground-plane hit noticeably (barrel distortion
    # at a corner pixel stretches the ray outward) — at least a centimeter.
    dx = abs(hit_with[0] - hit_without[0])
    dy = abs(hit_with[1] - hit_without[1])
    assert max(dx, dy) > 0.01


def test_intrinsic_round_trips_distortion_via_dict():
    dist = (-0.3, 0.1, 0.001, -0.0007, -0.05)
    intr = CameraIntrinsic(
        fx=800, fy=800, cx=640, cy=400, image_width=1280, image_height=800, distortion=dist
    )
    d = intr.to_dict()
    assert d["distortion"]["k1"] == -0.3
    again = CameraIntrinsic.from_dict(d)
    assert again.distortion == dist
    assert again.image_width == 1280
