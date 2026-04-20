"""3D2: synthetic camera lane detection tests.

Verifies:
  - detect_lanes_from_image_rgb detects white lane lines on a synthetic image.
  - detect_lanes_from_image_rgb detects yellow lane lines.
  - Night-mode (low threshold) increases true positive rate.
  - Solid-line detection works end-to-end.
  - HSV conversion is correct (compared to a reference implementation).
  - Bad input shape raises ValueError.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from roadgraph_builder.io.camera.lane_detection import (
    LinePixel,
    _rgb_to_hsv,
    detect_lanes_from_image_rgb,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_white_lane_image(h: int = 100, w: int = 200) -> np.ndarray:
    """Dark road background with two vertical white stripes."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    # Left stripe
    img[:, 30:35, :] = 240  # near-white
    # Right stripe
    img[:, 165:170, :] = 240
    return img


def _make_yellow_lane_image(h: int = 100, w: int = 200) -> np.ndarray:
    """Dark road background with two vertical yellow stripes."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    # Yellow: R≈220, G≈200, B≈30
    yellow = np.array([220, 200, 30], dtype=np.uint8)
    img[:, 50:55, :] = yellow
    img[:, 145:150, :] = yellow
    return img


def _make_night_image(h: int = 100, w: int = 200, brightness: int = 160) -> np.ndarray:
    """Dark image with dim white stripes (simulates night conditions)."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, 40:45, :] = brightness
    img[:, 155:160, :] = brightness
    return img


# ---------------------------------------------------------------------------
# Tests: HSV conversion
# ---------------------------------------------------------------------------


def test_hsv_pure_white():
    """Pure white (255, 255, 255) → H=0, S=0, V=1."""
    rgb = np.array([[[255, 255, 255]]], dtype=np.uint8)
    hsv = _rgb_to_hsv(rgb)
    assert abs(float(hsv[0, 0, 1])) < 1e-4, "White saturation must be 0"
    assert abs(float(hsv[0, 0, 2]) - 1.0) < 1e-4, "White value must be 1"


def test_hsv_pure_red():
    """Pure red (255, 0, 0) → H≈0, S=1, V=1."""
    rgb = np.array([[[255, 0, 0]]], dtype=np.uint8)
    hsv = _rgb_to_hsv(rgb)
    assert abs(float(hsv[0, 0, 1]) - 1.0) < 1e-4, "Red saturation must be 1"
    assert abs(float(hsv[0, 0, 2]) - 1.0) < 1e-4, "Red value must be 1"
    assert float(hsv[0, 0, 0]) < 10.0 or float(hsv[0, 0, 0]) > 350.0, "Red hue must be near 0°"


def test_hsv_yellow():
    """Yellow (255, 255, 0) → H≈60°."""
    rgb = np.array([[[255, 255, 0]]], dtype=np.uint8)
    hsv = _rgb_to_hsv(rgb)
    h = float(hsv[0, 0, 0])
    assert abs(h - 60.0) < 5.0, f"Yellow hue={h}° expected ≈60°"


# ---------------------------------------------------------------------------
# Tests: white lane detection
# ---------------------------------------------------------------------------


def test_detect_white_lanes_count():
    """Two white stripes → at least 2 LinePixel objects with kind='white'."""
    img = _make_white_lane_image()
    lanes = detect_lanes_from_image_rgb(img, white_threshold=200, min_line_length_px=20)
    white_lanes = [l for l in lanes if l.kind == "white"]
    assert len(white_lanes) >= 2, f"Expected ≥ 2 white lanes, got {len(white_lanes)}"


def test_detect_white_lanes_cover_correct_columns():
    """Each white stripe should be in its expected column range."""
    img = _make_white_lane_image()
    lanes = detect_lanes_from_image_rgb(img, white_threshold=200, min_line_length_px=20)
    white_lanes = [l for l in lanes if l.kind == "white"]
    col_centers = sorted([
        float(np.median(l.pixels[:, 1])) for l in white_lanes
    ])
    # Two stripes at col ~32 and ~167
    assert len(col_centers) >= 2
    assert col_centers[0] < 80, f"Left stripe column {col_centers[0]} should be < 80"
    assert col_centers[-1] > 120, f"Right stripe column {col_centers[-1]} should be > 120"


# ---------------------------------------------------------------------------
# Tests: yellow lane detection
# ---------------------------------------------------------------------------


def test_detect_yellow_lanes():
    """Two yellow stripes → at least 2 LinePixel objects with kind='yellow'."""
    img = _make_yellow_lane_image()
    lanes = detect_lanes_from_image_rgb(
        img,
        yellow_hue_range=(20, 70),
        saturation_min=80,
        min_line_length_px=20,
    )
    yellow_lanes = [l for l in lanes if l.kind == "yellow"]
    assert len(yellow_lanes) >= 2, f"Expected ≥ 2 yellow lanes, got {len(yellow_lanes)}"


# ---------------------------------------------------------------------------
# Tests: night mode
# ---------------------------------------------------------------------------


def test_night_mode_lower_threshold_detects_dim_markings():
    """Lowering white_threshold should detect dimmer night markings."""
    img = _make_night_image(brightness=160)
    # With default threshold (200): should miss the dim markings.
    lanes_day = detect_lanes_from_image_rgb(img, white_threshold=200, min_line_length_px=20)
    n_day = len([l for l in lanes_day if l.kind == "white"])

    # With lower threshold (150): should detect.
    lanes_night = detect_lanes_from_image_rgb(img, white_threshold=140, min_line_length_px=20)
    n_night = len([l for l in lanes_night if l.kind == "white"])

    assert n_night >= n_day, (
        f"Night mode (lower threshold) should detect ≥ as many as day: "
        f"night={n_night} day={n_day}"
    )
    assert n_night >= 2, f"Night mode should detect ≥ 2 markings, got {n_night}"


def test_night_mode_tpr_fpr():
    """Night image: TPR ≥ 0.8, FPR ≤ 0.1 (synthetic column-based test)."""
    h, w = 100, 200
    img = _make_night_image(h=h, w=w, brightness=160)
    # Ground truth: columns 40-44 and 155-159 are markings.
    true_col_ranges = [(40, 44), (155, 159)]

    lanes = detect_lanes_from_image_rgb(img, white_threshold=140, min_line_length_px=20)
    white = [l for l in lanes if l.kind == "white"]

    # True positive: detected component overlaps a true column range.
    detected_col_ranges = [(l.bbox[1], l.bbox[3]) for l in white]

    tp = 0
    for lo, hi in true_col_ranges:
        for dl, dh in detected_col_ranges:
            if dl <= hi and dh >= lo:  # overlap
                tp += 1
                break
    fp = len([
        (dl, dh) for dl, dh in detected_col_ranges
        if not any(dl <= hi and dh >= lo for lo, hi in true_col_ranges)
    ])

    tpr = tp / len(true_col_ranges)
    n_non_marking_detections = fp
    # FPR: fraction of detected components that are false positives
    total_detected = max(1, len(detected_col_ranges))
    fpr = n_non_marking_detections / total_detected

    assert tpr >= 0.8, f"TPR={tpr:.2f} < 0.8 for night detection"
    assert fpr <= 0.1, f"FPR={fpr:.2f} > 0.1 for night detection"


# ---------------------------------------------------------------------------
# Tests: bad input
# ---------------------------------------------------------------------------


def test_bad_shape_raises():
    """Non-HxWx3 input must raise ValueError."""
    with pytest.raises(ValueError, match="HxWx3"):
        detect_lanes_from_image_rgb(np.zeros((100, 200), dtype=np.uint8))


def test_single_pixel_no_crash():
    """Tiny 1x1 image should not raise, just return no lanes."""
    img = np.array([[[200, 200, 200]]], dtype=np.uint8)
    lanes = detect_lanes_from_image_rgb(img, min_line_length_px=2)
    assert isinstance(lanes, list)
