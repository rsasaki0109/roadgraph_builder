from __future__ import annotations

import argparse
import io
import json
from dataclasses import dataclass
from pathlib import Path

from roadgraph_builder.cli.camera import (
    camera_lanes_to_document,
    find_image_file,
    projection_result_to_document,
    run_apply_camera,
    run_detect_lane_markings_camera,
    run_project_camera,
)
from roadgraph_builder.core.graph.graph import Graph


@dataclass
class _ProjectionResult:
    observations: list[dict]
    projected_count: int = 0
    dropped_above_horizon: int = 0
    dropped_no_edge: int = 0


@dataclass
class _CameraLaneCandidate:
    edge_id: str
    world_xy_m: tuple[float, float]
    kind: str
    side: str
    confidence: float


def test_projection_result_to_document_keeps_schema_shape():
    result = _ProjectionResult(observations=[{"edge_id": "e1"}], projected_count=1)

    assert projection_result_to_document(result) == {
        "format_version": 1,
        "observations": [{"edge_id": "e1"}],
    }


def test_camera_lanes_to_document_serializes_candidates():
    doc = camera_lanes_to_document(
        [_CameraLaneCandidate("e1", (1.0, 2.0), "lane_marking", "left", 0.75)]
    )

    assert doc == {
        "camera_lanes": [
            {
                "edge_id": "e1",
                "world_xy_m": [1.0, 2.0],
                "kind": "lane_marking",
                "side": "left",
                "confidence": 0.75,
            }
        ]
    }


def test_find_image_file_matches_supported_extensions(tmp_path: Path):
    image = tmp_path / "frame_001.JPG"
    image.write_bytes(b"not actually decoded")

    assert find_image_file(tmp_path, "frame_001") == image
    assert find_image_file(tmp_path, "missing") is None


def test_run_apply_camera_injects_io_and_exporter():
    calls: list[object] = []
    graph = Graph()

    rc = run_apply_camera(
        argparse.Namespace(
            input_json="graph.json",
            detections_json="detections.json",
            output_json="out.json",
        ),
        load_graph=lambda path: graph,
        load_detections_func=lambda path: ["obs"],
        apply_detections_func=lambda g, obs: calls.append(("apply", g, obs)),
        export_graph_json_func=lambda g, path: calls.append(("export", g, path)),
    )

    assert rc == 0
    assert calls == [("apply", graph, ["obs"]), ("export", graph, "out.json")]


def test_run_apply_camera_reports_missing_detections_file():
    stderr = io.StringIO()

    rc = run_apply_camera(
        argparse.Namespace(
            input_json="graph.json",
            detections_json="missing.json",
            output_json="out.json",
        ),
        load_graph=lambda path: Graph(),
        load_detections_func=lambda path: (_ for _ in ()).throw(FileNotFoundError(path)),
        apply_detections_func=lambda g, obs: None,
        export_graph_json_func=lambda g, path: None,
        stderr=stderr,
    )

    assert rc == 1
    assert "File not found: missing.json" in stderr.getvalue()


def test_run_project_camera_injects_projection_and_writes_document(tmp_path: Path):
    stderr = io.StringIO()
    out = tmp_path / "camera_detections.json"

    rc = run_project_camera(
        argparse.Namespace(
            calibration_json="calibration.json",
            image_detections_json="images.json",
            graph_json="graph.json",
            output_json=str(out),
            ground_z_m=0.0,
            max_edge_distance_m=5.0,
        ),
        load_graph=lambda path: Graph(),
        load_calibration_func=lambda path: {"calibration": True},
        load_items_func=lambda path: [{"image_id": "img"}],
        project_func=lambda items, calibration, graph, **kwargs: _ProjectionResult(
            observations=[{"edge_id": "e1"}],
            projected_count=1,
            dropped_above_horizon=2,
            dropped_no_edge=3,
        ),
        stderr=stderr,
    )

    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "format_version": 1,
        "observations": [{"edge_id": "e1"}],
    }
    assert "projected 1" in stderr.getvalue()
    assert "dropped_above_horizon 2" in stderr.getvalue()


def test_run_detect_lane_markings_camera_validates_calibration_root():
    stderr = io.StringIO()

    rc = run_detect_lane_markings_camera(
        argparse.Namespace(
            graph_json="graph.json",
            calibration_json="calibration.json",
            images_dir="images",
            poses_json="poses.json",
            output="camera_lanes.json",
            white_threshold=200,
            yellow_hue_lo=20,
            yellow_hue_hi=40,
            saturation_min=100,
            min_line_length_px=30,
            max_edge_distance_m=3.5,
        ),
        load_graph=lambda path: Graph(),
        load_json=lambda path: [],
        stderr=stderr,
    )

    assert rc == 1
    assert "calibration JSON must be an object" in stderr.getvalue()
