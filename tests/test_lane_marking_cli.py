"""CLI smoke tests for detect-lane-markings and validate-lane-markings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_LAS = ROOT / "tests" / "fixtures" / "lane_markings_synth.las"


def _rb() -> str:
    exe = Path(sys.executable).parent / "roadgraph_builder"
    if not exe.is_file():
        pytest.skip(f"roadgraph_builder CLI not found next to {sys.executable}")
    return str(exe)


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [_rb(), *args],
        cwd=str(cwd) if cwd else str(ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return result


def _make_graph_json(tmp_path: Path, length_m: float = 30.0) -> Path:
    graph = {
        "schema_version": 1,
        "nodes": [
            {"id": "n0", "x": 0.0, "y": 0.0, "attributes": {}},
            {"id": "n1", "x": length_m, "y": 0.0, "attributes": {}},
        ],
        "edges": [
            {
                "id": "e0",
                "start_node_id": "n0",
                "end_node_id": "n1",
                "polyline": [{"x": 0.0, "y": 0.0}, {"x": length_m, "y": 0.0}],
                "length_m": length_m,
                "attributes": {},
            }
        ],
    }
    p = tmp_path / "graph.json"
    p.write_text(json.dumps(graph), encoding="utf-8")
    return p


def test_detect_lane_markings_help():
    r = _run("detect-lane-markings", "--help")
    assert r.returncode == 0, r.stderr
    assert "detect-lane-markings" in r.stdout or "lane" in r.stdout.lower()


def test_validate_lane_markings_help():
    r = _run("validate-lane-markings", "--help")
    assert r.returncode == 0, r.stderr


def test_detect_lane_markings_produces_json(tmp_path: Path):
    if not FIXTURE_LAS.is_file():
        pytest.skip("Fixture LAS not found; run scripts/make_sample_lane_las.py")
    graph_path = _make_graph_json(tmp_path)
    out_path = tmp_path / "lane_markings.json"
    r = _run(
        "detect-lane-markings",
        str(graph_path),
        str(FIXTURE_LAS),
        "--output",
        str(out_path),
    )
    assert r.returncode == 0, r.stderr
    assert out_path.is_file()
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert "candidates" in doc
    assert isinstance(doc["candidates"], list)


def test_validate_lane_markings_accepts_valid(tmp_path: Path):
    valid = {
        "candidates": [
            {
                "edge_id": "e0",
                "side": "left",
                "polyline_m": [[0.0, 1.75], [10.0, 1.75]],
                "intensity_median": 200.0,
                "point_count": 10,
            }
        ]
    }
    p = tmp_path / "lane_markings.json"
    p.write_text(json.dumps(valid), encoding="utf-8")
    r = _run("validate-lane-markings", str(p))
    assert r.returncode == 0, r.stderr


def test_validate_lane_markings_rejects_invalid(tmp_path: Path):
    invalid = {"candidates": [{"side": "diagonal"}]}  # missing required fields, bad enum
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(invalid), encoding="utf-8")
    r = _run("validate-lane-markings", str(p))
    assert r.returncode == 1


def test_detect_lane_markings_missing_las(tmp_path: Path):
    graph_path = _make_graph_json(tmp_path)
    r = _run(
        "detect-lane-markings",
        str(graph_path),
        str(tmp_path / "nonexistent.las"),
    )
    assert r.returncode == 1
    assert "not found" in r.stderr.lower() or "File not found" in r.stderr


def test_detect_and_validate_roundtrip(tmp_path: Path):
    """Detect candidates, write JSON, then validate with schema CLI."""
    if not FIXTURE_LAS.is_file():
        pytest.skip("Fixture LAS not found; run scripts/make_sample_lane_las.py")
    graph_path = _make_graph_json(tmp_path)
    out_path = tmp_path / "lane_markings.json"
    r1 = _run(
        "detect-lane-markings",
        str(graph_path),
        str(FIXTURE_LAS),
        "--output",
        str(out_path),
    )
    assert r1.returncode == 0, r1.stderr
    r2 = _run("validate-lane-markings", str(out_path))
    assert r2.returncode == 0, r2.stderr
