"""CLI smoke tests for validate-lanelet2-tags (ROADMAP_0.6.md §δ)."""

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


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_rb(), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def _write_osm(path: Path, *, missing_subtype: bool = False) -> None:
    tags = '<tag k="type" v="lanelet"/>\n'
    if not missing_subtype:
        tags += '<tag k="subtype" v="road"/>\n'
    tags += '<tag k="location" v="urban"/>\n'
    osm = f"""<?xml version="1.0" encoding="utf-8"?>
<osm version="0.6">
  <relation id="1">
    {tags}
  </relation>
</osm>
"""
    path.write_text(osm, encoding="utf-8")


def test_validate_lanelet2_tags_help():
    result = _run_cli(["validate-lanelet2-tags", "--help"])
    assert result.returncode == 0
    assert "lanelet" in result.stdout.lower() or "osm" in result.stdout.lower()


def test_validate_lanelet2_tags_valid_file_exit0(tmp_path):
    osm_path = tmp_path / "valid.osm"
    _write_osm(osm_path)
    result = _run_cli(["validate-lanelet2-tags", str(osm_path)])
    assert result.returncode == 0
    doc = json.loads(result.stdout)
    assert doc["result"] == "ok"
    assert doc["errors"] == 0


def test_validate_lanelet2_tags_missing_subtype_exit1(tmp_path):
    osm_path = tmp_path / "bad.osm"
    _write_osm(osm_path, missing_subtype=True)
    result = _run_cli(["validate-lanelet2-tags", str(osm_path)])
    assert result.returncode == 1
    assert "subtype" in result.stderr


def test_validate_lanelet2_tags_missing_file_exit1(tmp_path):
    result = _run_cli(["validate-lanelet2-tags", str(tmp_path / "nonexistent.osm")])
    assert result.returncode == 1


def test_validate_lanelet2_tags_export_output_passes(tmp_path):
    """Full round-trip: export a graph and validate its OSM output."""
    from roadgraph_builder.core.graph.edge import Edge
    from roadgraph_builder.core.graph.graph import Graph
    from roadgraph_builder.core.graph.node import Node
    from roadgraph_builder.io.export.lanelet2 import export_lanelet2

    n0 = Node("n0", (0.0, 0.0))
    n1 = Node("n1", (10.0, 0.0))
    e = Edge("e0", "n0", "n1", [(0.0, 0.0), (10.0, 0.0)])
    e.attributes = {
        "hd": {
            "lane_boundaries": {
                "left": [{"x": 0.0, "y": 1.75}, {"x": 10.0, "y": 1.75}],
                "right": [{"x": 0.0, "y": -1.75}, {"x": 10.0, "y": -1.75}],
            },
            "semantic_rules": [],
        }
    }
    graph = Graph(nodes=[n0, n1], edges=[e])
    osm_path = tmp_path / "map.osm"
    export_lanelet2(graph, osm_path, origin_lat=48.87, origin_lon=2.34)

    result = _run_cli(["validate-lanelet2-tags", str(osm_path)])
    assert result.returncode == 0
