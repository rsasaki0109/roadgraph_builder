"""End-to-end accuracy check on the shipped camera-pipeline demo dataset.

``scripts/generate_camera_demo.py`` forward-projects known world-frame features
through a wide-angle camera with Brown-Conrady distortion into pixel
coordinates (rounded to 0.1 px), embedding the ground truth in each
detection's ``_world_ground_truth_m`` field. This test runs the shipped
``examples/demo_image_detections.json`` back through our pipeline and asserts
each observation lands within a sub-decimetre of its ground truth — the only
material error source is pixel rounding, so the bound is tight.

Guards against regressions in ``undistort_pixel_to_normalized``,
``pixel_to_ground``, and the full pipeline glue.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from roadgraph_builder.core.graph.edge import Edge
from roadgraph_builder.core.graph.graph import Graph
from roadgraph_builder.core.graph.node import Node
from roadgraph_builder.io.camera import (
    load_camera_calibration,
    load_image_detections_json,
    project_image_detections_to_graph_edges,
)


_EX = Path(__file__).resolve().parent.parent / "examples"


def test_camera_demo_recovers_ground_truth_to_within_10cm():
    calib_path = _EX / "demo_camera_calibration.json"
    img_path = _EX / "demo_image_detections.json"
    if not calib_path.is_file() or not img_path.is_file():
        pytest.skip(
            "demo_camera_calibration.json / demo_image_detections.json absent — "
            "regenerate with `python scripts/generate_camera_demo.py`"
        )

    calib = load_camera_calibration(calib_path)
    items = load_image_detections_json(img_path)

    # A road along +x spanning the demo scene so the projected detections
    # have an edge to snap to. The pipeline's accuracy doesn't depend on the
    # graph — the edge snap is the last step and the ground-truth comparison
    # happens on the projected xy before snap.
    graph = Graph(
        nodes=[Node(id="n0", position=(0.0, 0.0)), Node(id="n1", position=(30.0, 0.0))],
        edges=[
            Edge(
                id="e0",
                start_node_id="n0",
                end_node_id="n1",
                polyline=[(0.0, 0.0), (30.0, 0.0)],
            )
        ],
    )

    result = project_image_detections_to_graph_edges(
        items, calib, graph, max_edge_distance_m=10.0
    )
    assert result.dropped_above_horizon == 0, (
        "Demo pixels are all below the horizon; any above-horizon drop means "
        "something regressed in the distortion inversion."
    )
    assert result.dropped_no_edge == 0
    assert result.projected_count >= 10

    # Build a lookup from (image_id, pixel tuple, kind) to ground truth.
    gt: dict = {}
    for it in items:
        for d in it["detections"]:
            if "_world_ground_truth_m" in d:
                key = (it["image_id"], d["kind"], d["pixel"]["u"], d["pixel"]["v"])
                gt[key] = d["_world_ground_truth_m"]

    max_err = 0.0
    for obs in result.observations:
        key = (obs.get("image_id"), obs["kind"], obs["pixel"]["u"], obs["pixel"]["v"])
        if key not in gt:
            continue
        gx, gy, _gz = gt[key]
        dx = obs["projection"]["x_m"] - gx
        dy = obs["projection"]["y_m"] - gy
        err = (dx * dx + dy * dy) ** 0.5
        if err > max_err:
            max_err = err

    assert max_err < 0.10, f"demo round-trip worse than 10 cm: max_err={max_err:.3f} m"
