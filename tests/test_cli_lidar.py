from __future__ import annotations

import argparse
import io
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from roadgraph_builder.cli.lidar import (
    lane_marking_candidates_to_document,
    run_detect_lane_markings,
    run_fuse_lidar,
    run_inspect_lidar,
)
from roadgraph_builder.core.graph.graph import Graph


@dataclass
class _Header:
    summary: dict[str, object]

    def to_summary(self) -> dict[str, object]:
        return self.summary


@dataclass
class _LaneMarkingCandidate:
    edge_id: str
    side: str
    polyline_m: list[tuple[float, float]]
    intensity_median: float
    point_count: int


def _fuse_args(points_path: Path, output_json: Path, **overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "input_json": "graph.json",
        "points_path": str(points_path),
        "output_json": str(output_json),
        "max_dist_m": 5.0,
        "bins": 32,
        "ground_plane": False,
        "height_band_lo": 0.0,
        "height_band_hi": 0.3,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _detect_args(points_path: Path, output_json: Path) -> argparse.Namespace:
    return argparse.Namespace(
        graph_json="graph.json",
        points_las=str(points_path),
        output=str(output_json),
        max_lateral_m=2.5,
        intensity_percentile=85.0,
        bin_m=1.0,
        min_points_per_bin=3,
    )


def test_lane_marking_candidates_to_document_serializes_candidates():
    doc = lane_marking_candidates_to_document(
        [_LaneMarkingCandidate("e1", "left", [(0.0, 0.0), (1.0, 1.0)], 123.0, 4)]
    )

    assert doc == {
        "candidates": [
            {
                "edge_id": "e1",
                "side": "left",
                "polyline_m": [[0.0, 0.0], [1.0, 1.0]],
                "intensity_median": 123.0,
                "point_count": 4,
            }
        ]
    }


def test_run_inspect_lidar_injects_header_reader(tmp_path: Path):
    las = tmp_path / "cloud.las"
    las.write_bytes(b"header")
    stdout = io.StringIO()

    rc = run_inspect_lidar(
        argparse.Namespace(input_las=str(las)),
        read_header_func=lambda path: _Header({"point_count": 7}),
        stdout=stdout,
    )

    assert rc == 0
    assert json.loads(stdout.getvalue()) == {"point_count": 7}


def test_run_inspect_lidar_reports_missing_file(tmp_path: Path):
    stderr = io.StringIO()

    rc = run_inspect_lidar(argparse.Namespace(input_las=str(tmp_path / "missing.las")), stderr=stderr)

    assert rc == 1
    assert "File not found" in stderr.getvalue()


def test_run_fuse_lidar_injects_loader_fuser_and_exporter(tmp_path: Path):
    points = tmp_path / "points.csv"
    points.write_text("x,y\n0,0\n", encoding="utf-8")
    output = tmp_path / "graph.json"
    calls: list[object] = []
    graph = Graph()

    rc = run_fuse_lidar(
        _fuse_args(points, output),
        load_graph=lambda path: graph,
        load_points_func=lambda path, use_ground_plane: np.zeros((1, 2)),
        fuse_2d_func=lambda g, pts, **kwargs: calls.append(("fuse2d", g, pts.shape, kwargs)),
        export_graph_json_func=lambda g, path: calls.append(("export", g, path)),
    )

    assert rc == 0
    assert calls[0][0] == "fuse2d"
    assert calls[0][1] is graph
    assert calls[0][2] == (1, 2)
    assert calls[1] == ("export", graph, str(output))


def test_run_fuse_lidar_validates_ground_plane_xyz_shape(tmp_path: Path):
    points = tmp_path / "points.csv"
    points.write_text("x,y\n0,0\n", encoding="utf-8")
    stderr = io.StringIO()

    rc = run_fuse_lidar(
        _fuse_args(points, tmp_path / "graph.json", ground_plane=True),
        load_graph=lambda path: Graph(),
        load_points_func=lambda path, use_ground_plane: np.zeros((1, 2)),
        fuse_3d_func=lambda *args, **kwargs: None,
        export_graph_json_func=lambda g, path: None,
        stderr=stderr,
    )

    assert rc == 1
    assert "--ground-plane requires x,y,z columns" in stderr.getvalue()


def test_run_detect_lane_markings_validates_graph_root():
    stderr = io.StringIO()

    rc = run_detect_lane_markings(
        _detect_args(Path("points.las"), Path("lane_markings.json")),
        load_json=lambda path: [],
        stderr=stderr,
    )

    assert rc == 1
    assert "graph JSON root must be an object" in stderr.getvalue()


def test_run_detect_lane_markings_injects_loader_and_detector(tmp_path: Path):
    points = tmp_path / "points.las"
    points.write_bytes(b"fake")
    output = tmp_path / "lane_markings.json"

    rc = run_detect_lane_markings(
        _detect_args(points, output),
        load_json=lambda path: {"edges": []},
        load_points_func=lambda path: np.zeros((1, 4)),
        detect_func=lambda graph, pts, **kwargs: [
            _LaneMarkingCandidate("e1", "left", [(0.0, 0.0)], 100.0, 1)
        ],
    )

    assert rc == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "candidates": [
            {
                "edge_id": "e1",
                "side": "left",
                "polyline_m": [[0.0, 0.0]],
                "intensity_median": 100.0,
                "point_count": 1,
            }
        ]
    }
