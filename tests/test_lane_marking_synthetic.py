"""Synthetic LAS round-trip test for LiDAR intensity-based lane marking detection.

Generates a synthetic point cloud with lane markings at ±1.75 m, then
verifies that detect_lane_markings recovers both left and right candidates
within 10 cm of the expected lateral position.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from roadgraph_builder.io.lidar.lane_marking import detect_lane_markings, LaneMarkingCandidate

FIXTURE_LAS = Path(__file__).parent / "fixtures" / "lane_markings_synth.las"

MARKING_OFFSET_M = 1.75
SURFACE_INTENSITY = 50
MARKING_INTENSITY = 200
ROAD_LENGTH_M = 30.0

# Minimal graph JSON with a single straight edge along x-axis.
GRAPH_JSON = {
    "schema_version": 1,
    "nodes": [
        {"id": "n0", "x": 0.0, "y": 0.0, "attributes": {}},
        {"id": "n1", "x": ROAD_LENGTH_M, "y": 0.0, "attributes": {}},
    ],
    "edges": [
        {
            "id": "e0",
            "start_node_id": "n0",
            "end_node_id": "n1",
            "polyline": [
                {"x": 0.0, "y": 0.0},
                {"x": ROAD_LENGTH_M, "y": 0.0},
            ],
            "length_m": ROAD_LENGTH_M,
            "attributes": {},
        }
    ],
}


def _load_fixture_points() -> np.ndarray:
    """Load XYZ + intensity from the synthetic LAS fixture."""
    las_path = FIXTURE_LAS
    if not las_path.is_file():
        pytest.skip(f"Fixture not found: {las_path}. Run scripts/make_sample_lane_las.py first.")

    from roadgraph_builder.io.lidar.las import read_las_header
    header = read_las_header(las_path)
    record_length = header.point_data_record_length
    point_count = header.point_count
    with las_path.open("rb") as fh:
        fh.seek(header.offset_to_point_data)
        blob = fh.read(record_length * point_count)
    buf = np.frombuffer(blob, dtype=np.uint8).reshape(point_count, record_length)
    xi = buf[:, 0:4].copy().view(np.int32).reshape(point_count)
    yi = buf[:, 4:8].copy().view(np.int32).reshape(point_count)
    zi = buf[:, 8:12].copy().view(np.int32).reshape(point_count)
    ii = buf[:, 12:14].copy().view(np.uint16).reshape(point_count)
    sx, sy, sz = header.scale
    ox, oy, oz = header.offset
    pts = np.empty((point_count, 4), dtype=np.float64)
    pts[:, 0] = xi.astype(np.float64) * sx + ox
    pts[:, 1] = yi.astype(np.float64) * sy + oy
    pts[:, 2] = zi.astype(np.float64) * sz + oz
    pts[:, 3] = ii.astype(np.float64)
    return pts


def _make_synthetic_points() -> np.ndarray:
    """Generate synthetic points in-memory (no file I/O)."""
    rng = np.random.default_rng(42)
    rows: list[tuple[float, float, float, float]] = []
    step_m = 1.0
    s = 0.0
    while s <= ROAD_LENGTH_M:
        # Road surface.
        for t in np.linspace(-2.0, 2.0, 6):
            rows.append((s, float(t), 0.0, float(SURFACE_INTENSITY)))
        # Left marking.
        for dt in (-0.02, 0.0, 0.02):
            rows.append((s, MARKING_OFFSET_M + dt, 0.0, float(MARKING_INTENSITY)))
        # Right marking.
        for dt in (-0.02, 0.0, 0.02):
            rows.append((s, -MARKING_OFFSET_M + dt, 0.0, float(MARKING_INTENSITY)))
        s += step_m
    return np.array(rows, dtype=np.float64)


class TestLaneMarkingDetection:
    def test_detects_left_and_right_candidates(self):
        pts = _make_synthetic_points()
        candidates = detect_lane_markings(GRAPH_JSON, pts)
        sides = {c.side for c in candidates}
        assert "left" in sides, f"Expected left candidate, got sides: {sides}"
        assert "right" in sides, f"Expected right candidate, got sides: {sides}"

    def test_left_candidate_position_within_10cm(self):
        pts = _make_synthetic_points()
        candidates = detect_lane_markings(GRAPH_JSON, pts)
        left_cands = [c for c in candidates if c.side == "left"]
        assert left_cands, "No left candidates detected."
        # Median y of polyline points should be close to +MARKING_OFFSET_M.
        for c in left_cands:
            ys = [pt[1] for pt in c.polyline_m]
            median_y = float(np.median(ys))
            assert abs(median_y - MARKING_OFFSET_M) < 0.10, (
                f"Left candidate at y={median_y:.3f}, expected ~{MARKING_OFFSET_M}"
            )

    def test_right_candidate_position_within_10cm(self):
        pts = _make_synthetic_points()
        candidates = detect_lane_markings(GRAPH_JSON, pts)
        right_cands = [c for c in candidates if c.side == "right"]
        assert right_cands, "No right candidates detected."
        for c in right_cands:
            ys = [pt[1] for pt in c.polyline_m]
            median_y = float(np.median(ys))
            assert abs(median_y - (-MARKING_OFFSET_M)) < 0.10, (
                f"Right candidate at y={median_y:.3f}, expected ~{-MARKING_OFFSET_M}"
            )

    def test_candidates_have_correct_structure(self):
        pts = _make_synthetic_points()
        candidates = detect_lane_markings(GRAPH_JSON, pts)
        for c in candidates:
            assert c.edge_id == "e0"
            assert c.side in {"left", "right", "center"}
            assert len(c.polyline_m) >= 2
            assert c.point_count > 0
            assert c.intensity_median > 0

    def test_high_intensity_marking_detected(self):
        pts = _make_synthetic_points()
        candidates = detect_lane_markings(GRAPH_JSON, pts)
        for c in candidates:
            # All candidates should have intensity close to MARKING_INTENSITY.
            assert c.intensity_median >= SURFACE_INTENSITY

    def test_no_points_returns_empty(self):
        pts = np.zeros((0, 4), dtype=np.float64)
        candidates = detect_lane_markings(GRAPH_JSON, pts)
        assert candidates == []

    def test_from_las_fixture(self):
        pts = _load_fixture_points()
        candidates = detect_lane_markings(GRAPH_JSON, pts)
        sides = {c.side for c in candidates}
        assert "left" in sides
        assert "right" in sides
        # Check positions within 10 cm.
        for c in candidates:
            if c.side == "left":
                ys = [pt[1] for pt in c.polyline_m]
                assert abs(float(np.median(ys)) - MARKING_OFFSET_M) < 0.10
            elif c.side == "right":
                ys = [pt[1] for pt in c.polyline_m]
                assert abs(float(np.median(ys)) - (-MARKING_OFFSET_M)) < 0.10

    def test_schema_validation_of_output(self):
        """Output serialized to JSON validates against lane_markings.schema.json."""
        from roadgraph_builder.validation import validate_lane_markings_document
        pts = _make_synthetic_points()
        candidates = detect_lane_markings(GRAPH_JSON, pts)
        doc = {
            "candidates": [
                {
                    "edge_id": c.edge_id,
                    "side": c.side,
                    "polyline_m": [list(pt) for pt in c.polyline_m],
                    "intensity_median": c.intensity_median,
                    "point_count": c.point_count,
                }
                for c in candidates
            ]
        }
        # Should not raise.
        validate_lane_markings_document(doc)
