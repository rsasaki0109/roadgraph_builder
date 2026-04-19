"""CLI smoke tests for infer-lane-count (ROADMAP_0.6.md §α)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _rb() -> str:
    exe = Path(sys.executable).parent / "roadgraph_builder"
    if not exe.is_file():
        pytest.skip(f"roadgraph_builder CLI not found next to {sys.executable}")
    return str(exe)


def _run_cli(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_rb(), *args],
        capture_output=True,
        text=True,
        check=check,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


GRAPH_JSON = {
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

LANE_MARKINGS = {
    "candidates": [
        {"edge_id": "e0", "side": "left", "polyline_m": [[0.0, 3.5], [10.0, 3.5]], "intensity_median": 200.0, "point_count": 5},
        {"edge_id": "e0", "side": "center", "polyline_m": [[0.0, 0.0], [10.0, 0.0]], "intensity_median": 200.0, "point_count": 5},
        {"edge_id": "e0", "side": "right", "polyline_m": [[0.0, -3.5], [10.0, -3.5]], "intensity_median": 200.0, "point_count": 5},
    ]
}


def test_infer_lane_count_help():
    result = _run_cli(["infer-lane-count", "--help"])
    assert result.returncode == 0
    assert "lane" in result.stdout.lower()


def test_infer_lane_count_default_no_markings(tmp_path):
    graph_path = tmp_path / "graph.json"
    out_path = tmp_path / "graph_lanes.json"
    graph_path.write_text(json.dumps(GRAPH_JSON), encoding="utf-8")

    result = _run_cli(["infer-lane-count", str(graph_path), str(out_path)])
    assert result.returncode == 0

    out = json.loads(out_path.read_text(encoding="utf-8"))
    edges = {e["id"]: e for e in out["edges"]}
    hd = edges["e0"].get("attributes", {}).get("hd", {})
    assert hd.get("lane_count") == 1
    assert hd.get("lanes") is not None
    assert len(hd["lanes"]) == 1


def test_infer_lane_count_with_markings_2_lanes(tmp_path):
    graph_path = tmp_path / "graph.json"
    lm_path = tmp_path / "lane_markings.json"
    out_path = tmp_path / "graph_lanes.json"
    graph_path.write_text(json.dumps(GRAPH_JSON), encoding="utf-8")
    lm_path.write_text(json.dumps(LANE_MARKINGS), encoding="utf-8")

    result = _run_cli([
        "infer-lane-count",
        str(graph_path),
        str(out_path),
        "--lane-markings-json", str(lm_path),
    ])
    assert result.returncode == 0

    out = json.loads(out_path.read_text(encoding="utf-8"))
    hd = out["edges"][0]["attributes"]["hd"]
    assert hd["lane_count"] == 2
    assert len(hd["lanes"]) == 2


def test_infer_lane_count_stdout_summary(tmp_path):
    graph_path = tmp_path / "graph.json"
    out_path = tmp_path / "graph_lanes.json"
    graph_path.write_text(json.dumps(GRAPH_JSON), encoding="utf-8")

    result = _run_cli(["infer-lane-count", str(graph_path), str(out_path)])
    summary = json.loads(result.stdout)
    assert "edges_processed" in summary
    assert summary["edges_processed"] == 1


def test_infer_lane_count_missing_graph_exit1(tmp_path):
    out_path = tmp_path / "out.json"
    result = _run_cli(["infer-lane-count", str(tmp_path / "no_such.json"), str(out_path)], check=False)
    assert result.returncode == 1


def test_infer_lane_count_output_validates_schema(tmp_path):
    """The output graph must still pass roadgraph schema validation."""
    graph_path = tmp_path / "graph.json"
    lm_path = tmp_path / "lane_markings.json"
    out_path = tmp_path / "graph_lanes.json"
    graph_path.write_text(json.dumps(GRAPH_JSON), encoding="utf-8")
    lm_path.write_text(json.dumps(LANE_MARKINGS), encoding="utf-8")

    _run_cli(["infer-lane-count", str(graph_path), str(out_path), "--lane-markings-json", str(lm_path)])
    result = _run_cli(["validate", str(out_path)])
    assert result.returncode == 0
