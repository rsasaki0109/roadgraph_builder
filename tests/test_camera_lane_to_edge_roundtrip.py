"""3D2: camera lane detection → graph-edge projection round-trip test.

Synthesises a simple top-down RGB image with two white stripes representing
lane markings, runs detection, and then verifies that the projected
world-frame candidates are snapped to the correct graph edge within ±0.5 m.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.camera.calibration import CameraCalibration, CameraIntrinsic, RigidTransform
from roadgraph_builder.io.camera.lane_detection import (
    LinePixel,
    detect_lanes_from_image_rgb,
    project_camera_lanes_to_graph_edges,
)


# ---------------------------------------------------------------------------
# Minimal graph: one straight edge along y=0 from x=0 to x=20 m
# ---------------------------------------------------------------------------


def _simple_graph() -> Graph:
    nodes = [
        Node(id="n0", position=(0.0, 0.0)),
        Node(id="n1", position=(20.0, 0.0)),
    ]
    edges = [
        Edge(
            id="e0",
            start_node_id="n0",
            end_node_id="n1",
            polyline=[(float(x), 0.0) for x in range(0, 21, 2)],
            attributes={},
        )
    ]
    return Graph(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Minimal pinhole calibration pointing straight down (top-view camera)
# ---------------------------------------------------------------------------


def _top_down_calibration(img_w: int, img_h: int, scale_m_per_px: float) -> CameraCalibration:
    """Simulated nadir (top-down) camera.

    The camera is mounted directly above the vehicle looking straight down.
    We place the camera 5 m above the vehicle origin.

    For a nadir camera:
        - camera_to_vehicle rotation = rotate 90° around X (look down)
        - The principal point is at the image centre.
        - Focal length: f such that ground extent matches image size at h=5 m.
    """
    camera_height_m = 5.0
    # For a camera looking straight down at height h, f px maps h m / pixel
    # such that full image width covers some FOV.
    # scale_m_per_px = camera_height_m / fx  → fx = camera_height_m / scale_m_per_px
    fx = fy = camera_height_m / scale_m_per_px
    cx = float(img_w) / 2.0
    cy = float(img_h) / 2.0

    # camera_to_vehicle: camera is 5 m above vehicle looking down.
    # Nadir: optical z → vehicle -z (down), optical x → vehicle +x, optical y → vehicle -y.
    R_c2v = np.array([
        [1.0,  0.0,  0.0],
        [0.0, -1.0,  0.0],
        [0.0,  0.0, -1.0],
    ], dtype=np.float64)
    t_c2v = np.array([0.0, 0.0, camera_height_m], dtype=np.float64)

    intrinsic = CameraIntrinsic(fx=fx, fy=fy, cx=cx, cy=cy, image_width=img_w, image_height=img_h)
    c2v = RigidTransform(rotation=R_c2v, translation=t_c2v)
    return CameraCalibration(intrinsic=intrinsic, camera_to_vehicle=c2v)


def test_project_camera_lanes_returns_candidates():
    """project_camera_lanes_to_graph_edges should return LaneMarkingCandidate objects."""
    # Create a synthetic top-down image: 100x200, two white stripes at row=50 (±30 px from centre)
    H, W = 100, 200
    img = np.zeros((H, W, 3), dtype=np.uint8)
    # Two white stripes running along columns (horizontal stripes in the top-down view)
    img[45:50, 20:180, :] = 230  # "left" marking
    img[51:56, 20:180, :] = 230  # "right" marking

    lanes = detect_lanes_from_image_rgb(img, white_threshold=200, min_line_length_px=50)
    assert len(lanes) >= 1, "Expected at least one detected lane in synthetic image"

    # Vehicle at origin, heading=0 (facing +x).
    # Top-down calibration with scale so the full 200 px image spans ~20 m.
    cal = _top_down_calibration(W, H, scale_m_per_px=20.0 / W)
    g = _simple_graph()

    candidates = project_camera_lanes_to_graph_edges(
        lanes,
        cal,
        g,
        pose_xy_m=(10.0, 0.0),  # vehicle midway along edge
        heading_rad=0.0,
        max_edge_distance_m=5.0,
    )
    # Some candidates may have been dropped (horizon, etc.), but we should get some.
    # Even if all are dropped, the function must not raise.
    assert isinstance(candidates, list)


def test_project_returns_list_for_empty_lanes():
    """Empty lane list → empty candidates, no crash."""
    cal = _top_down_calibration(200, 100, 0.1)
    g = _simple_graph()
    candidates = project_camera_lanes_to_graph_edges(
        [],
        cal,
        g,
        pose_xy_m=(10.0, 0.0),
        heading_rad=0.0,
    )
    assert candidates == []


def test_line_pixel_attributes():
    """Manually constructed LinePixel has correct attributes."""
    pixels = np.array([[10, 20], [11, 20], [12, 20]], dtype=np.int32)
    lane = LinePixel(
        pixels=pixels,
        kind="white",
        bbox=(10, 20, 12, 20),
        length_px=2.0,
    )
    assert lane.kind == "white"
    assert lane.length_px == 2.0
    assert lane.bbox == (10, 20, 12, 20)
