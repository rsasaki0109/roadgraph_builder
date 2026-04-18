"""Tests for pinhole camera projection + image→edge pipeline."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.camera import (
    CameraCalibration,
    CameraIntrinsic,
    RigidTransform,
    load_camera_calibration,
    pixel_to_ground,
    project_image_detections,
    project_image_detections_to_graph_edges,
)
from roadgraph_builder.io.camera.projection import load_image_detections_json
from roadgraph_builder.validation import validate_camera_detections_document


_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _unit_calib(cam_h_m: float = 1.5) -> CameraCalibration:
    intr = CameraIntrinsic(fx=500.0, fy=500.0, cx=500.0, cy=500.0)
    mount = RigidTransform.from_rpy_xyz((0.0, 0.0, 0.0), (0.0, 0.0, cam_h_m))
    return CameraCalibration(intrinsic=intr, camera_to_vehicle=mount)


def test_pixel_to_ground_horizontal_pixel_misses():
    calib = _unit_calib()
    pose = RigidTransform.from_rpy_xyz((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    assert pixel_to_ground(500.0, 500.0, calib, pose) is None


def test_pixel_to_ground_straight_below_principal_point():
    calib = _unit_calib(cam_h_m=1.5)
    pose = RigidTransform.from_rpy_xyz((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    # Pixel 500 rows below principal: K^{-1} * [cx, cy+500, 1] -> optical (0, 1, 1)
    # 45° downward from horizontal; ground hit at x = cam_height (1.5 m).
    x, y = pixel_to_ground(500.0, 1000.0, calib, pose)
    assert x == pytest.approx(1.5, abs=1e-6)
    assert y == pytest.approx(0.0, abs=1e-6)


def test_pixel_to_ground_right_side_goes_to_vehicle_right():
    calib = _unit_calib(cam_h_m=1.5)
    pose = RigidTransform.from_rpy_xyz((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    x, y = pixel_to_ground(1000.0, 1000.0, calib, pose)
    # 45° down + 45° right: hits at x=1.5 forward, y=-1.5 (right of vehicle).
    assert x == pytest.approx(1.5, abs=1e-6)
    assert y == pytest.approx(-1.5, abs=1e-6)


def test_pixel_to_ground_respects_vehicle_pose():
    calib = _unit_calib(cam_h_m=1.5)
    pose = RigidTransform.from_rpy_xyz((0.0, 0.0, math.pi / 2), (10.0, 0.0, 0.0))
    # Vehicle at (10, 0) facing +y (yaw +90°). Pixel below principal -> 1.5m in vehicle-forward (which is +y world). So world xy = (10, 1.5).
    x, y = pixel_to_ground(500.0, 1000.0, calib, pose)
    assert x == pytest.approx(10.0, abs=1e-6)
    assert y == pytest.approx(1.5, abs=1e-6)


def test_pixel_to_ground_above_horizon_returns_none():
    calib = _unit_calib()
    pose = RigidTransform.from_rpy_xyz((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    # Pixel above principal point -> ray points above horizon -> no hit.
    assert pixel_to_ground(500.0, 100.0, calib, pose) is None


def test_load_example_calibration_roundtrips():
    calib = load_camera_calibration(_EXAMPLES / "camera_calibration_sample.json")
    assert calib.intrinsic.fx == 800.0
    assert calib.camera_to_vehicle.translation.tolist() == [0.0, 0.0, 1.5]
    assert np.allclose(calib.camera_to_vehicle.rotation, np.eye(3))


def test_project_image_detections_accepts_example_file():
    items = load_image_detections_json(_EXAMPLES / "image_detections_sample.json")
    calib = load_camera_calibration(_EXAMPLES / "camera_calibration_sample.json")
    projections = project_image_detections(items, calib)
    # All three sample pixels are below the horizon -> should all project.
    assert len(projections) == 3
    for p in projections:
        assert p.kind in {"lane_marking", "stop_line", "speed_limit"}
        assert p.world_xy_m is not None


def test_projection_pipeline_attaches_to_nearest_edge():
    """End-to-end: one image, one detection, a one-edge graph — output must be schema-valid."""
    calib = _unit_calib(cam_h_m=1.5)
    # Graph: a single edge along the vehicle's +x axis from 0 to 5 m.
    graph = Graph(
        nodes=[
            Node(id="n0", position=(0.0, 0.0)),
            Node(id="n1", position=(5.0, 0.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 0.0), (5.0, 0.0)],
            )
        ],
    )
    items = [
        {
            "image_id": "img_A",
            "pose": {"translation_m": [0.0, 0.0, 0.0], "rotation_rpy_rad": [0.0, 0.0, 0.0]},
            "detections": [
                {"kind": "lane_marking", "pixel": {"u": 500.0, "v": 1000.0}, "value": "solid"}
            ],
        }
    ]
    result = project_image_detections_to_graph_edges(items, calib, graph)
    assert result.projected_count == 1
    assert result.dropped_above_horizon == 0
    assert result.dropped_no_edge == 0
    assert len(result.observations) == 1
    obs = result.observations[0]
    assert obs["edge_id"] == "e0"
    assert obs["kind"] == "lane_marking"
    assert obs["value"] == "solid"
    # The ground projection is at (1.5, 0), distance to the edge y=0 is 0.
    assert obs["projection"]["distance_to_edge_m"] == pytest.approx(0.0, abs=1e-6)
    # Schema-valid as a camera_detections document.
    validate_camera_detections_document({"format_version": 1, "observations": result.observations})


def test_projection_drops_detection_without_nearby_edge():
    calib = _unit_calib(cam_h_m=1.5)
    # Edge very far from any likely projection.
    graph = Graph(
        nodes=[
            Node(id="n0", position=(1000.0, 1000.0)),
            Node(id="n1", position=(1005.0, 1000.0)),
        ],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(1000.0, 1000.0), (1005.0, 1000.0)],
            )
        ],
    )
    items = [
        {
            "image_id": "img_A",
            "pose": {"translation_m": [0.0, 0.0, 0.0], "rotation_rpy_rad": [0.0, 0.0, 0.0]},
            "detections": [{"kind": "lane_marking", "pixel": {"u": 500.0, "v": 1000.0}}],
        }
    ]
    result = project_image_detections_to_graph_edges(
        items, calib, graph, max_edge_distance_m=5.0
    )
    assert result.projected_count == 1
    assert result.dropped_no_edge == 1
    assert result.observations == []


def test_projection_drops_rays_above_horizon():
    calib = _unit_calib(cam_h_m=1.5)
    graph = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0)), Node(id="n1", position=(5.0, 0.0))],
        edges=[Edge(id="e0", start_node_id="n0", end_node_id="n1", polyline=[(0.0, 0.0), (5.0, 0.0)])],
    )
    items = [
        {
            "image_id": "img_A",
            "pose": {"translation_m": [0.0, 0.0, 0.0], "rotation_rpy_rad": [0.0, 0.0, 0.0]},
            "detections": [
                # Below principal -> valid.
                {"kind": "lane_marking", "pixel": {"u": 500.0, "v": 1000.0}},
                # Above principal -> should be dropped as above-horizon.
                {"kind": "traffic_sign", "pixel": {"u": 500.0, "v": 100.0}},
            ],
        }
    ]
    result = project_image_detections_to_graph_edges(items, calib, graph)
    assert result.projected_count == 1
    assert result.dropped_above_horizon == 1
    assert len(result.observations) == 1
    assert result.observations[0]["kind"] == "lane_marking"


def test_project_camera_cli_end_to_end(tmp_path):
    """Smoke-test the CLI with the shipped example files + a minimal graph."""
    import subprocess, sys as _sys

    graph = {
        "schema_version": 1,
        "nodes": [
            {"id": "n0", "position": {"x": 0.0, "y": 0.0}, "attributes": {}},
            {"id": "n1", "position": {"x": 10.0, "y": 0.0}, "attributes": {}},
        ],
        "edges": [
            {
                "id": "e0",
                "start_node_id": "n0",
                "end_node_id": "n1",
                "polyline": [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}],
                "attributes": {},
            }
        ],
    }
    graph_path = tmp_path / "g.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    out_path = tmp_path / "cam_det.json"

    r = subprocess.run(
        [
            _sys.executable,
            "-m",
            "roadgraph_builder.cli.main",
            "project-camera",
            str(_EXAMPLES / "camera_calibration_sample.json"),
            str(_EXAMPLES / "image_detections_sample.json"),
            str(graph_path),
            str(out_path),
            "--max-edge-distance-m",
            "20",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    validate_camera_detections_document(doc)
    assert len(doc["observations"]) >= 1
